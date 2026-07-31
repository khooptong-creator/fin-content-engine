"""Pre-validated scene archetypes for HyperFrames sub-compositions.

Asking a model to author contract-compliant HTML+GSAP per frame is both the
expensive part of the pipeline and the fragile one: every frame is a fresh
opportunity to emit a relative tween, an unloaded font family, or overlapping
text. Frontier models needed four rounds of prompt hardening to stop doing it,
and a 7B local model does worse, not better.

So the contract is satisfied here, once, in Python. Each archetype below is a
hand-written template validated against `hyperframes check`. The model's only
job is to choose an archetype and fill its slots — structured data it cannot
use to violate the composition contract.

Adding an archetype: build the body with `_shell()`, register it in ARCHETYPES
with its slot schema, and add a case to tests/test_archetypes.py.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Callable

# Palette. Text on ground/surface is `TEXT`; text on any accent fill is `GROUND`.
# Every pairing used below clears WCAG AA at the sizes these templates use.
GROUND = "#0B1220"
SURFACE = "#1B2A4A"
SURFACE_ALT = "#24365C"
TEXT = "#F8FAFC"
MUTED = "#CBD5E1"

ACCENTS = {
    "accent": "#38BDF8",
    "positive": "#34D399",
    "warning": "#FBBF24",
    "negative": "#F87171",
}
DEFAULT_ACCENT = "accent"

FONT_STACK = "'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def accent_of(name: str | None) -> str:
    return ACCENTS.get(name or DEFAULT_ACCENT, ACCENTS[DEFAULT_ACCENT])


@dataclass(frozen=True)
class Archetype:
    """One scene shape: what it is for, what it needs, and how to build it."""

    name: str
    purpose: str
    slots: dict[str, str]
    build: Callable[..., tuple[str, str, str]]


def _shell(slug: str, duration: float, body: str, css: str, js: str) -> str:
    """Wrap an archetype body in the sub-composition contract.

    Everything the renderer requires lives here so archetypes cannot get it
    wrong: the <template> wrapper, the slug-prefixed root, the full-bleed
    background on a child rather than the root, and exactly one paused timeline
    registered under the composition id.
    """
    return f"""<template>
  <style>
    [id="{slug}-root"] {{
      width: 100%;
      height: 100%;
      position: relative;
      container-type: size;
      overflow: hidden;
    }}
    [id="{slug}-bg"] {{
      position: absolute;
      inset: 0;
      background: {GROUND};
    }}
    [id="{slug}-stage"] {{
      position: absolute;
      left: 0;
      top: 10cqh;
      width: 100%;
      height: 80cqh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 4cqh;
      padding: 0 8cqw;
      text-align: center;
      transform-style: preserve-3d;
      /* Inherited properties live here, not on the root: the runtime clones the
         template's contents into the host slot and the inner root element's own
         styling is dropped, so anything set there silently never applies. */
      font-family: {FONT_STACK};
      color: {TEXT};
    }}
{css}
  </style>

  <div id="{slug}-root" data-composition-id="{slug}"
       data-width="1080" data-height="1920" data-duration="{duration}">
    <div class="clip" id="{slug}-bg" data-start="0"
         data-duration="{duration}" data-track-index="0"></div>
    <div id="{slug}-stage">
{body}
    </div>
  </div>

  <script>
    (function () {{
      const tl = gsap.timeline({{ paused: true }});
      window.__timelines["{slug}"] = tl;
{js}
    }})();
  </script>
</template>
"""


# --------------------------------------------------------------------------
# Archetypes
# --------------------------------------------------------------------------


def _title_card(slug: str, slots: dict) -> tuple[str, str, str]:
    """Opening or closing statement. Also the safe fallback for any frame."""
    accent = accent_of(slots.get("accent"))
    headline = esc(slots.get("headline", ""))
    subhead = esc(slots.get("subhead", ""))

    css = f"""    [id="{slug}-headline"] {{
      font-size: 9cqw; font-weight: 800; line-height: 1.15; letter-spacing: -0.02em;
      color: {TEXT};
    }}
    [id="{slug}-rule"] {{
      width: 22cqw; height: 1.2cqh; border-radius: 1cqh; background: {accent};
    }}
    [id="{slug}-subhead"] {{
      font-size: 5cqw; font-weight: 600; line-height: 1.35; color: {MUTED};
    }}"""

    body = f"""      <div id="{slug}-headline">{headline}</div>
      <div id="{slug}-rule"></div>
      <div id="{slug}-subhead">{subhead}</div>"""

    js = f"""      tl.fromTo('[id="{slug}-headline"]',
        {{ opacity: 0, y: 60, rotateX: -25 }},
        {{ opacity: 1, y: 0, rotateX: 0, duration: 0.8, ease: "power3.out" }}, 0);
      tl.fromTo('[id="{slug}-rule"]',
        {{ opacity: 0, scaleX: 0 }},
        {{ opacity: 1, scaleX: 1, duration: 0.5, ease: "power2.out" }}, 0.5);
      tl.fromTo('[id="{slug}-subhead"]',
        {{ opacity: 0, y: 30 }},
        {{ opacity: 1, y: 0, duration: 0.6, ease: "power2.out" }}, 0.7);"""
    return body, css, js


def _stat_reveal(slug: str, slots: dict) -> tuple[str, str, str]:
    """One number carrying the whole frame. The workhorse for finance."""
    accent = accent_of(slots.get("accent"))
    headline = esc(slots.get("headline", ""))
    value = esc(slots.get("value", ""))
    label = esc(slots.get("label", ""))

    css = f"""    [id="{slug}-headline"] {{
      font-size: 5.5cqw; font-weight: 700; line-height: 1.3; color: {MUTED};
    }}
    [id="{slug}-card"] {{
      background: {SURFACE}; border-radius: 4cqw; padding: 6cqh 8cqw;
      box-shadow: 0 2cqh 6cqh rgba(0,0,0,0.45);
      display: flex; flex-direction: column; align-items: center; gap: 2cqh;
    }}
    [id="{slug}-value"] {{
      font-size: 20cqw; font-weight: 800; line-height: 1; color: {accent};
      letter-spacing: -0.04em;
    }}
    [id="{slug}-label"] {{
      font-size: 4.5cqw; font-weight: 600; color: {TEXT}; text-transform: uppercase;
      letter-spacing: 0.08em;
    }}"""

    body = f"""      <div id="{slug}-headline">{headline}</div>
      <div id="{slug}-card">
        <div id="{slug}-value">{value}</div>
        <div id="{slug}-label">{label}</div>
      </div>"""

    js = f"""      tl.fromTo('[id="{slug}-headline"]',
        {{ opacity: 0, y: 40 }},
        {{ opacity: 1, y: 0, duration: 0.6, ease: "power3.out" }}, 0);
      tl.fromTo('[id="{slug}-card"]',
        {{ opacity: 0, scale: 0.75, rotateX: -30, z: -200 }},
        {{ opacity: 1, scale: 1, rotateX: 0, z: 0, duration: 0.9, ease: "back.out(1.4)" }}, 0.35);
      tl.fromTo('[id="{slug}-value"]',
        {{ opacity: 0, scale: 0.6 }},
        {{ opacity: 1, scale: 1, duration: 0.6, ease: "back.out(2)" }}, 0.7);"""
    return body, css, js


def _comparison(slug: str, slots: dict) -> tuple[str, str, str]:
    """Two options weighed against each other: the this-versus-that frame."""
    left_accent = accent_of(slots.get("left_accent", "negative"))
    right_accent = accent_of(slots.get("right_accent", "positive"))
    headline = esc(slots.get("headline", ""))
    left_title = esc(slots.get("left_title", ""))
    left_value = esc(slots.get("left_value", ""))
    right_title = esc(slots.get("right_title", ""))
    right_value = esc(slots.get("right_value", ""))

    css = f"""    [id="{slug}-headline"] {{
      font-size: 6cqw; font-weight: 800; line-height: 1.25; color: {TEXT};
    }}
    [id="{slug}-row"] {{
      display: flex; flex-direction: row; gap: 4cqw; width: 100%;
      transform-style: preserve-3d;
    }}
    [id="{slug}-left"], [id="{slug}-right"] {{
      flex: 1; background: {SURFACE}; border-radius: 3cqw; padding: 4cqh 3cqw;
      display: flex; flex-direction: column; align-items: center; gap: 2cqh;
      box-shadow: 0 1.5cqh 4cqh rgba(0,0,0,0.4);
    }}
    [id="{slug}-left-title"], [id="{slug}-right-title"] {{
      font-size: 4cqw; font-weight: 700; color: {MUTED};
    }}
    [id="{slug}-left-value"] {{ font-size: 11cqw; font-weight: 800; color: {left_accent}; }}
    [id="{slug}-right-value"] {{ font-size: 11cqw; font-weight: 800; color: {right_accent}; }}"""

    body = f"""      <div id="{slug}-headline">{headline}</div>
      <div id="{slug}-row">
        <div id="{slug}-left">
          <div id="{slug}-left-title">{left_title}</div>
          <div id="{slug}-left-value">{left_value}</div>
        </div>
        <div id="{slug}-right">
          <div id="{slug}-right-title">{right_title}</div>
          <div id="{slug}-right-value">{right_value}</div>
        </div>
      </div>"""

    js = f"""      tl.fromTo('[id="{slug}-headline"]',
        {{ opacity: 0, y: 40 }},
        {{ opacity: 1, y: 0, duration: 0.6, ease: "power3.out" }}, 0);
      tl.fromTo('[id="{slug}-left"]',
        {{ opacity: 0, x: -120, rotateY: 35 }},
        {{ opacity: 1, x: 0, rotateY: 0, duration: 0.8, ease: "power3.out" }}, 0.4);
      tl.fromTo('[id="{slug}-right"]',
        {{ opacity: 0, x: 120, rotateY: -35 }},
        {{ opacity: 1, x: 0, rotateY: 0, duration: 0.8, ease: "power3.out" }}, 0.6);"""
    return body, css, js


def _list_build(slug: str, slots: dict) -> tuple[str, str, str]:
    """Points landing one at a time. Keeps the eye moving through an argument."""
    accent = accent_of(slots.get("accent"))
    headline = esc(slots.get("headline", ""))
    items = [str(i) for i in (slots.get("items") or [])][:4]

    rows, row_css, row_js = [], [], []
    for idx, item in enumerate(items):
        rid = f"{slug}-item-{idx}"
        rows.append(
            f"""        <div id="{rid}" class="{slug}-item">
          <div class="{slug}-bullet"></div>
          <div class="{slug}-item-text">{esc(item)}</div>
        </div>"""
        )
        row_js.append(
            f"""      tl.fromTo('[id="{rid}"]',
        {{ opacity: 0, x: -70, z: -120 }},
        {{ opacity: 1, x: 0, z: 0, duration: 0.55, ease: "power3.out" }}, {round(0.5 + idx * 0.55, 2)});"""
        )

    css = f"""    [id="{slug}-headline"] {{
      font-size: 6.5cqw; font-weight: 800; line-height: 1.2; margin-bottom: 2cqh;
      color: {TEXT};
    }}
    [id="{slug}-list"] {{
      display: flex; flex-direction: column; gap: 2.5cqh; width: 100%;
      transform-style: preserve-3d;
    }}
    .{slug}-item {{
      display: flex; flex-direction: row; align-items: center; gap: 3cqw;
      background: {SURFACE}; border-radius: 2.5cqw; padding: 3cqh 4cqw;
      text-align: left;
    }}
    .{slug}-bullet {{
      width: 3cqw; height: 3cqw; border-radius: 50%; background: {accent}; flex: none;
    }}
    .{slug}-item-text {{ font-size: 4.8cqw; font-weight: 600; line-height: 1.3; color: {TEXT}; }}"""
    row_css.append(css)

    body = f"""      <div id="{slug}-headline">{headline}</div>
      <div id="{slug}-list">
{chr(10).join(rows)}
      </div>"""

    js = f"""      tl.fromTo('[id="{slug}-headline"]',
        {{ opacity: 0, y: 40 }},
        {{ opacity: 1, y: 0, duration: 0.6, ease: "power3.out" }}, 0);
{chr(10).join(row_js)}"""
    return body, "\n".join(row_css), js


def _bar_chart(slug: str, slots: dict) -> tuple[str, str, str]:
    """Magnitudes compared. Bars grow from zero so the change is the message."""
    accent = accent_of(slots.get("accent"))
    headline = esc(slots.get("headline", ""))
    bars = (slots.get("bars") or [])[:4]

    peak = max((float(b.get("value", 0) or 0) for b in bars), default=1.0) or 1.0

    cols, col_js = [], []
    for idx, bar in enumerate(bars):
        bid = f"{slug}-bar-{idx}"
        height = max(6.0, round(float(bar.get("value", 0) or 0) / peak * 38.0, 2))
        cols.append(
            f"""        <div class="{slug}-col">
          <div class="{slug}-bar-label">{esc(bar.get('label', ''))}</div>
          <div id="{bid}" class="{slug}-bar" style="height: {height}cqh;"></div>
          <div class="{slug}-bar-value">{esc(bar.get('display', bar.get('value', '')))}</div>
        </div>"""
        )
        col_js.append(
            f"""      tl.fromTo('[id="{bid}"]',
        {{ scaleY: 0 }},
        {{ scaleY: 1, duration: 0.7, ease: "power2.out" }}, {round(0.45 + idx * 0.18, 2)});"""
        )

    css = f"""    [id="{slug}-headline"] {{
      font-size: 6cqw; font-weight: 800; line-height: 1.25; color: {TEXT};
    }}
    [id="{slug}-chart"] {{
      display: flex; flex-direction: row; align-items: flex-end;
      justify-content: center; gap: 4cqw; width: 100%;
    }}
    .{slug}-col {{
      display: flex; flex-direction: column; align-items: center; gap: 1.5cqh; flex: 1;
    }}
    .{slug}-bar {{
      width: 100%; background: {accent}; border-radius: 1.5cqw 1.5cqw 0 0;
      transform-origin: 50% 100%;
    }}
    .{slug}-bar-label {{ font-size: 3.6cqw; font-weight: 600; color: {MUTED}; }}
    .{slug}-bar-value {{ font-size: 4.6cqw; font-weight: 800; color: {TEXT}; }}"""

    body = f"""      <div id="{slug}-headline">{headline}</div>
      <div id="{slug}-chart">
{chr(10).join(cols)}
      </div>"""

    js = f"""      tl.fromTo('[id="{slug}-headline"]',
        {{ opacity: 0, y: 40 }},
        {{ opacity: 1, y: 0, duration: 0.6, ease: "power3.out" }}, 0);
{chr(10).join(col_js)}"""
    return body, css, js


def _quote(slug: str, slots: dict) -> tuple[str, str, str]:
    """A line worth sitting with. Used for the payoff or the CTA."""
    accent = accent_of(slots.get("accent"))
    text = esc(slots.get("text", ""))
    attribution = esc(slots.get("attribution", ""))

    css = f"""    [id="{slug}-mark"] {{
      font-size: 16cqw; font-weight: 800; line-height: 0.8; color: {accent};
    }}
    [id="{slug}-text"] {{
      font-size: 7cqw; font-weight: 700; line-height: 1.3; color: {TEXT};
    }}
    [id="{slug}-attribution"] {{
      font-size: 4cqw; font-weight: 600; color: {MUTED}; letter-spacing: 0.06em;
    }}"""

    body = f"""      <div id="{slug}-mark">&ldquo;</div>
      <div id="{slug}-text">{text}</div>
      <div id="{slug}-attribution">{attribution}</div>"""

    js = f"""      tl.fromTo('[id="{slug}-mark"]',
        {{ opacity: 0, scale: 0.4 }},
        {{ opacity: 1, scale: 1, duration: 0.5, ease: "back.out(2)" }}, 0);
      tl.fromTo('[id="{slug}-text"]',
        {{ opacity: 0, y: 50, rotateX: -20 }},
        {{ opacity: 1, y: 0, rotateX: 0, duration: 0.8, ease: "power3.out" }}, 0.25);
      tl.fromTo('[id="{slug}-attribution"]',
        {{ opacity: 0 }},
        {{ opacity: 1, duration: 0.5, ease: "power1.out" }}, 0.8);"""
    return body, css, js


ARCHETYPES: dict[str, Archetype] = {
    "title_card": Archetype(
        name="title_card",
        purpose="Open or close with a single statement. The safe default.",
        slots={"headline": "string, max 8 words", "subhead": "string, max 12 words",
               "accent": "accent|positive|warning|negative"},
        build=_title_card,
    ),
    "stat_reveal": Archetype(
        name="stat_reveal",
        purpose="Land one number that carries the whole point.",
        slots={"headline": "string, max 10 words", "value": "short string e.g. '18%' or 'Rs 4,200'",
               "label": "string, max 4 words", "accent": "accent|positive|warning|negative"},
        build=_stat_reveal,
    ),
    "comparison": Archetype(
        name="comparison",
        purpose="Weigh two options against each other.",
        slots={"headline": "string, max 10 words", "left_title": "string, max 3 words",
               "left_value": "short string", "right_title": "string, max 3 words",
               "right_value": "short string", "left_accent": "usually negative",
               "right_accent": "usually positive"},
        build=_comparison,
    ),
    "list_build": Archetype(
        name="list_build",
        purpose="Reveal 2-4 points one at a time.",
        slots={"headline": "string, max 8 words",
               "items": "array of 2-4 strings, each max 8 words",
               "accent": "accent|positive|warning|negative"},
        build=_list_build,
    ),
    "bar_chart": Archetype(
        name="bar_chart",
        purpose="Compare 2-4 magnitudes visually.",
        slots={"headline": "string, max 10 words",
               "bars": "array of 2-4 objects {label, value (number), display (string)}",
               "accent": "accent|positive|warning|negative"},
        build=_bar_chart,
    ),
    "quote": Archetype(
        name="quote",
        purpose="Sit on one memorable line. Good for the payoff or CTA.",
        slots={"text": "string, max 16 words", "attribution": "string, max 5 words, may be empty",
               "accent": "accent|positive|warning|negative"},
        build=_quote,
    ),
}

FALLBACK_ARCHETYPE = "title_card"


def render_archetype(slug: str, duration: float, spec: dict) -> str:
    """Build a sub-composition from `{"archetype": ..., "slots": {...}}`.

    An unknown archetype falls back to a title card rather than raising: a model
    inventing a name should cost the frame its shape, not the whole video.
    """
    name = spec.get("archetype", FALLBACK_ARCHETYPE)
    archetype = ARCHETYPES.get(name) or ARCHETYPES[FALLBACK_ARCHETYPE]
    slots = spec.get("slots") or {}
    body, css, js = archetype.build(slug, slots)
    return _shell(slug, duration, body, css, js)


def catalogue_for_prompt() -> str:
    """The archetype menu, rendered for an LLM system prompt."""
    lines = []
    for archetype in ARCHETYPES.values():
        slot_desc = ", ".join(f"{k} ({v})" for k, v in archetype.slots.items())
        lines.append(f"- {archetype.name}: {archetype.purpose}\n    slots: {slot_desc}")
    return "\n".join(lines)
