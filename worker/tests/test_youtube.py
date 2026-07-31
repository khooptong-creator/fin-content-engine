import uuid
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from app.youtube import (
    generate_youtube_video,
    publish_youtube_draft,
    _get_youtube_credentials,
    _parse_storyboard_frontmatter,
)


@pytest.mark.asyncio
@patch("app.youtube._fetch_story_details")
@patch("app.youtube._record_youtube_draft")
@patch("app.youtube._generate_script_for_story")
@patch("app.youtube._generate_frame_audio")
@patch("app.youtube._build_frames")
@patch("app.youtube.subprocess.run")
async def test_generate_youtube_video_manual(
    mock_run, mock_frames, mock_audio, mock_script, mock_record, mock_fetch, tmp_path
):
    story_id = uuid.uuid4()
    mock_fetch.return_value = {"headline": "Test Story"}
    mock_script.return_value = "---\ntitle: Test\npreset: daisy-days\n---\n\n# Scene 1\nVoiceover: Hello\n"
    mock_record.return_value = uuid.uuid4()
    mock_run.return_value = MagicMock(stdout="Mocked hyperframes output")
    mock_audio.return_value = []
    mock_frames.return_value = []

    with patch("app.youtube.VIDEOS_DIR", tmp_path):
        draft_id = await generate_youtube_video(
            story_id=story_id,
            channel_id="financial-channel",
            upload_preference="manual",
        )

    assert draft_id is not None
    video_dir = tmp_path / f"story-{story_id}"
    assert video_dir.exists()

    mock_record.assert_called_once()
    _, kwargs_rec = mock_record.call_args
    assert kwargs_rec["upload_preference"] == "manual"
    assert kwargs_rec["status"] == "pending"
    assert kwargs_rec["external_id"] is None


@pytest.mark.asyncio
@patch("app.youtube._fetch_story_details")
@patch("app.youtube._record_youtube_draft")
@patch("app.youtube._generate_script_for_story")
@patch("app.youtube._generate_frame_audio")
@patch("app.youtube._build_frames")
@patch("app.youtube.subprocess.run")
async def test_generate_youtube_video_auto_status(
    mock_run, mock_frames, mock_audio, mock_script, mock_record, mock_fetch, tmp_path
):
    story_id = uuid.uuid4()
    mock_fetch.return_value = {"headline": "Test Story"}
    mock_script.return_value = "---\ntitle: Test\npreset: daisy-days\n---\n\n# Scene 1\nVoiceover: Hello\n"
    mock_record.return_value = uuid.uuid4()
    mock_run.return_value = MagicMock(stdout="Mocked hyperframes output")
    mock_audio.return_value = []
    mock_frames.return_value = []

    with patch("app.youtube.VIDEOS_DIR", tmp_path):
        await generate_youtube_video(
            story_id=story_id,
            channel_id="financial-channel",
            upload_preference="auto",
        )

    _, kwargs_rec = mock_record.call_args
    assert kwargs_rec["status"] == "published"


@pytest.mark.asyncio
@patch("app.youtube._fetch_story_details")
@patch("app.youtube._record_youtube_draft")
@patch("app.youtube._generate_script_for_story")
@patch("app.youtube._generate_frame_audio")
# Patch the dispatcher, not a backend: the guard under test is about the
# placeholder ratio, which is the same whichever backend produced the frames.
# Patching a backend directly lets FRAME_BACKEND silently route around the mock
# and fire a live request at whatever the local one talks to.
@patch("app.youtube._build_frames")
@patch("app.youtube.subprocess.run")
async def test_generation_aborts_when_most_frames_are_placeholders(
    mock_run, mock_frames, mock_audio, mock_script, mock_record, mock_fetch, tmp_path
):
    """Placeholder cards render and pass validation, so nothing downstream would
    notice the video is mostly fallback. It must never reach YouTube."""
    story_id = uuid.uuid4()
    mock_fetch.return_value = {"headline": "Test Story"}
    mock_script.return_value = (
        "---\ntitle: Test\n---\n\n# Scene 1\nVoiceover: A\n\n# Scene 2\nVoiceover: B\n"
    )
    mock_record.return_value = uuid.uuid4()
    mock_run.return_value = MagicMock(stdout="Mocked hyperframes output")
    mock_audio.return_value = []
    # Both frames fell back, e.g. the LLM was rate limited.
    mock_frames.return_value = ["f01-frame", "f02-frame"]

    with patch("app.youtube.VIDEOS_DIR", tmp_path):
        draft_id = await generate_youtube_video(
            story_id=story_id,
            channel_id="financial-channel",
            upload_preference="auto",
        )

    assert draft_id is None
    mock_record.assert_not_called()


@pytest.mark.asyncio
@patch("app.youtube._fetch_story_details")
@patch("app.youtube._record_youtube_draft")
@patch("app.youtube._generate_script_for_story")
@patch("app.youtube._generate_frame_audio")
@patch("app.youtube._build_frames")
@patch("app.youtube.subprocess.run")
async def test_generation_aborts_when_most_frames_are_silent(
    mock_run, mock_frames, mock_audio, mock_script, mock_record, mock_fetch, tmp_path
):
    """Silence renders and validates exactly like narration, so a mute explainer
    passes every downstream check. It must never reach YouTube."""
    story_id = uuid.uuid4()
    mock_fetch.return_value = {"headline": "Test Story"}
    mock_script.return_value = (
        "---\ntitle: Test\n---\n\n# Scene 1\nVoiceover: A\n\n# Scene 2\nVoiceover: B\n"
    )
    mock_record.return_value = uuid.uuid4()
    mock_run.return_value = MagicMock(stdout="Mocked hyperframes output")
    mock_frames.return_value = []
    # Both lines failed TTS, e.g. the account hit its concurrency limit.
    mock_audio.return_value = ["f01-frame", "f02-frame"]

    with patch("app.youtube.VIDEOS_DIR", tmp_path):
        draft_id = await generate_youtube_video(
            story_id=story_id,
            channel_id="financial-channel",
            upload_preference="auto",
        )

    assert draft_id is None
    mock_record.assert_not_called()
    # Aborted before wasting a render on a mute video.
    mock_frames.assert_not_called()


@pytest.mark.asyncio
@patch("app.youtube._upload_to_youtube")
@patch("app.youtube._upload_thumbnail")
@patch("app.youtube.db.get_draft")
@patch("app.youtube.db.update_draft_published")
async def test_publish_youtube_draft_success(
    mock_update, mock_get_draft, mock_upload_thumb, mock_upload_video, tmp_path
):
    draft_id = uuid.uuid4()
    story_id = uuid.uuid4()
    video_dir = tmp_path / f"story-{story_id}" / "renders"
    video_dir.mkdir(parents=True)
    video_path = video_dir / "video.mp4"
    video_path.write_bytes(b"fake mp4")
    thumb_path = video_dir / "thumbnail.jpg"
    thumb_path.write_bytes(b"fake thumb")
    storyboard_path = video_dir.parent / "STORYBOARD.md"
    storyboard_path.write_text(
        "---\ntitle: My Title\ndescription: My Description\n---\n\n# Scene 1\nVoiceover: Hello\n"
    )

    mock_get_draft.return_value = {
        "id": str(draft_id),
        "story_id": str(story_id),
        "headline": "My Headline",
        "platform": "youtube",
        "body": {"file_path": str(video_path)},
        "status": "pending",
    }
    mock_upload_video.return_value = "abc123"

    result = await publish_youtube_draft(draft_id)

    assert result["video_id"] == "abc123"
    assert result["url"] == "https://youtube.com/watch?v=abc123"
    mock_upload_video.assert_called_once_with(str(video_path), "My Title", "My Description")
    mock_upload_thumb.assert_called_once_with("abc123", str(thumb_path))
    mock_update.assert_called_once_with(
        draft_id,
        status="published",
        published_ids={"youtube": "abc123"},
    )


def test_parse_storyboard_frontmatter():
    tmp = Path("/tmp/storyboard_test.md")
    # We can't write to /tmp on Windows; use a temp fixture instead.
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write("---\ntitle: Hello\ndescription: World\npreset: adult_male\n---\n\n# Scene 1\n")
        path = Path(f.name)
    try:
        fm = _parse_storyboard_frontmatter(path)
        assert fm["title"] == "Hello"
        assert fm["description"] == "World"
    finally:
        path.unlink(missing_ok=True)


def test_get_youtube_credentials_missing_token(tmp_path):
    from app.settings import get_settings

    with patch.object(get_settings(), "youtube_token_path", tmp_path / "missing.json"):
        with pytest.raises(RuntimeError):
            _get_youtube_credentials(["https://www.googleapis.com/auth/youtube.upload"])
