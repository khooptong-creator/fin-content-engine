"""APScheduler setup (Part II §4.3, §4.4, §4.6).

Key invariants:
  - AsyncIOScheduler + AsyncIOExecutor. Every job is `async def` (decision #22).
    `register_jobs` asserts `asyncio.iscoroutinefunction(fn)` for each entry
    and fails at BOOT, naming the offending job id — a build-time guarantee,
    not a code-review hope.
  - Advisory lock around each job body (§4.6), EXCEPT db_health (decision #27) —
    gating the DB-health probe behind a lock that itself needs the DB is
    self-defeating.
  - Single-replica is enforced at deploy time (Railway replicas=1); the
    advisory lock is belt-and-suspenders for the rolling-redeploy overlap.
"""

from __future__ import annotations

import asyncio
import inspect
import zlib
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import structlog
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.audit import audit_log
from app.db import get_pool

log = structlog.get_logger()

# Type alias for an async job function.
AsyncJob = Callable[[], Awaitable[Any]]


@dataclass
class JobSpec:
    id: str
    minutes: int
    fn: AsyncJob
    lock: bool = True  # db_health sets this False (decision #27)


# These are populated by build_job_specs() at startup so the scheduler is
# initialized lazily (after the DB pool is available).
_JOB_SPECS: list[JobSpec] | None = None


async def build_job_specs() -> list[JobSpec]:
    """Construct the job specs. Imported lazily to avoid a circular import with
    ingest/cluster (which import db, which imports settings — keep this layer
    free of those until the scheduler actually starts)."""
    from app.cluster import cluster_new_items, embed_retry_sweep
    from app.config import get_ingest_config
    from app.ingest import run_all_sources
    from app.db import ping as db_ping

    cfg = await get_ingest_config()
    return [
        JobSpec(id="poll_rss", minutes=cfg.rss_poll_minutes, fn=lambda: run_all_sources(kind="rss")),
        JobSpec(id="poll_edgar", minutes=cfg.edgar_poll_minutes, fn=lambda: run_all_sources(kind="edgar")),
        JobSpec(id="poll_nse", minutes=cfg.nse_poll_minutes, fn=lambda: run_all_sources(kind="nse")),
        JobSpec(id="cluster_new", minutes=15, fn=lambda: cluster_new_items()),
        JobSpec(id="embed_retry", minutes=30, fn=lambda: embed_retry_sweep()),
        # db_health exempt from advisory lock — the probe must work when the DB
        # is degraded, exactly the condition a lock-acquire failure would mimic.
        JobSpec(id="db_health", minutes=5, fn=db_ping, lock=False),
    ]


# ---------------------------------------------------------------------------
# Advisory lock wrapper (§4.6)
# ---------------------------------------------------------------------------

async def with_advisory_lock(key: str, fn: AsyncJob) -> Any:
    """Try to acquire a Postgres advisory lock keyed on `key`; on success, run
    `fn` and release. On contention, log + audit + return None (skip)."""
    from app.db import _fetchval

    key_hash = zlib.crc32(key.encode("utf-8")) & 0x7FFFFFFF
    pool = await get_pool()
    async with pool.connection() as conn:
        got = await _fetchval(conn, "SELECT pg_try_advisory_lock(%s)", key_hash)
        if not got:
            await audit_log(
                actor="system",
                action="advisory_lock_skip",
                entity=key,
                entity_type="job",
            )
            return None
        try:
            return await fn()
        finally:
            await conn.execute("SELECT pg_advisory_unlock(%s)", (key_hash,))


# ---------------------------------------------------------------------------
# Registry invariant: every job MUST be async def
# ---------------------------------------------------------------------------

def register_jobs(scheduler: AsyncIOScheduler, specs: list[JobSpec]) -> None:
    """Register all jobs. Asserts the async invariant (decision #22).

    Raises RuntimeError naming the offending job id if any fn is not a coroutine
    function — this is the syntax/build-time guard against the footgun where a
    plain `def` job silently runs in a thread pool that doesn't exist, or worse,
    a plain `def` containing `await` is a SyntaxError at import.
    """
    for spec in specs:
        fn = spec.fn
        # Use inspect.iscoroutinefunction (asyncio.iscoroutinefunction is
        # deprecated in Python 3.14+, slated for removal in 3.16).
        if not inspect.iscoroutinefunction(fn):
            raise RuntimeError(
                f"registry invariant violated: job '{spec.id}' fn is not async def. "
                f"Every job under AsyncIOExecutor MUST be `async def` — see decision #22."
            )

        # Wrap in advisory lock unless exempt.
        if spec.lock:
            wrapped: AsyncJob = lambda s=spec: with_advisory_lock(s.id, s.fn)
        else:
            wrapped = spec.fn

        scheduler.add_job(
            wrapped,
            trigger="interval",
            minutes=spec.minutes,
            id=spec.id,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=60,
        )


def make_scheduler(*, max_workers: int = 4) -> AsyncIOScheduler:
    """Build the AsyncIOScheduler with the §4.3 config. Does not register jobs
    or start — caller does both explicitly (see app.main).

    Note on `max_workers`: APScheduler 3.11's AsyncIOExecutor takes no
    constructor args — jobs run on the event loop, and same-job overlap is
    prevented by `max_instances=1`. The `max_workers` parameter is retained
    in the signature for forward-compat (a future APScheduler major, or a
    custom executor with a Semaphore) but is currently advisory only. At P1's
    job count (5 jobs, intervals 5–60 min), the loop's natural concurrency
    is sufficient; if a slow job ever starves others, wrap job bodies in an
    `asyncio.Semaphore(max_workers)`.
    """
    _ = max_workers  # advisory; see docstring
    return AsyncIOScheduler(
        jobstores={"default": MemoryJobStore()},
        executors={"default": AsyncIOExecutor()},
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": 60,
        },
        timezone="UTC",
    )


__all__ = [
    "JobSpec",
    "build_job_specs",
    "register_jobs",
    "make_scheduler",
    "with_advisory_lock",
]
