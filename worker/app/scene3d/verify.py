"""Render a generated shot in a real browser and decide whether it drew anything.

This is the mitigation the DSL approach is built on. Letting a model write
JavaScript reopens the malformed-composition failure class that the 2D
archetypes exclude by construction, and this gate is what closes it again: a
shot that throws, draws nothing, or never moves is rejected before it can reach
a render that would look perfectly valid.

Statistics are computed in-page from the canvas so Python needs no image
library; the PNG is written only so the GUI's shot inspector has something to
show a human.
"""

from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
from pathlib import Path

import structlog

from app.scene3d.probes import ProbeStats, ShotVerdict, judge_shot

log = structlog.get_logger()

# Early, middle and late. Enough to catch "never moves" without paying for more.
PROBE_FRACTIONS = (0.1, 0.5, 0.9)

# Computed in-page: mean luminance, variance, and a 64-bit average hash.
# The signature is a destructured array — Playwright's page.evaluate passes
# args as a single array argument.
_STATS_JS = """
([slug, t]) => {
  const tl = window.__timelines && window.__timelines[slug];
  if (tl) { tl.seek(t); }
  const canvas = document.getElementById(slug + '-canvas');
  if (!canvas) { return { mean_luma: 0, variance: 0, phash: '' }; }

  const small = document.createElement('canvas');
  small.width = 8; small.height = 8;
  const ctx = small.getContext('2d');
  ctx.drawImage(canvas, 0, 0, 8, 8);
  const data = ctx.getImageData(0, 0, 8, 8).data;

  const luma = [];
  for (let i = 0; i < data.length; i += 4) {
    luma.push((0.2126 * data[i] + 0.7152 * data[i+1] + 0.0722 * data[i+2]) / 255);
  }
  const mean = luma.reduce((a, b) => a + b, 0) / luma.length;
  const variance = luma.reduce((a, b) => a + (b - mean) ** 2, 0) / luma.length;

  let bits = '';
  for (const l of luma) { bits += (l > mean ? '1' : '0'); }
  let phash = '';
  for (let i = 0; i < 64; i += 4) {
    phash += parseInt(bits.slice(i, i + 4), 2).toString(16);
  }
  return { mean_luma: mean, variance, phash };
}
"""


async def verify_shot(
    frame_path: Path, duration: float, out_dir: Path
) -> tuple[ShotVerdict, list[ProbeStats], list[str]]:
    """Load one generated frame, probe it three times, and judge it.

    Runs entirely via the sync Playwright API inside a single
    ``asyncio.to_thread`` call — Playwright's sync API uses greenlets
    internally, and greenlets cannot switch threads. One thread for
    the whole lifecycle avoids ``greenlet.error: Cannot switch to a
    different thread``.
    """
    slug = frame_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    def _run():
        from playwright.sync_api import sync_playwright

        pw = sync_playwright().start()
        try:
            browser = pw.chromium.launch(
                args=[
                    "--use-gl=angle",
                    "--enable-unsafe-swiftshader",
                    "--hide-scrollbars",
                ]
            )
            try:
                page = browser.new_page(
                    viewport={"width": 1920, "height": 1080}
                )
                errors: list[str] = []
                page.on(
                    "console",
                    lambda m: errors.append(m.text)
                    if m.type == "error"
                    else None,
                )
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(frame_path.resolve().as_uri())
                page.wait_for_timeout(400)

                if errors:
                    return ShotVerdict(
                        False, f"runtime error: {errors[0]}"
                    ), [], errors

                probes: list[ProbeStats] = []
                for i, fraction in enumerate(PROBE_FRACTIONS):
                    t = fraction * duration
                    raw = page.evaluate(_STATS_JS, [slug, t])
                    probes.append(ProbeStats(t=t, **raw))
                    shot = page.screenshot()
                    (out_dir / f"{slug}-p{i}.png").write_bytes(shot)

                page.close()
                return None, probes, errors
            finally:
                browser.close()
        finally:
            pw.stop()

    maybe_verdict, probes, errors = await asyncio.to_thread(_run)
    if maybe_verdict is not None:
        return maybe_verdict, probes, errors

    verdict = judge_shot(probes)
    log.info("shot_verified", slug=slug, ok=verdict.ok, reason=verdict.reason)
    return verdict, probes, errors
