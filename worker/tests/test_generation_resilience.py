"""Two ways a finished render used to be lost or misreported.

Finding 5: an unguarded thumbnail shell-out threw away a rendered MP4 on any
machine without playwright installed.
Finding 6: `upload_preference="auto"` marked the draft `published` even though
the publish path is gone, so the drafts page showed "Live" for a video nobody
had uploaded.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.channels import Channel

FINANCE = Channel(
    id="finance",
    display_name="Finance",
    voice_key="adult_male",
    script_prompt="A prompt.",
    extra_blocklist=(),
)

GOOD_SCRIPT = (
    "---\ntitle: Real Title\ndescription: A real SEO description.\npreset: adult_male\n---\n\n"
    "# Scene 1\nVoiceover: A\n\n# Scene 2\nVoiceover: B\n\n"
    "# Scene 3\nVoiceover: C\n\n# Scene 4\nVoiceover: D\n"
)


def _arrange(mocks):
    """Give every mocked step the return value a healthy run would produce."""
    mock_run, mock_frames, mock_audio, mock_script, mock_record, mock_fetch = mocks
    mock_fetch.return_value = {"headline": "Test Story"}
    mock_script.return_value = GOOD_SCRIPT
    mock_record.return_value = uuid.uuid4()
    mock_run.return_value = MagicMock(stdout="mocked")
    mock_audio.return_value = []
    mock_frames.return_value = []


@pytest.mark.asyncio
@patch("app.youtube._fetch_story_details")
@patch("app.youtube._record_youtube_draft")
@patch("app.youtube._generate_script_for_story")
@patch("app.youtube._generate_frame_audio")
@patch("app.youtube._build_frames")
@patch("app.youtube.subprocess.run")
async def test_thumbnail_failure_still_records_the_draft(
    mock_run, mock_frames, mock_audio, mock_script, mock_record, mock_fetch, tmp_path
):
    """No playwright on the box must not cost us a completed render."""
    from app import youtube

    story_id = uuid.uuid4()
    _arrange((mock_run, mock_frames, mock_audio, mock_script, mock_record, mock_fetch))

    thumb = AsyncMock(side_effect=FileNotFoundError("npx playwright not found"))

    with patch("app.youtube.VIDEOS_DIR", tmp_path), \
            patch("app.channels.resolve", AsyncMock(return_value=FINANCE)), \
            patch("app.youtube._generate_thumbnail", thumb):
        draft_id = await youtube.generate_youtube_video(
            story_id=story_id, channel_id="finance", upload_preference="manual"
        )

    thumb.assert_awaited_once()
    assert draft_id is not None
    mock_record.assert_called_once()
    # upload.txt is still written, so the manual upload still has its metadata.
    assert (tmp_path / f"story-{story_id}" / "upload.txt").exists()


@pytest.mark.asyncio
@patch("app.youtube._fetch_story_details")
@patch("app.youtube._record_youtube_draft")
@patch("app.youtube._generate_script_for_story")
@patch("app.youtube._generate_frame_audio")
@patch("app.youtube._build_frames")
@patch("app.youtube.subprocess.run")
async def test_render_failure_is_not_swallowed_by_the_thumbnail_guard(
    mock_run, mock_frames, mock_audio, mock_script, mock_record, mock_fetch, tmp_path
):
    """The guard covers the thumbnail call only. A failed render still aborts."""
    import subprocess

    from app import youtube

    story_id = uuid.uuid4()
    _arrange((mock_run, mock_frames, mock_audio, mock_script, mock_record, mock_fetch))
    mock_run.side_effect = subprocess.CalledProcessError(1, "hyperframes")

    with patch("app.youtube.VIDEOS_DIR", tmp_path), \
            patch("app.channels.resolve", AsyncMock(return_value=FINANCE)):
        with pytest.raises(Exception, match="rendering failed"):
            await youtube.generate_youtube_video(
                story_id=story_id, channel_id="finance", upload_preference="manual"
            )

    mock_record.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("upload_preference", ["manual", "auto"])
@patch("app.youtube._fetch_story_details")
@patch("app.youtube._record_youtube_draft")
@patch("app.youtube._generate_script_for_story")
@patch("app.youtube._generate_frame_audio")
@patch("app.youtube._build_frames")
@patch("app.youtube.subprocess.run")
async def test_new_drafts_are_always_pending(
    mock_run, mock_frames, mock_audio, mock_script, mock_record, mock_fetch,
    upload_preference, tmp_path
):
    """Nothing publishes any more, so nothing may claim to be published.

    `auto` used to write status="published" with no video id, which the drafts
    page rendered as "Published / Live".
    """
    from app import youtube

    story_id = uuid.uuid4()
    _arrange((mock_run, mock_frames, mock_audio, mock_script, mock_record, mock_fetch))

    with patch("app.youtube.VIDEOS_DIR", tmp_path), \
            patch("app.channels.resolve", AsyncMock(return_value=FINANCE)), \
            patch("app.youtube._generate_thumbnail", AsyncMock()):
        await youtube.generate_youtube_video(
            story_id=story_id, channel_id="finance", upload_preference=upload_preference
        )

    kwargs = mock_record.call_args.kwargs
    assert kwargs["status"] == "pending"
    assert kwargs["external_id"] is None
