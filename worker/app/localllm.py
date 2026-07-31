"""Local LLM frame planning via Ollama.

The model never writes HTML. It picks an archetype and fills its slots, which is
a few dozen tokens of JSON instead of a few thousand tokens of GSAP and CSS.
That is why a 7B model running on one consumer GPU is enough here, and why a
rate limit can no longer stop a batch.

If Ollama is unreachable or returns unusable JSON, planning falls back to a
deterministic heuristic. A frame always gets a shape.
"""

from __future__ import annotations

import json
import os
import re

from typing import Sequence

import httpx
import structlog

from app.archetypes import ARCHETYPES, FALLBACK_ARCHETYPE, catalogue_for_prompt

log = structlog.get_logger()

# 127.0.0.1 rather than localhost: on Windows, localhost resolves to ::1 first
# and Ollama binds IPv4 only, so httpx fails every connection attempt.
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT", "120"))

SYSTEM_PROMPT = """You design one scene of a vertical finance explainer watched by teenagers and adults.

Choose the archetype that best carries the narration, then fill its slots.

ARCHETYPES:
{catalogue}

ACCENTS: accent (neutral highlight), positive (good/growth), warning (caution), negative (loss/cost).

RULES:
- Output ONE JSON object and nothing else. No markdown fence, no commentary.
- Shape: {{"archetype": "<name>", "slots": {{...}}}}
- Copy on screen is not the narration. Compress it: short, punchy, scannable.
- Respect each slot's stated word limits. Long strings overflow the frame.
- Numbers belong in stat_reveal or bar_chart, not buried in prose.
- Pick the archetype that fits the idea, and vary it across a video."""


def _extract_json(text: str) -> dict | None:
    """Pull the first JSON object out of a model response."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            return None
        candidate = text[start : end + 1]
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def heuristic_plan(voiceover: str, scene: str, title: str) -> dict:
    """Deterministic fallback so a frame always has a shape.

    Deliberately simple: it reads the narration for the signals each archetype
    exists to carry, and defaults to a title card when nothing stands out.
    """
    text = f"{voiceover} {scene}".strip()

    if re.search(r"\d+\s*%|\d[\d,]*\.?\d*\s*(crore|lakh|million|billion|bn|k)\b", text, re.I):
        number = re.search(r"\d[\d,]*\.?\d*\s*%?", text)
        return {
            "archetype": "stat_reveal",
            "slots": {
                "headline": title or "By the numbers",
                "value": (number.group(0).strip() if number else "?"),
                "label": "the figure",
                "accent": "warning",
            },
        }

    if re.search(r"\b(versus|vs\.?|instead of|rather than|compared to)\b", text, re.I):
        return {
            "archetype": "comparison",
            "slots": {
                "headline": title or "Compare",
                "left_title": "Option A", "left_value": "?",
                "right_title": "Option B", "right_value": "?",
            },
        }

    return {
        "archetype": FALLBACK_ARCHETYPE,
        "slots": {"headline": title or (voiceover[:60] if voiceover else "..."), "subhead": ""},
    }


def _validate(plan: dict, voiceover: str, scene: str, title: str) -> tuple[dict, bool]:
    """Reject a plan naming an unknown archetype or carrying no slots.

    Returns ``(plan, used_fallback)`` — see :func:`plan_frame`.
    """
    if not isinstance(plan, dict):
        return heuristic_plan(voiceover, scene, title), True
    name = plan.get("archetype")
    if name not in ARCHETYPES:
        log.warning("unknown_archetype", requested=name)
        return heuristic_plan(voiceover, scene, title), True
    if not isinstance(plan.get("slots"), dict) or not plan["slots"]:
        log.warning("archetype_missing_slots", archetype=name)
        return heuristic_plan(voiceover, scene, title), True
    return plan, False


async def _ask(
    client: httpx.AsyncClient, user_prompt: str, exclude: Sequence[str]
) -> tuple[str | None, str]:
    """One Ollama round trip. Returns (raw_response, error) — never raises."""
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": user_prompt,
        "system": SYSTEM_PROMPT.format(catalogue=catalogue_for_prompt(exclude)),
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.4, "num_predict": 400},
    }
    try:
        response = await client.post(f"{OLLAMA_URL}/api/generate", json=payload)
        response.raise_for_status()
        return response.json().get("response", ""), ""
    except Exception as exc:
        return None, str(exc)[:160]


async def plan_frame(
    voiceover: str,
    scene: str,
    title: str,
    direction: str = "",
    client: httpx.AsyncClient | None = None,
    used_archetypes: Sequence[str] = (),
) -> tuple[dict, bool]:
    """Ask the local model for one frame's archetype and slots.

    Returns ``(plan, used_fallback)``. A frame always gets a shape, so callers
    can render unconditionally, but the flag says whether the model actually
    produced it. Callers must not infer this by comparing the plan to
    ``heuristic_plan`` — the model legitimately agrees with the heuristic on
    simple frames, and counting those as failures can abort a sound video.
    """
    spent = list(dict.fromkeys(used_archetypes))
    unused = [n for n in ARCHETYPES if n not in spent]

    base_prompt = (
        f"GLOBAL DIRECTION: {direction or 'Clean, bold, 3D finance explainer.'}\n"
        f"FRAME TITLE: {title}\n"
        f"SCENE DESCRIPTION: {scene}\n"
        f"NARRATION SPOKEN OVER THIS FRAME: \"{voiceover}\"\n"
    )
    if spent:
        base_prompt += (
            f"ALREADY USED EARLIER IN THIS VIDEO: {', '.join(spent)}. "
            "Pick a different shape unless the narration truly demands a repeat.\n"
        )
    base_prompt += "\nDesign this frame."

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=OLLAMA_TIMEOUT)
    try:
        raw, error = await _ask(client, base_prompt, exclude=())
        if raw is None:
            log.warning("ollama_unavailable", error=error, fallback="heuristic")
            return heuristic_plan(voiceover, scene, title), True

        plan = _extract_json(raw)
        if plan is None:
            log.warning("ollama_unparseable_response", sample=raw[:160])
            return heuristic_plan(voiceover, scene, title), True
        plan, fell_back = _validate(plan, voiceover, scene, title)

        # Naming spent shapes in prose is a weak signal at 7B. If it repeated one
        # anyway and fresh shapes exist, ask again with those removed from the
        # menu outright — it cannot repeat what it cannot see.
        if not fell_back and unused and plan.get("archetype") in spent:
            log.info("archetype_repeat_retry", repeated=plan["archetype"], unused=unused)
            retry_raw, _ = await _ask(client, base_prompt, exclude=spent)
            retry_plan = _extract_json(retry_raw) if retry_raw else None
            if retry_plan is not None:
                candidate, candidate_fell_back = _validate(retry_plan, voiceover, scene, title)
                if not candidate_fell_back:
                    return candidate, False
        return plan, fell_back
    finally:
        if owns_client:
            await client.aclose()


async def is_available() -> bool:
    """Whether Ollama is reachable and the configured model is present."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{OLLAMA_URL}/api/tags")
            response.raise_for_status()
            names = {m.get("name", "") for m in response.json().get("models", [])}
    except Exception:
        return False
    base = OLLAMA_MODEL.split(":")[0]
    return any(n == OLLAMA_MODEL or n.startswith(f"{base}:") for n in names)
