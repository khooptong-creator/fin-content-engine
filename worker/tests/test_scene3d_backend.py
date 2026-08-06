"""Orchestration: retry on rejection, raise rather than substitute."""
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.scene3d.probes import ProbeStats, ShotVerdict
from app.storyboard import Frame, Storyboard


def _board(n=3):
    board = Storyboard(meta={"title": "T"})
    board.frames = [
        Frame(
            index=i,
            title=f"S{i}",
            voiceover=f"line {i}",
            scene=f"scene {i}",
            duration=5.0,
        )
        for i in range(1, n + 1)
    ]
    return board


def _probes(phash):
    return [
        ProbeStats(t=t, mean_luma=0.4, variance=0.05, phash=phash)
        for t in (0.5, 2.5, 4.5)
    ]


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_shots_pass_on_first_attempt(tmp_path):
    from app.scene3d.backend import build_3d_frames

    hashes = iter(["0000000000000001", "00000000000000ff", "000000000000ff00"])
    with (
        patch(
            "app.scene3d.backend.author_world",
            new=AsyncMock(return_value="world"),
        ),
        patch(
            "app.scene3d.backend.author_shot",
            new=AsyncMock(return_value="cam.at(0,1,5);"),
        ),
        patch(
            "app.scene3d.backend.verify_shot",
            new=AsyncMock(
                side_effect=lambda *a, **k: (
                    ShotVerdict(True),
                    _probes(next(hashes)),
                    [],
                )
            ),
        ),
    ):
        failed = await build_3d_frames(_board(), tmp_path)
    assert failed == []


# ---------------------------------------------------------------------------
# Retry on rejection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_rejected_shot_is_retried_with_the_reason(tmp_path):
    from app.scene3d.backend import build_3d_frames

    verdicts = [
        (ShotVerdict(False, "black frame at t=0.5"), [], []),
        (ShotVerdict(True), _probes("0000000000000001"), []),
        (ShotVerdict(True), _probes("00000000000000ff"), []),
        (ShotVerdict(True), _probes("000000000000ff00"), []),
    ]
    shot = AsyncMock(return_value="cam.at(0,1,5);")
    with (
        patch(
            "app.scene3d.backend.author_world",
            new=AsyncMock(return_value="world"),
        ),
        patch("app.scene3d.backend.author_shot", new=shot),
        patch(
            "app.scene3d.backend.verify_shot",
            new=AsyncMock(side_effect=verdicts),
        ),
    ):
        failed = await build_3d_frames(_board(), tmp_path)
    assert failed == []
    assert (
        shot.await_args_list[1].kwargs["last_error"] == "black frame at t=0.5"
    )


# ---------------------------------------------------------------------------
# Exhausted retries — report, never substitute
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_shot_failing_every_attempt_is_reported_not_substituted(tmp_path):
    from app.scene3d.backend import build_3d_frames

    with (
        patch(
            "app.scene3d.backend.author_world",
            new=AsyncMock(return_value="world"),
        ),
        patch(
            "app.scene3d.backend.author_shot",
            new=AsyncMock(return_value="cam.at(0,1,5);"),
        ),
        patch(
            "app.scene3d.backend.verify_shot",
            new=AsyncMock(
                return_value=(ShotVerdict(False, "uniform fill"), [], [])
            ),
        ),
    ):
        failed = await build_3d_frames(_board(1), tmp_path)
    assert failed == ["f01-s1"]
    # Nothing was written in place of the failed shot.
    assert not list((tmp_path / "compositions" / "frames").glob("*.html"))


# ---------------------------------------------------------------------------
# Repeated camera angle
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_repeated_camera_angle_is_rejected(tmp_path):
    """Same failure shape as the 2D archetype-repeat bug, in 3D."""
    from app.scene3d.backend import build_3d_frames

    same = "0f0f0f0f0f0f0f0f"
    with (
        patch(
            "app.scene3d.backend.author_world",
            new=AsyncMock(return_value="world"),
        ),
        patch(
            "app.scene3d.backend.author_shot",
            new=AsyncMock(return_value="cam.at(0,1,5);"),
        ),
        patch(
            "app.scene3d.backend.verify_shot",
            new=AsyncMock(
                return_value=(ShotVerdict(True), _probes(same), [])
            ),
        ),
    ):
        failed = await build_3d_frames(_board(2), tmp_path)
    assert "f02-s2" in failed


# ---------------------------------------------------------------------------
# World failure is fatal
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_world_authoring_failure_raises(tmp_path):
    """No world means no film. Never proceed with an invented one."""
    from app.scene3d.author import SceneAuthoringError
    from app.scene3d.backend import build_3d_frames

    with patch(
        "app.scene3d.backend.author_world",
        new=AsyncMock(side_effect=SceneAuthoringError("model returned no code")),
    ):
        with pytest.raises(SceneAuthoringError):
            await build_3d_frames(_board(), tmp_path)
