"""Stage 2 — triage new snapshots with the FAST model: relevance, dossier match, category."""

from __future__ import annotations

import json
import logging

from .config import LOGS, config, model_fast, today
from .llm import LLM, prompt_parts
from .models import Candidate, TriageResult
from .store import load_dossiers, load_snapshot, load_sources, next_candidate_id, save_candidate

log = logging.getLogger(__name__)


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "\n[... truncated ...]"


def triage_snapshot(llm: LLM, snapshot, dossier_list: str, source_name: str) -> TriageResult:
    system, user = prompt_parts(
        "triage",
        dossiers=dossier_list,
        source_name=source_name,
        trust=snapshot.trust,
        jurisdiction=snapshot.jurisdiction,
        url=snapshot.url,
        title=snapshot.title or "",
        published=snapshot.published or "unknown",
        text=_truncate(snapshot.text, 12000),
    )
    return llm.json_call(model_fast(), system, user, TriageResult, max_tokens=600)


def run(llm: LLM, snapshot_ids: list[str]) -> dict:
    dossiers = load_dossiers()
    dossier_list = "\n".join(f"- {d.id} — {d.title} — {d.jurisdiction}" for d in dossiers.values())
    names = {s.id: s.name for s in load_sources()}
    threshold = config()["triage"]["relevance_threshold"]
    report = {"candidates": [], "discarded": [], "new_dossier_suggestions": []}
    LOGS.mkdir(parents=True, exist_ok=True)
    discard_log = LOGS / f"triage-{today().isoformat()}.jsonl"
    for sid in snapshot_ids:
        snap = load_snapshot(sid)
        result = triage_snapshot(llm, snap, dossier_list, names.get(snap.source_id, snap.source_id))
        if result.dossier_id and result.dossier_id not in dossiers:
            result.new_dossier_suggestion = result.new_dossier_suggestion or result.dossier_id
            result.dossier_id = None
        entry = {"snapshot": sid, "url": snap.url, **result.model_dump()}
        if result.relevance < threshold or not result.dossier_id:
            with discard_log.open("a") as f:
                f.write(json.dumps(entry) + "\n")
            report["discarded"].append(entry)
            if result.relevance >= threshold and result.new_dossier_suggestion:
                report["new_dossier_suggestions"].append(entry)
            continue
        cand = Candidate(
            id=next_candidate_id(today()), created=today(), snapshot_id=sid, source_id=snap.source_id,
            source_url=snap.url, source_trust=snap.trust, title=snap.title, triage=result,
        )
        save_candidate(cand)
        report["candidates"].append(cand.id)
    return report
