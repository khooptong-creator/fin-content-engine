"""HTTP routes (Part II §3.9, §4.7).

Three endpoints:
  - GET  /health          : liveness probe for Railway (process + scheduler + DB)
  - GET  /stats           : the P1 "is it alive" surface
  - POST /ingest/trigger  : manual one-source poll (used by acceptance step 6)

The dashboard (P3) will add the rest; in P1 there is no GUI, so these are the
only surfaces. The scheduler is injected via FastAPI's app.state so /health can
report whether it's running.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.db import ping as db_ping, stats as db_stats

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    """Process + scheduler_running + db_reachable. NOT sources (§4.7): a dead
    feed is a /stats concern, not a liveness one. Returns 503 if any check fails
    so Railway restarts the container."""
    scheduler = getattr(request.app.state, "scheduler", None)
    scheduler_running = scheduler.running if scheduler is not False else False
    db_reachable = await db_ping()
    checks = {
        "process": "up",
        "scheduler_running": bool(scheduler_running),
        "db_reachable": db_reachable,
    }
    ok = all(checks.values())
    return JSONResponse(content=checks, status_code=200 if ok else 503)


@router.get("/stats")
async def stats() -> dict:
    """The /stats payload (Part II §3.9)."""
    return await db_stats()


@router.post("/ingest/trigger")
async def ingest_trigger(source_id: str) -> dict:
    """Manually trigger a poll for one source. Used by the soak checklist (§5.7
    step 6) to verify production idempotency."""
    from app.ingest import trigger_source

    try:
        sid = uuid.UUID(source_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid source_id (must be a uuid)")
    summary = await trigger_source(sid)
    if summary is None:
        raise HTTPException(status_code=404, detail="source not found")
    return summary


__all__ = ["router"]
