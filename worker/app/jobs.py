"""Coarse progress for a generation run.

Deliberately coarse: one row updated at stage boundaries, polled by the GUI
every couple of seconds. A finer-grained channel — websockets, per-frame
events — would be more infrastructure than a six-stage pipeline needs, and the
thing a human actually wants to know is "which stage, and did it fail".

`STAGES` is ordered and the GUI renders its progress bar from that ordering, so
inserting a stage in the middle is a deliberate, breaking change rather than an
append-anywhere list.
"""

from __future__ import annotations

import uuid

import structlog

from app.db import _fetchone, _fetchval, get_pool

log = structlog.get_logger()

# Ordered. "world" and "shots" only occur for 3D films; a 2D Short skips them,
# which the GUI renders as stages that never light up rather than as an error.
STAGES = ["queued", "script", "narration", "world", "shots", "render", "done"]


async def create_job(kind: str, story_id: uuid.UUID) -> uuid.UUID:
    """Open a job row and return its id."""
    pool = await get_pool()
    async with pool.connection() as conn:
        job_id = await _fetchval(
            conn,
            "INSERT INTO jobs (kind, story_id, stage) VALUES (%s, %s, 'queued') RETURNING id",
            kind,
            story_id,
        )
    log.info("job_created", job_id=str(job_id), kind=kind)
    return job_id


async def set_stage(job_id: uuid.UUID, stage: str, done: int = 0, total: int = 0) -> None:
    """Advance a job to a stage, optionally with an n-of-m counter."""
    if stage not in STAGES:
        # A typo here would render as a progress bar stuck at an unknown stage,
        # which reads as a hang rather than as the bug it is.
        raise ValueError(f"unknown stage {stage!r}; expected one of {STAGES}")
    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE jobs SET stage=%s, done=%s, total=%s, updated_at=now() WHERE id=%s",
            (stage, done, total, job_id),
        )


async def fail_job(job_id: uuid.UUID, error: str) -> None:
    """Record why a run stopped. The stage is left where it failed."""
    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE jobs SET error=%s, updated_at=now() WHERE id=%s",
            (error, job_id),
        )
    log.error("job_failed", job_id=str(job_id), error=error)


async def finish_job(job_id: uuid.UUID, draft_id: uuid.UUID) -> None:
    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE jobs SET stage='done', draft_id=%s, updated_at=now() WHERE id=%s",
            (draft_id, job_id),
        )
    log.info("job_finished", job_id=str(job_id), draft_id=str(draft_id))


async def get_job(job_id: uuid.UUID) -> dict | None:
    pool = await get_pool()
    async with pool.connection() as conn:
        return await _fetchone(conn, "SELECT * FROM jobs WHERE id=%s", job_id)
