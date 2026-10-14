"""Stage 1 — fetch all sources, de-duplicate, and store text snapshots in data/raw/."""

from __future__ import annotations

import hashlib
import io
import logging
from datetime import datetime, timedelta, timezone
from time import mktime

import feedparser
import httpx
import trafilatura
from lxml import html as lxml_html

from .config import config, today
from .models import Snapshot, Source
from .store import load_sources, save_snapshot, save_snapshot_index, snapshot_index

log = logging.getLogger(__name__)


def http_client() -> httpx.Client:
    cfg = config()["fetch"]
    return httpx.Client(
        headers={
            "User-Agent": cfg["user_agent"],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf;q=0.8,*/*;q=0.5",
            "Accept-Language": "en;q=1.0, *;q=0.5",
        },
        follow_redirects=True,
        timeout=cfg["timeout_seconds"],
    )


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _full_text(raw_html: str) -> str:
    tree = lxml_html.fromstring(raw_html)
    for bad in tree.xpath("//script|//style|//noscript|//nav|//header|//footer"):
        bad.drop_tree()
    lines = [" ".join(t.split()) for t in tree.itertext()]
    return "\n".join(line for line in lines if line)


def extract_text(content: bytes, content_type: str, mode: str = "main") -> tuple[str, str | None]:
    """Return (text, title). PDFs are read with pypdf; HTML with trafilatura (or full text)."""
    if "pdf" in content_type or content[:5] == b"%PDF-":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        return text.strip(), None
    raw = content.decode("utf-8", errors="replace")
    title = None
    try:
        t = lxml_html.fromstring(raw.encode()).findtext(".//title")
        title = " ".join(t.split()) if t else None
    except Exception:
        pass
    if mode == "full":
        return _full_text(raw.encode()), title
    main = trafilatura.extract(raw, include_tables=True, favor_recall=True, include_comments=False) or ""
    full = _full_text(raw.encode())
    # trafilatura sometimes drops most of a structured page; fall back to full text.
    if len(main) < 0.25 * len(full):
        return full, title
    return main, title


def make_snapshot(source: Source, url: str, text: str, title: str | None, published: str | None = None) -> Snapshot:
    digest = sha256(text)
    day = today().isoformat()
    return Snapshot(
        id=f"{day}/{source.id}-{digest[:10]}",
        source_id=source.id,
        url=url,
        title=title,
        fetched_at=datetime.now(timezone.utc),
        published=published,
        sha256=digest,
        trust=source.trust,
        jurisdiction=source.jurisdiction,
        lang=source.lang,
        text=text,
    )


# Per-host request headers. The EU Publications Office (CELLAR) serves the official legal texts that
# EUR-Lex displays; it negotiates on Accept/Accept-Language and wants ISO 639-2 language codes.
HOST_HEADERS = {
    "publications.europa.eu": {"Accept": "application/xhtml+xml, text/html;q=0.9", "Accept-Language": "eng"},
}


def fetch_url(client: httpx.Client, url: str, mode: str = "main") -> tuple[str, str | None, int]:
    host = httpx.URL(url).host
    r = client.get(url, headers=HOST_HEADERS.get(host, {}))
    if r.status_code != 200 or not r.content:
        raise httpx.HTTPStatusError(f"HTTP {r.status_code} (empty={not r.content})", request=r.request, response=r)
    text, title = extract_text(r.content, r.headers.get("content-type", ""), mode)
    return text, title, r.status_code


def _keep(source: Source, text: str) -> bool:
    if not source.keywords:
        return True
    low = text.lower()
    return any(k.lower() in low for k in source.keywords)


# --- source types -------------------------------------------------------------


def fetch_rss(client: httpx.Client, source: Source) -> list[Snapshot]:
    cfg = config()["fetch"]
    r = client.get(str(source.url))
    r.raise_for_status()
    feed = feedparser.parse(r.content)
    cutoff = datetime.now(timezone.utc) - timedelta(days=cfg["max_feed_item_age_days"])
    out = []
    for entry in feed.entries[: cfg["max_items_per_feed"]]:
        stamp = entry.get("published_parsed") or entry.get("updated_parsed")
        published = None
        if stamp:
            dt = datetime.fromtimestamp(mktime(stamp), tz=timezone.utc)
            if dt < cutoff:
                continue
            published = dt.date().isoformat()
        link = entry.get("link")
        if not link:
            continue
        teaser = f"{entry.get('title', '')}\n{entry.get('summary', '')}"
        if not _keep(source, teaser):
            continue
        try:
            text, title, _ = fetch_url(client, link, source.extract)
        except Exception as e:  # keep the feed teaser rather than nothing; it is still the publisher's text
            log.info("  item fetch failed (%s), keeping feed text: %s", e, link)
            text, title = trafilatura.extract(teaser) or teaser, None
        out.append(make_snapshot(source, link, text, title or entry.get("title"), published))
    return out


def fetch_page(client: httpx.Client, source: Source) -> list[Snapshot]:
    text, title, _ = fetch_url(client, str(source.url), source.extract)
    return [make_snapshot(source, str(source.url), text, title)]


def api_federal_register(client: httpx.Client, source: Source) -> list[Snapshot]:
    r = client.get(str(source.url))
    r.raise_for_status()
    out = []
    for doc in r.json().get("results", [])[: config()["fetch"]["max_items_per_feed"]]:
        body = f"{doc.get('title', '')}\n\n{doc.get('abstract') or ''}"
        if doc.get("raw_text_url"):
            try:
                rt = client.get(doc["raw_text_url"])
                if rt.status_code == 200:
                    body += "\n\n" + _full_text(rt.content) if b"<" in rt.content[:200] else "\n\n" + rt.text
            except httpx.HTTPError:
                pass
        meta = f"Agency: {', '.join(a.get('name', '') for a in doc.get('agencies', []))}\nType: {doc.get('type')}\nPublished: {doc.get('publication_date')}\n\n"
        out.append(make_snapshot(source, doc["html_url"], meta + body, doc.get("title"), doc.get("publication_date")))
    return out


API_HANDLERS = {"federal_register": api_federal_register}


def fetch_source(client: httpx.Client, source: Source) -> list[Snapshot]:
    if source.type == "rss":
        return fetch_rss(client, source)
    if source.type == "page-watch":
        return fetch_page(client, source)
    if source.type == "api":
        return API_HANDLERS[source.handler](client, source)
    log.info("skip %s: type %s is not fetched automatically", source.id, source.type)
    return []


def run(source_ids: list[str] | None = None) -> dict:
    """Fetch every enabled source; save only new or changed documents. Returns a run report."""
    index = snapshot_index()
    report = {"new": [], "unchanged": 0, "errors": {}}
    sources = [s for s in load_sources() if s.enabled and (not source_ids or s.id in source_ids)]
    with http_client() as client:
        for src in sources:
            if src.frequency == "weekly" and today().weekday() != 0 and not source_ids:
                continue
            log.info("fetch %s (%s)", src.id, src.type)
            try:
                snaps = fetch_source(client, src)
            except Exception as e:
                report["errors"][src.id] = f"{type(e).__name__}: {e}"[:300]
                log.warning("  failed: %s", report["errors"][src.id])
                continue
            for snap in snaps:
                if not snap.text.strip():
                    continue
                if snap.sha256 in index["hashes"] or index["urls"].get(snap.url) == snap.sha256:
                    report["unchanged"] += 1
                    continue
                save_snapshot(snap)
                index["hashes"][snap.sha256] = snap.id
                index["urls"][snap.url] = snap.sha256
                report["new"].append(snap.id)
    save_snapshot_index(index)
    return report


def capture(url: str, source_id: str = "manual", trust: str = "official", jurisdiction: str = "GLOBAL",
            mode: str = "main", lang: str = "en") -> Snapshot:
    """Capture one URL as a snapshot (used for seeding dossiers and for re-verification)."""
    src = Source(id=source_id, name=source_id, url=url, type="page-watch", jurisdiction=jurisdiction,
                 trust=trust, extract=mode, lang=lang)
    with http_client() as client:
        text, title, _ = fetch_url(client, url, mode)
    snap = make_snapshot(src, url, text, title)
    index = snapshot_index()
    if snap.sha256 in index["hashes"]:
        snap.id = index["hashes"][snap.sha256]
    else:
        save_snapshot(snap)
        index["hashes"][snap.sha256] = snap.id
    index["urls"][url] = snap.sha256
    save_snapshot_index(index)
    return snap
