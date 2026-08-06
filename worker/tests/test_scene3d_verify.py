"""Gate wiring. The browser is patched; Chromium is exercised in the e2e run."""
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.scene3d.probes import ProbeStats
from app.scene3d.verify import PROBE_FRACTIONS, verify_shot


def _stats(phash):
    return {"mean_luma": 0.4, "variance": 0.05, "phash": phash}


@asynccontextmanager
async def _mock_browser():
    """Stand in for _browser() — yields a dummy so no real Playwright runs."""
    yield MagicMock()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _patch_verify(page, errors=None):
    """Apply both patches needed to keep verify_shot offline."""
    if errors is None:
        errors = []
    # screenshot() must return bytes for write_bytes()
    page.screenshot = AsyncMock(return_value=b"\x89PNG\r\n\x1a\nfake")
    page.close = AsyncMock()
    return (
        patch("app.scene3d.verify._browser", side_effect=_mock_browser),
        patch("app.scene3d.verify._open_page", return_value=(page, errors)),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verify_shot_passes_a_healthy_frame(tmp_path):
    page = AsyncMock()
    page.evaluate = AsyncMock(
        side_effect=[
            _stats("0000ffff00001111"),
            _stats("0000ffff00003333"),
            _stats("0000ffff0000cccc"),
        ]
    )
    p_browser, p_open = _patch_verify(page)
    with p_browser, p_open:
        verdict, probes, errors = await verify_shot(
            tmp_path / "f01.html", 6.0, tmp_path
        )
    assert verdict.ok
    assert len(probes) == 3
    assert errors == []


@pytest.mark.asyncio
async def test_console_error_fails_the_shot_before_probing(tmp_path):
    """A shot that threw is rejected on the error, not on how it happened to look."""
    page = AsyncMock()
    page.evaluate = AsyncMock(return_value=_stats("0000ffff00001111"))
    p_browser, p_open = _patch_verify(page, errors=["TypeError: P.hill is not a function"])
    with p_browser, p_open:
        verdict, probes, errors = await verify_shot(
            tmp_path / "f01.html", 6.0, tmp_path
        )
    assert not verdict.ok
    assert "TypeError" in verdict.reason
    assert errors


@pytest.mark.asyncio
async def test_probes_are_taken_at_the_declared_fractions(tmp_path):
    page = AsyncMock()
    page.evaluate = AsyncMock(return_value=_stats("0000ffff00001111"))
    p_browser, p_open = _patch_verify(page)
    with p_browser, p_open:
        await verify_shot(tmp_path / "f01.html", 10.0, tmp_path)
    # Args passed as [slug, t] (array form for Playwright evaluate)
    seeked = [c.args[1][1] for c in page.evaluate.call_args_list]
    assert seeked == [f * 10.0 for f in PROBE_FRACTIONS]


@pytest.mark.asyncio
async def test_probe_stats_are_returned_as_dataclasses(tmp_path):
    page = AsyncMock()
    page.evaluate = AsyncMock(return_value=_stats("0000ffff00001111"))
    p_browser, p_open = _patch_verify(page)
    with p_browser, p_open:
        _, probes, _ = await verify_shot(tmp_path / "f01.html", 3.0, tmp_path)
    assert all(isinstance(p, ProbeStats) for p in probes)
