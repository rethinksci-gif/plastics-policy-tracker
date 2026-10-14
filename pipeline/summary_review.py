"""Review of dossier introductory summaries (the 'what is this law' text on the site).

Summaries carry no verbatim quote, so the reviewer gets excerpts of every saved snapshot of the dossier's
official links and update sources, centred on the numbers, dates and references the summary mentions.
Same model allocation as layer 3: the `review` stage model for every summary, plus the
`review_high_confirm` model for impact: high dossiers. The site shows a summary only if a passing record
exists for exactly that text, so any edit to a summary hides it until it is reviewed again.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

from pydantic import BaseModel

from .checks import snapshots_for_url
from .config import REVIEWS, config, model_for
from .llm import LLM, parallel_map, prompt_parts
from .models import Dossier, LLMReview

OUT = REVIEWS / "summaries"
# Anchors searched for in the sources: full dates, legal/standard references, codes such as B3011 or C22,
# and numbers (tried with both decimal separators, since many sources write 0,45 for 0.45).
_ANCHORS = [
    re.compile(r"\b\d{1,2} (?:January|February|March|April|May|June|July|August|September|October|November|December) \d{4}\b"),
    re.compile(r"\b\d{4}/\d+(?:/[A-Z]+)?\b"),
    re.compile(r"\b[A-Z]{1,4}\d{2,}[\w/-]*\b"),
    re.compile(r"\b[A-Z]{2,}[\w/-]*\d[\w/-]*\b"),
    re.compile(r"\b\d+(?:[.,]\d+)?\s?%"),
    re.compile(r"\b\d+[.,]\d+\b"),
    re.compile(r"\b(?:19|20)\d{2}\b"),
]


_DE_MONTHS = {"January": "Januar", "February": "Februar", "March": "März", "May": "Mai", "June": "Juni",
              "July": "Juli", "October": "Oktober", "December": "Dezember"}


def anchors(summary: str) -> list[str]:
    out: list[str] = []
    for m in _ANCHORS[0].finditer(summary):  # German sources write "11. August 2026", "5. Juli 2017"
        day, month, year = m.group(0).split()
        out.append(f"{day}. {_DE_MONTHS.get(month, month)} {year}")
    for rx in _ANCHORS:
        for m in rx.finditer(summary):
            tok = m.group(0).strip()
            out.append(tok)
            if re.fullmatch(r"\d+[.,]\d+\s?%?", tok):  # decimal separator variants
                out.append(tok.replace(".", "#").replace(",", ".").replace("#", ","))
            if tok.endswith("%"):
                out.append(tok.replace(" %", "%").replace("%", " %"))
    return list(dict.fromkeys(out))


class SummaryReviewRecord(BaseModel):
    review_id: str
    dossier_id: str
    summary: str
    summary_sha256: str
    created: datetime
    impact: str
    sources: list[str]
    llm_review: LLMReview | None = None
    model: str | None = None
    confirm_review: LLMReview | None = None
    confirm_model: str | None = None
    outcome: str  # passed | failed
    reasons: list[str] = []


def sha(text: str) -> str:
    return hashlib.sha256(text.strip().encode()).hexdigest()


def context_for(text: str, summary: str, budget: int, extra: list[str] = (), head: int = 2500,
                window: int = 1500, per_anchor: int = 3) -> str:
    """Document head plus windows around (a) passages already verified as update quotes (`extra`) and
    (b) up to `per_anchor` occurrences of each date, reference, code and number in the summary."""
    if len(text) <= budget:
        return text
    spans = [(0, min(head, len(text)))]
    low = text.lower()
    for q in extra:
        i = low.find(q[:80].lower())
        if i >= 0:
            spans.append((max(0, i - window), min(len(text), i + len(q) + window)))
    for tok in anchors(summary):
        start = 0
        for _ in range(per_anchor):
            i = text.find(tok, start)
            if i < 0:
                break
            spans.append((max(0, i - window), min(len(text), i + window)))
            start = i + len(tok)
    spans.sort()
    merged: list[list[int]] = []
    for s0, s1 in spans:
        if merged and s0 <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], s1)
        else:
            merged.append([s0, s1])
    out, used = [], 0
    for s0, s1 in merged:
        if used >= budget:
            break
        piece = text[s0:min(s1, s0 + budget - used)]
        out.append(piece)
        used += len(piece)
    return "\n[...]\n".join(out)


def source_excerpts(d: Dossier) -> tuple[str, list[str]]:
    urls = list(dict.fromkeys([str(u) for u in d.official_links] + [str(u.source_url) for u in d.updates]))
    found = [(u, max(snapshots_for_url(u), key=lambda s: len(s.text))) for u in urls if snapshots_for_url(u)]
    if not found:
        return "", []
    per = config()["llm"]["max_snapshot_chars"] // len(found)
    quotes = [u.source_quote for u in d.updates]
    parts = [f"--- SOURCE {i + 1}: {u}\n{context_for(s.text, d.summary or '', per, quotes)}"
             for i, (u, s) in enumerate(found)]
    return "\n\n".join(parts), [u for u, _ in found]


def review_one(llm: LLM, d: Dossier) -> SummaryReviewRecord:
    sources_text, used = source_excerpts(d)
    rec = dict(review_id=f"summary-{d.id}", dossier_id=d.id, summary=d.summary, summary_sha256=sha(d.summary),
               created=datetime.now(timezone.utc), impact=d.impact, sources=used, reasons=[])
    if not used:
        rec["reasons"] = ["no saved snapshot of any official source"]
        return _save(SummaryReviewRecord(**rec, outcome="failed"))
    system, user = prompt_parts("summary_reviewer", title=d.title, jurisdiction=d.jurisdiction,
                                summary=d.summary, sources=sources_text)
    min_conf = config()["review"]["min_confidence"]
    ok = lambda r: r.verdict == "supported" and r.confidence >= min_conf  # noqa: E731
    rec["model"] = model_for("review")
    rec["llm_review"] = first = llm.json_call(rec["model"], system, user, LLMReview, max_tokens=1500)
    if not ok(first):
        rec["reasons"].append(f"reviewer: {first.verdict} ({first.confidence:.2f}); " + "; ".join(first.issues[:5]))
    elif d.impact == "high":
        rec["confirm_model"] = model_for("review_high_confirm")
        rec["confirm_review"] = second = llm.json_call(rec["confirm_model"], system, user, LLMReview, max_tokens=1500)
        if not ok(second):
            rec["reasons"].append(f"high-impact confirmation: {second.verdict} ({second.confidence:.2f}); "
                                  + "; ".join(second.issues[:5]))
    return _save(SummaryReviewRecord(**rec, outcome="failed" if rec["reasons"] else "passed"))


def _save(r: SummaryReviewRecord) -> SummaryReviewRecord:
    """Written as soon as each review finishes, so one failure does not lose the others."""
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{r.review_id}.json").write_text(r.model_dump_json(indent=1))
    return r


def needs_review(d: Dossier) -> bool:
    if not d.summary:
        return False
    p = OUT / f"summary-{d.id}.json"
    return not p.exists() or SummaryReviewRecord.model_validate_json(p.read_text()).summary_sha256 != sha(d.summary)


def run(llm: LLM, dossiers: list[Dossier], force: bool = False) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    todo = [d for d in dossiers if d.summary and (force or needs_review(d))]
    recs = parallel_map(lambda d: review_one(llm, d), todo)
    return {"reviewed": len(recs), "passed": [r.dossier_id for r in recs if r.outcome == "passed"],
            "failed": {r.dossier_id: r.reasons for r in recs if r.outcome != "passed"}, "llm_calls": llm.calls}
