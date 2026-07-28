"""Source registry (Part II §3.1).

Routes a source row to its implementation by `kind`. Adding a source type =
add a class here. P1 has rss/edgar/nse; `internal` (LE) is reserved for P2.
"""

from __future__ import annotations

from app.sources.base import Source, SourceError
from app.sources.edgar import EDGARSource
from app.sources.nse import NSESource
from app.sources.rss import RSSSource

_REGISTRY: dict[str, type[Source]] = {
    "rss": RSSSource,
    "edgar": EDGARSource,
    "nse": NSESource,
    # 'internal' reserved for P2 (LE price tables). No P1 implementation.
}


def get_source(kind: str) -> Source:
    """Instantiate the source implementation for a given kind."""
    cls = _REGISTRY.get(kind)
    if cls is None:
        raise SourceError(f"unknown_source_kind:{kind}")
    return cls()


__all__ = ["get_source", "Source", "SourceError", "RSSSource", "EDGARSource", "NSESource"]
