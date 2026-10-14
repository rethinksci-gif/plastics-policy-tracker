"""Stage 6 — biweekly scheduling and the publish decision.

The Git side (commit, merge staging -> main, deploy Pages, open a PR when the gate is closed) lives in
.github/workflows/biweekly.yml; this module decides and reports, and writes step outputs for the workflow.
"""

from __future__ import annotations

import json
import os
from datetime import date

from .config import config


def is_publish_week(day: date) -> bool:
    """GitHub cron cannot express 'every other Monday', so publish on ISO weeks with the anchor's parity."""
    s = config()["schedule"]
    anchor = date.fromisocalendar(s["anchor_iso_year"], s["anchor_iso_week"], 1)
    monday = date.fromisocalendar(*day.isocalendar()[:2], 1)
    return ((monday - anchor).days // 7) % 2 == 0


def write_outputs(**values) -> None:
    """Expose values to later workflow steps via $GITHUB_OUTPUT (no-op locally)."""
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a") as f:
        for k, v in values.items():
            f.write(f"{k}={json.dumps(v) if not isinstance(v, str) else v}\n")


def pr_body(report: dict) -> str:
    maint = config()["github"]["maintainer"]
    lines = [f"@{maint} the publish gate is **closed** for `{report['issue']}`. Nothing has been published.", "",
             "**Why:**", *[f"- {h}" for h in report["hold_reasons"]], "",
             f"Draft issue: `{report['issue_file']}`",
             f"Review report: `reviews/issues/{report['review_id']}.md`", "",
             "**Quarantined items:**"]
    for q in report["quarantined_items"]:
        lines.append(f"- `{q['id']}` {q['dossier']} ({q['impact']}): {'; '.join(q['reasons'])[:300]}")
    lines += ["", "To publish anyway after checking: run the *Biweekly issue* workflow with `force_publish: true`."]
    return "\n".join(lines)
