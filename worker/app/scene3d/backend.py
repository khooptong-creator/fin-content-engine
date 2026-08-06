"""Orchestrate one film's 3D frames: world, then shot-verify-retry per frame.

The retry loop is the point. A model writing free-form JavaScript will
occasionally put the camera inside a hill or forget a light, and the gate
catches that — but only if the failure feeds back into the next attempt.
Exhausting the retries reports the slug; it never writes a substitute, because
a substituted shot renders and validates exactly like a real one.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import structlog

from app.scene3d.author import author_shot, author_world
from app.scene3d.probes import ProbeStats, frames_are_distinct
from app.scene3d.shell import render_3d_frame
from app.scene3d.verify import verify_shot

log = structlog.get_logger()

SHOT_RETRIES = int(os.environ.get("SHOT_RETRIES", "2"))
MIN_VERIFIED_FRAMES = int(os.environ.get("MIN_VERIFIED_FRAMES", "3"))

ASSETS = Path(__file__).resolve().parent / "assets"


@dataclass
class ShotReport:
    slug: str
    attempts: int = 0
    ok: bool = False
    reason: str = ""
    js: str = ""
    probe_pngs: list[str] = field(default_factory=list)


def _install_assets(video_dir: Path) -> None:
    """Copy the DSL and Three.js into the project so a render needs no network.

    Files land at ``assets/`` (project-root-relative), matching the paths the
    shell emits — ``assets/three.min.js`` and ``assets/primitives.js``.
    Spike Correction 1: ``three.min.js`` (UMD r160.1), NOT ``three.module.js``.
    """
    assets_dir = video_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    for name in ("three.min.js", "primitives.js"):
        shutil.copyfile(ASSETS / name, assets_dir / name)


async def build_3d_frames(board, video_dir: Path) -> list[str]:
    """Build every frame as a verified 3D shot. Returns slugs that never passed."""
    _install_assets(video_dir)
    frames_dir = video_dir / "compositions" / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    probe_dir = video_dir / "renders" / "probes"

    world_code = await author_world(board)
    (video_dir / "compositions" / "world.js").write_text(
        world_code, encoding="utf-8"
    )

    failed: list[str] = []
    reports: list[ShotReport] = []
    prior_shots: list[str] = []
    accepted_probes: list[ProbeStats] = []

    for frame in board.frames:
        report = ShotReport(slug=frame.slug)
        last_error: str | None = None
        frame_path = frames_dir / f"{frame.slug}.html"

        for attempt in range(SHOT_RETRIES + 1):
            report.attempts = attempt + 1
            shot_js = await author_shot(
                board, frame, world_code, prior_shots, last_error=last_error
            )
            frame_path.write_text(
                render_3d_frame(
                    frame.slug,
                    frame.duration,
                    shot_js,
                    frame.voiceover,
                    width=board.width,
                    height=board.height,
                ),
                encoding="utf-8",
            )
            verdict, probes, _errors = await verify_shot(
                frame_path, frame.duration, probe_dir
            )

            if (
                verdict.ok
                and accepted_probes
                and not frames_are_distinct(
                    accepted_probes[-1], probes[len(probes) // 2]
                )
            ):
                verdict = type(verdict)(
                    False, "shot looks identical to the previous one"
                )

            if verdict.ok:
                report.ok = True
                report.js = shot_js
                report.probe_pngs = [
                    f"{frame.slug}-p{i}.png" for i in range(3)
                ]
                prior_shots.append(shot_js)
                accepted_probes.append(probes[len(probes) // 2])
                break

            last_error = verdict.reason
            report.reason = verdict.reason
            log.warning(
                "shot_rejected",
                slug=frame.slug,
                attempt=attempt + 1,
                reason=verdict.reason,
            )

        if not report.ok:
            # Deliberately leave nothing behind. A substituted shot would render
            # and validate exactly like a real one, and ship.
            frame_path.unlink(missing_ok=True)
            failed.append(frame.slug)
        reports.append(report)

    board.meta["shot_reports"] = reports
    log.info("3d_frames_built", frames=len(board.frames), failed=len(failed))
    return failed
