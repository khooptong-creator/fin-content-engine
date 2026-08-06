"""Cloud authoring of world and shot modules.

Composing a 3D scene is thousands of tokens of spatial reasoning, well past a
7B, so this stage is cloud-only — the documented exception to the local-first
split. ``qwen2.5:7b`` keeps the 2D archetype path.

Nothing here ever fabricates a module on failure. A generated film whose scenes
were invented by a fallback renders and validates perfectly, which is exactly
how a total upstream outage once produced a publishable draft.
"""

from __future__ import annotations

import os
import re

import structlog

log = structlog.get_logger()

SCENE_MODEL = os.environ.get("SCENE_MODEL", "gemini-2.0-flash")
SCENE_MODEL_PROVIDER = os.environ.get("SCENE_MODEL_PROVIDER", "gemini").lower()
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get(
    "DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"
)

# Matches a fenced JS block — ```javascript, ```js, or bare ```
_FENCE = re.compile(r"```(?:javascript|js)?\s*\n(.*?)```", re.DOTALL)

# Generated code must never import Three.js — it must compose from Prim.
_BANNED_IMPORTS = ("from 'three'", 'from "three"', "three.module.js")


class SceneAuthoringError(RuntimeError):
    """The model did not return usable scene code."""


def extract_js(text: str) -> str:
    """Pull a JavaScript module out of a model response, or refuse it."""
    match = _FENCE.search(text or "")
    code = (match.group(1) if match else (text or "")).strip()

    if not code:
        raise SceneAuthoringError("model returned no code")
    if not any(token in code for token in ("=", "(", "{")):
        raise SceneAuthoringError(
            f"model returned prose, not code: {code[:120]!r}"
        )
    for banned in _BANNED_IMPORTS:
        if banned in code:
            raise SceneAuthoringError(
                "generated code imports Three.js directly; it must use the DSL"
            )
    # ESM syntax silently fails in HyperFrames (Correction 1).
    if re.search(r"\bimport\s+", code) or re.search(r"\bexport\s+", code):
        raise SceneAuthoringError(
            "generated code contains import/export — HyperFrames drops type=module"
        )
    return code


WORLD_SYSTEM_PROMPT = """You are a technical director building a low-poly 3D world for a narrated short film.

You write ONE JavaScript module that builds the film's persistent set: the
terrain, buildings, standing props and palette that every shot will reuse.

AVAILABLE API — the DSL is exposed as the global `Prim`:
  Stage:    Prim.createStage, Prim.seed, Prim.rand, Prim.randBetween
  Geometry: Prim.plane Prim.dome Prim.cone Prim.box Prim.cyl Prim.sphere
  Composite:Prim.tree Prim.flower Prim.fence Prim.path Prim.windowPane Prim.door Prim.building
  Finance:  Prim.coin Prim.vault Prim.stack Prim.chart3d
  Layout:   Prim.scatter Prim.row Prim.place
  Light:    Prim.sun Prim.ambient Prim.pointGlow Prim.bloom
  Type:     Prim.text3d
  Timing:   Prim.beat

HARD RULES:
- NEVER import Three.js. NEVER construct THREE.* directly. Use only Prim.*
- NEVER use requestAnimationFrame, Date.now, performance.now or setInterval.
- NEVER use Math.random. Use Prim.rand() so renders are reproducible.
- NEVER write `import` or `export` — this is a classic script, not an ES module.
- NO humanoid characters of any kind.
- Define exactly one function: `function buildWorld(stage) { ... return { root, palette }; }`
  where `stage` is the object returned by `Prim.createStage(...)` and `root` is
  a THREE.Group built by Prim helpers. `palette` is an object of hex strings the
  shots will reuse.

STYLE: flat-shaded low-poly. Rolling hills as squashed domes, conifers as cones,
scattered flowers, soft dusk palettes. Think a storybook diorama, not realism.

Return ONLY the JavaScript code in a ```javascript fence. No explanation."""


async def author_world(board) -> str:
    """Write the film's persistent set. One call per film."""
    prompt = (
        f"FILM TITLE: {board.title}\n"
        f"DIRECTION: {board.direction or 'none given'}\n\n"
        "SCENES THIS WORLD MUST SUPPORT:\n"
        + "\n".join(
            f"{i}. {f.scene or f.voiceover}" for i, f in enumerate(board.frames, 1)
        )
        + "\n\nBuild one world that every scene above can be filmed inside."
    )
    text = await _call_model(WORLD_SYSTEM_PROMPT, prompt)
    code = extract_js(text)
    log.info("world_authored", title=board.title, chars=len(code))
    return code


SHOT_SYSTEM_PROMPT = """You are a cinematographer framing ONE shot inside an existing low-poly 3D world.

The world module is given to you. You do not rebuild it — you place the camera,
set the light for the time of day, add any props specific to this moment, and
animate the shot on the timeline.

IN SCOPE for your code: `scene`, `camera`, `cam`, `tl`, `state`, and `Prim.*`.
The world's root group is already added to the scene as `world`.

AVAILABLE API — ONLY these, on `Prim`:
  Geometry: Prim.plane Prim.dome Prim.cone Prim.box Prim.cyl Prim.sphere
  Composite:Prim.tree Prim.flower Prim.fence Prim.path Prim.windowPane Prim.door Prim.building
  Finance:  Prim.coin Prim.vault Prim.stack Prim.chart3d
  Layout:   Prim.scatter Prim.row Prim.place
  Light:    Prim.sun Prim.ambient Prim.pointGlow Prim.bloom
  Type:     Prim.text3d
  Timing:   Prim.beat
  Camera:   cam.at(x,y,z) cam.lookAt(x,y,z) cam.dolly(from,to,dur) cam.orbit(r,h,dur,lookAt)

HARD RULES:
- NEVER import Three.js. NEVER construct THREE.* directly.
- NEVER use requestAnimationFrame, Date.now, performance.now or setInterval.
  The renderer SEEKS a paused timeline; wall-clock animation renders frozen.
- NEVER use Math.random. Use Prim.rand().
- ALL animation must be on `tl` (the paused timeline), spanning the shot duration.
- The camera must MOVE or something in frame must move. A completely static
  shot is rejected automatically.
- The camera must be OUTSIDE all geometry and something must be lit and visible.
  A black or uniform frame is rejected automatically.
- NO humanoid characters.
- NEVER write `import` or `export` — this is a classic script, not an ES module.

Write statements only — no function wrapper, no imports, no exports.
Return ONLY JavaScript in a ```javascript fence."""


async def author_shot(
    board,
    frame,
    world_code: str,
    prior_shots: list[str],
    last_error: str | None = None,
) -> str:
    """Frame one scene inside the film's world.

    ``prior_shots`` is passed for the same reason the 2D path passes used
    archetypes: each shot is authored in isolation, and without the history the
    model reaches for the same camera every time and the film reads as one
    angle repeated.
    """
    recent = "\n\n".join(prior_shots[-3:]) or "none yet — this is the first shot"
    parts = [
        f"FILM: {board.title}",
        f"DIRECTION: {board.direction or 'none given'}",
        f"SHOT DURATION: {frame.duration:.1f} seconds",
        "",
        "WORLD MODULE (already built and added to the scene as `world`):",
        "```javascript",
        world_code,
        "```",
        "",
        f"THIS SHOT — scene: {frame.scene or frame.title}",
        f"NARRATION OVER IT: {frame.voiceover}",
        "",
        "PREVIOUS SHOTS (do not repeat these camera angles):",
        "```javascript",
        recent,
        "```",
    ]
    if last_error:
        parts += [
            "",
            "YOUR PREVIOUS ATTEMPT WAS REJECTED. Fix this specific problem:",
            f"  {last_error}",
        ]
    text = await _call_model(SHOT_SYSTEM_PROMPT, "\n".join(parts))
    code = extract_js(text)
    log.info(
        "shot_authored", slug=frame.slug, chars=len(code), retry=bool(last_error)
    )
    return code


def _is_retryable_status(status: int) -> bool:
    """True for rate limits and server errors worth retrying."""
    return status in (429, 503, 500)


async def _call_model(system: str, user: str) -> str:
    """Single cloud call. Retries transient failures, then raises."""
    if SCENE_MODEL_PROVIDER == "deepseek":
        return await _call_deepseek(system, user)
    return await _call_gemini(system, user)


async def _call_gemini(system: str, user: str) -> str:
    import asyncio

    from google import genai
    from google.genai import types
    from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

    from app.youtube import _is_retryable

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    async def _once() -> str:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=SCENE_MODEL,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system, temperature=0.7
            ),
        )
        return response.text or ""

    return await _once()


async def _call_deepseek(system: str, user: str) -> str:
    import asyncio

    import httpx
    from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

    if not DEEPSEEK_API_KEY:
        raise RuntimeError(
            "DEEPSEEK_API_KEY is required when SCENE_MODEL_PROVIDER=deepseek"
        )

    model = SCENE_MODEL if SCENE_MODEL != "gemini-2.0-flash" else "deepseek-chat"

    def _should_retry(exc: BaseException) -> bool:
        if isinstance(exc, httpx.HTTPStatusError):
            return _is_retryable_status(exc.response.status_code)
        return isinstance(exc, (httpx.ConnectError, httpx.RemoteProtocolError))

    @retry(
        retry=retry_if_exception(_should_retry),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    async def _once() -> str:
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(
                f"{DEEPSEEK_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.7,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"] or ""

    return await _once()
