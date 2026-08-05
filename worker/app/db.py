"""Postgres access layer (Part II §2, §3, §4).

psycopg3 + pgvector. A single async pool is shared across the worker; tests can
point it at the local Docker DB via DATABASE_URL.

Key operations:
  - upsert_item: ON CONFLICT (hash) DO NOTHING — the exact-dupe guarantee (§1.1).
  - create_or_join_story: atomic story+link transaction — orphan prevention (§3.7).
  - vector_search: HNSW similarity lookup.
  - count_orphans: the §3.9 "is anything being dropped on the floor" counter.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
import structlog
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.settings import get_settings

log = structlog.get_logger()

_pool: AsyncConnectionPool | None = None


# ---------------------------------------------------------------------------
# Pool lifecycle
# ---------------------------------------------------------------------------

async def get_pool() -> AsyncConnectionPool:
    """Lazily-initialize the shared async pool. Idempotent.

    Detects a closed pool (can happen if close_pool() was called, e.g. between
    test sessions sharing a process) and recreates it — closed pools can't be
    reused."""
    global _pool
    if _pool is not None and not _pool.closed:
        return _pool
    settings = get_settings()
    _pool = AsyncConnectionPool(
        conninfo=settings.database_url,
        min_size=1,
        max_size=settings.scheduler_max_workers + 2,
        # kwargs for pgvector: register the type on every connection.
        configure=_configure_conn,
        open=False,
    )
    await _pool.open(wait=True)
    log.info("db_pool_opened", database_url=_safe_url(settings.database_url))
    return _pool


async def _configure_conn(conn: psycopg.AsyncConnection) -> None:
    # Register pgvector's type adapter so `vector` columns decode to Python lists.
    # psycopg3 note: configure callbacks must NOT leave the connection in an open
    # transaction (status INTRANS) — the pool discards such connections and
    # retries forever, which looks exactly like a hang. register_vector_async
    # and the row_factory assignment are both transaction-safe; we avoid SET
    # commands here (TIME ZONE is set at the DB level via migration instead).
    from pgvector.psycopg import register_vector_async

    await register_vector_async(conn)
    # psycopg3: row_factory is a settable property (not a set_row_factory method,
    # and set_session doesn't exist on async connections).
    conn.row_factory = dict_row


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def ping() -> bool:
    """SELECT 1 — used by /health (Part II §4.7). Returns False on any failure."""
    try:
        pool = await get_pool()
        async with pool.connection() as conn:
            await conn.execute("SELECT 1")
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("db_ping_failed", error=str(exc))
        return False


def _safe_url(url: str) -> str:
    """Strip the password from a connection URL for logging."""
    if "@" not in url:
        return url
    head, tail = url.split("@", 1)
    if ":" in head:
        scheme_user = head.rsplit(":", 1)[0]
        return f"{scheme_user}:***@{tail}"
    return head + ":***@" + tail


# ---------------------------------------------------------------------------
# psycopg3 query helpers (asyncpg-style convenience on top of the cursor API)
# ---------------------------------------------------------------------------
# psycopg3's AsyncConnection only has `execute`. For queries you must use the
# cursor pattern. These helpers give us the fetchrow/fetchval/fetch ergonomics
# the rest of db.py was written against. Each takes an already-acquired conn.

async def _fetchone(conn, query: str, *params) -> dict | None:
    async with conn.cursor() as cur:
        await cur.execute(query, params)
        return await cur.fetchone()


async def _fetchall(conn, query: str, *params) -> list[dict]:
    async with conn.cursor() as cur:
        await cur.execute(query, params)
        return await cur.fetchall()


async def _fetchval(conn, query: str, *params):
    row = await _fetchone(conn, query, *params)
    if row is None:
        return None
    # Return the first column value.
    return next(iter(row.values()))


# ---------------------------------------------------------------------------
# Typed row containers
# ---------------------------------------------------------------------------

@dataclass
class SourceRow:
    id: uuid.UUID
    kind: str
    url: str
    name: str
    market: str
    active: bool
    poll_minutes: int


@dataclass
class ItemRow:
    id: uuid.UUID
    source_id: uuid.UUID
    title: str
    url: str
    published_at: datetime
    full_text: str | None
    hash: str
    embedding: list[float] | None
    warnings: list[str]


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

async def active_sources(*, kind: str | None = None) -> list[SourceRow]:
    """Active sources, optionally filtered by kind."""
    pool = await get_pool()
    if kind is None:
        q = "SELECT id, kind, url, name, market, active, poll_minutes FROM sources WHERE active"
        params: tuple[Any, ...] = ()
    else:
        q = (
            "SELECT id, kind, url, name, market, active, poll_minutes "
            "FROM sources WHERE active AND kind = %s"
        )
        params = (kind,)
    async with pool.connection() as conn:
        rows = await _fetchall(conn, q, *params)
    return [SourceRow(**r) for r in rows]


async def get_source(source_id: uuid.UUID) -> SourceRow | None:
    pool = await get_pool()
    async with pool.connection() as conn:
        row = await _fetchone(
            conn,
            "SELECT id, kind, url, name, market, active, poll_minutes "
            "FROM sources WHERE id = %s",
            source_id,
        )
    return SourceRow(**row) if row else None


async def update_source_health(
    source_id: uuid.UUID,
    *,
    status: str,
    failed: bool,
) -> None:
    """Update bookkeeping after a poll. failed=True bumps consecutive_failures;
    failed=False resets to 0. Auto-disables the source after 3 consecutive fails
    (Part II §3.3) — the caller (ingest) also writes an `ingest_unhealthy` audit
    event when the auto-disable fires, so the soak checklist can find it."""
    pool = await get_pool()
    async with pool.connection() as conn:
        if failed:
            new_count_row = await _fetchone(
                conn,
                """
                UPDATE sources
                   SET consecutive_failures = consecutive_failures + 1,
                       last_status = %s,
                       last_run_at = now()
                 WHERE id = %s
             RETURNING consecutive_failures
                """,
                status,
                source_id,
            )
            count = new_count_row["consecutive_failures"] if new_count_row else 0
            if count >= 3:
                await conn.execute(
                    "UPDATE sources SET active = false WHERE id = %s",
                    (source_id,),
                )
        else:
            await conn.execute(
                """
                UPDATE sources
                   SET consecutive_failures = 0,
                       last_status = %s,
                       last_run_at = now()
                 WHERE id = %s
                """,
                (status, source_id),
            )


# ---------------------------------------------------------------------------
# Items — upsert (the dedup guarantee)
# ---------------------------------------------------------------------------

async def upsert_item(
    *,
    source_id: uuid.UUID,
    title: str,
    url: str,
    published_at: datetime,
    full_text: str | None,
    hash_: str,
    warnings: list[str] | None = None,
) -> uuid.UUID | None:
    """Insert an item if its hash isn't present. Returns the new item id, or
    None if it was a duplicate (ON CONFLICT DO NOTHING, §1.1)."""
    pool = await get_pool()
    async with pool.connection() as conn:
        row = await _fetchone(
            conn,
            """
            INSERT INTO items (source_id, title, url, published_at, full_text, hash, warnings)
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (hash) DO NOTHING
            RETURNING id
            """,
            source_id,
            title,
            url,
            published_at,
            full_text,
            hash_,
            _dumps(warnings or []),
        )
    if row is None:
        return None
    return row["id"]


async def set_embedding(item_id: uuid.UUID, embedding: list[float]) -> None:
    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE items SET embedding = %s WHERE id = %s",
            (embedding, item_id),
        )


async def append_warning(item_id: uuid.UUID, warning: str) -> None:
    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE items SET warnings = warnings || %s::jsonb WHERE id = %s",
            (_dumps([warning]), item_id),
        )


async def bump_retry_count(item_id: uuid.UUID) -> int:
    """Increment retry_count and return the new value."""
    pool = await get_pool()
    async with pool.connection() as conn:
        row = await _fetchone(
            conn,
            "UPDATE items SET retry_count = retry_count + 1 WHERE id = %s RETURNING retry_count",
            item_id,
        )
    return row["retry_count"] if row else 0


# ---------------------------------------------------------------------------
# Stories — atomic create-or-join (orphan prevention, §3.7)
# ---------------------------------------------------------------------------

async def create_or_join_story(
    *,
    item_id: uuid.UUID,
    headline: str,
    existing_story_id: uuid.UUID | None,
) -> uuid.UUID:
    """Atomically link an item to a story (existing or new).

    Wrapped in a single transaction so a crash between create_story and
    link_item_to_story rolls BOTH back — the orphan-prevention guarantee
    (Part II §3.7). Returns the story id the item was linked to.
    """
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            story_id = existing_story_id
            if story_id is None:
                row = await _fetchone(
                    conn,
                    "INSERT INTO stories (headline, status) VALUES (%s, 'inbox') RETURNING id",
                    headline,
                )
                story_id = row["id"] if row else None
            # link is idempotent: composite PK means re-link is a no-op
            await conn.execute(
                "INSERT INTO story_items (story_id, item_id) VALUES (%s, %s) "
                "ON CONFLICT (story_id, item_id) DO NOTHING",
                (story_id, item_id),
            )
    assert story_id is not None
    return story_id


async def create_manual_story(headline: str, channel_id: str) -> uuid.UUID:
    """Create a manual story for one channel, without items, for the autopilot."""
    pool = await get_pool()
    async with pool.connection() as conn:
        row = await _fetchone(
            conn,
            "INSERT INTO stories (headline, status, channel_id) VALUES (%s, 'inbox', %s) RETURNING id",
            headline,
            channel_id,
        )
        return row["id"]


# ---------------------------------------------------------------------------
# Vector search — HNSW-backed similarity (production uses approx; test uses exact)
# ---------------------------------------------------------------------------

@dataclass
class Neighbor:
    story_id: uuid.UUID
    item_id: uuid.UUID
    similarity: float


async def vector_search(
    *,
    embedding: list[float],
    threshold: float,
    within_hours: int,
    limit: int = 5,
) -> list[Neighbor]:
    """Find existing items whose embedding is within `threshold` cosine similarity
    of `embedding`, and which are linked to a story, created within `within_hours`.
    Production goes through the HNSW index (approximate); at P1 scale HNSW≈exact
    (Part II §5.4 engine caveat).

    The vector is bound as a single `%s::vector` parameter and reused via a CTE
    so we don't bind it three times (cosine distance <=> needs the literal).
    """
    pool = await get_pool()
    async with pool.connection() as conn:
        rows = await _fetchall(
            conn,
            """
            WITH q AS (SELECT %s::vector AS vec)
            SELECT si.story_id, si.item_id,
                   1 - (i.embedding <=> q.vec) AS similarity
              FROM items i
              CROSS JOIN q
              JOIN story_items si ON si.item_id = i.id
             WHERE i.embedding IS NOT NULL
               AND i.created_at > now() - make_interval(hours := %s)
               AND 1 - (i.embedding <=> q.vec) >= %s
             ORDER BY i.embedding <=> q.vec
             LIMIT %s
            """,
            embedding,
            within_hours,
            threshold,
            limit,
        )
    return [
        Neighbor(story_id=r["story_id"], item_id=r["item_id"], similarity=r["similarity"])
        for r in rows
    ]


async def items_without_story(*, within_hours: int) -> list[ItemRow]:
    """Items not yet linked to any story, created within `within_hours`."""
    pool = await get_pool()
    async with pool.connection() as conn:
        rows = await _fetchall(
            conn,
            """
            SELECT i.id, i.source_id, i.title, i.url, i.published_at, i.full_text,
                   i.hash, i.embedding, i.warnings
              FROM items i
              LEFT JOIN story_items si ON si.item_id = i.id
             WHERE si.story_id IS NULL
               AND i.created_at > now() - make_interval(hours := %s)
             ORDER BY i.created_at
            """,
            within_hours,
        )
    return [_row_to_item(r) for r in rows]


async def items_needing_embedding(*, within_hours: int) -> list[ItemRow]:
    """Items with embedding IS NULL, not yet permanently failed, within window."""
    pool = await get_pool()
    async with pool.connection() as conn:
        rows = await _fetchall(
            conn,
            """
            SELECT i.id, i.source_id, i.title, i.url, i.published_at, i.full_text,
                   i.hash, i.embedding, i.warnings
              FROM items i
             WHERE i.embedding IS NULL
               AND i.created_at > now() - make_interval(hours := %s)
               AND NOT i.warnings @> '["embedding_permanently_failed"]'
             ORDER BY i.created_at
            """,
            within_hours,
        )
    return [_row_to_item(r) for r in rows]


# ---------------------------------------------------------------------------
# Counts — for /stats
# ---------------------------------------------------------------------------

async def count(table: str) -> int:
    pool = await get_pool()
    async with pool.connection() as conn:
        row = await _fetchone(conn, f"SELECT count(*) AS n FROM {table}")  # noqa: S608 — table name is internal
    return row["n"] if row else 0


async def count_where(table: str, where_sql: str) -> int:
    """Count rows matching a WHERE clause. `where_sql` is trusted (internal only)."""
    pool = await get_pool()
    async with pool.connection() as conn:
        row = await _fetchone(conn, f"SELECT count(*) AS n FROM {table} WHERE {where_sql}")  # noqa: S608
    return row["n"] if row else 0


async def count_orphans() -> int:
    """Items older than 48h with no story_items row (Part II §3.9).
    Non-zero in steady state = upstream bug (a story creation crashed)."""
    return await count_where(
        "items",
        "created_at < now() - interval '48 hours' "
        "AND id NOT IN (SELECT item_id FROM story_items)",
    )


async def stats() -> dict[str, Any]:
    """The /stats payload (Part II §3.9)."""
    pool = await get_pool()
    async with pool.connection() as conn:
        sources_rows = await _fetchall(
            conn,
            """
            SELECT name, kind, active, last_run_at, last_status, consecutive_failures,
                   (SELECT count(*) FROM items WHERE source_id = sources.id
                      AND created_at > now() - interval '24 hours') AS items_new_24h
              FROM sources
             ORDER BY name
            """,
        )
        item_counts = await _fetchone(
            conn,
            """
            SELECT count(*) AS total,
                   count(embedding) AS with_embedding,
                   count(*) - count(embedding) AS without_embedding,
                   count(*) FILTER (
                       WHERE created_at < now() - interval '48 hours'
                         AND id NOT IN (SELECT item_id FROM story_items)
                   ) AS orphaned
              FROM items
            """,
        )
        story_counts = await _fetchone(
            conn,
            """
            WITH per_story AS (
                SELECT s.id
                  FROM stories s LEFT JOIN story_items si ON si.story_id = s.id
                 GROUP BY s.id
            )
            SELECT
                (SELECT count(*) FROM stories) AS total,
                (SELECT count(*) FROM stories WHERE created_at > now() - interval '24 hours') AS created_24h,
                COALESCE((SELECT avg(items_per_story) FROM (
                    SELECT count(si.item_id) AS items_per_story
                      FROM stories s LEFT JOIN story_items si ON si.story_id = s.id
                     GROUP BY s.id
                ) t), 0) AS avg_items_per_story
            """,
        )
    without = item_counts["without_embedding"] if item_counts else 0
    total = item_counts["total"] if item_counts else 0
    degraded_threshold = 0.20  # config.ingest.embedding_degraded_threshold; inlined to avoid circular import
    if total == 0:
        embedding_health = "ok"
    else:
        # Health is based on the fraction of *recent* items without embedding.
        recent = await count_where(
            "items", "created_at > now() - interval '24 hours'"
        )
        recent_missing = await count_where(
            "items",
            "embedding IS NULL AND created_at > now() - interval '24 hours'",
        )
        ratio = (recent_missing / recent) if recent else 0.0
        embedding_health = "degraded" if ratio > degraded_threshold else "ok"
    return {
        "sources": [dict(r) for r in (sources_rows or [])],
        "items": dict(item_counts) if item_counts else {},
        "stories": dict(story_counts) if story_counts else {},
        "embedding_health": embedding_health,
        "clustering": {"precision_last_test": None, "recall_last_test": None},
        "without_embedding_fraction": (without / total) if total else 0.0,
    }
# ---------------------------------------------------------------------------
# API Data Fetchers (Inbox & Drafts)
# ---------------------------------------------------------------------------

async def get_pending_stories() -> list[dict[str, Any]]:
    """Fetch stories with status 'inbox', along with their linked items."""
    pool = await get_pool()
    async with pool.connection() as conn:
        # Fetch inbox stories
        stories = await _fetchall(
            conn,
            "SELECT id, headline, status, channel_id, created_at FROM stories WHERE status = 'inbox' ORDER BY created_at DESC"
        )
        
        # For each story, fetch its items
        for story in stories:
            items = await _fetchall(
                conn,
                """
                SELECT i.id, i.title, i.url, s.name as source_name, i.published_at 
                FROM items i
                JOIN story_items si ON i.id = si.item_id
                JOIN sources s ON i.source_id = s.id
                WHERE si.story_id = %s
                ORDER BY i.published_at DESC
                """,
                story["id"]
            )
            story["items"] = items
            
    return stories


async def get_drafts() -> list[dict[str, Any]]:
    """Fetch all drafts (rendered or pending upload)."""
    pool = await get_pool()
    async with pool.connection() as conn:
        drafts = await _fetchall(
            conn,
            """
            SELECT d.id, d.story_id, s.headline, d.platform, d.format,
                   d.body->>'channel_id' AS channel_id,
                   d.body->>'upload_preference' AS upload_preference,
                   d.body->>'title' AS title,
                   d.body->>'description' AS description,
                   d.body, d.status, d.created_at, d.published_ids
            FROM drafts d
            JOIN stories s ON d.story_id = s.id
            ORDER BY d.created_at DESC
            """
        )
    return drafts


async def get_draft(draft_id: uuid.UUID) -> dict[str, Any] | None:
    """Fetch a single draft by id, joined with its story headline."""
    pool = await get_pool()
    async with pool.connection() as conn:
        row = await _fetchone(
            conn,
            """
            SELECT d.id, d.story_id, s.headline, d.platform, d.format,
                   d.body->>'channel_id' AS channel_id,
                   d.body->>'upload_preference' AS upload_preference,
                   d.body->>'title' AS title,
                   d.body->>'description' AS description,
                   d.body, d.status, d.created_at, d.published_ids
            FROM drafts d
            JOIN stories s ON d.story_id = s.id
            WHERE d.id = %s
            """,
            draft_id,
        )
    return row


async def update_draft_published(
    draft_id: uuid.UUID,
    *,
    status: str,
    published_ids: dict[str, str],
) -> None:
    """Update a draft's status and published_ids after a successful upload."""
    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            """
            UPDATE drafts
            SET status = %s, published_ids = %s::jsonb
            WHERE id = %s
            """,
            (status, _dumps(published_ids), draft_id),
        )


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

async def get_config(key: str) -> dict[str, Any] | None:
    pool = await get_pool()
    async with pool.connection() as conn:
        row = await _fetchone(conn, "SELECT value FROM config WHERE key = %s", key)
    return row["value"] if row else None


async def set_config(key: str, value: dict[str, Any]) -> None:
    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO config (key, value)
            VALUES (%s, %s::jsonb)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """,
            (key, _dumps(value)),
        )

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_item(r: Any) -> ItemRow:
    return ItemRow(
        id=r["id"],
        source_id=r["source_id"],
        title=r["title"],
        url=r["url"],
        published_at=r["published_at"],
        full_text=r["full_text"],
        hash=r["hash"],
        embedding=r["embedding"],
        warnings=list(r["warnings"]) if r["warnings"] else [],
    )


def _dumps(value: Any) -> str:
    import json

    return json.dumps(value, default=str)
