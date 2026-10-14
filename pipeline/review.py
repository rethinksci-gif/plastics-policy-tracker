"""Stage 4 — self-review.

Per candidate (daily):   layer 1 (deterministic) -> layer 2 (quote provenance) -> layer 3 (independent LLM reviewer).
Per issue (biweekly):    layers 1+2 re-run on everything passed, then layer 4 (editorial review) — see compose.py.

Anything that fails is quarantined: not published, written to reviews/, and raised as a GitHub issue.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from .checks import blocking, deterministic_checks, excerpt_for_review, flags, quote_in_text, snapshots_for_url
from .config import REVIEWS, config, model_for
from .github import open_issue
from .llm import LLM, parallel_map, prompt_parts
from .models import Candidate, CheckResult, Dossier, LLMReview, ReviewRecord
from .store import load_candidates, load_dossiers, load_snapshot, save_candidate

log = logging.getLogger(__name__)


def claim_text(c: Candidate) -> str:
    d = c.draft
    claim = {
        "dossier": c.triage.dossier_id,
        "date": d.date,
        "summary": d.summary,
        "source_quote": d.source_quote,
        "source_quote_en": d.source_quote_en,
        "stage_change": d.stage_change,
        "next_steps": [ns.model_dump(mode="json") for ns in d.next_steps],
        "key_dates": [kd.model_dump(mode="json") for kd in d.key_dates],
        "interpretation": d.interpretation,
    }
    return json.dumps(claim, indent=1, ensure_ascii=False)


def _verdict_ok(r: LLMReview) -> bool:
    return r.verdict == "supported" and r.confidence >= config()["review"]["min_confidence"]


def _reason(label: str, r: LLMReview) -> str:
    return f"L3 {label}: {r.verdict} (confidence {r.confidence:.2f}); " + "; ".join(r.issues[:5])


def layer3(llm: LLM, claim: str, url: str, source_text: str, quote: str, impact: str) -> dict:
    """Layer 3. Each reviewer sees only the snapshot and the claim — never the drafting prompt or reasoning.

    Every item gets the `review` stage model. Items with impact: high that pass it get an independent
    second opinion from the `review_high_confirm` stage model; both must pass. Items the first reviewer
    rejects are quarantined anyway, so they never use the second model.
    """
    text = excerpt_for_review(source_text, quote, config()["llm"]["max_snapshot_chars"])
    system, user = prompt_parts("reviewer", claim=claim, url=url, text=text)
    out = {"review": None, "model": model_for("review"), "confirm": None, "confirm_model": None, "reasons": []}
    out["review"] = llm.json_call(out["model"], system, user, LLMReview, max_tokens=1500)
    if not _verdict_ok(out["review"]):
        out["reasons"].append(_reason("reviewer", out["review"]))
    elif impact == "high":
        out["confirm_model"] = model_for("review_high_confirm")
        out["confirm"] = llm.json_call(out["confirm_model"], system, user, LLMReview, max_tokens=1500)
        if not _verdict_ok(out["confirm"]):
            out["reasons"].append(_reason("high-impact confirmation", out["confirm"]))
    return out


def review_candidate(llm: LLM | None, c: Candidate, dossier: Dossier, status_fn=None,
                     check_urls: bool | None = None) -> ReviewRecord:
    checks: list[CheckResult] = deterministic_checks(c.draft, dossier, status_fn=status_fn, check_urls=check_urls,
                                                       detected=c.created)
    reasons = [f"L{r.layer} {r.name}: {r.detail}" for r in blocking(checks)]
    if c.source_trust != "official":
        reasons.insert(0, f"L1 source-trust: lead came from a {c.source_trust} source; facts need an official source")
    l3 = {"review": None, "model": None, "confirm": None, "confirm_model": None}
    if not reasons:
        snaps = snapshots_for_url(c.draft.source_url) or [load_snapshot(c.snapshot_id)]
        matching = [s for s in snaps if quote_in_text(c.draft.source_quote, s.text)[0]] or [snaps[-1]]
        src = max(matching, key=lambda s: len(s.text))  # fullest snapshot gives the reviewer most context
        l3 = layer3(llm, claim_text(c), c.draft.source_url, src.text, c.draft.source_quote, dossier.impact)
        reasons += l3["reasons"]
    flag_reasons = [f"L{r.layer} {r.name}: {r.detail}" for r in flags(checks) if r.name == "stage-transition"]
    if reasons:
        outcome = "quarantined"
    elif flag_reasons:
        outcome, reasons = "human-review", flag_reasons
    else:
        outcome = "passed"
    return ReviewRecord(
        review_id=c.id, candidate_id=c.id, dossier_id=dossier.id, created=datetime.now(timezone.utc),
        impact=dossier.impact, checks=checks, llm_review=l3["review"], model=l3["model"] if l3["review"] else None,
        confirm_review=l3["confirm"], confirm_model=l3["confirm_model"], outcome=outcome, reasons=reasons,
    )


def record_markdown(rec: ReviewRecord, c: Candidate) -> str:
    d = c.draft
    lines = [
        f"# Review {rec.review_id}",
        "",
        f"- **Dossier:** `{rec.dossier_id}` (impact: {rec.impact})",
        f"- **Outcome:** **{rec.outcome}**",
        f"- **Source:** <{d.source_url}> (trust: {c.source_trust}; snapshot `{c.snapshot_id}`)",
        f"- **Reviewed:** {rec.created:%Y-%m-%d %H:%M} UTC",
        "",
        "## Claim",
        "",
        f"**{d.date}** — {d.summary}",
        "",
        f"> {d.source_quote}",
    ]
    if d.source_quote_en:
        lines += ["", f"> *(translation)* {d.source_quote_en}"]
    if d.stage_change:
        lines += ["", f"Proposed stage change: `{d.stage_change}`"]
    lines += ["", "## Layers 1–2: deterministic checks", "", "| Layer | Check | Result | Detail |", "|---|---|---|---|"]
    for r in rec.checks:
        mark = "pass" if r.passed else ("FLAG" if r.severity == "flag" else "FAIL")
        lines.append(f"| {r.layer} | {r.name} | {mark} | {r.detail.replace('|', '/')} |")
    lines += ["", "## Layer 3: independent reviewer", ""]
    if rec.llm_review:
        for title, lr, model in (("Reviewer", rec.llm_review, rec.model),
                                 ("High-impact confirmation", rec.confirm_review, rec.confirm_model)):
            if lr is None:
                continue
            lines += [f"**{title}** (`{model or 'model not recorded'}`): verdict **{lr.verdict}**, "
                      f"confidence {lr.confidence:.2f}."]
            lines += [""] + [f"- {k}: {'yes' if v else 'NO'}" for k, v in lr.checks.items()]
            if lr.issues:
                lines += ["", "Issues:"] + [f"- {i}" for i in lr.issues]
            lines.append("")
    else:
        lines.append("Not run (blocked by an earlier layer).")
    if rec.reasons:
        lines += ["", "## Reasons not passed", ""] + [f"- {r}" for r in rec.reasons]
    return "\n".join(lines) + "\n"


def save_record(rec: ReviewRecord, c: Candidate) -> None:
    out = REVIEWS / "items"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{rec.review_id}.json").write_text(rec.model_dump_json(indent=1))
    (out / f"{rec.review_id}.md").write_text(record_markdown(rec, c))


def raise_issue(rec: ReviewRecord, c: Candidate, dry_run: bool = False) -> str | None:
    cfg = config()["github"]
    title = f"[quarantine] {rec.dossier_id}: review {rec.review_id}"
    body = "\n".join([
        f"An update for **{rec.dossier_id}** (impact: {rec.impact}) failed self-review and was **not published**.",
        "",
        f"- Source: {c.draft.source_url}",
        f"- Snapshot: `data/raw/{c.snapshot_id}.json`",
        f"- Full report: `reviews/items/{rec.review_id}.md`",
        "",
        "**Claim**",
        "",
        f"> {c.draft.summary}",
        "",
        "**Why it was held**",
        "",
        *[f"- {r}" for r in rec.reasons],
        "",
        "To publish after checking: fix the candidate in `data/candidates/"
        f"{c.id}.json`, set `status` to `drafted` and re-run the daily workflow, or close this issue to discard it.",
    ])
    if dry_run:
        return None
    try:
        return open_issue(title, body, [cfg["review_label"]])
    except RuntimeError as e:
        log.warning("could not open issue: %s", e)
        return None


def run(llm: LLM, dry_run: bool = False, status_fn=None) -> dict:
    dossiers = load_dossiers()
    report = {"passed": [], "quarantined": [], "human_review": [], "issues": []}
    cands = load_candidates("drafted")
    recs = parallel_map(lambda c: review_candidate(llm, c, dossiers[c.triage.dossier_id], status_fn=status_fn), cands)
    for c, rec in zip(cands, recs):
        dossier = dossiers[c.triage.dossier_id]
        save_record(rec, c)
        c.review_id = rec.review_id
        c.status = "passed" if rec.outcome == "passed" else "quarantined"
        save_candidate(c)
        if rec.outcome == "passed":
            report["passed"].append(c.id)
            continue
        report["quarantined" if rec.outcome == "quarantined" else "human_review"].append(
            {"candidate": c.id, "dossier": dossier.id, "impact": dossier.impact, "reasons": rec.reasons})
        ref = raise_issue(rec, c, dry_run)
        if ref:
            report["issues"].append(ref)
    return report
