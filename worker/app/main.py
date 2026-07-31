"""FastAPI app + lifecycle hooks (Part II §4.5).

startup: open DB pool → build job specs → register (async invariant asserted)
         → start scheduler → audit worker_start.
shutdown: scheduler.shutdown(wait=True) → close DB pool → audit worker_stop.

The scheduler is attached to app.state so /health can report whether it's
running. SIGTERM (Railway/Fly redeploy) triggers FastAPI's shutdown.
"""

from __future__ import annotations

import contextlib

import os
from pathlib import Path
import structlog
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import routes
from app.audit import audit_log
from app.db import close_pool, get_pool
from app.scheduler import build_job_specs, make_scheduler, register_jobs
from app.settings import get_settings

log = structlog.get_logger()

VIDEOS_DIR = Path(os.environ.get("VIDEOS_DIR", "../videos")).resolve()


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    """Open pool, register jobs, start scheduler. Reverse on shutdown."""
    settings = get_settings()
    # Open pool (also runs _configure_conn: registers pgvector, sets UTC).
    await get_pool()

    # Build + register jobs. register_jobs asserts the async invariant.
    scheduler = make_scheduler(max_workers=settings.scheduler_max_workers)
    specs = await build_job_specs()
    register_jobs(scheduler, specs)
    scheduler.start()
    app.state.scheduler = scheduler

    await audit_log(
        actor="system",
        action="worker_start",
        entity=None,
        entity_type="worker",
        after={"jobs": [s.id for s in specs]},
    )
    log.info("worker_started", jobs=[s.id for s in specs])

    try:
        yield
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=True)
        await audit_log(
            actor="system",
            action="worker_stop",
            entity=None,
            entity_type="worker",
        )
        await close_pool()
        log.info("worker_stopped")

from fastapi.middleware.cors import CORSMiddleware

def create_app() -> FastAPI:
    app = FastAPI(title="Fin-Content Engine worker", version="0.1.0", lifespan=lifespan)
    app.state.scheduler = False  # set by lifespan; /health treats False as not-running
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Adjust in production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    app.include_router(routes.router)
    
    # Mount videos directory for static access by the frontend (audio/scripts)
    app.mount("/videos", StaticFiles(directory=VIDEOS_DIR), name="videos")
    
    return app


# uvicorn entrypoint: `uvicorn app.main:app --reload`
app = create_app()
