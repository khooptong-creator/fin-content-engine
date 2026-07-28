"""RSS source (Part II §3.3).

feedparser for parsing; charset-normalizer for encoding gremlins; readability-lxml
for partial-full_text rescue; httpx for HTTP with backoff. Every failure mode in
the §3.3 table is handled — none of them block insertion of the (clusterable)
title+url.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

import charset_normalizer as chardet
import feedparser
import httpx
import structlog
from readability import Document  # type: ignore[import-untyped]

from app.config import get_ingest_config
from app.sources.base import NormalizedItem, RawItem, Source, SourceError
from app.sources.canonicalize import canonicalize_url

log = structlog.get_logger()

# Backoff schedule after Retry-After is unavailable (Part II §3.3).
BACKOFF_SECONDS = [1, 2, 4, 8]

# Min length at which we consider `full_text` complete (vs. a 2-line summary).
MIN_FULL_TEXT_CHARS = 500


class RSSSource(Source):
    kind = "rss"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def fetch(self, source_row: Any) -> list[RawItem]:
        """Fetch + parse. Raises SourceError if the response isn't a feed."""
        client = self._client or httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={"user-agent": "Fin-Content-Engine/0.1 (+reader)"},
        )
        own_client = self._client is None
        try:
            raw_bytes, status, warnings = await self._fetch_with_backoff(
                client, source_row.url
            )
            if raw_bytes is None:
                raise SourceError(f"http status {status} after retries")

            # Decode with detected charset (charset-normalizer on bytes).
            decoded, encoding_warning = _decode(raw_bytes)
            if encoding_warning:
                warnings.append(encoding_warning)

            # Sniff: is this actually a feed? (Part II §3.3: HTML error pages
            # with HTTP 200 are common.)
            stripped = decoded.lstrip()[:512].lower()
            if not (
                stripped.startswith("<?xml")
                or stripped.startswith("<rss")
                or "<feed" in stripped[:200]
            ):
                raise SourceError("not_a_feed")

            parsed = feedparser.parse(decoded)
            if parsed.bozo and not parsed.entries:
                raise SourceError(f"feedparser bozo: {parsed.bozo_exception}")

            items: list[RawItem] = []
            for entry in parsed.entries:
                title = entry.get("title", "")
                link = entry.get("link", "")
                published = _entry_published(entry)
                summary_or_content = (
                    entry.get("content", [{}])[0].get("value")
                    if entry.get("content")
                    else entry.get("summary", "")
                )
                items.append(
                    RawItem(
                        source_id=str(source_row.id),
                        raw_title=title,
                        raw_url=link,
                        raw_published_at=published,
                        raw_html_or_xml=summary_or_content or "",
                        fetch_meta={"http_status": status},
                    )
                )
                items[-1].fetch_meta["warnings"] = list(warnings)
            return items
        finally:
            if own_client:
                await client.aclose()

    async def normalize(self, raw: RawItem) -> NormalizedItem:
        """Clean the raw item and (if needed) rescue a thin full_text."""
        warnings = list(raw.fetch_meta.get("warnings", []))

        # Start with whatever content the feed gave us.
        body = _strip_html(raw.raw_html_or_xml)
        full_text: str | None = body if body else None

        # If it's missing or a teaser, try fetching the article.
        if not full_text or len(full_text) < MIN_FULL_TEXT_CHARS:
            rescued = await _rescue_full_text(raw.raw_url)
            if rescued:
                full_text = rescued
            elif full_text is None:
                full_text = None
                if raw.raw_url:
                    warnings.append("full_text_extraction_failed")

        if raw.raw_published_at is None:
            warnings.append("date_missing")

        return NormalizedItem.build(
            source_id=raw.source_id,
            title=raw.raw_title,
            url=raw.raw_url,
            published_at=raw.raw_published_at,
            full_text=full_text,
            warnings=warnings,
        )

    async def _fetch_with_backoff(
        self, client: httpx.AsyncClient, url: str
    ) -> tuple[bytes | None, int, list[str]]:
        """Return (body, status, warnings). body=None means give up."""
        warnings: list[str] = []
        last_status = 0
        for attempt, delay in enumerate([0] + BACKOFF_SECONDS):
            if delay:
                await asyncio.sleep(delay)
            try:
                resp = await client.get(url)
            except httpx.HTTPError as exc:
                warnings.append(f"http_error_attempt{attempt}:{exc.__class__.__name__}")
                last_status = -1
                continue
            last_status = resp.status_code
            if resp.status_code == 200:
                return resp.content, resp.status_code, warnings
            if resp.status_code in (429, 500, 502, 503, 504):
                retry_after = resp.headers.get("retry-after")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else None
                if wait and attempt < len(BACKOFF_SECONDS):
                    await asyncio.sleep(wait)
                warnings.append(f"http_{resp.status_code}_attempt{attempt}")
                continue
            # Other 4xx: don't retry.
            return None, resp.status_code, warnings
        return None, last_status, warnings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _decode(raw: bytes) -> tuple[str, str | None]:
    """Decode bytes with detected charset. Returns (text, warning_or_None)."""
    # charset_normalizer.detect() returns a dict {encoding, language, confidence}.
    try:
        result = chardet.detect(raw)
    except Exception:  # noqa: BLE001
        return raw.decode("utf-8", errors="replace"), "charset_detection_failed"
    detected_encoding = result.get("encoding") if isinstance(result, dict) else None
    if not detected_encoding:
        decoded = raw.decode("utf-8", errors="replace")
        return decoded, None
    try:
        decoded = raw.decode(detected_encoding, errors="replace")
    except (LookupError, UnicodeDecodeError):
        decoded = raw.decode("utf-8", errors="replace")
        return decoded, "charset_decode_failed"

    # Compare against declared charset in the raw bytes (XML/HTML declaration).
    declared = raw[:200].decode("ascii", errors="ignore").lower()
    declared_charset = None
    if "charset=" in declared:
        declared_charset = (
            declared.split("charset=", 1)[1]
            .split('"')[0].split("'")[0].split(";")[0].strip()
        )
    warning = (
        "encoding_corrected"
        if declared_charset and declared_charset.lower() != detected_encoding.lower()
        else None
    )
    return decoded, warning


def _entry_published(entry: dict) -> datetime | None:
    """Best-effort extraction of published/updated from a feedparser entry."""
    for key in ("published_parsed", "updated_parsed"):
        st = entry.get(key)
        if st:
            try:
                import time as _time

                return datetime.fromtimestamp(_time.mktime(st), tz=timezone.utc)
            except Exception:  # noqa: BLE001
                continue
    # Fallback to string fields.
    for key in ("published", "updated"):
        v = entry.get(key)
        if v:
            try:
                import email.utils as eu

                tt = eu.parsedate_tz(v)
                if tt:
                    return datetime.fromtimestamp(eu.mktime_tz(tt), tz=timezone.utc)
            except Exception:  # noqa: BLE001
                continue
    return None


def _strip_html(s: str) -> str:
    """Strip tags from an HTML fragment. Conservative; readability handles real pages."""
    if not s:
        return ""
    import html
    import re

    text = re.sub(r"<[^>]+>", " ", s)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


async def _rescue_full_text(url: str) -> str | None:
    """Fetch the article URL and extract body text via readability.
    Time-boxed (Part II §3.3). Returns None on any failure."""
    if not url:
        return None
    cfg = await get_ingest_config()
    try:
        async with asyncio.timeout(cfg.max_full_text_fetch_seconds):
            async with httpx.AsyncClient(
                timeout=cfg.max_full_text_fetch_seconds,
                follow_redirects=True,
                headers={"user-agent": "Fin-Content-Engine/0.1 (+reader)"},
            ) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return None
                doc = Document(resp.text)
                summary = doc.summary()
                return _strip_html(summary)
    except Exception:  # noqa: BLE001 — readability failures are expected, not fatal
        return None


# Re-export so callers can build a pre-configured client for tests.
__all__ = ["RSSSource", "SourceError", "NormalizedItem", "RawItem", "canonicalize_url"]
