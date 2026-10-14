"""Command line: `uv run python -m pipeline <command>`."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from .config import LOGS, today


def _save_report(name: str, report: dict) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    (LOGS / f"{name}-{today().isoformat()}.json").write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps(report, indent=1, default=str)[:6000])


def cmd_fetch(a):
    from . import fetch

    _save_report("fetch", fetch.run(a.source or None))


def cmd_daily(a):
    from . import draft, fetch, review, triage
    from .github import open_issue
    from .llm import LLM, BudgetExceeded

    llm = LLM()
    report: dict = {"date": today().isoformat()}
    try:
        report["fetch"] = fetch.run(a.source or None) if not a.skip_fetch else {"new": a.snapshots or []}
        report["triage"] = triage.run(llm, report["fetch"]["new"])
        report["draft"] = draft.run(llm)
        report["review"] = review.run(llm, dry_run=a.dry_run)
        leads = report["triage"]["leads"]
        if leads and not a.dry_run:
            body = "Relevant items from trade-association or media sources. They are **not** published; find the " \
                   "official source and add it to `sources/feeds.yaml` or capture it with `python -m pipeline capture`.\n\n" + \
                   "\n".join(f"- [{l['url']}]({l['url']}) → `{l['dossier_id']}` ({l['relevance']:.2f}): {l['reason']}" for l in leads)
            open_issue(f"[leads] {today()}: {len(leads)} lead(s) to verify", body, ["lead"])
    except BudgetExceeded as e:
        report["budget_exceeded"] = str(e)
        if not a.dry_run:
            open_issue(f"[pipeline] LLM call budget reached on {today()}",
                       f"The daily run stopped: {e}. Unprocessed snapshots stay in data/raw and will be "
                       "picked up after the budget is raised or on the next run.", ["pipeline"])
    report["llm_calls"], report["llm_usage"] = llm.calls, llm.usage
    _save_report("daily", report)


def cmd_biweekly(a):
    from . import compose
    from .llm import LLM, BudgetExceeded
    from .publish import is_publish_week, pr_body, write_outputs

    if not (a.force or is_publish_week(today())):
        print(f"{today()} is not a publishing week; nothing to do.")
        write_outputs(decision="skip")
        return
    llm = LLM()
    try:
        r = compose.run(llm, dry_run=a.dry_run, override_gate=a.force_publish)
    except BudgetExceeded as e:
        write_outputs(decision="hold")
        print(f"LLM budget exceeded: {e}")
        sys.exit(2)
    write_outputs(decision=r["decision"], issue=r["issue"], issue_file=r["issue_file"])
    if r["decision"] == "hold":
        from .config import ROOT

        (ROOT / "data" / "logs").mkdir(parents=True, exist_ok=True)
        (ROOT / "data" / "logs" / "pr-body.md").write_text(pr_body(r))
    _save_report("biweekly", r)


def cmd_validate(a):
    from .checks import validate_dossier
    from .store import load_dossiers

    try:
        dossiers = load_dossiers()
    except Exception as e:
        print(f"SCHEMA ERROR: {e}")
        sys.exit(1)
    failed = flagged = 0
    for d in dossiers.values():
        for r in validate_dossier(d, check_urls=a.urls):
            if not r.passed:
                tag = "REJECT" if r.severity == "reject" else "FLAG"
                failed += r.severity == "reject"
                flagged += r.severity == "flag"
                print(f"{tag} L{r.layer} {r.name}: {r.detail}")
    print(f"{len(dossiers)} dossiers, {sum(len(d.updates) for d in dossiers.values())} updates; "
          f"{failed} rejected checks, {flagged} flags")
    sys.exit(1 if failed else 0)


def cmd_capture(a):
    from .fetch import capture

    failed = []
    for url in a.urls:
        try:
            s = capture(url, a.source_id, "official", a.jurisdiction, a.mode, a.lang)
            print(f"{s.id}  {len(s.text):>8} chars  {url}")
        except Exception as e:
            failed.append(url)
            print(f"FAILED {url}: {type(e).__name__}: {e}"[:300])
    sys.exit(1 if failed else 0)


def cmd_review_seeds(a):
    from .seed_review import run

    _save_report("seed-review", run(a.only or None))


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    p = argparse.ArgumentParser(prog="pipeline")
    sub = p.add_subparsers(required=True)

    s = sub.add_parser("fetch", help="fetch all sources into data/raw")
    s.add_argument("--source", action="append")
    s.set_defaults(fn=cmd_fetch)

    s = sub.add_parser("daily", help="fetch -> triage -> draft -> review")
    s.add_argument("--source", action="append")
    s.add_argument("--dry-run", action="store_true", help="do not open GitHub issues")
    s.add_argument("--skip-fetch", action="store_true")
    s.add_argument("--snapshots", nargs="*", help="with --skip-fetch: snapshot ids to triage")
    s.set_defaults(fn=cmd_daily)

    s = sub.add_parser("biweekly", help="compose (and decide whether to publish) an issue")
    s.add_argument("--force", action="store_true", help="ignore the ISO-week parity check")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--force-publish", action="store_true")
    s.set_defaults(fn=cmd_biweekly)

    s = sub.add_parser("validate", help="layer 1+2 checks over all dossiers")
    s.add_argument("--urls", action="store_true", help="also check every source URL returns HTTP 200")
    s.set_defaults(fn=cmd_validate)

    s = sub.add_parser("capture", help="snapshot one or more URLs into data/raw")
    s.add_argument("urls", nargs="+")
    s.add_argument("--source-id", default="manual")
    s.add_argument("--jurisdiction", default="GLOBAL")
    s.add_argument("--mode", default="main", choices=["main", "full"])
    s.add_argument("--lang", default="en")
    s.set_defaults(fn=cmd_capture)

    s = sub.add_parser("review-seeds", help="layer 3 review of seeded dossier updates")
    s.add_argument("--only", nargs="*")
    s.set_defaults(fn=cmd_review_seeds)

    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
