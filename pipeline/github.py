"""Thin wrapper around the `gh` CLI (pre-installed on GitHub runners; uses GH_TOKEN)."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess

from .config import config

log = logging.getLogger(__name__)


def available() -> bool:
    return bool(shutil.which("gh")) and bool(os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
                                              or os.environ.get("PPT_USE_LOCAL_GH"))


def _gh(*args: str) -> str:
    res = subprocess.run(["gh", *args, "--repo", config()["github"]["repo"]], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:2])} failed: {res.stderr.strip()[:300]}")
    return res.stdout.strip()


def ensure_label(name: str, color: str = "d93f0b", description: str = "") -> None:
    try:
        _gh("label", "create", name, "--color", color, "--description", description, "--force")
    except RuntimeError as e:
        log.warning("%s", e)


def find_open_issue(title: str) -> str | None:
    out = _gh("issue", "list", "--state", "open", "--search", f'"{title}" in:title', "--json", "number,title")
    for item in json.loads(out or "[]"):
        if item["title"] == title:
            return str(item["number"])
    return None


def open_issue(title: str, body: str, labels: list[str]) -> str | None:
    """Open an issue unless one with the same title is already open. Returns its URL/number."""
    if not available():
        log.info("gh not available; issue not opened: %s", title)
        return None
    for label in labels:
        ensure_label(label)
    existing = find_open_issue(title)
    if existing:
        return existing
    args = ["issue", "create", "--title", title, "--body", body]
    for label in labels:
        args += ["--label", label]
    return _gh(*args)
