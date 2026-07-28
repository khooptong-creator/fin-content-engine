"""SEC EDGAR source (Part II §3.4).

Current-filings Atom feed for 8-K + 13F-HR. Mandatory human-readable User-Agent.
Rate limit: 10 req/s, no concurrency — Semaphore(1) + 0.1s sleep, baked in now.
Canonical id = accession number; hash on (accession + form_type).
full_text = filing index URL (the landing page); deep-fetch is P2.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import feedparser
import httpx
import structlog

from app.config import get_edgar_config
from app.sources.base import NormalizedItem, RawItem, Source, SourceError
from app.sources.canonicalize import canonicalize_url

log = structlog.get_logger()

# EDGAR current-filings Atom endpoint. `type` is filled per form.
EDGAR_BASE = "https://www.sec.gov/cgi-bin/browse-edgar"

# EDGAR fair-access: 10 req/s, no concurrency. Single global semaphore.
_EDGAR_SEMAPHORE = asyncio.Semaphore(1)
_EDGAR_MIN_INTERVAL = 0.1  # seconds between calls

# Accession numbers look like 0000320193-25-000123 (with dashes) or as a path segment.
_ACCESSION_RE = re.compile(r"accession-number=([\w-]+)|/data/\d+/([\d-]+)")


class EDGARSource(Source):
    kind = "edgar"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def fetch(self, source_row: Any) -> list[RawItem]:
        cfg = await get_edgar_config()
        client = self._client or httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={
                # Mandatory per EDGAR fair-access policy; carries your email.
                "user-agent": _user_agent(),
                "accept": "application/atom+xml",
            },
        )
        own_client = self._client is None
        items: list[RawItem] = []
        try:
            for form_type in cfg.form_types:
                url = (
                    EDGAR_BASE
                    + "?"
                    + urlencode(
                        {
                            "action": "getcurrent",
                            "type": form_type,
                            "output": "atom",
                            "start": 0,
                            "count": 40,
                        }
                    )
                )
                async with _EDGAR_SEMAPHORE:
                    await asyncio.sleep(_EDGAR_MIN_INTERVAL)
                    try:
                        resp = await client.get(url)
                    except httpx.HTTPError as exc:
                        log.warning("edgar_http_error", form=form_type, error=str(exc))
                        continue
                    if resp.status_code != 200:
                        log.warning(
                            "edgar_non_200",
                            form=form_type,
                            status=resp.status_code,
                        )
                        continue
                    await asyncio.sleep(_EDGAR_MIN_INTERVAL)
                # Optional company_watch filter: keep only matching filers.
                # Empty watch = broad capture (default in P1; you tune later).
                watch = {c.lower() for c in cfg.company_watch}
                parsed = feedparser.parse(resp.text)
                for entry in parsed.entries:
                    # feedparser returns `author` differently for RSS vs Atom:
                    # RSS → string; Atom → {"name": ..., "href": ...}. Handle both.
                    author = entry.get("author", "")
                    if isinstance(author, dict):
                        filer = author.get("name", "") or entry.get("title", "")
                    else:
                        filer = author or entry.get("title", "")
                    if watch and not any(w in filer.lower() for w in watch):
                        continue
                    accession = _extract_accession(entry, resp.text)
                    if not accession:
                        continue
                    link = entry.get("link", "")
                    published = _atom_published(entry)
                    form = entry.get("title", form_type)
                    items.append(
                        RawItem(
                            source_id=str(source_row.id),
                            raw_title=f"{form} — {filer}",
                            raw_url=link or _index_url(accession),
                            raw_published_at=published,
                            raw_html_or_xml=entry.get("summary", ""),
                            fetch_meta={
                                "form_type": form_type,
                                "filer": filer,
                                "accession": accession,
                                "http_status": resp.status_code,
                            },
                        )
                    )
            if not items:
                # No matching filings this cycle — that's fine, not an error.
                return []
            return items
        finally:
            if own_client:
                await client.aclose()

    async def normalize(self, raw: RawItem) -> NormalizedItem:
        accession = raw.fetch_meta.get("accession", "")
        form_type = raw.fetch_meta.get("form_type", "")
        # Hash on accession + form_type so the same filing across two EDGAR feeds
        # collapses into one item. (Per §3.4.)
        title = f"{form_type} {accession} {raw.raw_title}"
        url = canonicalize_url(raw.raw_url)
        # Override the hash to be accession-based, not title+url-based.
        from app.sources.base import _hash, _to_utc

        return NormalizedItem(
            source_id=raw.source_id,
            title=_clean(raw.raw_title),
            url=url,
            published_at=_to_utc(raw.raw_published_at),
            full_text=raw.raw_url,  # store the index URL (Part II §3.4)
            hash=_hash(accession, form_type),
            warnings=["edgar_index_url_only"],
        )


def _user_agent() -> str:
    from app.settings import get_settings

    return get_settings().edgar_user_agent


def _extract_accession(entry: dict, raw_xml: str) -> str | None:
    """Pull the accession number from the entry id/link or the raw XML."""
    # feedparser gives entry.id like .../accession-number=000032019325000123
    eid = entry.get("id", "") or entry.get("link", "")
    m = _ACCESSION_RE.search(eid)
    if m:
        return m.group(1) or m.group(2)
    # Fallback: scan the entry's own XML chunk.
    m = _ACCESSION_RE.search(raw_xml)
    return (m.group(1) or m.group(2)) if m else None


def _index_url(accession: str) -> str:
    """Filing index URL given an accession. EDGAR's canonical landing page."""
    clean = accession.replace("-", "")
    if len(clean) >= 10:
        cik = clean[-10:-2] if len(clean) >= 10 else clean[-10:]
        # CIK is the first 10 digits of the accession (without dashes).
        cik_full = clean[:10].lstrip("0") or "0"
        return f"https://www.sec.gov/Archives/edgar/data/{int(cik_full)}/{clean}/"
    return f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=&type=&dateb=&owner=include&count=40&search_text={accession}"


def _atom_published(entry: dict) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        st = entry.get(key)
        if st:
            try:
                import time as _time

                return datetime.fromtimestamp(_time.mktime(st), tz=timezone.utc)
            except Exception:  # noqa: BLE001
                continue
    return None


def _clean(s: str) -> str:
    import html
    import re

    if not s:
        return ""
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


__all__ = ["EDGARSource", "SourceError"]
