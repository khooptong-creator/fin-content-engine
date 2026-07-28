"""NSE announcements source (Part II §3.5 — scope-cut).

P1 ships the third-party/mirror RSS route. The seeded NSE source row points at
an invalid placeholder URL and `active=false`; if a reliable NSE RSS is found at
build time, replace the URL and flip active=true. **P1 will not scrape NSE.**

Implementation: if the source's URL is a working RSS, behave exactly like the
RSS source (the failure-mode handling is identical). If the URL is invalid,
fetch() raises SourceError('nse_disabled') — caught by the orchestrator as a
known-skip, not a failure to log.
"""

from __future__ import annotations

from typing import Any

import structlog

from app.sources.base import NormalizedItem, RawItem, Source, SourceError
from app.sources.rss import RSSSource

log = structlog.get_logger()


class NSESource(Source):
    """Thin wrapper: delegates to RSSSource when the URL is real, else no-ops.

    NSESource exists as a distinct class so the worker's source-kind routing
    (§3.2) can keep NSE separate even if its implementation is currently RSS.
    """

    kind = "nse"

    def __init__(self) -> None:
        self._rss = RSSSource()

    async def fetch(self, source_row: Any) -> list[RawItem]:
        url = (source_row.url or "").strip()
        if not url or "example.invalid" in url or not source_row.active:
            # Documented-skip, not an error. The soak checklist (§5.7 step 4)
            # accepts NSE active=false as long as it was *seeded* inactive,
            # not auto-disabled mid-run.
            raise SourceError("nse_disabled")
        # If we have a real URL, treat it as RSS (Part II §3.5 explicit choice).
        return await self._rss.fetch(source_row)

    async def normalize(self, raw: RawItem) -> NormalizedItem:
        return await self._rss.normalize(raw)


__all__ = ["NSESource", "SourceError"]
