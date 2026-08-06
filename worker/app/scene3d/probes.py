"""Predicates over rendered-pixel statistics.

The 2D backends could only ever measure proportions of their output — and a
proportion cannot detect a degraded *input*, which is how a one-frame stub
scored 100% on every ratio and shipped. 3D produces inspectable pixels, so the
checks here are absolute and per-shot: does it draw, does it vary, does it move.

Statistics are computed in-page by the browser and arrive as plain numbers, so
nothing in this module does I/O or needs an image library.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# A frame darker than this is unlit, or the camera is inside geometry.
MIN_MEAN_LUMA = float(os.environ.get("MIN_MEAN_LUMA", "0.02"))
# A frame flatter than this is a single fill: void, fog, or an inside-out mesh.
MIN_VARIANCE = float(os.environ.get("MIN_VARIANCE", "0.0008"))
# Perceptual-hash distance at or below this counts as "the same picture".
MAX_HAMMING_FOR_IDENTICAL = int(os.environ.get("MAX_HAMMING_FOR_IDENTICAL", "4"))

PHASH_LEN = 16


@dataclass(frozen=True)
class ProbeStats:
    """One screenshot's summary, computed in-page."""

    t: float
    mean_luma: float
    variance: float
    phash: str


@dataclass(frozen=True)
class ShotVerdict:
    ok: bool
    reason: str = ""


def _hamming(a: str, b: str) -> int | None:
    if len(a) != PHASH_LEN or len(b) != PHASH_LEN:
        return None
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except ValueError:
        return None


def frames_are_distinct(a: ProbeStats, b: ProbeStats) -> bool:
    """True when two probes are visibly different pictures.

    An unreadable hash returns False rather than True: refusing to certify
    distinctness we cannot measure is the safe direction, since the caller
    uses this to reject repetition.
    """
    distance = _hamming(a.phash, b.phash)
    if distance is None:
        return False
    return distance > MAX_HAMMING_FOR_IDENTICAL


def judge_shot(probes: list[ProbeStats]) -> ShotVerdict:
    """Decide whether one shot rendered something worth keeping."""
    if len(probes) < 3:
        return ShotVerdict(False, f"expected 3 probes, got {len(probes)}")

    for probe in probes:
        if probe.mean_luma < MIN_MEAN_LUMA:
            return ShotVerdict(
                False, f"black frame at t={probe.t} (luma {probe.mean_luma:.4f})"
            )
        if probe.variance < MIN_VARIANCE:
            return ShotVerdict(
                False,
                f"uniform fill at t={probe.t} (variance {probe.variance:.6f})",
            )

    first, last = probes[0], probes[-1]
    if not frames_are_distinct(first, last):
        return ShotVerdict(
            False, "static shot: first and last probes are the same picture"
        )

    return ShotVerdict(True)
