# Low-poly narrative 3D films — design

**Date:** 2026-08-03
**Status:** awaiting review
**Phase:** 1 of 2 (Phase 2 — harvesting 3D primitives into portrait Shorts archetypes — gets its own spec)

## Reference

A 92s, 1920×1080, 30fps low-poly film narrating a passage from *The Hobbit*:
a persistent Bag End set revisited from many camera angles, flat-shaded
geometry with no textures, day→dusk→night lighting shifts, an emissive
treasure pile with bloom, burned-in subtitles tracking the narration, and
kinetic serif typography floating in the scene.

The style is the reason this is buildable. Flat-shaded low-poly geometry is
*fully described by code*: a hill is a squashed sphere, a tree is a cone on a
cylinder. There are no textures to source, no UV maps, no PBR tuning, no
binary assets. That collapses the expensive half of 3D production — asset
creation — into token generation, which this pipeline already does well.

## Decisions taken

| Decision | Choice | Why |
|---|---|---|
| Scope | Narrative landscape films first; Shorts later | Harder target proves the engine; Shorts inherit a proven renderer instead of a parallel one |
| Characters | **None in v1** | Every remaining element reduces to code-generated primitives. No Blender, no rigs, no purchased assets. The reference's strongest shots contain no character |
| Scene-authoring model | **Cloud** (Gemini/Claude) | Composing a 3D scene is thousands of tokens of spatial reasoning, well past `qwen2.5:7b`. Amends the local/cloud table in `CLAUDE.md`: frame *design* is cloud for this backend; render stays local |
| What the model emits | **JavaScript against a curated DSL** | A declarative node schema caps expressiveness at whatever node types are hand-written. Composition over a dozen parameterised primitives generates a far larger space than a hundred rigid types |
| Mitigation | **Headless render-and-screenshot gate** | Generated code can throw. This is the failure class the 2D archetypes were built to exclude, and the gate is the entire mitigation |

## 1. Architecture and data flow

A new frame backend, `three`, selected in `_build_frames`. Backend selection
is per request: `generate_youtube_video` takes an explicit backend argument,
and the `FRAME_BACKEND` env var supplies the default when none is given. The
GUI's Short/Story Film toggle sets it per generation, so both formats can be
produced from one running worker without an env change or restart.
Everything upstream (script generation, ElevenLabs TTS, `attach_audio`,
`assign_timing`) and downstream (`compile_storyboard`, `index.html`,
`hyperframes render`, ffmpeg) is unchanged.

This works because `storyboard.py` wires each frame into `index.html` as a
sub-composition via `data-composition-src` → `compositions/frames/<slug>.html`.
The composition contract cares only that the file exists and honours
`data-start` / `data-duration`. It has no opinion about what is inside, so a
3D frame is simply a third producer of that same file.

**A persistent set therefore needs no change to the composition unit.** Every
frame HTML imports the same `world.js` from the project directory and places a
different camera. The world is shared by code reuse, not by restructuring.

### Two LLM calls per film

| Call | Frequency | Produces |
|---|---|---|
| **World** | Once per film | `compositions/world.js` — terrain, buildings, standing props, the locked palette |
| **Shot** | Once per frame | `compositions/frames/<slug>.js` — camera placement, time-of-day lighting, shot-local props, the GSAP timeline |

The split does double duty. Artistically it is what makes the film feel like a
place rather than ten unrelated slides. Economically it puts the expensive
creative token spend on one call, leaving each shot a cheap camera-and-light
delta. It also makes the model's job easier: "frame this existing world from a
low angle at dusk" is far more constrained than "invent a scene."

### Pipeline

```
story ─► script (cloud, narrative prompt, pacing: story, format: 1920x1080)
      ─► narration (ElevenLabs, unchanged)
      ─► attach_audio + assign_timing (unchanged — voice-first timing)
      ─► WORLD call ──────────► compositions/world.js
      ─► per frame: SHOT call ─► compositions/frames/<slug>.js
                              ─► shell.py writes <slug>.html
                              ─► VERIFY gate (headless render + pixel probes)
                              ─► retry with error fed back, or raise
      ─► compile_storyboard → index.html (unchanged)
      ─► hyperframes render → mp4 (unchanged)
```

Subtitles are burned in by the frame shell from `frame.voiceover`. No LLM call
— the text is already on the `Frame` dataclass.

### Modules

```
worker/app/scene3d/
  primitives.js   the DSL. Hand-written, copied into each project dir
  three.module.js vendored Three.js (see Risks)
  shell.py        HTML template for a 3D frame
  author.py       cloud calls: world prompt, shot prompt, code extraction
  verify.py       the render-and-screenshot gate
worker/app/youtube.py      +1 branch in _build_frames
worker/app/storyboard.py   +1 pacing profile ("story"), landscape format
```

One responsibility each. `verify.py` and `primitives.js` are independently
testable without any LLM.

### The determinism constraint

HyperFrames renders by seeking a **paused** timeline. The Three.js scene must
draw from timeline state, never from `requestAnimationFrame` wall-clock or
`Date.now()`. Concretely: one `gsap.timeline({paused:true})` drives a plain
state object, and its `onUpdate` calls `renderer.render()`.

Getting this wrong produces a render frozen on frame one, or juddering — and
it looks correct in interactive preview, which is what makes it dangerous.
This is the riskiest unknown in the build and is spiked first (see Risks).

## 2. The DSL and primitive library

`primitives.js` is hand-written and owned by us. The model composes it; it
never writes raw Three.js.

**Material policy is enforced by the primitives, not by the prompt.** Every
primitive builds flat-shaded `MeshToonMaterial` / `MeshLambertMaterial` with
no textures and no PBR. The model cannot select a material, so it cannot break
the art direction. Art direction that lives in code cannot be prompted away.

The palette is fixed by the world call and imported by every shot, so shots
cannot drift in colour.

| Group | Primitives |
|---|---|
| Environment | `world({ground, sky, fog})`, `terrain()`, `hills([...])` |
| Geometry | `dome`, `cone`, `box`, `cyl`, `sphere`, `lathe`, `plane` |
| Composites | `tree(style)`, `flower`, `fence`, `path`, `window`, `door`, `building` |
| Finance domain | `coin`, `vault`, `stack`, `chart3d` |
| Layout | `scatter(n, fn, area)`, `row(n, fn, spacing)`, `place(obj, [x,y,z])` |
| Light | `sun(azimuth, elevation, color)`, `ambient()`, `pointGlow()` |
| Post | `bloom(strength)`, `vignette()` |
| Camera | `cam.at().lookAt()`, `cam.dolly(from,to)`, `cam.orbit()`, `cam.push()` |
| Type | `text3d(str, {font, at, style})` |
| Timing | `beat(t, fn)` |

The expressiveness argument, concretely: the reference's scattered treasure
pile is `scatter(120, () => gem(rand()))` — three lines the model can invent.
Under a declarative node schema it would be a builder feature someone had to
anticipate and hand-write.

## 3. Guards and error handling

Existing guards (`MIN_SCRIPT_FRAMES`, `MAX_SILENT_RATIO`,
`MAX_PLACEHOLDER_RATIO`) are unchanged and still apply. The 3D backend adds a
gate the 2D path could never have, because 3D produces inspectable pixels:

1. **Static check.** `node --check` the emitted module before writing it. Cheap reject.
2. **Sandbox execution.** Load the frame in headless Chromium. Capture `console.error`, `window.onerror`, unhandled rejections. Any → fail.
3. **Pixel probes.** Screenshot at 10%, 50%, 90% of frame duration. Fail if:
   - mean luminance below floor (black frame — no light, or camera inside geometry)
   - luminance variance below floor (uniform fill — camera in the void)
   - all three probes byte-identical (nothing animating; timeline not driving the render)
4. **Cross-frame distinctness.** Adjacent frames' mid-probes must not be near-identical. This is the 3D form of the archetype-repeat bug fixed in `110121b`.
5. **`MIN_VERIFIED_FRAMES`** — an absolute floor, not a ratio. Ratios cannot detect a truncated input: a one-frame film scores 100% on every proportion. Same lesson as `MIN_SCRIPT_FRAMES`.
6. **Retry, then raise.** A failed shot is retried up to `SHOT_RETRIES` (default 2, so three attempts total) with the captured error text fed back into the prompt. Still failing → **raise**. Never substitute a placeholder shot; a fabricated fallback becomes a publishable draft.

Checks 2–4 are absolute, per-frame, and operate on rendered output rather than
on proportions of it. That is deliberately the shape the ratio guards lacked.

## 4. GUI

The existing GUI is Next 16 / React 19 with pages `home`, `drafts`,
`settings`, `docs`, talking to `/youtube/generate`, `/youtube/publish`,
`/stories`, `/drafts`, `/config/{key}`.

**New page `/films`:**

- Pick a story (existing `/stories`) or enter a manual one
- Choose format: **Short (2D)** or **Story Film (3D)**
- Generate, then watch live progress: script → narration → world → shots (n/N) → verify (n/N) → render
- On completion: inline video player, download, publish

**Shot inspector** — for each frame, its probe screenshot alongside the
generated JS and any retry history. This is the highest-value screen in the
build: without it, a failed film is a wall of logs, and the whole point of the
gate is knowing *which* shot broke and why.

**API changes:**

- `POST /youtube/generate` gains `mode: "short" | "film"`
- New `jobs` table and `GET /youtube/jobs/{id}` for progress, polled every 2s. No websockets — polling is sufficient and adds no infrastructure.
- 3D settings (`FRAME_BACKEND`, scene model, bloom strength, palette override) ride the existing `/config/{key}` endpoint and Settings page.

## 5. Testing

Per `CLAUDE.md`: tests must not touch the network, and mocks patch
`_build_frames`, not a backend.

| Unit | Test |
|---|---|
| `verify.py` predicates | Synthetic PNGs — black, uniform, varied, identical pair. No browser needed |
| `primitives.js` | Node + headless snapshot of a known fixed scene |
| `author.py` | Patch the LLM call; assert the shot prompt carries world context and prior shots |
| `_build_frames` | Patch the dispatcher, assert `three` routes correctly |
| Determinism | Render a fixed scene twice, assert byte-identical frames |

## Risks and open items

| Risk | Mitigation |
|---|---|
| **Three.js ↔ HyperFrames seek determinism** — the riskiest unknown | Spike this before anything else. A throwaway hand-written 3D frame, rendered and checked for frozen/juddering output. If it fails, the whole approach needs rethinking, and we want to know on day one |
| Render time rises (WebGL frames vs DOM) | Measure during the spike. Low-poly should be cheap |
| Cloud dependency enters frame generation | The retry-then-raise logic from `7213e45` already covers transient 503/429 |
| Three.js vendored vs CDN | Existing compositions load GSAP from jsdelivr. Three.js is vendored instead: a render should not depend on the network mid-run. One file copy per project |
| Gate cost (~10 frames × 3 screenshots) | Expected seconds, not minutes. Measure |

## Out of scope for Phase 1

- Characters of any kind
- Portrait Shorts 3D archetypes (Phase 2)
- Music/SFX beyond the existing BGM track
- Any change to upload, publish or analytics
