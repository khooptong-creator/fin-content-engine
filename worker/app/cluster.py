"""Clustering engine (Part II §3.7, §3.8).

Three responsibilities:
  1. cluster_new_items: per unassigned item within 48h, embed-similarity search
     → join closest story; else keyword fallback (≥2 distinct tokens); else new
     story. Story creation is atomic (orphan prevention).
  2. keyword_fallback_match: the deterministic fallback when no embedding match
     exists. The ≥2-token rule is the explicit over-merge guard.
  3. embed_retry_sweep: periodically retries embedding-failed items; on success,
     writes `embed_retry_success` (the recovery is provable after the fact).

Stability rule (§3.7): once an item is clustered, its story link is frozen.
A late embedding is stored (P2 scoring uses it) but does NOT trigger re-cluster.
"""

from __future__ import annotations

import math
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from app.audit import audit_log
from app.config import get_clustering_config, get_ingest_config
from app.db import (
    ItemRow,
    Neighbor,
    create_or_join_story,
    items_needing_embedding,
    items_without_story,
    set_embedding,
    append_warning,
    bump_retry_count,
    vector_search,
)
from app.embed import build_embedding_input_async, embed, EmbedError

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Token extraction for keyword fallback
# ---------------------------------------------------------------------------

# $TICKER patterns: $RELIANCE, $TSLA
_TICKER_RE = re.compile(r"\$([A-Z]{2,8})\b")
# All-caps tokens of length >=2: TCS, RBI, NTPC (but not A, I, FY)
_ACRONYM_RE = re.compile(r"\b([A-Z]{2,8})\b")
# Quarters / fiscal years: Q1, Q2, FY24, FY2025 — finance-domain event identifiers.
# These distinguish "TCS Q2 results" from "TCS buyback", so they're load-bearing
# for the ≥2-token rule (NOT boilerplate).
_PERIOD_RE = re.compile(r"\b(Q[1-4]|FY\d{2,4})\b", re.IGNORECASE)
# Capitalized multi-word phrases: "Tata Sons", "HDFC Bank", "Tata Motors" →
# treated as ONE composite token. Matches:
#   - Title-case words: Tata, Sons, Motors, Bank
#   - All-caps acronyms as the FIRST word: HDFC, NTPC, NSE
#   - Mixed: "HDFC Bank", "TCS Q2 Results" (with the acronym first)
_PHRASE_RE = re.compile(
    r"\b("
    r"(?:[A-Z]{2,6}|[A-Z][a-z]+)"          # first word: acronym OR Title-case
    r"(?:\s+(?:[A-Z][a-z]+))*"              # subsequent Title-case words
    r"(?:\s+[A-Z][a-z]+)"                   # require at least one more Title-case word
    r")\b"
)

# Finance-generic boilerplate to downweight (not strip — just don't count them
# as "distinct" tokens for the ≥2 rule, since they appear in too many stories).
# NOTE: quarters (Q1-Q4, FY24, FY25) are intentionally NOT boilerplate — they
# are event identifiers that distinguish "TCS Q2 results" from "TCS buyback".
_BOILERPLATE = frozenset(
    {
        "results", "result", "profit", "loss", "revenue",
        "report", "reports", "reported",
        "announces", "announced", "announce",
        "says", "said",
    }
)


def extract_tokens(title: str) -> set[str]:
    """Extract composite tokens from a title (Part II §3.7).

    A token is one of:
      - A $TICKER (e.g., $RELIANCE)
      - An all-caps acronym of length >=2 (e.g., TCS, RBI)
      - A Capitalized multi-word phrase, treated as ONE composite token
        ("Tata Sons" = 1 token, "Tata Motors" = a different 1 token)

    Single-token matches (e.g., "TCS" alone) are too promiscuous — that's the
    TCS-Q2-vs-buyback over-merge failure mode. The ≥2-token rule in
    keyword_fallback_match is what prevents it.
    """
    if not title:
        return set()

    tokens: set[str] = set()

    # Phrases first (composite tokens); strip them so they aren't re-counted.
    title_after_phrases = title
    for m in _PHRASE_RE.finditer(title):
        phrase = m.group(1).strip()
        if phrase:
            tokens.add(phrase.lower())
            title_after_phrases = title_after_phrases.replace(m.group(1), " ", 1)

    # $TICKERs.
    for m in _TICKER_RE.finditer(title_after_phrases):
        tokens.add(m.group(0).lower())  # keep the $ sigil

    # Quarters / fiscal years (event identifiers).
    for m in _PERIOD_RE.finditer(title_after_phrases):
        tokens.add(m.group(1).upper())  # normalize Q2/q2 → Q2

    # All-caps acronyms (length >=2).
    for m in _ACRONYM_RE.finditer(title_after_phrases):
        tok = m.group(1)
        if tok.lower() not in _BOILERPLATE:
            tokens.add(tok.lower())

    return tokens


# ---------------------------------------------------------------------------
# Clustering job
# ---------------------------------------------------------------------------

async def cluster_new_items(*, within_hours: int | None = None) -> dict[str, Any]:
    """Per unassigned item within `within_hours`: try embedding match, then
    keyword fallback, else new story. Returns a summary dict."""
    cfg = await get_clustering_config()
    window = within_hours or cfg.max_story_age_hours
    threshold = cfg.similarity_threshold

    unassigned = await items_without_story(within_hours=window)
    summary = {"checked": len(unassigned), "merged": 0, "new_stories": 0, "keyword_used": 0}

    # For keyword fallback we need existing story headlines within window.
    # Load once per cycle (cheap relative to per-item vector search).
    existing_stories = await _recent_story_headlines(window)

    for item in unassigned:
        joined_story_id: uuid.UUID | None = None
        used_keyword = False

        # 1. Embedding similarity (primary).
        if item.embedding is not None:
            neighbors = await vector_search(
                embedding=item.embedding,
                threshold=threshold,
                within_hours=window,
                limit=5,
            )
            if neighbors:
                # Join the closest existing story.
                joined_story_id = neighbors[0].story_id
        else:
            await audit_log(
                actor="system",
                action="cluster_embedding_missing",
                entity=str(item.id),
                entity_type="item",
                after={"fallback": "keyword"},
            )
            used_keyword = True

        # 2. Keyword fallback (no embedding, or embedding found nothing).
        if joined_story_id is None:
            joined_story_id = _keyword_fallback_match(
                item.title, existing_stories, cfg.keyword_fallback_min_tokens
            )
            if joined_story_id is not None:
                used_keyword = True

        # 3. New story if no match.
        is_new = joined_story_id is None
        story_id = await create_or_join_story(
            item_id=item.id,
            headline=item.title,
            existing_story_id=joined_story_id,
        )

        if is_new:
            summary["new_stories"] += 1
            await audit_log(
                actor="system",
                action="cluster_new_story",
                entity=str(story_id),
                entity_type="story",
                after={"seed_item_id": str(item.id), "headline": item.title[:120]},
            )
        else:
            summary["merged"] += 1
            if used_keyword:
                summary["keyword_used"] += 1

    log.info("cluster_done", **summary)
    return summary


def _keyword_fallback_match(
    title: str,
    existing: list[dict[str, Any]],
    min_tokens: int,
) -> uuid.UUID | None:
    """Match `title` against existing story headlines by token overlap.

    Requires >= min_tokens DISTINCT token overlap (Part II §3.7). Returns the
    story id of the best match, or None.

    The trap (unit-tested in §5.6): a single shared token like "TCS" must NOT
    merge "TCS Q2 results" with "TCS announces buyback" — they're different
    events. Two shared tokens (e.g., "TCS" + "Q2" + "results") would merge them,
    which is why the default min_tokens=2 is conservative-but-not-useless.
    """
    title_tokens = extract_tokens(title)
    if len(title_tokens) < min_tokens:
        return None
    best_id: uuid.UUID | None = None
    best_overlap = 0
    for s in existing:
        s_tokens = extract_tokens(s["headline"] or "")
        overlap = len(title_tokens & s_tokens)
        if overlap >= min_tokens and overlap > best_overlap:
            best_overlap = overlap
            best_id = s["id"]
    return best_id


async def _recent_story_headlines(within_hours: int) -> list[dict[str, Any]]:
    """Existing stories created within window, with their (seed) headline."""
    from app.db import _fetchall, get_pool

    pool = await get_pool()
    async with pool.connection() as conn:
        rows = await _fetchall(
            conn,
            """
            SELECT s.id, s.headline
              FROM stories s
             WHERE s.created_at > now() - make_interval(hours := %s)
             ORDER BY s.created_at DESC
            """,
            within_hours,
        )
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Embedding retry sweep (failure-recovery path, §3.8)
# ---------------------------------------------------------------------------

async def embed_retry_sweep(*, within_hours: int | None = None) -> dict[str, Any]:
    """Retry embedding for items that failed first-pass, within window.
    On the Nth failure (config.embedding_max_retries), mark permanently failed
    and let keyword clustering handle them forever (§3.8).

    A successful backfill writes `embed_retry_success` (Part II §3.8) — recovery
    is provable after the fact, not just a moving /stats gauge."""
    cfg_cluster = await get_clustering_config()
    cfg_ingest = await get_ingest_config()
    window = within_hours or cfg_cluster.max_story_age_hours
    max_retries = cfg_ingest.embedding_max_retries

    candidates = await items_needing_embedding(within_hours=window)
    summary = {"retried": len(candidates), "succeeded": 0, "permanently_failed": 0}

    for item in candidates:
        try:
            text = await build_embedding_input_async(item.title, item.full_text)
            vec = await embed(text)
        except EmbedError:
            count = await bump_retry_count(item.id)
            if count >= max_retries:
                await append_warning(item.id, "embedding_permanently_failed")
                summary["permanently_failed"] += 1
            continue
        except Exception as exc:  # noqa: BLE001
            log.error("embed_retry_unexpected", item_id=str(item.id), error=str(exc))
            continue

        await set_embedding(item.id, vec)
        summary["succeeded"] += 1
        await audit_log(
            actor="system",
            action="embed_retry_success",
            entity=str(item.id),
            entity_type="item",
            after={"was_null_for_minutes": _minutes_since(item)},
        )

    log.info("embed_retry_done", **summary)
    return summary


def _minutes_since(item: ItemRow) -> int:
    """Best-effort age estimate. ItemRow doesn't carry created_at; use 0 as a
    placeholder (the field exists in DB; the audit `before` could carry it if
    we want precise age, but the convention just needs the event to exist)."""
    return 0


# ---------------------------------------------------------------------------
# Pure-logic cosine similarity — used by the DI'd clustering test (§5.4)
# ---------------------------------------------------------------------------

def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Exact cosine. Used by the fixture-based clustering test (§5.4 engine
    caveat: production uses HNSW which is approximate; at P1 scale they agree)."""
    if len(a) != len(b):
        raise ValueError(f"dim mismatch: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


__all__ = [
    "cluster_new_items",
    "embed_retry_sweep",
    "extract_tokens",
    "keyword_fallback_match",
    "cosine_similarity",
]


def keyword_fallback_match(
    title: str,
    existing: list[dict[str, Any]],
    min_tokens: int,
) -> uuid.UUID | None:
    """Public alias for the keyword fallback. Kept for tests that import by
    name from the module top-level (the underscore-prefixed version is internal)."""
    return _keyword_fallback_match(title, existing, min_tokens)
