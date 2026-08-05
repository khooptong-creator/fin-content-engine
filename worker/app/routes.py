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
from pydantic import BaseModel, Field

from app.db import ping as db_ping, stats as db_stats

router = APIRouter()

# Background generation tasks are held here for their lifetime. asyncio keeps
# only a weak reference to a bare create_task(), so without this a long render
# can be garbage-collected mid-run.
_RUNNING_JOBS: set = set()


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


class YouTubeGenerateRequest(BaseModel):
    story_id: str
    channel_id: str = Field(min_length=1)
    upload_preference: str = "manual"


class YouTubeJobRequest(BaseModel):
    story_id: str
    channel_id: str = Field(min_length=1)
    upload_preference: str = "manual"
    mode: str | None = None


# "short" keeps whatever FRAME_BACKEND is configured; "film" forces the 3D path.
MODE_BACKENDS: dict[str, str | None] = {"short": None, "film": "three"}


def backend_for_mode(mode: str | None) -> str | None:
    """Map the GUI's format toggle to a frame backend.

    `None` means "use the FRAME_BACKEND default", which is what a Short wants.
    An unrecognised mode raises rather than defaulting, so a typo cannot
    quietly publish a portrait 2D video under a film's headline.
    """
    if mode is None:
        return None
    if mode not in MODE_BACKENDS:
        raise ValueError(f"unknown mode {mode!r}; expected one of {sorted(MODE_BACKENDS)}")
    return MODE_BACKENDS[mode]



@router.post("/youtube/generate")
async def youtube_generate(req: YouTubeGenerateRequest) -> dict:
    """Trigger YouTube video generation for a given story."""
    import traceback
    from app.channels import ChannelConfigError
    from app.youtube import generate_youtube_video
    try:
        try:
            sid = uuid.UUID(req.story_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid story_id (must be a uuid)")

        draft_id = await generate_youtube_video(
            story_id=sid,
            channel_id=req.channel_id,
            upload_preference=req.upload_preference
        )
        if draft_id is None:
            raise HTTPException(status_code=404, detail="story not found")

        return {"draft_id": str(draft_id)}
    except HTTPException:
        raise
    except ChannelConfigError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        print(f"Error in youtube_generate: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/youtube/jobs")
async def youtube_job_start(req: YouTubeJobRequest) -> dict:
    """Start a generation run in the background and return its job id.

    Separate from POST /youtube/generate, which blocks until the render
    finishes and is what the existing Drafts button relies on. Adding a second
    surface leaves that path exactly as it is.
    """
    import asyncio

    from app import channels
    from app.channels import ChannelConfigError
    from app.jobs import create_job, fail_job, finish_job
    from app.youtube import generate_youtube_video

    try:
        try:
            sid = uuid.UUID(req.story_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid story_id (must be a uuid)")

        try:
            backend = backend_for_mode(req.mode)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        # Resolved synchronously, same as /youtube/generate: a bad channel_id
        # must fail the request, never a background task that already returned 202.
        await channels.resolve(req.channel_id)

        job_id = await create_job(kind=req.mode or "short", story_id=sid)
    except HTTPException:
        raise
    except ChannelConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def run() -> None:
        try:
            draft_id = await generate_youtube_video(
                story_id=sid,
                channel_id=req.channel_id,
                upload_preference=req.upload_preference,
                backend=backend,
                job_id=job_id,
            )
            if draft_id is None:
                # A guard refused the video. That is a completed decision, not a
                # crash, and the reason is already in the worker log.
                await fail_job(job_id, "generation aborted by a quality guard; see worker logs")
            else:
                await finish_job(job_id, draft_id)
        except Exception as exc:  # noqa: BLE001
            await fail_job(job_id, str(exc))

    # Held so the task is not garbage-collected mid-render.
    task = asyncio.create_task(run())
    _RUNNING_JOBS.add(task)
    task.add_done_callback(_RUNNING_JOBS.discard)

    return {"job_id": str(job_id)}


@router.get("/youtube/jobs/{job_id}")
async def youtube_job_status(job_id: str) -> dict:
    """Current stage of a run. Polled by the GUI."""
    from app.jobs import get_job

    try:
        jid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid job_id (must be a uuid)")

    job = await get_job(jid)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return {
        key: (str(value) if isinstance(value, uuid.UUID) else value)
        for key, value in job.items()
    }




@router.get("/stories")
async def get_stories() -> list[dict]:
    """Fetch pending stories for the Inbox."""
    from app.db import get_pending_stories
    return await get_pending_stories()


class ManualStoryRequest(BaseModel):
    headline: str
    channel_id: str = Field(min_length=1)


@router.post("/stories/manual")
async def create_manual_story_endpoint(req: ManualStoryRequest) -> dict:
    """Create a manual story idea."""
    from app.db import create_manual_story
    story_id = await create_manual_story(req.headline, req.channel_id)
    return {"id": str(story_id)}


@router.get("/drafts")
async def get_drafts() -> list[dict]:
    """Fetch all drafts."""
    from app.db import get_drafts
    return await get_drafts()


@router.get("/youtube/analytics")
async def youtube_analytics_endpoint() -> dict:
    """Fetch analytics for all published videos."""
    from app.db import get_drafts
    from app.youtube import get_youtube_analytics
    
    drafts = await get_drafts()
    video_ids = []
    for d in drafts:
        if d.get("status") == "published" and d.get("published_ids") and isinstance(d["published_ids"], dict):
            yt_id = d["published_ids"].get("youtube")
            if yt_id:
                video_ids.append(yt_id)
                
    if not video_ids:
        return {}
        
    return await get_youtube_analytics(video_ids)


@router.get("/config/{key}")
async def get_config_endpoint(key: str) -> dict:
    """Fetch a configuration object by key."""
    from app.db import get_config
    val = await get_config(key)
    if val is None:
        raise HTTPException(status_code=404, detail="config key not found")
    return val


@router.put("/config/{key}")
async def set_config_endpoint(key: str, request: Request) -> dict:
    """Update a configuration object by key."""
    from app.db import set_config
    try:
        val = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    await set_config(key, val)
    return {"status": "ok"}


__all__ = ["router"]
