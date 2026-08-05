"""Autopilot Ideation Job."""

import os
import uuid

import structlog

from app import db
from app.channels import ChannelConfigError
from app.youtube import generate_youtube_video

log = structlog.get_logger()


async def autopilot_job() -> None:
    """
    Find the top pending stories in the inbox and kick off video generation.

    Each story is generated under its own `stories.channel_id`. There is no
    default: a story that carries no channel is skipped, because guessing one
    produces a toddler script in the finance voice (or the reverse) and nothing
    downstream would catch it.
    """
    log.info("autopilot_job_started")

    # At most N per run so we don't spam.
    max_drafts = int(os.environ.get("AUTOPILOT_MAX_DRAFTS_PER_RUN", "3"))

    # Already sorted by created_at DESC.
    stories = await db.get_pending_stories()
    if not stories:
        log.info("autopilot_no_pending_stories")
        return

    top_stories = stories[:max_drafts]
    log.info("autopilot_found_stories", count=len(top_stories))

    for story in top_stories:
        story_id_str = str(story.get("id"))

        channel_id = story.get("channel_id")
        if not isinstance(channel_id, str) or not channel_id.strip():
            log.warning(
                "autopilot_skipped_story_without_channel",
                story_id=story_id_str,
                detail="story has no channel_id; assign one before it can be generated",
            )
            continue

        try:
            sid = uuid.UUID(story_id_str)
        except ValueError:
            log.error("autopilot_invalid_story_id", story_id=story_id_str)
            continue

        log.info("autopilot_generating_video", story_id=story_id_str, channel_id=channel_id)
        try:
            await generate_youtube_video(
                story_id=sid,
                channel_id=channel_id,
                # Uploads are manual; this no longer selects a publish behaviour.
                upload_preference="manual",
            )
        except ChannelConfigError as e:
            # Distinct from a generic failure on purpose: a bad or missing
            # channel config is a configuration problem to go and fix, not a
            # transient generation error to retry tomorrow.
            log.error(
                "autopilot_channel_config_error",
                story_id=story_id_str,
                channel_id=channel_id,
                error=str(e),
            )
            continue
        except Exception as e:
            log.error(
                "autopilot_generation_error",
                story_id=story_id_str,
                channel_id=channel_id,
                error=str(e),
            )
            continue

    log.info("autopilot_job_completed")
