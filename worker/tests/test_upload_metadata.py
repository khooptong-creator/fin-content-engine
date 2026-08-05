from pathlib import Path

import pytest

from app.channels import Channel

FINANCE = Channel(
    id="finance",
    display_name="Finance",
    voice_key="adult_male",
    script_prompt="A prompt.",
    extra_blocklist=(),
)

KIDS = Channel(
    id="kids",
    display_name="Kids",
    voice_key="baby",
    script_prompt="A prompt.",
    extra_blocklist=(),
)


def test_upload_txt_contains_title_and_description(tmp_path):
    from app.youtube import _write_upload_txt

    path = _write_upload_txt(tmp_path, FINANCE, "My Title", "My long description.")
    text = path.read_text(encoding="utf-8")

    assert path.name == "upload.txt"
    assert "My Title" in text
    assert "My long description." in text


def test_upload_txt_reminds_about_made_for_kids_on_the_kids_channel(tmp_path):
    from app.youtube import _write_upload_txt

    text = _write_upload_txt(tmp_path, KIDS, "T", "D").read_text(encoding="utf-8")
    assert "Made for kids" in text


def test_upload_txt_has_no_kids_reminder_on_finance(tmp_path):
    from app.youtube import _write_upload_txt

    text = _write_upload_txt(tmp_path, FINANCE, "T", "D").read_text(encoding="utf-8")
    assert "Made for kids" not in text


def test_empty_description_raises(tmp_path):
    """No title-as-description fallback. An empty description is a real failure."""
    from app.youtube import _require_metadata

    with pytest.raises(ValueError) as exc:
        _require_metadata({"title": "T", "description": ""})
    assert "description" in str(exc.value)


def test_missing_title_raises():
    from app.youtube import _require_metadata

    with pytest.raises(ValueError) as exc:
        _require_metadata({"title": "", "description": "D"})
    assert "title" in str(exc.value)


def test_valid_metadata_returns_both():
    from app.youtube import _require_metadata

    title, description = _require_metadata({"title": "T", "description": "D"})
    assert (title, description) == ("T", "D")


import uuid
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
@patch("app.youtube._fetch_story_details")
@patch("app.youtube._record_youtube_draft")
@patch("app.youtube._generate_script_for_story")
@patch("app.youtube._generate_frame_audio")
@patch("app.youtube._build_frames")
@patch("app.youtube.subprocess.run")
async def test_generation_writes_upload_txt_and_records_metadata(
    mock_run, mock_frames, mock_audio, mock_script, mock_record, mock_fetch, tmp_path
):
    from app import youtube

    story_id = uuid.uuid4()
    mock_fetch.return_value = {"headline": "Test Story"}
    mock_script.return_value = (
        "---\ntitle: Real Title\ndescription: A real SEO description.\npreset: adult_male\n---\n\n"
        "# Scene 1\nVoiceover: A\n\n# Scene 2\nVoiceover: B\n\n"
        "# Scene 3\nVoiceover: C\n\n# Scene 4\nVoiceover: D\n"
    )
    mock_record.return_value = uuid.uuid4()
    mock_run.return_value = MagicMock(stdout="mocked")
    mock_audio.return_value = []
    mock_frames.return_value = []

    with patch("app.youtube.VIDEOS_DIR", tmp_path), patch(
        "app.channels.resolve", AsyncMock(return_value=FINANCE)
    ):
        await youtube.generate_youtube_video(
            story_id=story_id, channel_id="finance", upload_preference="manual"
        )

    upload_txt = tmp_path / f"story-{story_id}" / "upload.txt"
    assert upload_txt.exists()
    assert "Real Title" in upload_txt.read_text(encoding="utf-8")

    kwargs = mock_record.call_args.kwargs
    assert kwargs["title"] == "Real Title"
    assert kwargs["description"] == "A real SEO description."


@pytest.mark.asyncio
@patch("app.youtube._fetch_story_details")
@patch("app.youtube._record_youtube_draft")
@patch("app.youtube._generate_script_for_story")
@patch("app.youtube._generate_frame_audio")
@patch("app.youtube._build_frames")
@patch("app.youtube.subprocess.run")
async def test_bad_metadata_aborts_before_render(
    mock_run, mock_frames, mock_audio, mock_script, mock_record, mock_fetch, tmp_path
):
    """Empty description must abort before the render subprocess runs.

    If validation regresses to after the render (its old position), this
    assertion on mock_run is the one that would catch it.
    """
    from app import youtube

    story_id = uuid.uuid4()
    mock_fetch.return_value = {"headline": "Test Story"}
    mock_script.return_value = (
        "---\ntitle: Real Title\npreset: adult_male\n---\n\n"
        "# Scene 1\nVoiceover: A\n\n# Scene 2\nVoiceover: B\n\n"
        "# Scene 3\nVoiceover: C\n\n# Scene 4\nVoiceover: D\n"
    )
    mock_run.return_value = MagicMock(stdout="mocked")
    mock_audio.return_value = []
    mock_frames.return_value = []

    with patch("app.youtube.VIDEOS_DIR", tmp_path), patch(
        "app.channels.resolve", AsyncMock(return_value=FINANCE)
    ):
        with pytest.raises(ValueError, match="description"):
            await youtube.generate_youtube_video(
                story_id=story_id, channel_id="finance", upload_preference="manual"
            )

    mock_run.assert_not_called()
    mock_frames.assert_not_called()
    assert not (tmp_path / f"story-{story_id}" / "upload.txt").exists()
