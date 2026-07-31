"""Autopilot Ideation Job."""

import os
import structlog
from app import db
from app.youtube import generate_youtube_video

log = structlog.get_logger()

async def autopilot_job() -> None:
    """
    Finds the top pending stories from the inbox and automatically kicks off video generation.
    """
    log.info("autopilot_job_started")
    
    # 1. Get channel ID
    channel_id = os.environ.get("DEFAULT_YOUTUBE_CHANNEL_ID")
    if not channel_id:
        log.warning("autopilot_skipped_no_channel_id", detail="Set DEFAULT_YOUTUBE_CHANNEL_ID env var")
        return
        
    # 2. Get pending stories (these are already sorted by created_at DESC)
    # At most 3 per run so we don't spam
    MAX_DRAFTS = int(os.environ.get("AUTOPILOT_MAX_DRAFTS_PER_RUN", "3"))
    stories = await db.get_pending_stories()
    if not stories:
        log.info("autopilot_no_pending_stories")
        return
        
    top_stories = stories[:MAX_DRAFTS]
    log.info("autopilot_found_stories", count=len(top_stories))
    
    # 3. Generate drafts for each
    for story in top_stories:
        story_id_str = story["id"]
        # Convert to UUID if it isn't already, but get_pending_stories returns dicts directly from DB.
        import uuid
        try:
            sid = uuid.UUID(str(story_id_str))
            log.info("autopilot_generating_video", story_id=str(sid))
            # Auto upload preference
            await generate_youtube_video(
                story_id=sid, 
                channel_id=channel_id,
                upload_preference="auto"
            )
        except Exception as e:
            log.error("autopilot_generation_error", story_id=str(story_id_str), error=str(e))
            
    log.info("autopilot_job_completed")
