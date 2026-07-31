"""Render one video locally, without Postgres.

The full autopilot path needs a story row in the database. Video generation
itself does not: it only needs a storyboard, so this harness drives the compiler,
TTS, frame generation, and renderer directly.

    # Compile an existing board, no API spend at all
    python render_local.py --storyboard ../videos/the-emi-illusion/STORYBOARD.md --dry

    # Real narration + real frames, then render an mp4
    python render_local.py --storyboard ../videos/the-emi-illusion/STORYBOARD.md --render

    # Write a fresh board from a topic first
    python render_local.py --topic "Why your 10% raise is actually a pay cut" --render

Flags exist so you can isolate a stage: --dry skips both paid APIs, --skip-audio
keeps Gemini frames but silences narration, --skip-frames keeps narration but
uses placeholder cards.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path

# Storyboards carry em dashes and curly quotes; a cp1252 console would raise
# UnicodeEncodeError the moment narration is echoed back.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    print("! python-dotenv not installed; relying on ambient environment")

from app.storyboard import (
    assign_timing,
    attach_audio,
    parse_storyboard,
    prune_stale_assets,
    render_index_html,
)
from app.youtube import (
    _build_frames,
    _generate_frame_audio,
    _placeholder_frame,
    _write_silence,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

SCRIPT_PROMPT = """You are writing a vertical short-form finance explainer for a channel watched by teenagers and curious adults alike.

Output a markdown document beginning with YAML frontmatter:
---
format: 1080x1920
title: "The video title"
description: "An SEO-friendly description. Never mention AI or automation."
preset: adult_male
pacing: explainer
music: soft upbeat playful
---

## Video direction
One paragraph on tone, colour, and typography.

Then 4-6 frames, each exactly in this shape:

## Frame 1 - Hook
- duration: 5s
- scene: what is on screen
- voiceover: "one spoken line, short and punchy"

**Shot Sequence:**
- 0.0s: what happens first
- 2.5s: what happens next

RULES:
- Educational only. Never recommend buying or selling anything.
- One idea per frame. Every frame's voiceover is a single natural sentence.
- Open with a hook that stops a scroll in under 2 seconds.
"""


def write_project_files(video_dir: Path) -> None:
    """Minimal files the hyperframes CLI expects alongside index.html."""
    (video_dir / "package.json").write_text(
        '{ "name": "local-test-video", "private": true, "type": "module" }',
        encoding="utf-8",
    )
    if not (video_dir / "hyperframes.json").exists():
        (video_dir / "hyperframes.json").write_text(
            '{\n  "paths": {\n    "blocks": "compositions",\n'
            '    "components": "compositions/components",\n'
            '    "assets": "assets"\n  }\n}\n',
            encoding="utf-8",
        )


async def generate_script(topic: str) -> str:
    """Write a storyboard from a topic with a direct Gemini call (no DB)."""
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("! GEMINI_API_KEY is not set; pass --storyboard instead of --topic")

    client = genai.Client(api_key=api_key)
    response = await asyncio.to_thread(
        client.models.generate_content,
        model="gemini-flash-latest",
        contents=f"Write the storyboard for this topic:\n{topic}",
        config=types.GenerateContentConfig(
            system_instruction=SCRIPT_PROMPT, temperature=0.7
        ),
    )
    return response.text or ""


def run_cli(args: list[str], video_dir: Path) -> int:
    """Run a hyperframes CLI command inside the project directory."""
    npx = "npx.cmd" if sys.platform == "win32" else "npx"
    print(f"\n$ npx hyperframes {' '.join(args)}")
    return subprocess.run([npx, "hyperframes", *args], cwd=video_dir).returncode


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--storyboard", type=Path, help="existing STORYBOARD.md to compile")
    source.add_argument("--topic", help="generate a storyboard from this topic first")
    parser.add_argument("--out", type=Path, help="output dir (default videos/local-test)")
    parser.add_argument("--dry", action="store_true", help="skip both paid APIs")
    parser.add_argument("--skip-audio", action="store_true", help="silent narration")
    parser.add_argument("--skip-frames", action="store_true", help="placeholder frames")
    parser.add_argument("--render", action="store_true", help="render an mp4 after checking")
    parser.add_argument(
        "--allow-placeholders",
        action="store_true",
        help="continue even when frames fell back to placeholder cards",
    )
    args = parser.parse_args()

    skip_audio = args.dry or args.skip_audio
    skip_frames = args.dry or args.skip_frames

    video_dir = (args.out or REPO_ROOT / "videos" / "local-test").resolve()
    video_dir.mkdir(parents=True, exist_ok=True)
    print(f"-> project: {video_dir}")

    # 1. Storyboard
    if args.topic:
        print("-> generating storyboard...")
        script = await generate_script(args.topic)
    else:
        script = args.storyboard.read_text(encoding="utf-8")
    (video_dir / "STORYBOARD.md").write_text(script, encoding="utf-8")

    board = parse_storyboard(script)
    if not board.frames:
        sys.exit("! storyboard produced no frames - check its headings")
    print(f"-> {len(board.frames)} frames parsed: {board.title}")

    # 2. Narration, one clip per frame. Prune first: iterating on a board renames
    #    frames, and orphans from the last run would still be validated.
    (video_dir / "assets" / "voice").mkdir(parents=True, exist_ok=True)
    pruned = prune_stale_assets(board, video_dir)
    if pruned:
        print(f"-> pruned {pruned} stale file(s) from a previous run")
    if skip_audio:
        print("-> narration: silent placeholders (--skip-audio)")
        for frame in board.frames:
            _write_silence(video_dir / frame.voice_filename, frame.declared_duration or 4.0)
    else:
        print("-> narration: ElevenLabs...")
        await _generate_frame_audio(board, video_dir, script)

    # 3. Timing derived from the audio that now exists on disk
    attach_audio(board, video_dir)
    assign_timing(board, board.meta.get("pacing"))

    print(f"\n  {'frame':24} {'start':>7} {'dur':>7}  narration")
    for frame in board.frames:
        print(
            f"  {frame.slug:24} {frame.start:7.2f} {frame.duration:7.2f}"
            f"  {frame.voiceover[:44]}"
        )
    print(f"  {'TOTAL':24} {'':7} {board.total_duration:7.2f}\n")

    # 4. Composition wiring
    (video_dir / "index.html").write_text(
        render_index_html(board, with_bgm=(video_dir / "bgm.mp3").exists()),
        encoding="utf-8",
    )
    write_project_files(video_dir)

    # 5. Per-frame visuals
    frames_dir = video_dir / "compositions" / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    if skip_frames:
        print("-> frames: placeholder cards (--skip-frames)")
        for frame in board.frames:
            (frames_dir / f"{frame.slug}.html").write_text(
                _placeholder_frame(frame), encoding="utf-8"
            )
    else:
        print("-> frames: planning archetypes...")
        placeholders = await _build_frames(board, video_dir)
        if placeholders:
            # These render and pass check, so without this the run looks clean
            # while most of the video is fallback title cards.
            print(
                f"\n!! {len(placeholders)}/{len(board.frames)} frames fell back to "
                f"heuristic fallback: {', '.join(placeholders)}"
            )
            print("!! the frame planner was unavailable - check the logged error above")
            if not args.allow_placeholders:
                sys.exit("!! refusing to continue; pass --allow-placeholders to override")

    # 6. Validate before rendering - a contract violation inside a <template>
    #    fails quietly, so never go straight to render.
    if run_cli(["check"], video_dir) != 0:
        sys.exit("\n! check failed - fix the findings above before rendering")
    print("\nOK: check passed")

    if args.render:
        if run_cli(["render", "--output", "renders/video.mp4"], video_dir) != 0:
            sys.exit("! render failed")
        print(f"\nOK: {video_dir / 'renders' / 'video.mp4'}")
    else:
        print(f"\nPreview it:  cd \"{video_dir}\"; npx hyperframes preview")
        print("Render it:   re-run with --render")


if __name__ == "__main__":
    asyncio.run(main())
