"""Stage 5 — compose a biweekly issue from reviewed candidates, with the issue-level review (layer 4)
and the publish gate."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone

from pydantic import BaseModel

from .checks import blocking, deterministic_checks
from .config import ISSUES, REVIEWS, config, model_for, today
from .llm import LLM, prompt_parts
from .models import Candidate, Dossier, EditorialReview, KeyDate, NextStep, Update, fuzzy_date_bounds
from .store import dump_yaml, load_candidates, load_dossiers, save_candidate, save_dossier

log = logging.getLogger(__name__)

JURISDICTION_ORDER = ["GLOBAL", "EU", "UK", "US", "CN"]
JURISDICTION_NAMES = {
    "GLOBAL": "Global", "EU": "European Union", "UK": "United Kingdom", "US": "United States", "CN": "China",
    "EU-FR": "France", "EU-NL": "Netherlands", "EU-DE": "Germany", "EU-IT": "Italy", "EU-ES": "Spain",
    "EU-SE": "Sweden", "US-CA": "California", "US-OR": "Oregon", "US-CO": "Colorado", "US-ME": "Maine",
    "US-MN": "Minnesota", "US-MD": "Maryland", "US-WA": "Washington State", "US-FED": "US federal",
}


def jurisdiction_name(code: str) -> str:
    return JURISDICTION_NAMES.get(code, code)


def jurisdiction_sort_key(code: str):
    root = code.split("-")[0]
    return (JURISDICTION_ORDER.index(root) if root in JURISDICTION_ORDER else 99, code != root, code)


class Highlights(BaseModel):
    highlights: list[str]


def issue_number() -> int:
    published = [p for p in ISSUES.glob("*.md")]
    return len(published) + 1


def upcoming_dates(dossiers: dict[str, Dossier], start: date, days: int) -> list[dict]:
    end = start + timedelta(days=days)
    out = []
    for d in dossiers.values():
        for kd in d.key_dates:
            lo, hi = fuzzy_date_bounds(kd.date)
            if hi >= start and lo <= end:
                out.append({"date": kd.date, "dossier": d.id, "title": d.short_title or d.title, "text": kd.text,
                            "kind": "key date", "source_url": str(kd.source_url) if kd.source_url else None})
        for ns in d.next_steps:
            lo, hi = fuzzy_date_bounds(ns.date)
            if hi >= start and lo <= end:
                out.append({"date": ns.date, "dossier": d.id, "title": d.short_title or d.title, "text": ns.text,
                            "kind": "expected" if ns.status == "expected" else "to be confirmed",
                            "source_url": str(ns.source_url)})
    return sorted(out, key=lambda x: x["date"])


def apply_candidate(d: Dossier, c: Candidate) -> Dossier:
    dr = c.draft
    upd = Update(date=dr.date, summary=dr.summary, source_url=dr.source_url, source_quote=dr.source_quote,
                 source_quote_en=dr.source_quote_en, source_lang=dr.source_lang, stage_change=dr.stage_change,
                 review_id=c.review_id or c.id)
    updates = sorted([upd, *d.updates], key=lambda u: fuzzy_date_bounds(u.date)[0], reverse=True)
    steps = list(d.next_steps)
    for ns in dr.next_steps:
        if not any(s.text == ns.text and s.date == ns.date for s in steps):
            steps.append(NextStep.model_validate(ns.model_dump()))
    kds = list(d.key_dates)
    for kd in dr.key_dates:
        if not any(k.text == kd.text and k.date == kd.date for k in kds):
            kds.append(KeyDate.model_validate(kd.model_dump()))
    data = d.model_dump()
    data.update(updates=updates, next_steps=sorted(steps, key=lambda s: s.date),
                key_dates=sorted(kds, key=lambda k: k.date), stage=dr.stage_change or d.stage)
    return Dossier.model_validate(data)


def item_view(c: Candidate, d: Dossier) -> dict:
    dr = c.draft
    return {
        "id": c.id, "review_id": c.review_id or c.id, "dossier": d.id, "title": d.short_title or d.title,
        "jurisdiction": d.jurisdiction, "impact": d.impact, "date": dr.date, "summary": dr.summary,
        "stage_before": d.stage, "stage_after": dr.stage_change or d.stage, "affected": d.affected,
        "next_steps": [ns.model_dump(mode="json") for ns in dr.next_steps],
        "source_url": dr.source_url, "source_quote": dr.source_quote, "source_quote_en": dr.source_quote_en,
        "source_lang": dr.source_lang, "interpretation": dr.interpretation,
    }


def editorial_review(llm: LLM, items: list[dict], quarantined: list[dict], dossiers: dict[str, Dossier],
                     issue_date: date) -> EditorialReview:
    affected = {i["dossier"] for i in items}
    history = {
        did: {"stage": dossiers[did].stage, "impact": dossiers[did].impact,
              "updates": [{"date": u.date, "summary": u.summary, "stage_change": u.stage_change}
                          for u in dossiers[did].updates[:8]]}
        for did in affected
    }
    system, user = prompt_parts(
        "editor", issue_date=issue_date.isoformat(),
        items=json.dumps(items, indent=1, ensure_ascii=False),
        quarantined=json.dumps(quarantined, indent=1, ensure_ascii=False) or "[]",
        history=json.dumps(history, indent=1, ensure_ascii=False),
    )
    return llm.json_call(model_for("editor"), system, user, EditorialReview, max_tokens=3000)


BLOCKING_KEYS = ("contradictions", "history_conflicts", "translation_issues", "fact_vs_interpretation_issues")


def editorial_blocking(ed: EditorialReview) -> dict[str, list[str]]:
    """Items layer 4 holds back. Only factual problems (item_flags) block; terminology and style notes
    (terminology_issues, style_notes) are reported in the review record and never quarantine an item."""
    return {cid: probs for cid, probs in ed.item_flags.items() if probs}


def editorial_unattached_blocking(ed: EditorialReview) -> list[str]:
    """Blocking findings the editor could not pin to an item; these hold the whole issue. The editor's
    `passed` flag is not used on its own, so a model that fails an issue for style alone cannot hold it."""
    if ed.item_flags:
        return []
    return [x for key in BLOCKING_KEYS for x in getattr(ed, key)]


def write_highlights(llm: LLM, items: list[dict]) -> list[str]:
    if not items:
        return []
    slim = [{k: i[k] for k in ("title", "jurisdiction", "impact", "date", "summary", "stage_before", "stage_after")}
            for i in items]
    system, user = prompt_parts("highlights", items=json.dumps(slim, indent=1, ensure_ascii=False))
    return llm.json_call(model_for("highlights"), system, user, Highlights, max_tokens=800).highlights[:5]


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def _base() -> str:
    return config()["site"]["base"].rstrip("/")


def render_item(i: dict) -> str:
    base = _base()
    stage = (f"`{i['stage_before']}` → `{i['stage_after']}`" if i["stage_after"] != i["stage_before"]
             else f"no change (`{i['stage_after']}`)")
    nxt = "; ".join(f"{n['text']} ({n['date']})" for n in i["next_steps"]) or "None stated in the source."
    lines = [
        f"### [{i['title']}]({base}/dossiers/{i['dossier']}/)",
        "",
        f"**What happened ({i['date']}):** {i['summary']}",
        "",
        f"- **Stage:** {stage}",
        f"- **Affects:** {', '.join(i['affected'])}",
        f"- **Next:** {nxt}",
        f"- **Source:** [{i['source_url']}]({i['source_url']}) · review [`{i['review_id']}`]({base}/reviews/{i['review_id']}/)",
        "",
        "<details><summary>Source quote</summary>",
        "",
        f"> {i['source_quote']}",
    ]
    if i.get("source_quote_en"):
        lines += ["", f"> *English translation:* {i['source_quote_en']}"]
    lines += ["", "</details>"]
    if i.get("interpretation"):
        lines += ["", f'<aside class="analysis"><strong>Analysis</strong> (our interpretation, not part of the verified record): {i["interpretation"]}</aside>']
    return "\n".join(lines)


def render_issue(meta: dict, items: list[dict], deadlines: list[dict], unchanged: list[dict],
                 quarantined: list[dict]) -> str:
    base = _base()
    front = dump_yaml({k: meta[k] for k in ("title", "number", "date", "status", "highlights", "review_report",
                                             "items_count", "quarantined_count", "description")})
    out = ["---", front.rstrip(), "---", ""]
    out += ["## In this issue", ""]
    out += [f"- {h}" for h in meta["highlights"]] or ["- No verified changes in this period."]
    out += ["", "## What changed", ""]
    if not items:
        out += ["No verified changes in this period.", ""]
    groups: dict[str, list[dict]] = {}
    for i in items:
        groups.setdefault(i["jurisdiction"], []).append(i)
    for code in sorted(groups, key=jurisdiction_sort_key):
        out += [f"## {jurisdiction_name(code)}", ""]
        for i in sorted(groups[code], key=lambda x: ({"high": 0, "medium": 1, "low": 2}[x["impact"]], x["date"])):
            out += [render_item(i), ""]
    out += [f"## Upcoming deadlines (next {config()['schedule']['lookahead_days']} days)", ""]
    if deadlines:
        out += ["| Date | Dossier | What | Status |", "|---|---|---|---|"]
        for dl in deadlines:
            out.append(f"| {dl['date']} | [{dl['title']}]({base}/dossiers/{dl['dossier']}/) | {dl['text']} | {dl['kind']} |")
    else:
        out.append("No recorded deadlines in the next 60 days.")
    out += ["", f"Subscribe to all dates: [calendar.ics]({base}/calendar.ics)", ""]
    out += ["## Dossiers with no change", "", f"<details><summary>{len(unchanged)} dossiers unchanged</summary>", ""]
    out += [f"- [{u['title']}]({base}/dossiers/{u['id']}/) — `{u['stage']}`" for u in unchanged]
    out += ["", "</details>", ""]
    out += ["## Resources", "",
            f"- [All dossiers]({base}/dossiers/) — filter by jurisdiction, topic, stage and impact",
            f"- [Calendar]({base}/calendar/) and [.ics feed]({base}/calendar.ics)",
            f"- [How we verify]({base}/verification/)",
            "- Official portals: [EUR-Lex](https://eur-lex.europa.eu/), [Legislative Observatory](https://oeil.secure.europarl.europa.eu/), "
            "[Have Your Say](https://ec.europa.eu/info/law/better-regulation/have-your-say), "
            "[Federal Register](https://www.federalregister.gov/), [UNEP INC](https://www.unep.org/inc-plastic-pollution)",
            ""]
    out += ["---", "",
            f"**Verification.** Every item above passed four layers of checks. "
            f"[Read this issue's review report]({base}/reviews/{meta['review_report']}/). "
            f"{len(quarantined)} item(s) were held back for human review and are not included.", ""]
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------


def run(llm: LLM, dry_run: bool = False, issue_date: date | None = None, status_fn=None,
        override_gate: bool = False) -> dict:
    """override_gate: the maintainer has checked a held issue and approved it (force_publish)."""
    issue_date = issue_date or today()
    dossiers = load_dossiers()
    number = issue_number()
    slug = f"{issue_date.isoformat()}-issue-{number:03d}"

    pool = [c for c in load_candidates() if c.issue is None and c.status in ("passed", "quarantined")]
    passed = [c for c in pool if c.status == "passed"]
    quarantined_c = [c for c in pool if c.status == "quarantined"]

    # Global re-check of layers 1+2 (dates, duplicates and provenance may have changed since the daily run).
    recheck_failures = {}
    for c in list(passed):
        res = deterministic_checks(c.draft, dossiers[c.triage.dossier_id], status_fn=status_fn)
        bad = blocking(res)
        if bad:
            recheck_failures[c.id] = [f"L{r.layer} {r.name}: {r.detail}" for r in bad]
            passed.remove(c)
            quarantined_c.append(c)

    items = [item_view(c, dossiers[c.triage.dossier_id]) for c in passed]
    q_items = []
    for c in quarantined_c:
        d = dossiers[c.triage.dossier_id]
        reasons = recheck_failures.get(c.id)
        if not reasons:
            rec_path = REVIEWS / "items" / f"{c.review_id or c.id}.json"
            reasons = json.loads(rec_path.read_text())["reasons"] if rec_path.exists() else ["see review"]
        q_items.append({"id": c.id, "dossier": d.id, "title": d.short_title or d.title, "impact": d.impact,
                        "summary": c.draft.summary if c.draft else None,
                        "source_url": c.source_url, "reasons": reasons})

    # Layer 4 — editorial review of the whole issue.
    editorial = editorial_review(llm, items, q_items, dossiers, issue_date) if items else EditorialReview(passed=True)
    for cid, problems in editorial_blocking(editorial).items():
        match = next((i for i in items if i["id"] == cid), None)
        if match:
            items.remove(match)
            c = next(c for c in passed if c.id == cid)
            passed.remove(c)
            quarantined_c.append(c)
            q_items.append({"id": cid, "dossier": match["dossier"], "title": match["title"],
                            "impact": match["impact"], "summary": match["summary"],
                            "source_url": match["source_url"], "reasons": [f"L4 editor: {p}" for p in problems]})

    # Publish gate.
    total = len(items) + len(q_items)
    ratio = len(q_items) / total if total else 0.0
    gate_cfg = config()["gate"]
    hold_reasons = []
    if ratio > gate_cfg["max_quarantine_ratio"]:
        hold_reasons.append(f"{ratio:.0%} of items quarantined (limit {gate_cfg['max_quarantine_ratio']:.0%})")
    high_q = [q for q in q_items if q["impact"] == "high"]
    if gate_cfg["hold_on_high_impact_quarantine"] and high_q:
        hold_reasons.append("high-impact item(s) quarantined: " + ", ".join(sorted({q["dossier"] for q in high_q})))
    unattached = editorial_unattached_blocking(editorial)
    if unattached:
        hold_reasons.append("editorial review found blocking problems not tied to one item: " + "; ".join(unattached)[:400])
    if dry_run:
        decision = "dry-run"
    elif hold_reasons and not override_gate:
        decision = "hold"
    else:
        decision = "publish"

    highlights = write_highlights(llm, items)
    # Dossiers after applying this issue's items (for the deadline list).
    after = dict(dossiers)
    for c in passed:
        after[c.triage.dossier_id] = apply_candidate(after[c.triage.dossier_id], c)
    deadlines = upcoming_dates(after, issue_date, config()["schedule"]["lookahead_days"])
    changed_ids = {i["dossier"] for i in items}
    unchanged = [{"id": d.id, "title": d.short_title or d.title, "stage": d.stage}
                 for d in sorted(after.values(), key=lambda d: (jurisdiction_sort_key(d.jurisdiction), d.id))
                 if d.id not in changed_ids]

    review_slug = f"issue-{number:03d}"
    meta = {
        "title": f"Issue {number} — {issue_date:%d %B %Y}",
        "number": number,
        "date": issue_date.isoformat(),
        "status": "published" if decision == "publish" else "draft",
        "highlights": highlights,
        "review_report": review_slug,
        "items_count": len(items),
        "quarantined_count": len(q_items),
        "description": highlights[0] if highlights else "Plastics policy changes verified against official sources.",
    }
    body = render_issue(meta, items, deadlines, unchanged, q_items)

    issue_report = {
        "review_id": review_slug, "issue": slug, "created": datetime.now(timezone.utc).isoformat(),
        "decision": decision, "would_publish": not hold_reasons, "hold_reasons": hold_reasons,
        "gate_overridden_by_maintainer": bool(override_gate and hold_reasons and not dry_run),
        "quarantine_ratio": round(ratio, 3),
        "published_items": [{"id": i["id"], "dossier": i["dossier"], "review_id": i["review_id"],
                             "summary": i["summary"]} for i in items],
        "quarantined_items": q_items, "editorial_review": editorial.model_dump(),
        "llm_calls": llm.calls, "llm_usage": llm.usage,
    }
    write_issue_report(issue_report)

    target = ISSUES / f"{slug}.md" if decision == "publish" else ISSUES.parent / "data" / "drafts" / f"{slug}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body)

    if decision == "publish":
        for c in passed:
            save_dossier(after[c.triage.dossier_id])
            c.status, c.issue = "published", slug
            save_candidate(c)
        for c in quarantined_c:
            c.issue = slug
            save_candidate(c)
    issue_report["issue_file"] = str(target.relative_to(ISSUES.parent))
    return issue_report


def write_issue_report(r: dict) -> None:
    out = REVIEWS / "issues"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{r['review_id']}.json").write_text(json.dumps(r, indent=1, ensure_ascii=False))
    ed = r["editorial_review"]
    lines = [f"# Review report — {r['issue']}", "",
             f"- **Decision:** {r['decision']} (gate {'open' if r['would_publish'] else 'closed'})",
             f"- **Quarantine ratio:** {r['quarantine_ratio']:.0%}",
             f"- **LLM calls this run:** {r['llm_calls']}", ""]
    if r["hold_reasons"]:
        lines += ["## Why the gate is closed", ""] + [f"- {h}" for h in r["hold_reasons"]] + [""]
    lines += ["## Published items", ""]
    lines += [f"- `{i['review_id']}` {i['dossier']}: {i['summary']}" for i in r["published_items"]] or ["- none"]
    lines += ["", "## Quarantined items (not published)", ""]
    for q in r["quarantined_items"]:
        lines += [f"- `{q['id']}` **{q['dossier']}** (impact {q['impact']}) — {q.get('summary') or ''}",
                  f"  - source: {q['source_url']}"] + [f"  - {x}" for x in q["reasons"]]
    if not r["quarantined_items"]:
        lines.append("- none")
    lines += ["", "## Layer 4: editorial review", "", f"Passed: **{ed['passed']}**", "", ed.get("notes", ""), ""]
    lines += ["### Blocking (factual) findings", ""]
    blocking_found = False
    for key in ("contradictions", "history_conflicts", "translation_issues", "fact_vs_interpretation_issues"):
        if ed.get(key):
            blocking_found = True
            lines += [f"**{key.replace('_', ' ')}**", ""] + [f"- {x}" for x in ed[key]] + [""]
    if not blocking_found:
        lines += ["None.", ""]
    lines += ["### Style and terminology notes (reported only, not blocking)", ""]
    notes = [f"- {x}" for x in ed.get("terminology_issues", [])]
    notes += [f"- `{cid}`: {x}" for cid, xs in (ed.get("style_notes") or {}).items() for x in xs]
    lines += (notes or ["None."]) + [""]
    if ed.get("missing_high_impact"):
        lines += ["### High-impact dossiers with held or missing items", ""] + [f"- {x}" for x in ed["missing_high_impact"]] + [""]
    (out / f"{r['review_id']}.md").write_text("\n".join(lines) + "\n")
