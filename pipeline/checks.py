"""Review layers 1 and 2 — deterministic checks, no LLM involved.

Layer 1: schema, source URL (HTTP 200 + trusted official domain), date sanity, legal stage
         transitions, de-duplication.
Layer 2: provenance — the verbatim `source_quote` must exist in a saved snapshot of the cited URL.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from datetime import date
from typing import Callable
from urllib.parse import urlparse

from pydantic import ValidationError

from .config import RAW, config, today
from .models import STAGES, CheckResult, Dossier, DraftUpdate, Update, fuzzy_date_bounds
from .store import iter_snapshots, load_trusted_domains, snapshot_index

# ---------------------------------------------------------------------------
# Text normalisation for quote matching
# ---------------------------------------------------------------------------

_QUOTES = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'", "`": "'", "´": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"', "«": '"', "»": '"', "″": '"',
    "「": '"', "」": '"', "『": '"', "』": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
}
_INVISIBLE = re.compile("[­​‌‍⁠﻿]")
_WS = re.compile(r"\s+")
_HYPHEN_BREAK = re.compile(r"(\w)- (\w)")
_ELLIPSIS = re.compile(r"\s*(?:\.\.\.|…|\[\.\.\.\]|\[…\])\s*")
MIN_FRAGMENT = 20


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = _INVISIBLE.sub("", text)
    text = "".join(_QUOTES.get(ch, ch) for ch in text)
    text = _WS.sub(" ", text).strip().lower()
    text = _HYPHEN_BREAK.sub(r"\1\2", text)  # PDF line-break hyphenation: "recy- cled" -> "recycled"
    # CJK text has no spaces between words; extraction may insert some. Drop them between CJK chars.
    text = re.sub(r"(?<=[　-鿿＀-￯]) (?=[　-鿿＀-￯])", "", text)
    return text


def quote_in_text(quote: str, text: str) -> tuple[bool, str]:
    """True if the quote appears verbatim (after normalisation) in text.

    An ellipsis ("..." / "…") may separate fragments; each fragment must be at least
    MIN_FRAGMENT characters and the fragments must appear in order.
    """
    hay = normalise(text)
    fragments = [normalise(f) for f in _ELLIPSIS.split(quote) if f.strip()]
    if not fragments:
        return False, "empty quote"
    pos = 0
    for frag in fragments:
        frag = frag.strip(" \"'")
        if len(frag) < MIN_FRAGMENT and len(fragments) > 1:
            return False, f"fragment too short around ellipsis: '{frag}'"
        idx = hay.find(frag, pos)
        if idx < 0:
            return False, f"not found in snapshot: '{frag[:80]}'"
        pos = idx + len(frag)
    return True, "found"


# ---------------------------------------------------------------------------
# Layer 2
# ---------------------------------------------------------------------------


def snapshots_for_url(url: str, raw_dir=None) -> list:
    """All saved snapshots of a URL (any date)."""
    raw_dir = raw_dir or RAW
    want = url.rstrip("/")
    out = [s for s in iter_snapshots(raw_dir) if s.url.rstrip("/") == want]
    if not out:
        # The same text may have been saved first under another URL (content hash de-duplication).
        idx = snapshot_index(raw_dir)
        h = idx["urls"].get(url) or idx["urls"].get(want)
        if h and h in idx["hashes"]:
            out = [s for s in iter_snapshots(raw_dir) if s.sha256 == h]
    return out


def check_quote(quote: str, source_url: str, snapshot_texts: list[str] | None = None, raw_dir=None) -> CheckResult:
    if snapshot_texts is None:
        snapshot_texts = [s.text for s in snapshots_for_url(source_url, raw_dir)]
    if not snapshot_texts:
        return CheckResult(layer=2, name="quote-provenance", passed=False,
                           detail=f"no saved snapshot for {source_url}")
    reason = ""
    for text in snapshot_texts:
        ok, reason = quote_in_text(quote, text)
        if ok:
            return CheckResult(layer=2, name="quote-provenance", passed=True, severity="info",
                               detail="verbatim quote found in snapshot")
    return CheckResult(layer=2, name="quote-provenance", passed=False, detail=reason)


# ---------------------------------------------------------------------------
# Layer 1
# ---------------------------------------------------------------------------


def domain_trust(url: str, trusted: dict[str, list[str]] | None = None) -> str | None:
    trusted = trusted if trusted is not None else load_trusted_domains()
    host = (urlparse(url).hostname or "").lower()
    for level in ("official", "trade-association", "media"):
        for d in trusted.get(level, []) or []:
            d = d.lower()
            if host == d or host.endswith("." + d):
                return level
    return None


def check_domain(url: str, trusted=None) -> CheckResult:
    level = domain_trust(url, trusted)
    ok = level == "official"
    return CheckResult(layer=1, name="trusted-domain", passed=ok, severity="info" if ok else "reject",
                       detail=f"domain trust: {level or 'not on whitelist'}")


def default_url_status(url: str) -> int:
    from .fetch import HOST_HEADERS, http_client

    with http_client() as c:
        try:
            host = urlparse(url).hostname or ""
            with c.stream("GET", url, headers=HOST_HEADERS.get(host, {})) as r:
                return r.status_code
        except Exception:
            return 0


def check_url_live(url: str, status_fn: Callable[[str], int] | None = None) -> CheckResult:
    status = (status_fn or default_url_status)(url)
    return CheckResult(layer=1, name="url-200", passed=status == 200,
                       severity="info" if status == 200 else "reject", detail=f"HTTP {status}")


def check_event_date(d: str, now: date | None = None) -> CheckResult:
    now = now or today()
    start, _ = fuzzy_date_bounds(d)
    ok = start <= now
    return CheckResult(layer=1, name="event-date", passed=ok, severity="info" if ok else "reject",
                       detail=f"{d} {'<=' if ok else 'is after'} today {now}")


def next_step_expired(d: str, now: date | None = None) -> bool:
    _, end = fuzzy_date_bounds(d)
    return end < (now or today())


def check_stage_change(current: str, proposed: str | None) -> CheckResult:
    if not proposed or proposed == current:
        return CheckResult(layer=1, name="stage-transition", passed=True, severity="info", detail="no stage change")
    if proposed in ("withdrawn", "stalled") or current in ("withdrawn", "stalled"):
        return CheckResult(layer=1, name="stage-transition", passed=False, severity="flag",
                           detail=f"{current} -> {proposed}: terminal-state change needs human review")
    a, b = STAGES.index(current), STAGES.index(proposed)
    jump = b - a
    max_jump = config()["review"]["max_stage_jump"]
    if jump < 0:
        return CheckResult(layer=1, name="stage-transition", passed=False, severity="flag",
                           detail=f"{current} -> {proposed}: stage moves backwards")
    if jump > max_jump:
        return CheckResult(layer=1, name="stage-transition", passed=False, severity="flag",
                           detail=f"{current} -> {proposed}: skips {jump - 1} stages")
    return CheckResult(layer=1, name="stage-transition", passed=True, severity="info",
                       detail=f"{current} -> {proposed}")


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, normalise(a), normalise(b)).ratio()


def check_duplicate(draft: DraftUpdate | Update, dossier: Dossier, exclude_self: bool = False) -> CheckResult:
    seen_self = False
    for u in dossier.updates:
        if exclude_self and not seen_self and u is draft:
            seen_self = True
            continue
        same_quote = normalise(u.source_quote) == normalise(draft.source_quote)
        same_event = u.date == draft.date and str(u.source_url).rstrip("/") == str(draft.source_url).rstrip("/")
        near = u.date == draft.date and _similar(u.summary, draft.summary) > 0.85
        if same_quote or same_event or near:
            return CheckResult(layer=1, name="duplicate", passed=False,
                               detail=f"duplicates existing update of {u.date} ({u.review_id})")
    return CheckResult(layer=1, name="duplicate", passed=True, severity="info", detail="no duplicate")


def check_schema(draft: DraftUpdate) -> CheckResult:
    try:
        Update.model_validate({
            "date": draft.date, "summary": draft.summary, "source_url": draft.source_url,
            "source_quote": draft.source_quote, "source_quote_en": draft.source_quote_en,
            "source_lang": draft.source_lang, "stage_change": draft.stage_change, "review_id": "pending",
        })
    except ValidationError as e:
        return CheckResult(layer=1, name="schema", passed=False, detail=str(e).replace("\n", " ")[:400])
    return CheckResult(layer=1, name="schema", passed=True, severity="info", detail="valid")


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def deterministic_checks(draft: DraftUpdate, dossier: Dossier, snapshot_texts: list[str] | None = None,
                         status_fn=None, trusted=None, now: date | None = None,
                         check_urls: bool | None = None) -> list[CheckResult]:
    """All layer-1 and layer-2 checks for a drafted update."""
    if check_urls is None:
        check_urls = config()["review"]["check_source_urls"]
    results = [check_schema(draft), check_domain(draft.source_url, trusted)]
    if check_urls:
        results.append(check_url_live(draft.source_url, status_fn))
    results += [
        check_event_date(draft.date, now),
        check_stage_change(dossier.stage, draft.stage_change),
        check_duplicate(draft, dossier),
        check_quote(draft.source_quote, draft.source_url, snapshot_texts),
    ]
    for ns in draft.next_steps:
        if next_step_expired(ns.date, now):
            ns.status = "to-be-confirmed"
            results.append(CheckResult(layer=1, name="next-step-date", passed=False, severity="flag",
                                       detail=f"next step dated {ns.date} is already past; marked to-be-confirmed"))
    return results


def blocking(results: list[CheckResult]) -> list[CheckResult]:
    return [r for r in results if not r.passed and r.severity == "reject"]


def flags(results: list[CheckResult]) -> list[CheckResult]:
    return [r for r in results if not r.passed and r.severity == "flag"]


def validate_dossier(d: Dossier, now: date | None = None, status_fn=None, trusted=None,
                     check_urls: bool = False, raw_dir=None) -> list[CheckResult]:
    """Layer 1 + 2 over an entire stored dossier (used by `validate` and in CI)."""
    out: list[CheckResult] = []
    for link in d.official_links:
        r = check_domain(str(link), trusted)
        r.name = f"official-link-domain {link}"
        out.append(r)
    for i, u in enumerate(d.updates):
        tag = f"[{d.id} update {u.date}]"
        for r in (check_event_date(u.date, now), check_domain(str(u.source_url), trusted),
                  check_quote(u.source_quote, str(u.source_url), raw_dir=raw_dir)):
            r.detail = f"{tag} {r.detail}"
            out.append(r)
        if check_urls:
            r = check_url_live(str(u.source_url), status_fn)
            r.detail = f"{tag} {r.detail}"
            out.append(r)
        for other in d.updates[i + 1:]:
            if normalise(other.source_quote) == normalise(u.source_quote) or (
                other.date == u.date and str(other.source_url) == str(u.source_url)
            ):
                out.append(CheckResult(layer=1, name="duplicate", passed=False,
                                       detail=f"{tag} duplicate of update {other.date}"))
    for ns in d.next_steps:
        r = check_domain(str(ns.source_url), trusted)
        r.detail = f"[{d.id} next step {ns.date}] {r.detail}"
        out.append(r)
        if next_step_expired(ns.date, now) and ns.status != "to-be-confirmed":
            out.append(CheckResult(layer=1, name="next-step-date", passed=False, severity="flag",
                                   detail=f"[{d.id}] next step {ns.date} has passed; mark to-be-confirmed"))
    return out


def excerpt_for_review(text: str, quote: str, limit: int, head: int = 6000) -> str:
    """Text to show a reviewer. Long documents are cut to the document head plus a wide window
    around where the quote occurs, so the reviewer always sees the quoted passage in context."""
    if len(text) <= limit:
        return text
    hay = normalise(text)
    frag = normalise(_ELLIPSIS.split(quote)[0])[:120]
    idx = hay.find(frag)
    if idx < 0:
        return text[:limit]
    centre = int(idx / max(len(hay), 1) * len(text))  # normalisation shrinks text slightly; window absorbs drift
    half = (limit - head) // 2
    start, end = max(head, centre - half), min(len(text), centre + half)
    return f"{text[:head]}\n\n[... {start - head} characters omitted ...]\n\n{text[start:end]}" + (
        f"\n\n[... {len(text) - end} characters omitted ...]" if end < len(text) else "")
