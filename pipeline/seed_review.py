"""Run layers 1–3 on the updates that were seeded into dossiers by hand (review ids 'seed-...').

Seeded updates go through the same gates as pipeline output: the quote must be found in a saved
snapshot (layer 2) and the independent reviewer must mark the update supported with confidence
>= the threshold (layer 3). Records go to reviews/items/<review_id>.json|md like any other review.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

from .checks import excerpt_for_review, check_domain, check_event_date, check_quote, quote_in_text, snapshots_for_url
from .config import REVIEWS, config, model_pro
from .llm import LLM, parallel_map, prompt_parts
from .models import Candidate, DraftUpdate, LLMReview, ReviewRecord, TriageResult
from .review import record_markdown
from .store import load_dossiers


def _review_one(llm: LLM, d, u, out_dir) -> dict:
    url = str(u.source_url)
    checks = [check_event_date(u.date), check_domain(url), check_quote(u.source_quote, url)]
    reasons = [f"L{c.layer} {c.name}: {c.detail}" for c in checks if not c.passed]
    review = None
    if not reasons:
        # Of the snapshots containing the quote, give the reviewer the fullest one (most context).
        snap = max((s for s in snapshots_for_url(url) if quote_in_text(u.source_quote, s.text)[0]),
                   key=lambda s: len(s.text))
        claim = json.dumps({"dossier": d.id, "date": u.date, "summary": u.summary,
                            "source_quote": u.source_quote, "source_quote_en": u.source_quote_en,
                            "stage_change": u.stage_change}, indent=1, ensure_ascii=False)
        system, user = prompt_parts("reviewer", claim=claim, url=url,
                                    text=excerpt_for_review(snap.text, u.source_quote,
                                                            config()["llm"]["max_snapshot_chars"]))
        review = llm.json_call(model_pro(), system, user, LLMReview, max_tokens=1500)
        if review.verdict != "supported" or review.confidence < config()["review"]["min_confidence"]:
            reasons.append(f"L3 reviewer: {review.verdict} ({review.confidence:.2f}); " + "; ".join(review.issues[:5]))
    rec = ReviewRecord(review_id=u.review_id, candidate_id="seed", dossier_id=d.id,
                       created=datetime.now(timezone.utc), impact=d.impact, checks=checks,
                       llm_review=review, model=model_pro() if review else None, outcome="passed" if not reasons else "quarantined", reasons=reasons)
    fake = Candidate(id=u.review_id, created=date.today(), snapshot_id="(seed)", source_id="seed",
                     source_url=url, source_trust="official",
                     triage=TriageResult(relevance=1, dossier_id=d.id, category="seed", reason="seed"),
                     draft=DraftUpdate(dossier_id=d.id, date=u.date, summary=u.summary, source_url=url,
                                       source_quote=u.source_quote, source_quote_en=u.source_quote_en,
                                       source_lang=u.source_lang, stage_change=u.stage_change))
    (out_dir / f"{u.review_id}.json").write_text(rec.model_dump_json(indent=1))
    (out_dir / f"{u.review_id}.md").write_text(record_markdown(rec, fake))
    return {"review_id": u.review_id, "dossier": d.id, "reasons": reasons}


def run(only: list[str] | None = None) -> dict:
    llm = LLM()
    out_dir = REVIEWS / "items"
    out_dir.mkdir(parents=True, exist_ok=True)
    tasks = [(d, u) for d in load_dossiers().values() if not only or d.id in only for u in d.updates
             if only or not (out_dir / f"{u.review_id}.json").exists()]
    results = parallel_map(lambda t: _review_one(llm, t[0], t[1], out_dir), tasks)
    return {"passed": [r for r in results if not r["reasons"]], "failed": [r for r in results if r["reasons"]],
            "llm_calls": llm.calls}
