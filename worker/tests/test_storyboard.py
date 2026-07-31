"""Tests for the STORYBOARD.md -> HyperFrames compiler."""

import pytest

from app.storyboard import (
    PACING_PROFILES,
    Frame,
    Storyboard,
    assign_timing,
    parse_storyboard,
    render_index_html,
    resolve_pacing,
)

# The dialect the hand-authored boards under videos/ use.
HAND_AUTHORED = """---
format: 1080x1920
duration: 60s
title: "The EMI Illusion"
music: soft upbeat playful
---

## Video direction

**Tone**: Cheerful, clean, 3D depth.

## Frame 1 — Hook

- status: outline
- duration: 4.5s
- scene: A shiny new phone with a "0% EMI" badge.
- voiceover: "There is no such thing as a No Cost EMI."

**Shot Sequence:**
- 0.0s: [Scene 1] Phone card pops in center.
- 2.5s: [Scene 2] Badge slides onto the phone.

## Frame 2 — Intro

- duration: 5.0s
- scene: A playful title card.
- voiceover: "The bank still charges interest."
"""

# The dialect Gemini emits today from _generate_script_for_story.
GEMINI_OUTPUT = """---
title: "The Inflation Trap"
description: "Why your raise is a pay cut."
preset: adult_male
music: soft upbeat playful
---

# Video direction
A clean, minimal, cartoonized explainer video.

# Scene 1
Voiceover: "Did you get a 10% raise? Bad news."
Visual: A bright title card introducing the topic.

# Scene 2
Voiceover: "Real inflation is the invisible tax."
Visual: A grocery bag shrinking while a salary slip grows.
"""


def test_parses_hand_authored_dialect():
    board = parse_storyboard(HAND_AUTHORED)

    assert board.title == "The EMI Illusion"
    assert (board.width, board.height) == (1080, 1920)
    assert len(board.frames) == 2

    hook = board.frames[0]
    assert hook.title == "Hook"
    assert hook.voiceover == "There is no such thing as a No Cost EMI."
    assert hook.declared_duration == 4.5
    assert len(hook.shots) == 2
    assert hook.slug == "f01-hook"


def test_parses_gemini_dialect():
    """Autopilot output must compile through the same path as hand-authored boards."""
    board = parse_storyboard(GEMINI_OUTPUT)

    assert board.title == "The Inflation Trap"
    assert len(board.frames) == 2
    assert board.frames[0].voiceover == "Did you get a 10% raise? Bad news."
    assert board.frames[1].voiceover == "Real inflation is the invisible tax."
    # No `format:` key -> falls back to vertical shorts dimensions.
    assert (board.width, board.height) == (1080, 1920)


def test_frontmatter_survives_unescaped_colons():
    """LLM-written descriptions contain colons; a strict YAML parser would choke."""
    board = parse_storyboard(
        '---\ntitle: "Truth: the real cost"\n---\n\n# Scene 1\nVoiceover: "Hello."\n'
    )
    assert board.title == "Truth: the real cost"


def test_duplicate_scene_numbers_are_renumbered():
    board = parse_storyboard(
        "# Scene 1\nVoiceover: \"a\"\n\n# Scene 2\nVoiceover: \"b\"\n\n# Scene 2\nVoiceover: \"c\"\n"
    )
    assert [f.index for f in board.frames] == [1, 2, 3]
    # Unnamed frames fall back to the index alone, so a renumbered frame can
    # never carry a slug that contradicts its position.
    assert [f.slug for f in board.frames] == ["f01-frame", "f02-frame", "f03-frame"]


def _timed_board() -> Storyboard:
    board = Storyboard(meta={"title": "T"})
    board.frames = [
        Frame(index=1, title="Hook", voiceover="a", audio_duration=3.0),
        Frame(index=2, title="Meat", voiceover="b", audio_duration=5.0),
    ]
    return assign_timing(board)


def test_frames_are_laid_end_to_end_without_gaps():
    board = _timed_board()

    assert board.frames[0].start == 0.0
    # Frame 2 must begin exactly where frame 1 ends, or audio drifts.
    assert board.frames[1].start == pytest.approx(board.frames[0].duration)
    assert board.total_duration == pytest.approx(
        board.frames[0].duration + board.frames[1].duration
    )


def test_every_frame_gets_positive_duration():
    """A zero-length clip is dropped by the renderer and vanishes silently."""
    board = Storyboard(meta={"title": "T"})
    board.frames = [
        Frame(index=1, title="Silent", audio_duration=None, declared_duration=None),
        Frame(index=2, title="Declared", audio_duration=None, declared_duration=6.0),
    ]
    assign_timing(board)

    assert all(f.duration > 0 for f in board.frames)


def test_longer_narration_yields_longer_frame():
    """Timing must track the voice, not a fixed cadence."""
    board = Storyboard(meta={"title": "T"})
    board.frames = [
        Frame(index=1, title="Short", audio_duration=2.0),
        Frame(index=2, title="Long", audio_duration=9.0),
    ]
    assign_timing(board)

    assert board.frames[1].duration > board.frames[0].duration


def test_narrated_frame_is_never_shorter_than_its_audio():
    """Truncating below the audio cuts the voice off mid-sentence."""
    board = Storyboard(meta={"title": "T"})
    # Well past the explainer soft ceiling of 12s.
    board.frames = [Frame(index=1, title="Rambling", audio_duration=20.0)]
    assign_timing(board, "explainer")

    assert board.frames[0].duration >= 20.0


def test_readability_floor_applies_to_very_short_narration():
    board = Storyboard(meta={"title": "T"})
    board.frames = [Frame(index=1, title="Blip", audio_duration=0.4)]
    assign_timing(board, "explainer")

    assert board.frames[0].duration == pytest.approx(PACING_PROFILES["explainer"].floor)


def test_news_profile_cuts_tighter_than_explainer():
    """Real-time adult news and kids explainers cannot share one cadence."""

    def duration_under(profile: str) -> float:
        board = Storyboard(meta={"title": "T"})
        board.frames = [Frame(index=1, title="Line", audio_duration=1.0)]
        assign_timing(board, profile)
        return board.frames[0].duration

    assert duration_under("news") < duration_under("explainer")


def test_pacing_profile_comes_from_frontmatter():
    board = parse_storyboard('---\ntitle: "T"\npacing: news\n---\n\n# Scene 1\nVoiceover: "a"\n')
    assert resolve_pacing(None, board) is PACING_PROFILES["news"]


def test_unknown_pacing_profile_falls_back_instead_of_crashing():
    """An LLM writing `pacing: snappy` must not take down the render."""
    board = parse_storyboard('---\ntitle: "T"\npacing: snappy\n---\n\n# Scene 1\nVoiceover: "a"\n')
    assert resolve_pacing(None, board) is PACING_PROFILES["explainer"]


def test_voice_fits_inside_its_frame_without_being_clamped():
    """The audio slot is its own length; padding belongs to the frame, not the voice.

    Giving the audio element the padded frame duration makes the renderer clamp
    it back to the media length and emit a clip_media_fit warning.
    """
    board = Storyboard(meta={"title": "T"})
    board.frames = [Frame(index=1, title="Hook", audio_duration=5.0)]
    assign_timing(board, "explainer")
    frame = board.frames[0]

    html = render_index_html(board)
    assert 'data-duration="5.0"' in html  # the audio element, not the frame
    # Voice starts after the lead-in and still ends inside the frame.
    assert frame.voice_offset > 0
    assert frame.voice_offset + frame.voice_duration <= frame.duration


def test_silent_frame_voice_is_not_offset():
    board = Storyboard(meta={"title": "T"})
    board.frames = [Frame(index=1, title="Silent", declared_duration=5.0)]
    assign_timing(board, "explainer")

    assert board.frames[0].voice_offset == 0.0


def test_index_html_satisfies_composition_contract():
    board = _timed_board()
    html = render_index_html(board)

    # Root declares the composition and the full timeline length.
    assert 'data-composition-id="main"' in html
    assert f'data-duration="{board.total_duration}"' in html
    assert 'data-width="1080"' in html

    # Exactly one paused timeline registered under the root id.
    assert html.count("gsap.timeline({ paused: true })") == 1
    assert 'window.__timelines["main"]' in html

    # Each frame wires a sub-composition host plus its narration on the voice track.
    for frame in board.frames:
        assert f'data-composition-src="compositions/frames/{frame.slug}.html"' in html
        assert f'data-composition-id="{frame.slug}"' in html
        assert f'src="{frame.voice_filename}"' in html
    assert html.count('data-track-index="1"') == len(board.frames)
    assert html.count('data-track-index="10"') == len(board.frames)


def test_background_is_on_full_bleed_child_not_root():
    """A fill on the composition root can be dropped by the producer -> black frame."""
    html = render_index_html(_timed_board(), ground="#0B1220")

    assert "#stage-fill" in html
    assert "background: #0B1220" in html
    # The root itself must not carry the scene fill.
    root_block = html.split("#root {")[1].split("}")[0]
    assert "#0B1220" not in root_block


def test_bgm_can_be_omitted_when_no_track_exists():
    html = render_index_html(_timed_board(), with_bgm=False)
    assert 'id="el-bgm"' not in html
