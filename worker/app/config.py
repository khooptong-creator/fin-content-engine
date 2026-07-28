"""Config-table access (Part II §2.5).

Tuning values live in the `config` table; this module loads them, typed, with
sensible defaults so a missing key never breaks a job. Caches per key for the
duration of a process — the worker reads config at job-fire time, so to pick up
a changed config value, restart the worker (or call `clear_config_cache()`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.db import get_pool


# ---------------------------------------------------------------------------
# Typed config sections. Each mirrors a row in the `config` table.
# Adding a field here requires a default (so a missing DB value doesn't crash).
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ClusteringConfig:
    # NOTE: 0.92 is the empirical operating point for gte-small on finance news,
    # NOT the spec's original 0.78 guess. gte-small has a high baseline cosine
    # similarity for in-domain text (median pairwise ~0.79); 0.78 merges almost
    # everything. Tuned via the §5 fixture sweep — see TUNING.md. If the embedding
    # model ever changes, re-sweep before trusting this number.
    similarity_threshold: float = 0.92
    embedding_model: str = "gte-small"
    embedding_dim: int = 384
    min_items_for_story: int = 1
    max_story_age_hours: int = 48
    title_weight_repeat: int = 2
    body_truncate_chars: int = 500
    keyword_fallback_min_tokens: int = 2


@dataclass(frozen=True)
class IngestConfig:
    rss_poll_minutes: int = 30
    edgar_poll_minutes: int = 60
    nse_poll_minutes: int = 30
    market_hours_only: bool = False
    max_items_per_cycle: int = 50
    max_full_text_fetch_seconds: int = 10
    embedding_timeout_seconds: int = 5
    embedding_degraded_threshold: float = 0.20
    embedding_max_retries: int = 3


@dataclass(frozen=True)
class EdgarConfig:
    form_types: tuple[str, ...] = ("8-K", "13F-HR")
    company_watch: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Loader. Caches per key; call clear_config_cache() to invalidate.
# ---------------------------------------------------------------------------

_cache: dict[str, dict[str, Any]] = {}


async def _load(key: str) -> dict[str, Any]:
    if key in _cache:
        return _cache[key]
    pool = await get_pool()
    async with pool.connection() as conn:
        from app.db import _fetchone

        row = await _fetchone(conn, "SELECT value FROM config WHERE key = %s", key)
    value = dict(row["value"]) if row else {}
    _cache[key] = value
    return value


async def get_clustering_config() -> ClusteringConfig:
    raw = await _load("clustering")
    return ClusteringConfig(**{k: v for k, v in raw.items() if k in ClusteringConfig.__annotations__ or hasattr(ClusteringConfig, k)})


async def get_ingest_config() -> IngestConfig:
    raw = await _load("ingest")
    return IngestConfig(**{k: v for k, v in raw.items() if k in IngestConfig.__annotations__ or hasattr(IngestConfig, k)})


async def get_edgar_config() -> EdgarConfig:
    raw = await _load("edgar")
    # Normalize lists to tuples (tuples are hashable + frozen-dataclass-friendly).
    raw = {**raw}
    if "form_types" in raw and isinstance(raw["form_types"], list):
        raw["form_types"] = tuple(raw["form_types"])
    if "company_watch" in raw and isinstance(raw["company_watch"], list):
        raw["company_watch"] = tuple(raw["company_watch"])
    return EdgarConfig(**{k: v for k, v in raw.items() if hasattr(EdgarConfig, k)})


def clear_config_cache() -> None:
    """Invalidate the cached config so the next read hits the DB."""
    _cache.clear()


# ---------------------------------------------------------------------------
# JSON helpers for tests / migrations
# ---------------------------------------------------------------------------

def dumps(value: dict[str, Any]) -> str:
    return json.dumps(value, default=str)
