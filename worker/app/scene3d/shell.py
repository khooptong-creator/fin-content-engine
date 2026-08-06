"""Wrap a generated shot module in the HyperFrames sub-composition contract.

The 3D analogue of ``archetypes._shell``. Everything the renderer requires lives
here so a generated shot cannot get it wrong: the ``<template>`` wrapper, the
slug-prefixed root, the canvas, the burned-in subtitle, and exactly one paused
timeline registered under the composition id.

Corrected for the spike findings (2026-08-03-spike-result.md):
- Plain ``<script>`` tags — **no** ``type="module"``. HyperFrames does not
  preserve it on injected sub-compositions (Correction 1).
- Three.js loaded via ``assets/three.min.js`` (UMD) and primitives via
  ``assets/primitives.js`` — project-root-relative, no ``../`` traversal
  (Correction 2).
- The generated shot module never writes an ``import`` or ``export``
  statement. It receives the stage objects (scene, camera, tl, state, cam)
  unpacked into scope by the shell.
"""

from __future__ import annotations

import html


_SUBTITLE_CSS = """
    [id="{slug}-subtitle"] {{
      position: absolute;
      left: 8%;
      right: 8%;
      bottom: 7%;
      text-align: center;
      font-family: Georgia, 'Times New Roman', serif;
      font-size: 30px;
      line-height: 1.4;
      color: #F5F5F5;
      text-shadow: 0 2px 6px rgba(0,0,0,0.85);
      pointer-events: none;
    }}
"""


def render_3d_frame(
    slug: str,
    duration: float,
    shot_js: str,
    subtitle: str,
    width: int = 1920,
    height: int = 1080,
) -> str:
    """Build one frame's HTML from a generated shot module.

    The caller (backend.py) writes the returned string to
    ``compositions/frames/<slug>.html``. Everything upstream (timing,
    narration) and downstream (storyboard compilation, render) is unchanged
    from the 2D pipeline — the frame is just a different producer of the
    same file contract.
    """
    # Seed is deterministic per slug so scatter positions don't drift across
    # re-renders.  Python's ``hash()`` is stable within one process.
    seed = abs(hash(slug)) % 100000

    return f"""<template>
  <style>
    [id="{slug}-root"] {{
      width: 100%;
      height: 100%;
      position: relative;
      overflow: hidden;
    }}
    [id="{slug}-canvas"] {{
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      display: block;
    }}
{_SUBTITLE_CSS.format(slug=slug)}
  </style>

  <div id="{slug}-root" data-composition-id="{slug}"
       data-width="{width}" data-height="{height}" data-duration="{duration}">
    <canvas id="{slug}-canvas" class="clip" data-start="0"
            data-duration="{duration}" data-track-index="0"></canvas>
    <div id="{slug}-subtitle">{html.escape(subtitle, quote=True)}</div>
  </div>

  <script src="assets/three.min.js"></script>
  <script src="assets/primitives.js"></script>
  <script>
    var canvas = document.getElementById('{slug}-canvas');
    var stage = Prim.createStage({{ width: {width}, height: {height}, canvas: canvas }});
    var scene = stage.scene;
    var camera = stage.camera;
    var tl = stage.tl;
    var state = stage.state;
    var cam = stage.cam;
    Prim.seed({seed});

    // ---- generated shot module ----
{shot_js}
    // ---- end generated shot module ----

    window.__timelines = window.__timelines || {{}};
    window.__timelines["{slug}"] = tl;
    stage.render();
  </script>
</template>
"""
