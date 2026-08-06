"""The gate's judgement, tested without a browser.

Probe statistics are computed in-page and handed back as plain numbers, so
every predicate here is a pure function over a dataclass. That is the whole
reason this module is separate from verify.py.
"""

import pytest

from app.scene3d.probes import (
    ProbeStats,
    frames_are_distinct,
    judge_shot,
)


def p(t=0.5, mean_luma=0.4, variance=0.05, phash="0" * 16):
    """Shorthand for building a ProbeStats in tests."""
    return ProbeStats(t=t, mean_luma=mean_luma, variance=variance, phash=phash)


# ---------------------------------------------------------------------------
# Healthy shot
# ---------------------------------------------------------------------------

def test_healthy_shot_passes():
    probes = [
        p(0.1, phash="0000ffff00001111"),
        p(0.5, phash="0000ffff00003333"),
        p(0.9, phash="0000ffff0000cccc"),
    ]
    assert judge_shot(probes).ok


# ---------------------------------------------------------------------------
# Black frame
# ---------------------------------------------------------------------------

def test_black_frame_is_rejected():
    probes = [p(0.1, mean_luma=0.002), p(0.5), p(0.9)]
    verdict = judge_shot(probes)
    assert not verdict.ok
    assert "black" in verdict.reason


# ---------------------------------------------------------------------------
# Uniform fill
# ---------------------------------------------------------------------------

def test_uniform_fill_is_rejected():
    """Camera inside geometry, or staring into empty fog."""
    probes = [p(0.1, variance=0.0001), p(0.5), p(0.9)]
    verdict = judge_shot(probes)
    assert not verdict.ok
    assert "uniform" in verdict.reason


# ---------------------------------------------------------------------------
# Static shot
# ---------------------------------------------------------------------------

def test_completely_static_shot_is_rejected():
    """All three probes identical means the timeline never drove the render."""
    probes = [
        p(0.1, phash="abcd" * 4),
        p(0.5, phash="abcd" * 4),
        p(0.9, phash="abcd" * 4),
    ]
    verdict = judge_shot(probes)
    assert not verdict.ok
    assert "static" in verdict.reason


# ---------------------------------------------------------------------------
# Probe count
# ---------------------------------------------------------------------------

def test_too_few_probes_is_rejected():
    assert not judge_shot([p(0.5)]).ok


def test_empty_probes_is_rejected():
    """An absolute check. A shot that produced no probes is not a passing shot."""
    assert not judge_shot([]).ok


# ---------------------------------------------------------------------------
# Inter-frame distinctness
# ---------------------------------------------------------------------------

def test_distinctness_between_neighbouring_shots():
    a = p(phash="0000000000000000")
    b = p(phash="ffffffffffffffff")
    assert frames_are_distinct(a, b)


def test_neighbouring_shots_that_look_identical_are_not_distinct():
    a = p(phash="0f0f0f0f0f0f0f0f")
    b = p(phash="0f0f0f0f0f0f0f0f")
    assert not frames_are_distinct(a, b)


@pytest.mark.parametrize("bad", ["", "xyz", "0" * 15])
def test_malformed_phash_is_not_distinct(bad):
    """Refuse to call a shot distinct on the basis of a hash we cannot read."""
    assert not frames_are_distinct(p(phash=bad), p(phash="0" * 16))
