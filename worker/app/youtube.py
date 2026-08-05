"""YouTube video automation pipeline (Path B)."""
import os
import subprocess
import uuid
import asyncio
from pathlib import Path
from typing import Any

import structlog

from app import db
from app.channels import BASE_COMPLIANCE_RULES, Channel
from app.settings import get_settings
from app.storyboard import (
    Frame,
    Storyboard,
    assign_timing,
    attach_audio,
    parse_storyboard,
    prune_stale_assets,
    render_index_html,
)

log = structlog.get_logger()
settings = get_settings()

VIDEOS_DIR = Path(os.environ.get("VIDEOS_DIR", "../videos")).resolve()

# Above this share of fallback title cards the video no longer represents the
# story, so generation aborts instead of producing something publishable.
MAX_PLACEHOLDER_RATIO = float(os.environ.get("MAX_PLACEHOLDER_RATIO", "0.25"))

# Narration carries the explainer, so the bar is stricter than for visuals: a
# quarter of a video can survive fallback cards, but not a quarter in silence.
MAX_SILENT_RATIO = float(os.environ.get("MAX_SILENT_RATIO", "0.2"))

# A real explainer opens, develops and closes. Anything shorter than this is a
# truncated script rather than a video, and the ratio guards below cannot catch
# it: one good frame out of one is a perfect score.
MIN_SCRIPT_FRAMES = int(os.environ.get("MIN_SCRIPT_FRAMES", "3"))

# 503 UNAVAILABLE from Gemini is routine and clears in seconds.
SCRIPT_MAX_ATTEMPTS = int(os.environ.get("SCRIPT_MAX_ATTEMPTS", "4"))


def _get_youtube_credentials(scopes: list[str]) -> Any:
    """
    Load and refresh OAuth credentials for the YouTube Data API.
    Looks for an existing token at FCE_YOUTUBE_TOKEN_PATH. If the token is
    expired but has a refresh token, it refreshes and rewrites the file.
    Raises a clear RuntimeError if no credentials are available.
    """
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    token_path = settings.youtube_token_path
    creds = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json(), encoding="utf-8")

    if not creds or not creds.valid:
        raise RuntimeError(
            "YouTube OAuth credentials are missing or invalid. "
            f"Run the OAuth flow to create {token_path} "
            f"(e.g., `python worker/test_youtube_upload.py`)."
        )

    return creds


async def _stage(job_id, stage: str, done: int = 0, total: int = 0) -> None:
    """Report progress when a job is tracking this run, otherwise do nothing.

    Progress is optional so the original synchronous entrypoint — and every
    test that drives it — keeps working untouched.
    """
    if job_id is None:
        return
    from app.jobs import set_stage

    try:
        await set_stage(job_id, stage, done, total)
    except Exception as exc:  # noqa: BLE001
        # Losing a progress update must never abort a render that is otherwise fine.
        log.warning("stage_update_failed", stage=stage, error=str(exc))


async def generate_youtube_video(
    story_id: uuid.UUID,
    channel_id: str,
    upload_preference: str = "manual",
    backend: str | None = None,
    job_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """
    Main entrypoint for generating a YouTube video from a story.
    Triggered via GUI dashboard.

    `backend` selects the frame backend for this run only, so one worker can
    produce both formats without an env change or a restart; `FRAME_BACKEND`
    supplies the default. `job_id`, when given, receives stage progress.
    """
    log.info("youtube_generation_started", story_id=str(story_id), channel_id=channel_id)

    from app import channels
    channel = await channels.resolve(channel_id)

    # 1. Fetch story details
    story = await _fetch_story_details(story_id)
    if not story:
        log.error("story_not_found", story_id=str(story_id))
        return None
        
    slug = f"story-{story_id}"
    video_dir = VIDEOS_DIR / slug
    video_dir.mkdir(parents=True, exist_ok=True)
    
    # 2. Scripting & Storyboard Generation
    await _stage(job_id, "script")
    try:
        script_content = await _generate_script_for_story(story, channel)
    except Exception as e:
        log.error("youtube_generation_aborted", reason="script_generation_failed", error=str(e))
        return None
    storyboard_path = video_dir / "STORYBOARD.md"
    storyboard_path.write_text(script_content, encoding="utf-8")

    # Validate upload metadata before any frame building or rendering. A script
    # with a missing/empty title or description must abort here, not after
    # burning the entire HyperFrames/ffmpeg render.
    frontmatter = _parse_storyboard_frontmatter(storyboard_path)
    title, description = _require_metadata(frontmatter)

    # 3. Storyboard compilation (voice first, visuals second)
    #
    # Narration is generated per frame so each frame's on-screen duration can be
    # derived from its own measured audio. A single concatenated mp3 leaves no
    # per-frame timing to key visuals off, which is why this pipeline used to
    # fall back to a static placeholder card.
    board = parse_storyboard(script_content)
    if len(board.frames) < MIN_SCRIPT_FRAMES:
        # Too short to be the story, and every later guard is a ratio: they read
        # a one-frame script as a flawless video.
        log.error(
            "youtube_generation_aborted",
            reason="script_too_short",
            story_id=str(story_id),
            frames=len(board.frames),
            minimum=MIN_SCRIPT_FRAMES,
        )
        return None

    log.info("youtube_audio_generation_started", video_dir=str(video_dir), frames=len(board.frames))
    await _stage(job_id, "narration", 0, len(board.frames))
    silenced = await _generate_frame_audio(board, video_dir, script_content)
    if silenced:
        # Silence renders and validates exactly like narration, so nothing
        # downstream notices. A mostly-mute explainer is not the video the story
        # asked for; refuse it here rather than publish it.
        ratio = len(silenced) / len(board.frames)
        log.error(
            "narration_degraded",
            story_id=str(story_id),
            silenced=len(silenced),
            frames=len(board.frames),
            slugs=silenced,
        )
        if ratio > MAX_SILENT_RATIO:
            log.error("youtube_generation_aborted", reason="too_many_silent_frames")
            return None

    prune_stale_assets(board, video_dir)
    attach_audio(board, video_dir)
    assign_timing(board, board.meta.get("pacing"))

    index_html_path = video_dir / "index.html"
    index_html_path.write_text(
        render_index_html(board, with_bgm=(video_dir / "bgm.mp3").exists()),
        encoding="utf-8",
    )
    duration = board.total_duration
    log.info("storyboard_compiled", frames=len(board.frames), duration=duration)

    await _stage(job_id, "shots", 0, len(board.frames))
    placeholders = await _build_frames(board, video_dir, backend=backend)
    if placeholders:
        # A placeholder renders fine and passes validation, so nothing downstream
        # would notice that most of the video is fallback title cards. Refuse to
        # continue rather than publish that under the story's headline.
        ratio = len(placeholders) / len(board.frames)
        log.error(
            "frame_generation_degraded",
            story_id=str(story_id),
            placeholders=len(placeholders),
            frames=len(board.frames),
            slugs=placeholders,
        )
        if ratio > MAX_PLACEHOLDER_RATIO:
            log.error("youtube_generation_aborted", reason="too_many_placeholder_frames")
            return None

    package_json_path = video_dir / "package.json"
    if not package_json_path.exists():
        package_json_path.write_text(
            '{ "name": "generated-video", "private": true, "type": "module" }',
            encoding="utf-8",
        )
    
    await _stage(job_id, "render")

    import sys
    import subprocess
    from starlette.concurrency import run_in_threadpool
    npx_cmd = "npx.cmd" if sys.platform == "win32" else "npx"
    try:
        def run_hyperframes():
            return subprocess.run(
                [npx_cmd, "hyperframes", "render", "--output", "renders/video.mp4"],
                cwd=str(video_dir),
                capture_output=True,
                check=True
            )
            
        proc = await asyncio.to_thread(run_hyperframes)
        log.info("youtube_rendering_complete")
    except subprocess.CalledProcessError as e:
        log.error("youtube_rendering_failed", returncode=e.returncode)
        raise Exception("youtube rendering failed")
    except Exception as e:
        log.error("youtube_rendering_error", error=str(e))
        raise

    mp4_path = video_dir / "renders" / "video.mp4"

    _write_upload_txt(video_dir, channel, title, description)

    # 4. Local Draft Registration
    # User requested all output videos to be stored locally and NOT pushed to VPS/Cloud.
    # "manual" means a human reviews in the dashboard first; "auto" tries to upload immediately.
    status = "pending" if upload_preference == "manual" else "published"
    external_id = None

    draft_id = await _record_youtube_draft(
        story_id=story_id,
        channel_id=channel_id,
        upload_preference=upload_preference,
        file_path=str(mp4_path),
        status=status,
        external_id=external_id,
        title=title,
        description=description,
    )
    
    log.info("youtube_generation_finished", draft_id=str(draft_id))
    return draft_id

async def _fetch_story_details(story_id: uuid.UUID) -> dict | None:
    pool = await db.get_pool()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT headline FROM stories WHERE id = %s", (story_id,))
            row = await cur.fetchone()
            if row:
                return {"headline": row["headline"]}
    return None

async def _generate_script_for_story(story: dict, channel: Channel) -> str:
    """
    Call the LLM to generate the storyboard markdown for one channel.

    The channel supplies voice and prompt. Compliance rules come from
    channels.BASE_COMPLIANCE_RULES and are not channel-overridable.
    """
    headline = story.get("headline", "Default Headline")

    import os
    from google import genai
    from google.genai import types

    blocklist_str = ", ".join(f'"{word}"' for word in channel.effective_blocklist)

    system_instruction = f"""You are generating a script for a faceless YouTube explainer video.
Your Voice & Personality: {channel.script_prompt}

COMPLIANCE RULES (CRITICAL):
{BASE_COMPLIANCE_RULES}
ABSOLUTELY FORBIDDEN WORDS: {blocklist_str}.
These rules and forbidden words apply to the YAML frontmatter, including the
title and description fields, exactly as they apply to the narration.

FORMAT:
You must output a valid markdown document that starts with YAML frontmatter.
Example format:
---
title: "The video title"
description: "A highly detailed, SEO-optimized description of the video. Write this as a human expert. NEVER mention or allude to AI, ChatGPT, or automated generation."
preset: {channel.voice_key}
music: soft upbeat playful
---

# Video direction
A clean, minimal, yet highly descriptive cartoonized explainer video.

# Scene 1
Voiceover: "Welcome to today's topic..."
Visual: "A bright, cute title card..."
"""

    user_prompt = f"Write a video script for the following story headline:\n{headline}"

    log.info("gemini_generation_started", channel_id=channel.id, preset=channel.voice_key)

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable is not set")

    client = genai.Client(api_key=api_key)

    def call_gemini():
        # The SDK is synchronous; off the event loop so the pool keeps serving.
        return client.models.generate_content(
            model='gemini-flash-latest',
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.7,
            ),
        )

    # This used to swallow every failure and return a one-scene stub. That stub
    # renders cleanly and passes the placeholder and silence guards — one good
    # frame out of one is a perfect score — so a Gemini outage produced a five
    # second "video" recorded as a draft ready to publish. There is no safe
    # fabricated script: fail loudly and let the caller abort.
    last_error: Exception | None = None
    for attempt in range(1, SCRIPT_MAX_ATTEMPTS + 1):
        try:
            response = await asyncio.to_thread(call_gemini)
            log.info("gemini_generation_completed", attempt=attempt)
            return response.text
        except Exception as e:
            last_error = e
            if attempt == SCRIPT_MAX_ATTEMPTS or not _is_retryable(e):
                break
            delay = 2 ** attempt
            log.warning(
                "gemini_generation_retry",
                attempt=attempt,
                delay=delay,
                error=str(e)[:160],
            )
            await asyncio.sleep(delay)

    log.error("gemini_generation_failed", attempts=attempt, error=str(last_error))
    raise RuntimeError(f"script generation failed after {attempt} attempts: {last_error}")

async def _record_youtube_draft(
    story_id: uuid.UUID,
    channel_id: str,
    upload_preference: str,
    file_path: str,
    status: str,
    external_id: str | None,
    title: str,
    description: str,
) -> uuid.UUID | None:
    pool = await db.get_pool()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                # channel_id and upload_preference are written twice on purpose.
                # Readers go through body->>'...' (see db.py), but migration 006
                # added real columns, and leaving them NULL/default means any SQL
                # that trusts the schema silently reads every draft as 'manual'.
                """
                INSERT INTO drafts
                (story_id, platform, format, body, status, published_ids,
                 channel_id, upload_preference)
                VALUES (%s, 'youtube', 'video', %s::jsonb, %s, %s::jsonb, %s, %s)
                RETURNING id
                """,
                (
                    story_id,
                    db._dumps({
                        "file_path": file_path,
                        "channel_id": channel_id,
                        "upload_preference": upload_preference,
                        "title": title,
                        "description": description,
                    }),
                    status,
                    db._dumps({"youtube": external_id}) if external_id else None,
                    channel_id,
                    upload_preference,
                )
            )
            row = await cur.fetchone()
            return row["id"] if row else None

# ElevenLabs voice ids keyed by the storyboard's `preset` field.
#
# These must be voices the account can actually reach. The original ids (Antoni,
# Rachel, Josh, Elli, Gigi) are legacy library voices: on a free plan the API
# rejects them with 402 paid_plan_required, and every frame silently fell back to
# silence. Everything below is `premade`, which is free-tier usable.
# Re-check with: client.voices.get_all() -> category == "premade".
VOICE_MAP = {
    "teenage_boy": "TX3LPaxmHKxFdv7VOQHJ",   # Liam - energetic social-media creator
    "teenage_girl": "cgSgspJ2msm6clMCkdW9",  # Jessica - playful, bright, warm
    "adult_male": "cjVigY5qzO86Huf0OWal",    # Eric - smooth, trustworthy
    "adult_female": "EXAVITQu4vr4xnSDxMaL",  # Sarah - mature, reassuring
    "news": "onwK4e9ZLuTAKqWW03F9",          # Daniel - steady broadcaster
    "baby": "cgSgspJ2msm6clMCkdW9",          # Jessica - no child voice is premade
}
DEFAULT_VOICE = "adult_male"

# Free plan allows 2 parallel TTS requests; anything more is rejected with 429.
TTS_MAX_CONCURRENCY = int(os.environ.get("TTS_MAX_CONCURRENCY", "2"))
TTS_MAX_ATTEMPTS = 4


def _extract_preset(script_content: str) -> str:
    import re

    match = re.search(r"^preset:\s*(.+)$", script_content, re.MULTILINE)
    return match.group(1).strip() if match else "default"


async def _synthesize_line(client: Any, text: str, voice_id: str, output_path: Path) -> None:
    """Render one narration line to its own mp3.

    elevenlabs>=2 removed client.generate(); text_to_speech.convert() replaces it
    and takes voice_id/model_id rather than voice/model. It is not awaited — it
    returns the async byte iterator directly.
    """
    audio_stream = client.text_to_speech.convert(
        voice_id=voice_id,
        text=text,
        model_id="eleven_multilingual_v2",
        output_format="mp3_44100_128",
    )
    with open(output_path, "wb") as fh:
        async for chunk in audio_stream:
            fh.write(chunk)


def _write_silence(output_path: Path, seconds: float = 4.0) -> None:
    """Emit a silent placeholder so a failed line can't break the whole render."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
            "-t", str(seconds), "-q:a", "9", "-acodec", "libmp3lame", str(output_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


async def _generate_frame_audio(
    board: Storyboard, video_dir: Path, script_content: str
) -> list[str]:
    """Render one voice clip per frame into assets/voice/NN.mp3.

    Per-frame rather than one concatenated track: the compiler measures each clip
    to place its frame on the timeline, so a single blob would leave every frame
    without a duration of its own.

    Returns the slugs that fell back to silence.
    """
    from elevenlabs.client import AsyncElevenLabs

    voice_dir = video_dir / "assets" / "voice"
    voice_dir.mkdir(parents=True, exist_ok=True)

    preset = _extract_preset(script_content)
    voice_id = VOICE_MAP.get(preset, VOICE_MAP[DEFAULT_VOICE])
    api_key = os.environ.get("ELEVENLABS_API_KEY")

    if not api_key:
        log.warning("elevenlabs_api_key_missing", fallback="silent_frames")
        for frame in board.frames:
            _write_silence(video_dir / frame.voice_filename)
        return

    client = AsyncElevenLabs(api_key=api_key)

    # ElevenLabs bills concurrency, not just characters: the free plan allows 2
    # requests in parallel and 429s the rest. Fanning out one call per frame put
    # most of a board over that line and silently silenced those frames.
    gate = asyncio.Semaphore(TTS_MAX_CONCURRENCY)
    silenced: list[str] = []

    async def render(frame: Frame) -> None:
        destination = video_dir / frame.voice_filename
        if not frame.voiceover:
            _write_silence(destination, seconds=2.0)
            return
        for attempt in range(TTS_MAX_ATTEMPTS):
            try:
                async with gate:
                    await _synthesize_line(client, frame.voiceover, voice_id, destination)
                return
            except Exception as exc:
                # A concurrency 429 clears on its own, so it is worth waiting out.
                # Anything else (402, bad voice id) will not, so stop immediately.
                retryable = "429" in str(exc) or "concurrent_limit" in str(exc)
                if not retryable or attempt == TTS_MAX_ATTEMPTS - 1:
                    log.error("frame_tts_failed", frame=frame.slug, error=str(exc)[:200])
                    break
                await asyncio.sleep(2 * (attempt + 1))
        # One failed line must not cost the whole video; the frame still occupies
        # time and the storyboard stays intact. The caller decides if too many did.
        silenced.append(frame.slug)
        _write_silence(destination)

    await asyncio.gather(*(render(frame) for frame in board.frames))
    log.info(
        "frame_audio_generated",
        frames=len(board.frames),
        preset=preset,
        silenced=len(silenced),
    )
    return silenced


_FRAME_SYSTEM_PROMPT = """You write a single HyperFrames sub-composition: one HTML file that renders one scene of a vertical finance explainer.

AUDIENCE: teenagers and curious adults at once. Bold, clean, confident. Never babyish, never a corporate slide deck.

HARD CONTRACT — a violation means the frame fails to render:
1. Output ONLY one <template> element. No <!doctype>, <html>, <head>, or markdown fences.
2. Put <style> and <script> INSIDE the <template>. Anything outside it is discarded.
3. The root element inside the template must be exactly:
   <div id="{slug}-root" data-composition-id="{slug}" data-width="1080" data-height="1920" data-duration="{duration}">
4. Register exactly one timeline, built synchronously:
   window.__timelines["{slug}"] = gsap.timeline({{ paused: true }});
5. Prefix EVERY id with "{slug}-". Ids must be unique across the whole assembled page.
   Select with attribute selectors: '[id="{slug}-card"]'.
6. The scene background goes on a full-bleed child (position:absolute; inset:0), NEVER on the root element itself — a fill on the root renders black in the final video.
7. Give the root `container-type: size` and size children in cqw/cqh units so the layout scales.

DETERMINISM — frames are rendered out of order by parallel workers, so identical timestamps must produce identical pixels:
- No Date, no performance.now(), no unseeded Math.random(), no network requests, no repeat:-1 (use a finite repeat count).
- Animate only transform, opacity, filter, color, background-color, and stroke/fill.
- Never animate display or visibility.
- Every tween needs an explicit position parameter so the timeline is reproducible.
- NEVER use relative values such as "+=60" or "-=5". Relative tweens capture their base when the tween initialises, so a worker starting mid-timeline resolves a different base and renders the same frame differently. Always use fromTo() with explicit from and to values.
- Never let two tweens write the same property of the same element at overlapping times. Sequence them so they do not overlap, or pass overwrite: "auto".

FONTS — never declare a family you have not loaded, and never load one:
- The ONLY permitted font-family declaration is:
    font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
- No <link> and no @import from fonts.googleapis.com. External font requests add latency and can fail mid-render.
- If the global direction names a typeface (Fredoka, Quicksand, Poppins, anything), IGNORE the name and use the stack above. Declaring an unloaded family makes the renderer silently substitute a fallback, so the rendered typography stops matching the design.
- Express personality through weight, size, letter-spacing, and colour instead of typeface choice.

PALETTE — use these exact values, nothing else:
  ground   #0B1220   surface  #1B2A4A   surface-alt #24365C
  text     #F8FAFC   muted    #CBD5E1
  accent   #38BDF8   positive #34D399   warning #FBBF24   negative #F87171

CONTRAST — the render is rejected below 4.5:1 on text:
- Text on ground/surface/surface-alt is #F8FAFC, or #CBD5E1 for secondary text only.
- Text on an accent, positive, warning or negative fill is ALWAYS #0B1220.
- Never colour text with an accent on top of a coloured surface, and never place a light accent on a light fill.
- Accents belong to shapes, bars, borders, and glows, not to body copy.

LAYOUT — overlapping text is rejected:
- Lay the frame out as a single vertical column: `display:flex; flex-direction:column` with gap. Every text block gets its own row.
- Never absolutely position one text block on top of another, and never put SVG <text> over an HTML text block.
- Decorative absolutely-positioned elements must contain no text.
- Keep content inside the middle 80% of the height; the top and bottom are covered by platform UI.

3D STYLE: the parent composition sets `perspective: 1400px` and this scene inherits `transform-style: preserve-3d`. Use translateZ, rotateY and rotateX on cards so elements have real depth, with soft shadows to sell it. Animate with GSAP eases such as power3.out and back.out(1.5).

Text must be legible at a glance: display type at least 7cqw, body at least 4.5cqw, weight 600+. No <br> in body text."""


# "local" builds frames from archetypes planned by Ollama (free, no rate limit);
# "gemini" has the cloud model author raw HTML per frame.
FRAME_BACKEND = os.environ.get("FRAME_BACKEND", "local").lower()


async def _build_frames(
    board: Storyboard, video_dir: Path, backend: str | None = None
) -> list[str]:
    """Dispatch frame generation to the requested backend.

    Backend is per request so a single running worker can produce both a
    portrait 2D Short and a landscape 3D film without an env change or a
    restart; FRAME_BACKEND only supplies the default.
    """
    chosen = (backend or FRAME_BACKEND).lower()
    if chosen == "gemini":
        return await _generate_frame_compositions(board, video_dir)
    return await _generate_frame_compositions_local(board, video_dir)


def _is_retryable(exc: BaseException) -> bool:
    """Rate limits and transient server errors are worth another attempt."""
    text = str(exc)
    return any(
        marker in text
        for marker in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE", "500")
    )


async def _generate_frame_compositions_local(board: Storyboard, video_dir: Path) -> list[str]:
    """Build every frame from pre-validated archetypes, planned by the local LLM.

    Returns the slugs that fell back to the heuristic planner. Unlike the
    HTML-authoring path this cannot produce an invalid composition: the model
    only chooses a shape and fills slots, and the templates were validated once.
    """
    import httpx

    from app.archetypes import render_archetype
    from app.localllm import OLLAMA_TIMEOUT, plan_frame

    frames_dir = video_dir / "compositions" / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    degraded: list[str] = []

    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:

        # Each frame is planned in isolation, so without this the model reaches
        # for the same shape every time and the video reads as one slide repeated.
        used_archetypes: list[str] = []

        async def build(frame: Frame) -> None:
            plan, used_fallback = await plan_frame(
                voiceover=frame.voiceover,
                scene=frame.scene,
                title=frame.title,
                direction=board.direction,
                client=client,
                used_archetypes=used_archetypes,
            )
            if used_fallback:
                degraded.append(frame.slug)
            used_archetypes.append(plan.get("archetype", ""))
            (frames_dir / f"{frame.slug}.html").write_text(
                render_archetype(frame.slug, frame.duration, plan), encoding="utf-8"
            )

        # Sequential: one local GPU serves one request at a time, so fanning out
        # only adds queueing latency.
        for frame in board.frames:
            await build(frame)

    log.info(
        "frame_compositions_generated",
        backend="local",
        frames=len(board.frames),
        heuristic=len(degraded),
    )
    return degraded


async def _generate_frame_compositions(board: Storyboard, video_dir: Path) -> list[str]:
    """Generate one sub-composition per frame. Returns the slugs that fell back.

    The caller must inspect the return value. A placeholder keeps the render
    alive, but a video mostly made of placeholders is not the video that was
    asked for and must never be published as though it were.
    """
    from google import genai
    from google.genai import types
    from tenacity import (
        AsyncRetrying,
        retry_if_exception,
        stop_after_attempt,
        wait_exponential,
    )

    frames_dir = video_dir / "compositions" / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    failed: list[str] = []

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        log.warning("gemini_api_key_missing", fallback="placeholder_frames")
        for frame in board.frames:
            (frames_dir / f"{frame.slug}.html").write_text(
                _placeholder_frame(frame), encoding="utf-8"
            )
        return [frame.slug for frame in board.frames]

    client = genai.Client(api_key=api_key)

    async def build(frame: Frame) -> None:
        destination = frames_dir / f"{frame.slug}.html"
        system_instruction = _FRAME_SYSTEM_PROMPT.format(
            slug=frame.slug, duration=frame.duration
        )
        shots = "\n".join(frame.shots) or "(no shot sequence given)"
        user_prompt = (
            f"GLOBAL DIRECTION: {board.direction or 'Clean, bold, 3D finance explainer.'}\n\n"
            f"SCENE: {frame.scene or frame.title}\n"
            f"NARRATION SPOKEN OVER THIS FRAME: \"{frame.voiceover}\"\n"
            f"ON SCREEN FOR: {frame.duration} seconds\n"
            f"SHOT SEQUENCE:\n{shots}\n\n"
            "Write the sub-composition."
        )
        try:
            # Rate limits are the common failure when generating a whole board at
            # once, and they clear on their own; retry before giving up a frame.
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(4),
                wait=wait_exponential(multiplier=2, min=2, max=30),
                retry=retry_if_exception(_is_retryable),
                reraise=True,
            ):
                with attempt:
                    response = await asyncio.to_thread(
                        client.models.generate_content,
                        model="gemini-flash-latest",
                        contents=user_prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=system_instruction, temperature=0.6
                        ),
                    )
            html = _strip_code_fence(response.text or "")
            if "<template" not in html:
                raise ValueError("response did not contain a <template> element")
            destination.write_text(html, encoding="utf-8")
        except Exception as exc:
            # A frame that fails to generate still has to occupy its slot, or the
            # narration plays over nothing.
            log.error("frame_composition_failed", frame=frame.slug, error=str(exc)[:200])
            destination.write_text(_placeholder_frame(frame), encoding="utf-8")
            failed.append(frame.slug)

    await asyncio.gather(*(build(frame) for frame in board.frames))
    log.info(
        "frame_compositions_generated",
        frames=len(board.frames),
        placeholders=len(failed),
    )
    return failed


def _strip_code_fence(text: str) -> str:
    """Remove ```html fences the model sometimes wraps its output in."""
    import re

    stripped = text.strip()
    fence = re.match(r"^```[a-zA-Z]*\n(.*)\n```$", stripped, re.DOTALL)
    return fence.group(1).strip() if fence else stripped


def _placeholder_frame(frame: Frame) -> str:
    """Minimal valid sub-composition: the narration as a legible title card."""
    text = (frame.voiceover or frame.title).replace("<", "&lt;").replace(">", "&gt;")
    return f"""<template>
  <style>
    [id="{frame.slug}-root"] {{
      width: 100%; height: 100%; position: relative;
      container-type: size; overflow: hidden;
    }}
    [id="{frame.slug}-bg"] {{ position: absolute; inset: 0; background: #0B1220; }}
    [id="{frame.slug}-text"] {{
      position: absolute; inset: 0;
      display: flex; align-items: center; justify-content: center;
      padding: 10cqw;
      font-family: 'Inter', system-ui, sans-serif;
      font-size: 7cqw; font-weight: 700; line-height: 1.3;
      color: #F8FAFC; text-align: center;
    }}
  </style>

  <div id="{frame.slug}-root" data-composition-id="{frame.slug}"
       data-width="1080" data-height="1920" data-duration="{frame.duration}">
    <div class="clip" id="{frame.slug}-bg" data-start="0"
         data-duration="{frame.duration}" data-track-index="0"></div>
    <div id="{frame.slug}-text">{text}</div>
  </div>

  <script>
    (function () {{
      const tl = gsap.timeline({{ paused: true }});
      window.__timelines["{frame.slug}"] = tl;
      tl.fromTo('[id="{frame.slug}-text"]',
        {{ opacity: 0, y: 40 }},
        {{ opacity: 1, y: 0, duration: 0.6, ease: "power3.out" }},
        0
      );
    }})();
  </script>
</template>
"""


async def _generate_audio_for_script(script_content: str, output_path: Path):
    """
    Parses the generated script for 'Voiceover:' lines, concatenates them,
    and calls the ElevenLabs API to generate TTS audio.
    """
    import re
    import os
    from elevenlabs.client import AsyncElevenLabs
    
    # 1. Parse preset from YAML frontmatter
    preset = "default"
    preset_match = re.search(r"^preset:\s*(.+)$", script_content, re.MULTILINE)
    if preset_match:
        preset = preset_match.group(1).strip()
    
    # 2. Extract Voiceover lines
    # We look for lines starting with 'Voiceover:' or 'Voiceover: "'
    # It might be in bold `**Voiceover:**` so we handle that too.
    voiceover_lines = []
    for line in script_content.splitlines():
        line = line.strip()
        # Regex to match Voiceover: <text> with optional markdown formatting
        match = re.match(r"^(?:\*\*)?Voiceover:(?:\*\*)?\s*\"?(.+?)\"?$", line, re.IGNORECASE)
        if match:
            voiceover_lines.append(match.group(1).strip())
            
    if not voiceover_lines:
        log.warning("no_voiceover_lines_found", preset=preset)
        voiceover_text = "No voiceover text found."
    else:
        voiceover_text = " ".join(voiceover_lines)
        
    log.info("parsed_voiceover_text", length=len(voiceover_text), preset=preset)
    
    # 3. Map preset to ElevenLabs Voice ID
    # These are default ElevenLabs voices mapped to our personas
    voice_map = {
        "teenage_boy": "ErXwobaYiN019PkySvjV",  # Antoni
        "teenage_girl": "21m00Tcm4TlvDq8ikWAM", # Rachel
        "adult_male": "TxGEqnHWrfWFTfGW9XjX",   # Josh
        "adult_female": "MF3mGyEYCl7XYWbV9V6O", # Elli
        "baby": "jBpfuIE2acCO8z3wKNLl",         # Gigi (child)
    }
    
    voice_id = voice_map.get(preset, voice_map["adult_male"]) # default to adult_male if not found
    
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        log.warning("elevenlabs_api_key_missing", fallback="dummy_audio")
        import subprocess
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
            "-t", "30", "-q:a", "9", "-acodec", "libmp3lame", str(output_path)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
        
    # 4. Generate audio via ElevenLabs
    try:
        client = AsyncElevenLabs(api_key=api_key)
        audio_generator = await client.generate(
            text=voiceover_text,
            voice=voice_id,
            model="eleven_multilingual_v2"
        )
        
        # Write bytes to output_path
        with open(output_path, "wb") as f:
            async for chunk in audio_generator:
                f.write(chunk)
                
        log.info("youtube_audio_generation_completed", path=str(output_path))
    except Exception as e:
        log.error("youtube_audio_generation_failed", error=str(e))
        # Write dummy file on failure so rendering doesn't crash entirely if it depends on the file
        import subprocess
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
            "-t", "30", "-q:a", "9", "-acodec", "libmp3lame", str(output_path)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

async def _upload_to_youtube(video_path: str, title: str, description: str) -> str:
    """
    Uploads a video to YouTube Data API v3. 
    Runs the blocking Google API client in a threadpool.
    """
    from starlette.concurrency import run_in_threadpool
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    
    def _do_upload():
        creds = _get_youtube_credentials(["https://www.googleapis.com/auth/youtube.upload"])
        youtube = build("youtube", "v3", credentials=creds)
        
        body = {
            "snippet": {
                "title": title[:100],  # Max 100 chars
                "description": description[:5000],  # Max 5000 chars
                "tags": ["finance", "explainer", "shorts"],
                "categoryId": "27"  # Education
            },
            "status": {
                "privacyStatus": "private",  # Upload as draft
                "selfDeclaredMadeForKids": False
            }
        }
        
        media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
        request = youtube.videos().insert(
            part=",".join(body.keys()),
            body=body,
            media_body=media
        )
        
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                log.info("youtube_upload_progress", progress=int(status.progress() * 100))
        
        return response["id"]
        
    return await run_in_threadpool(_do_upload)

async def _generate_thumbnail(title: str, output_path: str):
    """
    Generates a thumbnail using a minimal HTML template and Playwright.
    """
    from starlette.concurrency import run_in_threadpool
    import subprocess
    import tempfile
    import sys
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                margin: 0;
                width: 1280px;
                height: 720px;
                background: linear-gradient(135deg, #1e1e2f, #2a2a40);
                display: flex;
                align-items: center;
                justify-content: center;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                color: #ffffff;
                text-align: center;
                padding: 60px;
                box-sizing: border-box;
                border: 12px solid #ff4a5a;
            }}
            h1 {{
                font-size: 80px;
                font-weight: 900;
                text-transform: uppercase;
                text-shadow: 0 10px 30px rgba(0,0,0,0.8);
                line-height: 1.2;
                margin: 0;
            }}
            .badge {{
                position: absolute;
                top: 40px;
                left: 40px;
                background: #ff4a5a;
                color: white;
                padding: 10px 30px;
                font-size: 30px;
                font-weight: bold;
                border-radius: 50px;
                text-transform: uppercase;
                box-shadow: 0 4px 15px rgba(255, 74, 90, 0.4);
            }}
        </style>
    </head>
    <body>
        <div class="badge">Trending</div>
        <h1>{title}</h1>
    </body>
    </html>
    """
    
    def _run():
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
            f.write(html)
            temp_html = f.name
            
        npx_cmd = "npx.cmd" if sys.platform == "win32" else "npx"
        try:
            # We use playwright cli to snapshot it
            subprocess.run(
                [npx_cmd, "playwright", "screenshot", f"file:///{temp_html.replace(chr(92), '/')}", output_path],
                check=True,
                capture_output=True
            )
        finally:
            import os
            try:
                os.unlink(temp_html)
            except:
                pass
                
    await run_in_threadpool(_run)

async def _upload_thumbnail(video_id: str, thumbnail_path: str):
    """
    Uploads a custom thumbnail for the given YouTube video ID.
    """
    from starlette.concurrency import run_in_threadpool
    from googleapiclient.discovery import build
    
    def _do_upload():
        creds = _get_youtube_credentials(["https://www.googleapis.com/auth/youtube.upload"])
        youtube = build("youtube", "v3", credentials=creds)
        request = youtube.thumbnails().set(
            videoId=video_id,
            media_body=thumbnail_path
        )
        request.execute()
        
    return await run_in_threadpool(_do_upload)

async def get_youtube_analytics(video_ids: list[str]) -> dict:
    """
    Fetches view count, like count, and comment count for the given video IDs.
    Returns a dictionary mapping videoId to stats.
    """
    if not video_ids:
        return {}
        
    from starlette.concurrency import run_in_threadpool
    from googleapiclient.discovery import build
    
    def _do_fetch():
        creds = _get_youtube_credentials(
            ["https://www.googleapis.com/auth/youtube.readonly", "https://www.googleapis.com/auth/youtube.upload"]
        )
        youtube = build("youtube", "v3", credentials=creds)
        
        # YouTube API allows up to 50 IDs per request
        results = {}
        for i in range(0, len(video_ids), 50):
            batch = video_ids[i:i+50]
            request = youtube.videos().list(
                part="statistics,snippet",
                id=",".join(batch)
            )
            response = request.execute()
            
            for item in response.get("items", []):
                stats = item.get("statistics", {})
                results[item["id"]] = {
                    "views": stats.get("viewCount", "0"),
                    "likes": stats.get("likeCount", "0"),
                    "comments": stats.get("commentCount", "0"),
                    "title": item.get("snippet", {}).get("title", "")
                }
        return results
        
    try:
        return await run_in_threadpool(_do_fetch)
    except Exception as e:
        log.error("youtube_analytics_fetch_failed", error=str(e))
        return {}


def _require_metadata(frontmatter: dict[str, str]) -> tuple[str, str]:
    """Return (title, description) or raise.

    The old publish path read `frontmatter.get("description") or title`, so a
    generation that produced no description silently yielded a one-line title in
    the description box. That fallback is gone: an empty field is a generation
    failure and should be visible.
    """
    title = (frontmatter.get("title") or "").strip()
    description = (frontmatter.get("description") or "").strip()

    missing = [n for n, v in (("title", title), ("description", description)) if not v]
    if missing:
        raise ValueError(
            f"storyboard frontmatter is missing: {', '.join(missing)}"
        )

    return title, description


def _write_upload_txt(
    video_dir: Path, channel: Channel, title: str, description: str
) -> Path:
    """Write the paste-ready metadata beside the storyboard.

    Uploads are manual, so this file is how the metadata reaches YouTube. It also
    means the metadata survives a database reset and travels with the folder.
    """
    lines = [
        f"CHANNEL: {channel.display_name}",
        "",
        "TITLE",
        "-----",
        title,
        "",
        "DESCRIPTION",
        "-----------",
        description,
        "",
    ]

    if channel.id == "kids":
        lines += [
            "REMINDER",
            "--------",
            "Tick \"Made for kids\" in YouTube Studio before publishing. This is a",
            "COPPA requirement and nothing in this pipeline sets it for you.",
            "",
        ]

    path = video_dir / "upload.txt"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _parse_storyboard_frontmatter(storyboard_path: Path) -> dict[str, str]:
    """
    Parse a simple YAML frontmatter block from the storyboard markdown.
    Returns a dict with at least 'title' and 'description' keys.
    """
    text = storyboard_path.read_text(encoding="utf-8") if storyboard_path.exists() else ""
    frontmatter: dict[str, str] = {"title": "", "description": ""}
    if text.startswith("---"):
        try:
            _, fm, _ = text.split("---", 2)
            for line in fm.strip().splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    frontmatter[key.strip()] = value.strip().strip('"').strip("'")
        except Exception:
            pass
    return frontmatter


async def publish_youtube_draft(draft_id: uuid.UUID) -> dict[str, str]:
    """
    Publish a pending YouTube draft: upload the rendered MP4, attach a thumbnail,
    and update the draft record. Returns {video_id, url}.
    """
    log.info("youtube_publish_started", draft_id=str(draft_id))

    draft = await db.get_draft(draft_id)
    if not draft:
        raise ValueError(f"Draft {draft_id} not found")
    if draft.get("platform") != "youtube":
        raise ValueError(f"Draft {draft_id} is not a YouTube draft")

    body = draft.get("body") or {}
    file_path = body.get("file_path")
    if not file_path:
        raise ValueError(f"Draft {draft_id} has no file_path")

    video_path = Path(file_path)
    if not video_path.exists():
        raise FileNotFoundError(f"Rendered video not found: {video_path}")

    # Prefer an already-rendered thumbnail; fall back to generating one.
    thumbnail_path = video_path.parent / "thumbnail.jpg"
    if not thumbnail_path.exists():
        thumbnail_path = video_path.parent / "thumbnail.png"
    if not thumbnail_path.exists():
        thumbnail_path = video_path.parent / "thumbnail.jpg"
        await _generate_thumbnail(draft.get("headline", "Video"), str(thumbnail_path))

    storyboard_path = video_path.parent.parent / "STORYBOARD.md"
    frontmatter = _parse_storyboard_frontmatter(storyboard_path)

    title = frontmatter.get("title") or draft.get("headline") or "Untitled Video"
    description = frontmatter.get("description") or title

    video_id = await _upload_to_youtube(str(video_path), title, description)
    await _upload_thumbnail(video_id, str(thumbnail_path))

    await db.update_draft_published(
        draft_id,
        status="published",
        published_ids={"youtube": video_id},
    )

    log.info("youtube_publish_finished", draft_id=str(draft_id), video_id=video_id)
    return {"video_id": video_id, "url": f"https://youtube.com/watch?v={video_id}"}
