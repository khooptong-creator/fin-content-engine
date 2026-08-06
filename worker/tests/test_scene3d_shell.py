"""Tests for the 3D frame shell — the HTML wrapper around a generated shot.

Corrected for spike findings: no type=module, assets/ paths (not ../../), plain
<script> tags, Prim global (no import statements).
"""

import pytest
from app.scene3d.shell import render_3d_frame


# ---------------------------------------------------------------------------
# Composition contract
# ---------------------------------------------------------------------------

def test_shell_declares_the_composition_contract():
    html = render_3d_frame("f01-open", 6.5, "// shot", "Hello there")
    assert 'data-composition-id="f01-open"' in html
    assert 'data-duration="6.5"' in html
    assert 'data-width="1920"' in html
    assert 'data-height="1080"' in html
    assert html.lstrip().startswith("<template>")


def test_shell_wraps_in_template_tag():
    html = render_3d_frame("f99-wrap", 2.0, "// x", "y")
    assert html.strip().startswith("<template>")
    assert html.strip().endswith("</template>")


def test_shell_canvas_is_a_clip_track():
    html = render_3d_frame("f10-canvas", 3.0, "// x", "sub")
    assert 'class="clip"' in html
    assert 'data-track-index="0"' in html


# ---------------------------------------------------------------------------
# Shot embedding and subtitle
# ---------------------------------------------------------------------------

def test_shell_embeds_the_shot_module_and_subtitle():
    html = render_3d_frame(
        "f02-turn", 4.0, "stage.tl.to(state, {x: 1});", "A line of narration"
    )
    assert "stage.tl.to(state, {x: 1});" in html
    assert "A line of narration" in html


def test_shell_escapes_subtitle_html():
    html = render_3d_frame("f03", 3.0, "// shot", 'He said "<b>no</b>" & left')
    assert "<b>no</b>" not in html
    assert "&lt;b&gt;no&lt;/b&gt;" in html


# ---------------------------------------------------------------------------
# Timeline registration
# ---------------------------------------------------------------------------

def test_shell_registers_exactly_one_timeline_under_the_slug():
    html = render_3d_frame("f04-x", 3.0, "// shot", "x")
    assert html.count('window.__timelines["f04-x"]') == 1


def test_shell_includes_stage_render_call():
    html = render_3d_frame("f05-render", 2.0, "// shot", "x")
    assert "stage.render();" in html


# ---------------------------------------------------------------------------
# Spike corrections — no ESM, no type=module, assets/ paths
# ---------------------------------------------------------------------------

def test_shell_never_uses_type_module():
    """Correction 1: type=module dies silently in HyperFrames sub-compositions."""
    html = render_3d_frame("f06-noesm", 3.0, "// shot", "x")
    assert 'type="module"' not in html


def test_shell_never_contains_import_or_export():
    """The shell must not emit ESM syntax — the shot code relies on the Prim
    global and the unpacked stage variables."""
    html = render_3d_frame("f07-noimport", 3.0, "// shot", "x")
    assert "import " not in html
    assert "export " not in html


def test_shell_loads_assets_from_project_root():
    """Correction 2: asset paths must be project-root-relative (assets/…),
    not ../../ traversal — the latter passes render but fails Studio preview
    and lint."""
    html = render_3d_frame("f08-paths", 3.0, "// shot", "x")
    assert 'src="assets/three.min.js"' in html
    assert 'src="assets/primitives.js"' in html
    assert "../../" not in html, (
        "../../ paths fail HyperFrames lint; use assets/ (project-root-relative)"
    )
    # The shell references Prim, not an imported P
    assert "Prim.createStage" in html
    assert "Prim.seed(" in html


def test_shell_unpacks_stage_for_the_shot():
    """The generated shot must receive scene, camera, tl, state, cam already
    unpacked — it should never call Prim.createStage itself."""
    html = render_3d_frame("f09-unpack", 2.0, "// shot", "x")
    assert "var scene = stage.scene" in html
    assert "var camera = stage.camera" in html
    assert "var tl = stage.tl" in html
    assert "var state = stage.state" in html
    assert "var cam = stage.cam" in html


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------

def test_shell_seed_is_per_slug():
    """Different slugs must produce different seeds so scatter positions
    differ across frames."""
    a = render_3d_frame("slug-a", 2.0, "// shot", "x")
    b = render_3d_frame("slug-b", 2.0, "// shot", "x")
    assert "Prim.seed(" in a
    assert "Prim.seed(" in b
    # The seed values must differ
    import re
    seed_a = int(re.search(r"Prim\.seed\((\d+)\)", a).group(1))
    seed_b = int(re.search(r"Prim\.seed\((\d+)\)", b).group(1))
    assert seed_a != seed_b


def test_shell_seed_is_deterministic():
    """Same slug → same seed, so re-renders are byte-identical."""
    a = render_3d_frame("deterministic", 2.0, "// shot", "x")
    b = render_3d_frame("deterministic", 2.0, "// shot", "x")
    assert a == b
