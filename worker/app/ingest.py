"""Ingest orchestrator (Part II §3.1, §3.2, §3.6).

Per source kind, one job iterates active sources: fetch → normalize → upsert
(ON CONFLICT hash DO NOTHING) → embed new items INLINE (synchronous, within
the poll job — §3.6 trigger pin). There is no separate `embed_new` job and no
queue; the embed_retry sweep (§3.8) exists only for the failure-recovery path.

This module is what the scheduler calls and what `/ingest/trigger` invokes.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog

from app.audit import audit_log
from app.config import get_ingest_config, clear_config_cache
from app.db import (
    SourceRow,
    active_sources,
    set_embedding,
    append_warning,
    update_source_health,
    upsert_item,
)
from app.embed import build_embedding_input_async, embed, EmbedError
from app.sources import get_source, SourceError

log = structlog.get_logger()


async def run_for_source(source_row: SourceRow) -> dict[str, Any]:
    """Run one poll cycle for a single source. Returns a small summary dict.
    Never raises — failures are logged + recorded in audit_log + reflected in
    the source's health bookkeeping."""
    summary: dict[str, Any] = {
        "source_id": str(source_row.id),
        "name": source_row.name,
        "fetched": 0,
        "new": 0,
        "embedded": 0,
        "embed_failures": 0,
        "status": "ok",
    }

    try:
        source = get_source(source_row.kind)
    except SourceError as exc:
        await update_source_health(source_row.id, status="error", failed=True)
        await audit_log(
            actor="system",
            action="ingest_error",
            entity=str(source_row.id),
            entity_type="source",
            after={"error": str(exc), "name": source_row.name},
        )
        summary["status"] = "error"
        return summary

    try:
        raw_items = await source.fetch(source_row)
    except SourceError as exc:
        # 'not_a_feed', 'nse_disabled', http errors after retries.
        status = "not_a_feed" if "not_a_feed" in str(exc) else "error"
        is_known_skip = "nse_disabled" in str(exc)
        if not is_known_skip:
            await update_source_health(source_row.id, status=status, failed=True)
        await audit_log(
            actor="system",
            action="ingest_error",
            entity=str(source_row.id),
            entity_type="source",
            after={"error": str(exc), "known_skip": is_known_skip},
        )
        summary["status"] = status if not is_known_skip else "skipped"
        return summary

    # Cap cold-start backlogs (§3.3). Newest-first (feedparser preserves order,
    # which is typically most-recent-first for news feeds).
    cfg = await get_ingest_config()
    if len(raw_items) > cfg.max_items_per_cycle:
        raw_items = raw_items[: cfg.max_items_per_cycle]
        summary["truncated"] = True

    summary["fetched"] = len(raw_items)

    # fetch → normalize → upsert → embed (inline, §3.6 trigger pin).
    for raw in raw_items:
        try:
            normalized = await source.normalize(raw)
        except Exception as exc:  # noqa: BLE001 — normalize failures are per-item
            log.warning(
                "normalize_failed",
                source=str(source_row.id),
                title=raw.raw_title[:80],
                error=str(exc),
            )
            continue

        item_id = await upsert_item(
            source_id=uuid.UUID(normalized.source_id),
            title=normalized.title,
            url=normalized.url,
            published_at=normalized.published_at,
            full_text=normalized.full_text,
            hash_=normalized.hash,
            warnings=normalized.warnings or None,
        )
        if item_id is None:
            # Exact dupe (§1.1) — ON CONFLICT (hash) DO NOTHING fired. Skip embed.
            continue

        summary["new"] += 1

        # Inline embedding (§3.6). On failure, the item is stored with
        # embedding IS NULL + warning; the embed_retry sweep will recover it.
        try:
            text = await build_embedding_input_async(normalized.title, normalized.full_text)
            vec = await embed(text)
            await set_embedding(item_id, vec)
            summary["embedded"] += 1
        except EmbedError as exc:
            summary["embed_failures"] += 1
            await append_warning(item_id, "embedding_failed")
            await audit_log(
                actor="system",
                action="embedding_failed",
                entity=str(item_id),
                entity_type="item",
                after={"reason": str(exc), "retries_left": cfg.embedding_max_retries},
            )
        except Exception as exc:  # noqa: BLE001
            summary["embed_failures"] += 1
            await append_warning(item_id, "embedding_failed")
            log.error("embed_unexpected_error", item_id=str(item_id), error=str(exc))

    # Embedding health check: if >threshold of new items failed, flag degraded.
    if summary["new"] > 0:
        fail_ratio = summary["embed_failures"] / summary["new"]
        if fail_ratio > cfg.embedding_degraded_threshold:
            await audit_log(
                actor="system",
                action="embedding_degraded",
                entity=str(source_row.id),
                entity_type="cycle",
                after={"failed_fraction": round(fail_ratio, 3)},
            )

    await update_source_health(source_row.id, status="ok", failed=False)
    await audit_log(
        actor="system",
        action="ingest_run",
        entity=str(source_row.id),
        entity_type="source",
        after={
            "fetched": summary["fetched"],
            "new": summary["new"],
            "embedded": summary["embedded"],
            "embed_failures": summary["embed_failures"],
        },
    )
    log.info("ingest_done", **summary)
    return summary


async def run_all_sources(*, kind: str | None = None) -> list[dict[str, Any]]:
    """Iterate active sources of a kind (or all kinds). One bad source doesn't
    kill the loop (§3.2)."""
    clear_config_cache()  # pick up any tuning changes since last cycle
    sources = await active_sources(kind=kind)
    summaries: list[dict[str, Any]] = []
    for src in sources:
        summaries.append(await run_for_source(src))
    return summaries


async def trigger_source(source_id: uuid.UUID) -> dict[str, Any] | None:
    """Manual one-source poll (used by /ingest/trigger). Returns None if the
    source isn't found."""
    from app.db import get_source as get_source_row

    src = await get_source_row(source_id)
    if src is None:
        return None
    return await run_for_source(src)


__all__ = ["run_for_source", "run_all_sources", "trigger_source"]
