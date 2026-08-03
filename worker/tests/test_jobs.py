"""Job stage contract. No DB, no network — the ordering is what the GUI draws."""

import pytest

from app.jobs import STAGES, set_stage


def test_stages_are_the_expected_set_in_order():
    assert STAGES == ["queued", "script", "narration", "world", "shots", "render", "done"]


def test_stage_ordering_is_monotonic():
    """The GUI renders a progress bar from index order, not from a lookup table."""
    assert all(STAGES.index(a) < STAGES.index(b) for a, b in zip(STAGES, STAGES[1:]))


def test_stages_are_unique():
    assert len(set(STAGES)) == len(STAGES)


@pytest.mark.asyncio
async def test_unknown_stage_is_rejected_before_touching_the_db():
    """A typo would render as a bar stuck at an unknown stage — a hang, not a bug."""
    with pytest.raises(ValueError, match="unknown stage"):
        await set_stage("00000000-0000-0000-0000-000000000000", "rendering")
