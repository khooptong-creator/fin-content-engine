"""Gate wiring. Chromium is exercised in the e2e run; here asyncio.to_thread
is patched out so verify_shot runs without a browser."""
from pathlib import Path
from unittest.mock import patch

import pytest

from app.scene3d.probes import ProbeStats, ShotVerdict
from app.scene3d.verify import PROBE_FRACTIONS, verify_shot


def _stats(phash):
    return {"mean_luma": 0.4, "variance": 0.05, "phash": phash}


def _probes(hashes):
    return [ProbeStats(t=t, mean_luma=0.4, variance=0.05, phash=h) for t, h in zip((0.5, 2.5, 4.5), hashes)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _patch_to_thread(return_value):
    """Make ``asyncio.to_thread`` a no-op that returns the given value."""
    async def _fake(fn, *a, **kw):
        return return_value
    return patch("app.scene3d.verify.asyncio.to_thread", side_effect=_fake)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verify_shot_passes_a_healthy_frame(tmp_path):
    verdict = ShotVerdict(True)
    probes = _probes(["0000ffff00001111", "0000ffff00003333", "0000ffff0000cccc"])
    with _patch_to_thread((None, probes, [])):
        result, result_probes, errors = await verify_shot(
            tmp_path / "f01.html", 6.0, tmp_path
        )
    assert result.ok
    assert len(result_probes) == 3
    assert errors == []


@pytest.mark.asyncio
async def test_console_error_fails_the_shot_before_probing(tmp_path):
    """A shot that threw is rejected on the error, not on how it happened to look."""
    verdict = ShotVerdict(False, "runtime error: TypeError: Prim.hill is not a function")
    with _patch_to_thread((verdict, [], ["TypeError: Prim.hill is not a function"])):
        result, probes, errors = await verify_shot(
            tmp_path / "f01.html", 6.0, tmp_path
        )
    assert not result.ok
    assert "TypeError" in result.reason
    assert errors


@pytest.mark.asyncio
async def test_too_few_probes_are_judged_by_the_predicate(tmp_path):
    """The gate still runs judge_shot on whatever probes come back."""
    # Return only 1 probe — should fail the minimum-count check
    verdict = ShotVerdict(True)
    probes = _probes(["0000ffff00001111"])[:1]
    with _patch_to_thread((None, probes, [])):
        result, _, _ = await verify_shot(
            tmp_path / "f01.html", 3.0, tmp_path
        )
    assert not result.ok
    assert "expected 3" in result.reason


@pytest.mark.asyncio
async def test_probe_stats_are_returned_as_dataclasses(tmp_path):
    probes = _probes(["0000ffff00001111", "0000ffff00003333", "0000ffff0000cccc"])
    with _patch_to_thread((None, probes, [])):
        _, result_probes, _ = await verify_shot(
            tmp_path / "f01.html", 3.0, tmp_path
        )
    assert all(isinstance(p, ProbeStats) for p in result_probes)
