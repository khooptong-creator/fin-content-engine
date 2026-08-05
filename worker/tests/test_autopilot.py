"""Autopilot must generate under each story's own channel, or not at all.

The bug these cover: the job read a channel from DEFAULT_YOUTUBE_CHANNEL_ID and
applied it to every pending story, so setting it to `finance` generated a kids
story in the finance voice. Nothing downstream would notice.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.channels import ChannelConfigError


def _story(channel_id, story_id=None):
    return {
        "id": str(story_id or uuid.uuid4()),
        "headline": "A headline",
        "status": "inbox",
        "channel_id": channel_id,
        "items": [],
    }


@pytest.mark.asyncio
async def test_generates_under_each_storys_own_channel():
    from app import ideation

    finance, kids = _story("finance"), _story("kids")
    gen = AsyncMock(return_value=uuid.uuid4())

    with patch("app.ideation.db.get_pending_stories", AsyncMock(return_value=[finance, kids])), \
            patch("app.ideation.generate_youtube_video", gen):
        await ideation.autopilot_job()

    assert gen.await_count == 2
    used = {c.kwargs["channel_id"] for c in gen.await_args_list}
    assert used == {"finance", "kids"}
    ids = {str(c.kwargs["story_id"]) for c in gen.await_args_list}
    assert ids == {finance["id"], kids["id"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("empty", [None, "", "   "])
async def test_story_without_a_channel_is_skipped_not_defaulted(empty, monkeypatch):
    """No env var, no config value, nothing may supply a channel here."""
    from app import ideation

    monkeypatch.setenv("DEFAULT_YOUTUBE_CHANNEL_ID", "finance")

    unassigned = _story(empty)
    assigned = _story("kids")
    gen = AsyncMock(return_value=uuid.uuid4())

    with patch("app.ideation.db.get_pending_stories", AsyncMock(return_value=[unassigned, assigned])), \
            patch("app.ideation.generate_youtube_video", gen):
        await ideation.autopilot_job()

    # The unassigned story is skipped; the assigned one still runs.
    assert gen.await_count == 1
    assert gen.await_args.kwargs["channel_id"] == "kids"
    assert str(gen.await_args.kwargs["story_id"]) == assigned["id"]


@pytest.mark.asyncio
async def test_default_channel_env_var_is_not_read_at_all(monkeypatch):
    """Setting the old env var must not resurrect the default-channel path."""
    from app import ideation

    monkeypatch.setenv("DEFAULT_YOUTUBE_CHANNEL_ID", "finance")
    gen = AsyncMock(return_value=uuid.uuid4())

    with patch("app.ideation.db.get_pending_stories", AsyncMock(return_value=[_story(None)])), \
            patch("app.ideation.generate_youtube_video", gen):
        await ideation.autopilot_job()

    gen.assert_not_awaited()


@pytest.mark.asyncio
async def test_channel_config_error_is_logged_distinctly_and_does_not_stop_the_run():
    """A bad channel config is a configuration fault to go and fix. It must not
    be indistinguishable from a generic generation failure in the log."""
    from app import ideation

    bad, good = _story("typo"), _story("kids")

    async def _gen(*, story_id, channel_id, upload_preference):
        if channel_id == "typo":
            raise ChannelConfigError("unknown channel 'typo'; configured: finance, kids")
        return uuid.uuid4()

    gen = AsyncMock(side_effect=_gen)
    fake_log = MagicMock()

    with patch("app.ideation.db.get_pending_stories", AsyncMock(return_value=[bad, good])), \
            patch("app.ideation.generate_youtube_video", gen), \
            patch("app.ideation.log", fake_log):
        await ideation.autopilot_job()

    events = [c.args[0] for c in fake_log.error.call_args_list if c.args]
    assert "autopilot_channel_config_error" in events
    assert "autopilot_generation_error" not in events

    # The bad story must not take the rest of the batch down with it.
    assert gen.await_count == 2


@pytest.mark.asyncio
async def test_generic_failure_keeps_its_own_event_name():
    from app import ideation

    gen = AsyncMock(side_effect=RuntimeError("render died"))
    fake_log = MagicMock()

    with patch("app.ideation.db.get_pending_stories", AsyncMock(return_value=[_story("finance")])), \
            patch("app.ideation.generate_youtube_video", gen), \
            patch("app.ideation.log", fake_log):
        await ideation.autopilot_job()

    events = [c.args[0] for c in fake_log.error.call_args_list if c.args]
    assert events == ["autopilot_generation_error"]


@pytest.mark.asyncio
async def test_respects_the_per_run_cap(monkeypatch):
    from app import ideation

    monkeypatch.setenv("AUTOPILOT_MAX_DRAFTS_PER_RUN", "2")
    gen = AsyncMock(return_value=uuid.uuid4())
    stories = [_story("finance") for _ in range(5)]

    with patch("app.ideation.db.get_pending_stories", AsyncMock(return_value=stories)), \
            patch("app.ideation.generate_youtube_video", gen):
        await ideation.autopilot_job()

    assert gen.await_count == 2
