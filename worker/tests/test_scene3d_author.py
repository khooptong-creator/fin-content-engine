"""Cloud authoring tests. extract_js is pure — no network, no model."""
import pytest

from app.scene3d.author import SceneAuthoringError, extract_js


def test_extract_js_unwraps_a_fenced_block():
    assert (
        extract_js("Here you go:\n```javascript\nconst a = 1;\n```\n") == "const a = 1;"
    )


def test_extract_js_accepts_a_bare_js_fence():
    assert extract_js("```js\nconst a = 1;\n```") == "const a = 1;"


def test_extract_js_accepts_unfenced_code():
    assert extract_js("const a = 1;") == "const a = 1;"


def test_extract_js_rejects_empty_output():
    """A failed model must raise, never yield an empty module that renders black."""
    with pytest.raises(SceneAuthoringError):
        extract_js("```javascript\n\n```")


def test_extract_js_rejects_prose_with_no_code():
    with pytest.raises(SceneAuthoringError):
        extract_js("I'm sorry, I can't help with that.")


def test_extract_js_rejects_a_direct_three_import():
    """Bypassing the DSL bypasses the flat-shading rules the style depends on."""
    with pytest.raises(SceneAuthoringError):
        extract_js(
            "```javascript\nimport * as THREE from 'three';\nconst a = 1;\n```"
        )


# ---------------------------------------------------------------------------
# Spike Correction 1 — ESM silently fails in HyperFrames
# ---------------------------------------------------------------------------

def test_extract_js_rejects_import_statement():
    with pytest.raises(SceneAuthoringError):
        extract_js("import { dome } from './primitives.js';\nconst a = 1;")


def test_extract_js_rejects_export_statement():
    with pytest.raises(SceneAuthoringError):
        extract_js("export function buildWorld(P) { return { root: null }; }")


def test_extract_js_rejects_three_module_js_in_code():
    with pytest.raises(SceneAuthoringError):
        extract_js("var src = 'three.module.js';\nconst a = 1;")
