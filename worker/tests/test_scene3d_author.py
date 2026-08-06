"""Cloud authoring tests. extract_js is pure — no network, no model."""
from unittest.mock import AsyncMock, patch

import pytest

from app.scene3d.author import SceneAuthoringError, author_shot, extract_js
from app.storyboard import Frame, Storyboard


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


# ---------------------------------------------------------------------------
# Shot authoring (network-free — _call_model is patched)
# ---------------------------------------------------------------------------


def _board():
    board = Storyboard(meta={"title": "The Vault"}, direction="dusk, warm")
    board.frames = [
        Frame(
            index=1,
            title="Open",
            voiceover="It began quietly.",
            scene="wide of the hill",
            duration=5.0,
        ),
        Frame(
            index=2,
            title="Turn",
            voiceover="Then it did not.",
            scene="push in on the door",
            duration=4.0,
        ),
    ]
    return board


@pytest.mark.asyncio
async def test_shot_prompt_carries_world_and_prior_shots():
    board = _board()
    with patch(
        "app.scene3d.author._call_model",
        new=AsyncMock(return_value="```js\ncam.at(0,2,8);\n```"),
    ) as call:
        await author_shot(
            board, board.frames[1],
            "function buildWorld(){}",
            ["cam.orbit(9,3,6);"],
        )
    user_prompt = call.await_args.args[1]
    assert "buildWorld" in user_prompt
    assert "cam.orbit(9,3,6);" in user_prompt
    assert "push in on the door" in user_prompt


@pytest.mark.asyncio
async def test_shot_prompt_feeds_the_previous_error_back():
    """The retry has to know what broke, or it reruns the same mistake."""
    board = _board()
    with patch(
        "app.scene3d.author._call_model",
        new=AsyncMock(return_value="```js\ncam.at(0,2,8);\n```"),
    ) as call:
        await author_shot(
            board, board.frames[0], "world", [],
            last_error="TypeError: Prim.hill is not a function",
        )
    assert "Prim.hill is not a function" in call.await_args.args[1]


@pytest.mark.asyncio
async def test_shot_raises_rather_than_returning_a_stub():
    board = _board()
    with patch(
        "app.scene3d.author._call_model",
        new=AsyncMock(return_value="Sorry, I cannot."),
    ):
        with pytest.raises(SceneAuthoringError):
            await author_shot(board, board.frames[0], "world", [])
