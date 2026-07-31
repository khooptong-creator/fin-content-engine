"""STORYBOARD.md -> HyperFrames composition compiler.

The autopilot pipeline previously rendered a hardcoded placeholder (`<h1>Generated
Draft Video</h1>`) because nothing consumed the storyboard the LLM produced. This
module closes that gap: it parses the storyboard into frames, derives each frame's
timing from its *narration audio* rather than from a number the LLM guessed, and
emits an `index.html` that satisfies the HyperFrames composition contract.

Voice first, visuals second: `data-start` offsets are a cumulative sum over measured
audio durations, so a scene can never drift out of sync with the line being spoken.

Deliberately free of I/O against the DB or any LLM so it stays unit-testable.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import structlog

log = structlog.get_logger()

# Track layout, matching the hand-authored reference projects in videos/.
TRACK_SCENE = 1
TRACK_VOICE = 10
TRACK_BGM = 11

BGM_VOLUME = 0.35
DEFAULT_WIDTH = 1080
DEFAULT_HEIGHT = 1920

# A frame with no audio and no declared duration still has to occupy time.
FALLBACK_FRAME_DURATION = 4.0


@dataclass(frozen=True)
class Pacing:
    """How long frames breathe. Different audiences need different cadences.

    `floor` is the readability guard: a frame shorter than this is gone before a
    viewer has parsed what is on it, however short the narration was.
    `soft_ceiling` is not a clamp — it is the threshold above which a frame is
    reported as overlong, signalling a script line that should have been split.
    """

    floor: float
    soft_ceiling: float
    lead_in: float
    tail: float


PACING_PROFILES: dict[str, Pacing] = {
    # Evergreen explainers for kids/teens: financial vocabulary is still being
    # built, so frames need to sit long enough to actually be read.
    "explainer": Pacing(floor=3.0, soft_ceiling=12.0, lead_in=0.25, tail=0.5),
    # Real-time news for adults: viewers already have the vocabulary and the
    # value is recency, so the cut is tighter and the cadence quicker.
    "news": Pacing(floor=2.0, soft_ceiling=8.0, lead_in=0.15, tail=0.3),
}

DEFAULT_PACING = "explainer"


@dataclass
class Frame:
    """One scene of the video: a narration line plus the visual that carries it."""

    index: int
    # Empty when the heading carried no name ("# Scene 1"). Never derive a
    # fallback from the heading's number: frames are renumbered after parsing,
    # which would leave the title contradicting the index.
    title: str = ""
    voiceover: str = ""
    scene: str = ""
    shots: list[str] = field(default_factory=list)
    declared_duration: float | None = None
    audio_duration: float | None = None
    # Filled in by assign_timing().
    start: float = 0.0
    duration: float = 0.0
    # Offset of the narration inside the frame. The visual lands first and the
    # voice follows, so the cut never coincides with the first syllable.
    voice_offset: float = 0.0

    @property
    def voice_duration(self) -> float:
        """The audio element's own length, which is not the frame's length.

        The frame is padded with silence at both ends; the audio is not. Giving
        the audio element the padded duration makes the renderer clamp it back
        to the media length and warn.
        """
        return self.audio_duration or self.duration

    @property
    def slug(self) -> str:
        """Stable id used for the composition id, filename, and element ids.

        Leading "f" is load-bearing: element ids derive from this, and an id
        starting with a digit makes `#01-hook` an invalid CSS selector that
        throws a SyntaxError in querySelector(). Generated frames reach for
        `#id` selectors naturally, so the hazard is removed at the source
        rather than defended against in every frame.
        """
        base = re.sub(r"[^a-z0-9]+", "-", self.title.lower()).strip("-")
        return f"f{self.index:02d}-{base or 'frame'}"

    @property
    def voice_filename(self) -> str:
        return f"assets/voice/{self.index:02d}.mp3"

    @property
    def composition_src(self) -> str:
        return f"compositions/frames/{self.slug}.html"


@dataclass
class Storyboard:
    meta: dict[str, str] = field(default_factory=dict)
    direction: str = ""
    frames: list[Frame] = field(default_factory=list)

    @property
    def width(self) -> int:
        return self._format_dim(0, DEFAULT_WIDTH)

    @property
    def height(self) -> int:
        return self._format_dim(1, DEFAULT_HEIGHT)

    def _format_dim(self, idx: int, default: int) -> int:
        fmt = self.meta.get("format", "")
        match = re.match(r"\s*(\d+)\s*x\s*(\d+)\s*", fmt)
        return int(match.group(idx + 1)) if match else default

    @property
    def total_duration(self) -> float:
        if not self.frames:
            return 0.0
        last = self.frames[-1]
        return round(last.start + last.duration, 3)

    @property
    def title(self) -> str:
        return self.meta.get("title", "Untitled")


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

# Accepts both dialects present in the repo:
#   "## Frame 1 — Hook"  (hand-authored boards under videos/)
#   "# Scene 1"          (Gemini autopilot output)
_FRAME_HEADING = re.compile(
    r"^#{1,3}\s*(?:Frame|Scene)\s*(\d+)\s*(?:[—\-:]\s*(.+?))?\s*$",
    re.IGNORECASE,
)

# "voiceover:", "- voiceover:", "**Voiceover:**", with or without wrapping quotes.
def _field_pattern(name: str) -> re.Pattern[str]:
    return re.compile(
        rf"^\s*(?:[-*]\s*)?(?:\*\*)?{name}\s*:?(?:\*\*)?\s*:?\s*[\"']?(.+?)[\"']?\s*$",
        re.IGNORECASE,
    )


_VOICEOVER = _field_pattern("voiceover")
_SCENE = _field_pattern("scene")
_DURATION = _field_pattern("duration")
_SHOT = re.compile(r"^\s*[-*]\s*(\d+(?:\.\d+)?)s:\s*(.+?)\s*$")


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split leading `---` YAML-ish frontmatter from the body.

    Hand-rolled rather than pulling in PyYAML: the frontmatter is flat
    `key: value` pairs written by an LLM, and a strict YAML parser would reject
    the unescaped colons and quotes that show up in generated descriptions.
    """
    if not text.lstrip().startswith("---"):
        return {}, text

    stripped = text.lstrip()
    end = stripped.find("\n---", 3)
    if end == -1:
        return {}, text

    block = stripped[3:end]
    body = stripped[end + 4 :]

    meta: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line or line.strip().startswith("#"):
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip().strip("\"'")
    return meta, body


def _parse_seconds(raw: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)", raw)
    return float(match.group(1)) if match else None


def parse_storyboard(text: str) -> Storyboard:
    """Parse STORYBOARD.md into an ordered list of frames."""
    meta, body = _parse_frontmatter(text)
    board = Storyboard(meta=meta)

    current: Frame | None = None
    direction_lines: list[str] = []
    in_direction = False

    for line in body.splitlines():
        heading = _FRAME_HEADING.match(line)
        if heading:
            in_direction = False
            current = Frame(
                index=int(heading.group(1)),
                title=(heading.group(2) or "").strip(),
            )
            board.frames.append(current)
            continue

        # "# Video direction" / "## Video direction" blocks describe global style.
        if re.match(r"^#{1,3}\s*Video direction", line, re.IGNORECASE):
            in_direction = True
            current = None
            continue

        if current is None:
            if in_direction and line.strip():
                direction_lines.append(line.strip())
            continue

        shot = _SHOT.match(line)
        if shot:
            current.shots.append(f"{shot.group(1)}s: {shot.group(2)}")
            continue

        if not current.voiceover and (m := _VOICEOVER.match(line)):
            current.voiceover = m.group(1).strip()
            continue
        if not current.scene and (m := _SCENE.match(line)):
            current.scene = m.group(1).strip()
            continue
        if current.declared_duration is None and (m := _DURATION.match(line)):
            current.declared_duration = _parse_seconds(m.group(1))
            continue

    board.direction = " ".join(direction_lines)

    # Renumber defensively: an LLM may emit "Scene 1, Scene 2, Scene 2".
    for position, frame in enumerate(board.frames, start=1):
        frame.index = position

    log.info("storyboard_parsed", frames=len(board.frames), title=board.title)
    return board


# --------------------------------------------------------------------------
# Timing
# --------------------------------------------------------------------------


def probe_duration(audio_path: Path) -> float | None:
    """Measure an audio file's real duration with ffprobe.

    ffmpeg is already a hard runtime dependency (the TTS fallback shells out to
    it), so this adds no new package.
    """
    if not audio_path.exists():
        return None
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(audio_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return float(json.loads(result.stdout)["format"]["duration"])
    except (subprocess.CalledProcessError, KeyError, ValueError, json.JSONDecodeError) as exc:
        log.warning("probe_duration_failed", path=str(audio_path), error=str(exc))
        return None


def resolve_frame_duration(frame: Frame, pacing: Pacing) -> float:
    """Decide how long a single frame stays on screen.

    Measured narration wins whenever it exists: a frame is the spoken line plus
    breathing room at each end, so the cut never lands on a syllable. The only
    adjustment is the readability floor.

    There is deliberately no upper clamp on narrated frames. Truncating a frame
    below its audio would cut the voice off mid-sentence — a far worse artifact
    than a frame that lingers — so an overlong line is reported rather than
    trimmed, which surfaces scripts the LLM should have split into two frames.
    """
    if frame.audio_duration:
        spoken = frame.audio_duration + pacing.lead_in + pacing.tail
        if spoken > pacing.soft_ceiling:
            log.warning(
                "frame_exceeds_soft_ceiling",
                frame=frame.slug,
                duration=round(spoken, 2),
                ceiling=pacing.soft_ceiling,
                hint="narration line is long enough to split into two frames",
            )
        return max(spoken, pacing.floor)

    # No audio: TTS failed, or the frame is intentionally silent. Fall back to
    # the LLM's guess, then to a fixed hold. Still floored, so a frame can never
    # collapse to zero and vanish from the render.
    intended = frame.declared_duration or FALLBACK_FRAME_DURATION
    return max(intended, pacing.floor)


def resolve_pacing(pacing: Pacing | str | None, board: Storyboard | None = None) -> Pacing:
    """Resolve a pacing profile from an explicit value or the board's frontmatter."""
    if isinstance(pacing, Pacing):
        return pacing
    name = pacing or (board.meta.get("pacing") if board else None) or DEFAULT_PACING
    if name not in PACING_PROFILES:
        log.warning("unknown_pacing_profile", requested=name, fallback=DEFAULT_PACING)
        name = DEFAULT_PACING
    return PACING_PROFILES[name]


def assign_timing(board: Storyboard, pacing: Pacing | str | None = None) -> Storyboard:
    """Lay frames end to end, deriving each start from the durations before it.

    This is the voice-first step: `data-start` is a cumulative sum over real
    narration lengths, so visuals can never drift away from the spoken line.
    """
    resolved = resolve_pacing(pacing, board)
    cursor = 0.0
    for frame in board.frames:
        frame.duration = round(resolve_frame_duration(frame, resolved), 3)
        frame.start = round(cursor, 3)
        frame.voice_offset = round(resolved.lead_in, 3) if frame.audio_duration else 0.0
        cursor += frame.duration
    return board


def prune_stale_assets(board: Storyboard, video_dir: Path) -> int:
    """Delete frame/voice files left over from a previous compile of this project.

    Regenerating a video can rename frames (a retitled scene changes its slug).
    Orphans are not harmless: `hyperframes check` validates every file in the
    frames directory, so stale ones report findings against a video that no
    longer contains them.
    """
    removed = 0
    expected_frames = {f"{frame.slug}.html" for frame in board.frames}
    expected_voice = {Path(frame.voice_filename).name for frame in board.frames}

    frames_dir = video_dir / "compositions" / "frames"
    if frames_dir.is_dir():
        for path in frames_dir.glob("*.html"):
            if path.name not in expected_frames:
                path.unlink()
                removed += 1

    voice_dir = video_dir / "assets" / "voice"
    if voice_dir.is_dir():
        for path in voice_dir.iterdir():
            if path.is_file() and path.name not in expected_voice:
                path.unlink()
                removed += 1

    if removed:
        log.info("pruned_stale_assets", count=removed, video_dir=str(video_dir))
    return removed


def attach_audio(board: Storyboard, video_dir: Path) -> Storyboard:
    """Probe each frame's rendered voice clip and record its measured length."""
    for frame in board.frames:
        frame.audio_duration = probe_duration(video_dir / frame.voice_filename)
    return board


# --------------------------------------------------------------------------
# Emission
# --------------------------------------------------------------------------

_INDEX_TEMPLATE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={width}, height={height}" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <style>
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{
        width: {width}px;
        height: {height}px;
        overflow: hidden;
        background: #000;
      }}
      #root {{
        position: relative;
        width: {width}px;
        height: {height}px;
        overflow: hidden;
        perspective: 1400px;
      }}
      /* Full-bleed child, never the root itself: the producer's frame
         compositing can drop a background set on the composition root, which
         renders black even though preview and snapshot look correct. */
      #stage-fill {{
        position: absolute;
        inset: 0;
        background: {ground};
      }}
      .scene {{
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        transform-style: preserve-3d;
      }}
    </style>
  </head>
  <body>
    <div
      id="root"
      data-composition-id="main"
      data-start="0"
      data-duration="{total}"
      data-width="{width}"
      data-height="{height}"
    >
      <div id="stage-fill" class="clip" data-start="0" data-duration="{total}" data-track-index="0"></div>
{scenes}
{bgm}
    </div>

    <script>
      window.__timelines = window.__timelines || {{}};
      window.__timelines["main"] = gsap.timeline({{ paused: true }});
    </script>
  </body>
</html>
"""

_SCENE_TEMPLATE = """      <div
        id="el-{slug}"
        class="scene"
        data-composition-id="{slug}"
        data-composition-src="{src}"
        data-start="{start}"
        data-duration="{duration}"
        data-track-index="{track_scene}"
      ></div>
      <audio
        id="el-{slug}-voice"
        src="{voice}"
        data-start="{voice_start}"
        data-duration="{voice_duration}"
        data-track-index="{track_voice}"
        data-volume="1"
      ></audio>
"""

_BGM_TEMPLATE = """
      <audio
        id="el-bgm"
        src="bgm.mp3"
        data-start="0"
        data-duration="{total}"
        data-track-index="{track_bgm}"
        data-volume="{volume}"
      ></audio>
"""


def render_index_html(board: Storyboard, ground: str = "#0B1220", with_bgm: bool = True) -> str:
    """Emit the top-level composition wiring every frame to its narration."""
    total = board.total_duration
    scenes = "\n".join(
        _SCENE_TEMPLATE.format(
            slug=frame.slug,
            src=frame.composition_src,
            start=frame.start,
            duration=frame.duration,
            voice=frame.voice_filename,
            voice_start=round(frame.start + frame.voice_offset, 3),
            voice_duration=round(frame.voice_duration, 3),
            track_scene=TRACK_SCENE,
            track_voice=TRACK_VOICE,
        )
        for frame in board.frames
    )
    bgm = (
        _BGM_TEMPLATE.format(total=total, track_bgm=TRACK_BGM, volume=BGM_VOLUME)
        if with_bgm
        else ""
    )
    return _INDEX_TEMPLATE.format(
        width=board.width,
        height=board.height,
        total=total,
        ground=ground,
        scenes=scenes,
        bgm=bgm,
    )


def compile_storyboard(
    storyboard_text: str,
    video_dir: Path,
    ground: str = "#0B1220",
    with_bgm: bool = True,
    pacing: Pacing | str | None = None,
) -> Storyboard:
    """Parse, time against real audio, and write index.html into `video_dir`."""
    board = parse_storyboard(storyboard_text)
    attach_audio(board, video_dir)
    assign_timing(board, pacing)

    (video_dir / "index.html").write_text(
        render_index_html(board, ground=ground, with_bgm=with_bgm), encoding="utf-8"
    )
    log.info(
        "storyboard_compiled",
        frames=len(board.frames),
        duration=board.total_duration,
        path=str(video_dir / "index.html"),
    )
    return board
