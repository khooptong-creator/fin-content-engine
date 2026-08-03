# Spike Result — Three.js under HyperFrames paused-timeline seek

**Date:** 2026-08-03
**Task:** Task 1 of `2026-08-03-lowpoly-3d-films.md`
**Verdict: PASS** — with three corrections later tasks must absorb.

Three.js renders deterministically under HyperFrames' paused-timeline seek. The
`gsap.timeline({paused:true})` + `onUpdate → renderer.render()` pattern works,
with no `requestAnimationFrame` anywhere. Task 2 may start.

## Versions

| Component | Version |
|---|---|
| HyperFrames | 0.7.90 |
| Three.js | **0.160.1, `build/three.min.js` (classic UMD)** — *not* 0.169.0 `three.module.js` |
| Node | v24.15.0 |
| GPU in render browser | hardware — ANGLE / NVIDIA RTX 3070 / D3D11 |

## Evidence

Six frames sampled across a single 90° sector of the cube's 2π spin
(frames 0, 5, 10, 15, 20, 25 of 120 — i.e. 0°, 15°, 30°, 45°, 60°, 75°):

| Frame | Angle | MD5 |
|---|---|---|
| 0 | 0° | `6F45CBF1A9451A4B41A32193E4E2FF98` |
| 5 | 15° | `82D67158612984ACAF27794F94F10080` |
| 10 | 30° | `D70241F7BDCE42DC098D6D7FD8967038` |
| 15 | 45° | `D4BAD6F427C37E561C907898EE1DAECE` |
| 20 | 60° | `FDA5BCB3D74CFAD769517EAACC1FEA08` |
| 25 | 75° | `4C81E7E98C0F411D178BDB8E1497DC4D` |

Six distinct hashes; visual inspection confirms a monotonic turn from face-on to
corner-on. **Determinism:** two independent renders of the same project produced
byte-identical frames at all six sample points.

Render health after the fix: `pollSubCompositionTimelines complete (ready)` in
633 ms, zero correctness warnings, 283.1 KB / 4.0 s, rendered in 9.0 s.

## Correction 1 — frames cannot use ES modules

**This was the initial failure.** The first render exited 0 and produced a valid
4.0 s MP4 containing no cube at all, with `sub_timeline_readiness_timeout` for
both `main` and `f01-spike`. `npx hyperframes check --json` gave the root cause:

```
page_error: "Cannot use import statement outside a module"
```

HyperFrames injects a sub-composition's `<template>` content into the parent
document, and **`type="module"` is not preserved** — the block executes as a
classic script, so `import * as THREE from '...'` is a parse-time SyntaxError.
The whole script body is dead, which is why the frame's trailing
`renderer.render(scene, camera)` never ran and no timeline registered.

Consequences for the design:

- Frames load Three.js with a plain `<script src>`; generated shot modules must
  never emit an `import` or `export` statement.
- The last Three.js release shipping a classic UMD build is **r160.1**. r161+ is
  ESM-only and therefore unusable from a frame. Pin r160.1.
- **Task 2 must vendor `three.min.js` (UMD), not `three.module.js`.** As written,
  Task 2 vendors the ESM build and would reintroduce this exact failure.
- r160.1 covers everything this design needs (`BoxGeometry`, `MeshLambertMaterial`,
  `flatShading`, lights, `PerspectiveCamera`). No post-r160 API is required.

## Correction 2 — asset paths must be project-root-relative

`../../three.min.js` from `compositions/frames/` fails lint with
`invalid_parent_traversal_in_asset_path`: renders resolve such paths against the
sub-composition's source path, while Studio preview resolves against the project
root, so the two disagree and one 404s.

Use `assets/three.min.js` — root-relative, no `./`, no `../`. This matches the
convention already used by the 2D pipeline (`assets/voice/01.mp3`).

Lint also enforces this **per file**: any file referencing `THREE` must itself
load a Three.js script. Loading it only from the parent `index.html` fails with
`missing_three_script`. Each generated frame therefore carries its own
`<script src="assets/three.min.js">`, which is the better outcome anyway — frames
stay self-contained instead of coupling to the parent shell.

## Correction 3 — `check`'s `sweep_static` is a false positive for 3D frames

`npx hyperframes check` reports:

```
sweep_static: Timeline did not advance under seek; every green verdict
              on this run is unreliable.
```

...on the **working** composition. The sweep fingerprints DOM geometry and
opacity; a cube rotating inside a `<canvas>` changes neither. Any pure-WebGL
frame trips this.

**Task 7's verification gate must not treat `check` as authoritative for 3D
frames.** Motion has to be established from canvas pixels — which is what the
plan's probe statistics (mean luminance, variance, average hash) already do. Keep
that, and do not add a `check`-based motion assertion on top of it.

## Correction 4 — do not reuse the plan's probe sampling

The plan's Step 5 samples frames 0, 30, 60, 90 of a 120-frame 2π spin: exactly
0°, 90°, 180°, 270°. A cube is 4-fold symmetric about Y and `MeshLambertMaterial`
shades from world-space normals, so a correct render and a frozen one are
**pixel-identical at all four instants**. The first pass through this spike
produced four identical stills for that reason alone.

This matters beyond the spike: it is the same failure shape as `MIN_SCRIPT_FRAMES`
— a check a broken system passes for free. **Task 6/7 probe timestamps must not
be harmonics of the animation they measure.** Prefer prime-ish fractions of the
duration (e.g. 0.13, 0.41, 0.87) over evenly spaced samples.

## Note — renderer clear colour hides the CSS backdrop

The default opaque black clear colour paints over the frame's background clip
(`#0B1220` in the spike). Fine when the 3D scene owns the full frame. If a frame
ever needs the CSS backdrop to show through, construct the renderer with
`{ alpha: true }`.

## Reproduce

```powershell
cd "F:\Content Creation Project\videos\spike-three"
npx hyperframes check
npx hyperframes render --output renders/spike.mp4
ffmpeg -y -v error -i renders/spike.mp4 -vf "select='lt(n\,26)*not(mod(n\,5))',scale=480:-1" -vsync 0 "renders/seq%02d.png"
Get-FileHash renders/seq*.png -Algorithm MD5
```

Expect six distinct hashes and a visibly turning cube.
