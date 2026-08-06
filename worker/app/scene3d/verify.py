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


@asynccontextmanager
async def _browser():
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            args=[
                "--use-gl=angle",
                "--enable-unsafe-swiftshader",
                "--hide-scrollbars",
            ]
        )
        try:
            yield browser
        finally:
            await browser.close()


async def _open_page(browser, frame_path: Path):
    """Load a frame and collect anything it complained about."""
    page = await browser.new_page(viewport={"width": 1920, "height": 1080})
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    await page.goto(frame_path.resolve().as_uri())
    await page.wait_for_timeout(400)
    return page, errors


async def verify_shot(
    frame_path: Path, duration: float, out_dir: Path
) -> tuple[ShotVerdict, list[ProbeStats], list[str]]:
    """Load one generated frame, probe it three times, and judge it."""
    slug = frame_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    async with _browser() as browser:
        page, errors = await _open_page(browser, frame_path)

        if errors:
            # Reject on the exception, never on how the broken frame happened to
            # look. A shot that threw may still paint a plausible background.
            return ShotVerdict(False, f"runtime error: {errors[0]}"), [], errors

        probes: list[ProbeStats] = []
        for i, fraction in enumerate(PROBE_FRACTIONS):
            t = fraction * duration
            raw = await page.evaluate(_STATS_JS, [slug, t])
            probes.append(ProbeStats(t=t, **raw))
            shot = await page.screenshot()
            (out_dir / f"{slug}-p{i}.png").write_bytes(shot)

        await page.close()

    verdict = judge_shot(probes)
    log.info("shot_verified", slug=slug, ok=verdict.ok, reason=verdict.reason)
    return verdict, probes, errors
