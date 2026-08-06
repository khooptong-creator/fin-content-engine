"""The DSL is hand-written and copied verbatim into every project.

These tests assert the contract the generated code depends on, so a careless
edit to primitives.js fails here rather than in a render an hour later.

Corrected for the spike findings (2026-08-03-spike-result.md):
- Vendored file is ``three.min.js`` (UMD r160.1), NOT ``three.module.js`` (ESM).
- ``primitives.js`` is a classic script — no ``import`` or ``export``.
- Three.js is accessed via the ``THREE`` global, never imported.
"""

from pathlib import Path

import re

import pytest

ASSETS = Path(__file__).resolve().parents[1] / "app" / "scene3d" / "assets"


def _strip_comments(source: str) -> str:
    """Remove JS comments so checks don't false-positive on doc strings."""
    # Multi-line comments
    source = re.sub(r"/\*[\s\S]*?\*/", "", source)
    # Single-line comments (but not URLs)
    source = re.sub(r"//(?![^\s]*\.[^\s]*).*", "", source)
    return source

PRIM_EXPORTS = [
    # Stage
    "createStage",
    # Geometry
    "dome", "cone", "box", "cyl", "sphere", "plane",
    # Lights
    "sun", "ambient", "pointGlow",
    # Effects
    "bloom",
    # Seeded PRNG
    "seed", "rand", "randBetween",
    # Layout
    "place", "scatter", "row",
    # Composites
    "tree", "flower", "fence", "path", "windowPane", "door", "building",
    # Finance / data-vis
    "coin", "vault", "stack", "chart3d",
    # Type
    "text3d", "beat",
]


# ---------------------------------------------------------------------------
# Asset presence
# ---------------------------------------------------------------------------

def test_three_is_vendored():
    """We vendor r160.1 UMD, not a later ESM build — the spike proved
    HyperFrames does not preserve ``type="module"`` on injected
    sub-compositions."""
    path = ASSETS / "three.min.js"
    assert path.exists(), f"three.min.js not found at {path}"
    # Sanity: it's the UMD build, not a thin ESM wrapper
    content = path.read_text(encoding="utf-8")
    assert "THREE" in content


def test_three_module_not_present():
    """The ESM build must NOT be vendored — it silently fails in HyperFrames.
    See spike-result Correction 1."""
    assert not (ASSETS / "three.module.js").exists(), (
        "three.module.js (ESM) must not be vendored — "
        "HyperFrames does not preserve type=module on sub-compositions"
    )


# ---------------------------------------------------------------------------
# primitives.js structure
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def primitives_source():
    return (ASSETS / "primitives.js").read_text(encoding="utf-8")


def test_primitives_exists():
    assert (ASSETS / "primitives.js").exists()


@pytest.mark.parametrize("name", PRIM_EXPORTS)
def test_primitives_namespace_exports(name, primitives_source):
    """Every primitive must be on the ``Prim`` namespace (global pattern)."""
    assert (f"Prim.{name}" in primitives_source
            or f"{name}:" in primitives_source), (
        f"Prim.{name} not found in primitives.js"
    )


def test_primitives_is_classic_script(primitives_source):
    """Correction 1 from the spike: ESM ``import``/``export`` dies silently
    when HyperFrames injects the sub-composition. The file must be a classic
    script that assigns to ``window.Prim``."""
    code = _strip_comments(primitives_source)
    assert "import " not in code, (
        "primitives.js must not contain 'import' — use the THREE global from three.min.js"
    )
    assert "export " not in code, (
        "primitives.js must not contain 'export' — assign to window.Prim instead"
    )


def test_primitives_uses_three_global(primitives_source):
    """References must go through the global ``THREE``, not an import."""
    assert "global.THREE" in primitives_source or "var THREE = global.THREE" in primitives_source, (
        "primitives.js must read THREE from the global scope "
        "(e.g. var THREE = global.THREE)"
    )
    assert "from './three.module.js'" not in primitives_source
    assert "unpkg.com" not in primitives_source
    assert "cdn.jsdelivr" not in primitives_source


def test_primitives_exposes_on_window(primitives_source):
    """The namespace must land on ``window.Prim`` so generated shot modules
    can reach it."""
    assert "global.Prim = Prim" in primitives_source or "window.Prim = Prim" in primitives_source


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_primitives_never_uses_wall_clock(primitives_source):
    """A render is a seek, not a playback. Wall-clock time desynchronises it."""
    banned = ("requestAnimationFrame", "Date.now", "performance.now", "setInterval")
    for token in banned:
        assert token not in primitives_source, f"{token} breaks deterministic seek"


def test_primitives_never_uses_math_random(primitives_source):
    """Unseeded randomness breaks reproducible renders."""
    code = _strip_comments(primitives_source)
    assert "Math.random" not in code, (
        "Math.random is non-deterministic; use Prim.rand() (seeded mulberry32)"
    )


def test_primitives_has_seeded_prng(primitives_source):
    """The three PRNG entries must all be present."""
    for name in ("seed", "rand", "randBetween"):
        assert name in primitives_source, f"seeded PRNG missing: {name}"
    # Verify the mulberry32 constant is present (not a thin alias for Math.random)
    assert "1664525" in primitives_source, "expected mulberry32 PRNG constants"
