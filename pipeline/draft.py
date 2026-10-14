"""Stage 3 — draft a dossier update for each triaged candidate with the PRO model."""

from __future__ import annotations

import logging

from pydantic import BaseModel, model_validator

from .config import config, model_pro
from .llm import LLM, prompt_parts
from .models import DraftUpdate
from .store import load_candidates, load_dossiers, load_snapshot, save_candidate

log = logging.getLogger(__name__)


class _DraftOrSkip(BaseModel):
    skip: bool = False
    reason: str | None = None
    draft: DraftUpdate | None = None

    @model_validator(mode="before")
    @classmethod
    def _wrap(cls, obj):  # the model returns either {"skip": true, ...} or a bare draft
        if isinstance(obj, dict) and not obj.get("skip") and "draft" not in obj:
            return {"draft": obj}
        return obj


def run(llm: LLM) -> dict:
    dossiers = load_dossiers()
    limit = config()["llm"]["max_snapshot_chars"]
    report = {"drafted": [], "skipped": []}
    for cand in load_candidates("triaged"):
        d = dossiers[cand.triage.dossier_id]
        snap = load_snapshot(cand.snapshot_id)
        recent = "\n".join(f"- {u.date}: {u.summary}" for u in d.updates[:5]) or "(none)"
        system, user = prompt_parts(
            "drafter", stage=d.stage, url=snap.url, dossier_id=d.id, dossier_title=d.title,
            jurisdiction=d.jurisdiction, recent_updates=recent, title=snap.title or "",
            published=snap.published or "unknown", text=snap.text[:limit],
        )
        out = llm.json_call(model_pro(), system, user, _DraftOrSkip, max_tokens=2500)
        if out.skip or out.draft is None:
            cand.status = "discarded"
            report["skipped"].append({"candidate": cand.id, "reason": out.reason})
        else:
            out.draft.dossier_id = d.id
            cand.draft = out.draft
            cand.status = "drafted"
            report["drafted"].append(cand.id)
        save_candidate(cand)
    return report
