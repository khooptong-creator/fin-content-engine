"""Source protocol + shared types (Part II §3.1).

One protocol, three (P1) implementations: rss, edgar, nse. `internal` (LE)
exists as a kind but has no implementation in P1 — its source row is seeded
active=false; P2 adds the poller.
"""

from __future__ import annotations

import abc
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.sources.canonicalize import canonicalize_url


class SourceError(Exception):
    """Raised when a source returns something unusable (not a feed, bad data).
    The orchestrator catches this, logs, marks the source unhealthy, and moves on."""


@dataclass
class RawItem:
    """Exactly what the source gave us, pre-cleaning."""
    source_id: str
    raw_title: str
    raw_url: str
    raw_published_at: datetime | None
    raw_html_or_xml: str
    fetch_meta: dict = field(default_factory=dict)


@dataclass
class NormalizedItem:
    """What we store: cleaned, canonicalized, hashable, tz-aware UTC."""
    source_id: str
    title: str
    url: str
    published_at: datetime
    full_text: str | None
    hash: str
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def build(
        cls,
        *,
        source_id: str,
        title: str,
        url: str,
        published_at: datetime | None,
        full_text: str | None,
        warnings: list[str] | None = None,
    ) -> "NormalizedItem":
        """Construct a NormalizedItem, applying canonicalization + hashing +
        UTC normalization. This is the single chokepoint — every source goes
        through it."""
        clean_title = _clean_text(title)
        canon_url = canonicalize_url(url)
        ts = _to_utc(published_at)
        h = _hash(clean_title, canon_url)
        return cls(
            source_id=source_id,
            title=clean_title,
            url=canon_url,
            published_at=ts,
            full_text=full_text,
            hash=h,
            warnings=list(warnings or []),
        )


def _clean_text(s: str) -> str:
    """Collapse whitespace, strip HTML entities' common forms."""
    import html
    import re

    if not s:
        return ""
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _to_utc(dt: datetime | None) -> datetime:
    """Coerce to tz-aware UTC. None → now() (Part II §3.3: never block insertion
    on a bad date; surface it as a warning instead)."""
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        # Assume UTC for naive datetimes (EDGAR gives UTC; some feeds do too).
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _hash(title: str, url: str) -> str:
    """SHA-256 over normalized title+url. Stable across runs (§5.6 unit test)."""
    h = hashlib.sha256()
    h.update(title.encode("utf-8"))
    h.update(b"|")
    h.update(url.encode("utf-8"))
    return h.hexdigest()


class Source(abc.ABC):
    """Base class for source implementations. Subclasses implement fetch/normalize."""

    kind: str = "abstract"

    @abc.abstractmethod
    async def fetch(self, source_row) -> list[RawItem]:  # type: ignore[override]
        ...

    @abc.abstractmethod
    async def normalize(self, raw: RawItem) -> NormalizedItem:
        ...
