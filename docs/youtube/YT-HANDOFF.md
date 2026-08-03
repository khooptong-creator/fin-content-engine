# Handoff Note: YouTube Integration into The Cyborg Desk

This document outlines the architectural pathway for integrating the dual-channel YouTube pipeline into the existing "Cyborg Desk" GUI (Fin-Content Engine).

## Current State vs Future State
- **Current State:** Cyborg Desk handles X (Twitter) and Instagram text/carousel posts. The YouTube pipeline is currently a manual AI workflow (generate script -> voiceover -> animate).
- **Future State:** A unified GUI where a single news event (e.g., "RBI raises rates") generates a compliant X thread, an IG carousel, *and* a 60-second YouTube Shorts script, all awaiting human approval in the same dashboard.

## Phase 1: Scripting Integration (✅ COMPLETED)
To bring YouTube into the GUI, we extended the current Worker (`fce-worker`).
1. **Extend Content Archetypes:** Supported archetypes mapping to YouTube.
2. **Prompt Injection:** Connected DB configs to inject Retention Framework and compliance rules.
3. **Compliance Gate:** Gemini 1.5 Flash is strictly instructed to avoid financial advice via blocklists and system prompts. Output is validated as YAML-frontmatter Markdown.

## Phase 2: Asset Generation Integration (✅ COMPLETED)
1. **Voiceover API:** Integrated the ElevenLabs API directly into the Cyborg Desk backend. The worker parses `Voiceover:` lines from the LLM script, maps the preset to a voice ID, and generates the `audio.mp3`.
2. **Video Rendering:** Triggered locally via `hyperframes render` passing the generated Markdown and Audio.

## Phase 3: GUI Updates (The Dashboard) (✅ COMPLETED)
- Added a "YouTube Package" tab to the Drafts Queue page.
- Displays the script via ReactMarkdown, the generated voiceover with an HTML5 audio player, and download links for script + audio.
- Added a real **Publish to YouTube** button with loading, error, and success states.

## Phase 4: YouTube API Integration (✅ COMPLETED)
- Added `FCE_YOUTUBE_TOKEN_PATH`, `FCE_YOUTUBE_CLIENT_SECRETS_PATH`, and `FCE_YOUTUBE_CHANNEL_ID` settings.
- Refactored `worker/app/youtube.py` to load/refresh OAuth credentials from the configured token path.
- Added `POST /youtube/publish` endpoint that uploads the rendered MP4, attaches the thumbnail, and updates the draft record.
- Wired the GUI **Publish to YouTube** button to the new endpoint with real loading, error, and success states.

*Note: Fully automating the animation process within the GUI is computationally heavy and error-prone. The GUI should handle the "Pre-Production" (Script, Compliance, Audio), and humans/software handle the "Production" (Animation, Editing).*

---

## Session Handoff — 2026-07-30

### What was produced
A complete, upload-ready YouTube Short:
- **Project:** `videos/the-emi-illusion/`
- **Topic:** *The EMI Illusion* — why "No Cost EMIs" are not actually free
- **Final MP4:** `videos/the-emi-illusion/renders/video.mp4` (1080×1920, 39.7s, H.264 + AAC)
- **Thumbnail:** `videos/the-emi-illusion/renders/thumbnail.jpg`
- **Script/storyboard:** `videos/the-emi-illusion/STORYBOARD.md` and `SCRIPT.md`
- **Description:** added to `STORYBOARD.md` frontmatter — "Think your 'No Cost EMI' is really free? This short explains the hidden trick brands and banks use to make you pay full price while pretending you're getting a discount. Learn why paying upfront can actually save you money, and how to negotiate the discount yourself. No financial advice—just a clear breakdown of how EMI pricing works. Share this with a friend who's about to buy a phone!"

### Pipeline used
- HyperFrames 0.7.82 for composition and render
- 5 custom HTML/GSAP frames under `compositions/frames/`
- Voiceover: Microsoft Edge TTS (`en-IN-PrabhatNeural`) via `edge-tts` fallback
- BGM reused from `videos/the-inflation-trap/bgm.mp3`

### Why edge-tts was used instead of ElevenLabs
The ElevenLabs API key provided is on the free tier. Free-tier keys cannot use library voices via the API (`paid_plan_required` error) and cannot request WAV output (`subscription_required` error). Once the account is upgraded to a paid plan, replace the `edge-tts` call in the generation script with `elevenlabs.text_to_speech.convert()`.

### Validation
`npm run check` passed with only warnings (IDs starting with digits, Google Fonts imports, contrast suggestions). No runtime errors.

### Current blocker
Google Cloud project quota is exhausted. A quota increase request has been submitted and is pending review (~2 business days). Until it is approved, the YouTube Data API cannot be used for uploads.

### Next steps for the next session
1. **If quota is approved:** run `python worker/test_youtube_upload.py` from `worker/` to generate `worker/token.json`, then click **Publish to YouTube** in the Drafts Queue for the EMI Illusion draft.
2. **If you need it live sooner:** upload `videos/the-emi-illusion/renders/video.mp4` and `thumbnail.jpg` to YouTube Studio manually.
3. After any successful upload, verify the video appears as a private draft in YouTube Studio, then set visibility/schedule there.

---

## Session Handoff — 2026-07-31

### Headline

The production entry point `generate_youtube_video()` ran end-to-end against
local Postgres for the first time. Everything demonstrated before this session
went through the `render_local.py` harness, which skips the DB, the guards and
the draft write. The first real run failed in a way no test would have caught.

### The bug the run found

Gemini returned `503 UNAVAILABLE`. `_generate_script_for_story` swallowed it and
returned a hardcoded one-scene stub. That stub rendered into a 5.2 second video
and was written to `drafts` as `status='pending'` — a publishable artifact
produced by a total upstream outage. The pipeline logged success.

The three guards that were supposed to prevent exactly this all passed, and
could only pass: `MAX_SILENT_RATIO` and `MAX_PLACEHOLDER_RATIO` are **ratios**,
and one good frame out of one scores 100% on both. The degradation was in the
input, not the processing, so no proportion of the output could reveal it.

Fixed in `7213e45`:
- retry Gemini on transient errors (503/429/500) with exponential backoff, then
  **raise** rather than fabricate; `generate_youtube_video` aborts on it
- `MIN_SCRIPT_FRAMES` (default 3) — the one check a ratio cannot express
- run the synchronous `genai` SDK via `asyncio.to_thread`
- write `channel_id`/`upload_preference` to the real columns migration 006 added,
  not only into `body` JSONB — SQL trusting the schema read every draft as
  `'manual'`, including autopilot's `'auto'` drafts

### Verified output

| Property | Value |
|---|---|
| Path | `videos/story-f49134c1-068a-4205-9b9b-35a93bd3c2d0/renders/video.mp4` |
| Format | 1080×1920, H.264 + AAC, 8.5 MB |
| Duration | 179.4s, 10 frames |
| Narration | 10/10 real ElevenLabs, 0 silent |
| Frames | 0 heuristic fallbacks; archetype-repeat retry fired twice |
| Draft row | written with `channel_id` and `upload_preference` populated |

### Also landed this session

| Commit | Change |
|---|---|
| `575ff79` | font fix verified from extracted stills + backlog |
| `04102fa` | test seam: patch `_build_frames` (the dispatcher), not a backend — mocks were routing around `FRAME_BACKEND` and firing live HTTP at Ollama |
| `4d1ebf4` | `plan_frame` returns explicit `(plan, used_fallback)`; inferring failure by `plan == heuristic_plan(...)` gave false positives whenever the 7B legitimately agreed with the heuristic |
| `574a3e8` | TTS repair: SDK v2 `text_to_speech.convert()`, `premade` voice IDs (free tier rejects library voices with 402), `Semaphore(2)` for the free-plan concurrency cap |
| `110121b` | pass already-used archetypes into each prompt — frames no longer repeat, 2/5 distinct → 5/5 |
| `07f23a4` | bar_chart slot guidance, explicit English rule + CJK retry, narration guard |
| `7213e45` | script generation guards (above) |

Suite: **93 passed**, ~5s, no network.

### Gotcha worth remembering

Do not run `pytest` while an end-to-end run is in flight. The DB tests truncate
tables; doing this deleted the seeded story mid-render and surfaced as a
`ForeignKeyViolation` on the draft insert that looked like a persistence bug in
the pool. It was not — commits work fine.

### Open items, ranked

1. **Frame pacing.** All 10 frames blew the 12s soft ceiling (13.4–23.5s each).
   Gemini writes one long paragraph per scene, so each composition sits static
   for ~18s. Constrain the script prompt to shorter beats (cheaper, addresses
   the cause) or split long narration into multiple frames at compile time.
2. **YouTube upload dry-run.** The OAuth path has still never executed. This is
   the last unproven stage.
3. **Thumbnails** are generated at publish time only (`publish_youtube_draft`
   falls back to `_generate_thumbnail`). Works, but never exercised.
4. **Repo hygiene.** `fix_db.py`, `fix_db2.py`, `update_db.py`, `test_run.py`,
   `mock_publish.py`, `seed_mock_story.py` are one-off scratch at the worker
   root and are now tracked.

---

## Session Handoff — 2026-08-03

### Headline

Two things happened: a 3D video capability was designed and planned end to end
(spec + implementation plan, **no code written**), and the GUI got a working
generation page with real pipeline progress (**shipped and verified**).

The single most useful discovery is unrelated to either: **the worker could not
start on this machine at all**, and had not been able to. Every previous
end-to-end run went through a script, never the served app.

### What shipped — `1967902`

`/films` in the GUI: pick a story, choose Short or Story Film, watch the run
advance through `script → narration → shots → render → done`.

| Change | Why |
|---|---|
| `worker/run_worker.py` | **The blocker.** See below |
| `supabase/migrations/007_jobs.sql` | `jobs` table. Applied to local `fce` |
| `worker/app/jobs.py` | Stage records. `STAGES` order is what the GUI draws |
| `POST /youtube/jobs`, `GET /youtube/jobs/{id}` | Async start + polling |
| `generate_youtube_video(backend=, job_id=)` | Both optional, so no existing caller or test changed |
| `_build_frames(board, video_dir, backend=)` | Per-request backend; `FRAME_BACKEND` is now only the default |
| `gui/src/app/films/page.tsx`, `components/FilmProgress.tsx` | The page and its progress bar |

Verified with a real run, not just a build: reached `done` in ~120s and
produced a 1080×1920 H.264+AAC draft. Suite **105 passed** (93 before + 12 new).

### The worker would not start on Windows

`uvicorn app.main:app` dies during lifespan startup:

```
Psycopg cannot use the 'ProactorEventLoop' to run in async mode
psycopg_pool.PoolTimeout: pool initialization incomplete after 30.0 sec
```

Setting an event loop **policy** does not fix this, and neither does setting it
inside `app/main.py`. Since 0.36, uvicorn passes an explicit `loop_factory` to
`asyncio.run()`, and an explicit factory overrides any policy; uvicorn also
creates the loop *before* importing the application module. The only thing that
works is calling `asyncio.run()` yourself with a selector loop and telling
uvicorn not to supply a factory (`loop="none"`). That is `worker/run_worker.py`.

**Always start the worker with `..\.venv\Scripts\python.exe run_worker.py`.**
Plain `uvicorn` will never work here.

`tests/conftest.py` solves the same problem the older way, which is why the
suite passes on a machine where the server will not boot — and why this went
unnoticed for so long.

### The old progress bar was lying

`GenerateDraftButton` fills 1% per second against a guessed 100-second render
and shows success on `res.ok`. On a run that aborted at 48s it would sit near
48% and then report "Sent to Drafts!". The new page reads real stages, which is
how the Ollama outage below was caught at all. **`GenerateDraftButton` still
has the simulated bar** — it was left alone deliberately so a working path
stayed working, but it is now the odd one out.

### Guards fired correctly, twice

First run aborted: Ollama was not running, all 8 frames fell back to heuristic,
`MAX_PLACEHOLDER_RATIO` refused it. Started Ollama (`qwen2.5:7b`), reran, green.
Worth noting the local model is **not** started automatically by anything.

### The 3D work — designed, not built

- Spec: `docs/superpowers/specs/2026-08-03-lowpoly-3d-films-design.md`
- Plan: `docs/superpowers/plans/2026-08-03-lowpoly-3d-films.md` (16 tasks, TDD)

Reference was a 92s 1080p low-poly Hobbit/Bag End film: a persistent set shot
from many angles, flat-shaded untextured geometry, day→night lighting, bloom,
burned-in subtitles, kinetic serif type.

Decisions taken with the owner:

| Decision | Choice |
|---|---|
| Scope | Phase 1 narrative landscape films; portrait Shorts primitives are Phase 2, separate spec |
| Characters | **None in v1** — every asset then reduces to code-generated primitives, no Blender, no rigs |
| Scene model | **Cloud.** Amends the local/cloud table for this backend only; render stays local |
| What the model emits | **JavaScript against a curated DSL**, not a declarative node schema — composition reaches the reference, a hand-written type list cannot |
| Mitigation | Headless render gate: sandbox execution, pixel probes at 3 timestamps, cross-frame distinctness, `MIN_VERIFIED_FRAMES` absolute floor, retry-then-raise |

Why the frame contract absorbs this cheaply: `storyboard.py` wires each frame in
as a sub-composition via `data-composition-src` and has no opinion about the
file's contents, so a 3D frame is a third producer of the same artifact. A
persistent set needs no change to the composition unit — every frame imports the
same `world.js` and places a different camera.

**`FRAME_BACKEND=three` does not exist yet.** The GUI's Story Film toggle maps
to it and will fail; the page warns in amber when it is selected.

### Start here next session

1. **Task 1 of the plan — the Three.js determinism spike.** A cube making one
   revolution, rendered, then four stills extracted. If they differ, the
   approach holds. If they are identical the timeline is not driving the scene;
   if they are black WebGL is not compositing. Those are different problems and
   the spike is shaped to tell them apart. **Nothing else in the plan should
   start until this records a verdict** — a failure invalidates both the DSL
   and the gate.
2. Then Tasks 2–11 in order (DSL → shell → probes → gate → authoring →
   orchestrator → wiring).
3. Task 15's shot inspector was deferred with the rest of the 3D work; the
   `/films` page has no inspector yet.

### Still open from before

Unchanged: YouTube **upload has still never executed** — the OAuth path remains
the only completely unproven stage. Frame pacing still blows the 12s soft
ceiling. Worker-root scratch files are still tracked.

### Gotcha, repeated the hard way

Running `pytest` **after** a completed end-to-end run still truncates `stories`
and `drafts`. It cost the verified draft row from this session's green run — the
mp4 survived on disk, the row did not. Re-seed with
`..\.venv\Scripts\python.exe seed_mock_story.py`. The existing note said "not
during a run"; the accurate rule is "not against the `fce` database at all when
you care about its contents".

---

## Session Handoff — 2026-08-03 (session 2: the Three.js spike)

### Headline

**Task 1 of the 3D plan is done and the verdict is PASS.** Three.js renders
deterministically under HyperFrames' paused-timeline seek, so the DSL and the
gate are both viable and Tasks 2–16 are unblocked.

It failed on the first attempt, and that failure is the useful part: the render
**exited 0 and produced a valid 4.0s MP4 with no cube in it**. Same shape as
every guard bug in this repo — a broken run that passes every checkpoint.

Shipped as `4ebbc0b`. Verdict recorded in
`docs/superpowers/plans/2026-08-03-spike-result.md`.

### The evidence

Six frames across one 90° sector of the cube's 2π spin (0°, 15°, 30°, 45°, 60°,
75°): six distinct MD5s and a visibly monotonic turn. Two independent renders
produced **byte-identical frames** at all six points — determinism proven, not
assumed. Post-fix render health: timelines ready in 633ms, zero correctness
warnings, 283.1 KB / 4.0s, 9.0s wall clock (the broken run took 98s and made
11.2 KB).

Render browser has **hardware WebGL** (ANGLE / NVIDIA RTX 3070 / D3D11), so the
"WebGL photographs black" risk the plan hedged against is off the table.

### Four corrections the plan must absorb

| # | Finding | Affects |
|---|---|---|
| 1 | Sub-composition scripts execute as **classic scripts** — `type="module"` is dropped, so `import` in a frame is a parse-time SyntaxError that silently kills the whole script body | **Task 2 is stale.** It vendors `three.module.js`; must be `three.min.js`, UMD **r160.1** — the last non-ESM release |
| 2 | Asset paths must be project-root-relative (`assets/three.min.js`). `../` fails lint; lint also requires the three script **per file** | Task 4 shell — every generated frame carries its own `<script src>`, so frames stay self-contained |
| 3 | `check`'s `sweep_static` is a **false positive** for pure-WebGL frames — it fingerprints DOM geometry, which a canvas never changes | Task 7 gate must judge motion from canvas pixels only. Do not add a `check`-based motion assertion |
| 4 | The plan's own probe sampling (frames 0/30/60/90 of a 2π spin) lands exactly on the cube's 4-fold symmetry points, where a working and a frozen render are pixel-identical | Task 6/7 probe timestamps must not be harmonics of the motion they measure. Prefer 0.13 / 0.41 / 0.87 over evenly spaced |

Correction 4 is the one to internalise. The plan's verification step was blind to
the exact thing it existed to measure, and the first reading of this spike was a
false FAIL because of it. `MIN_SCRIPT_FRAMES` all over again.

### How the root cause was actually found

The render log only said `sub_timeline_readiness_timeout`. What gave the answer
in one line was:

```powershell
npx hyperframes check --json
# page_error: "Cannot use import statement outside a module"
```

**Reach for `check --json` first on any render that succeeds but looks wrong.**
It reports console errors and failed network requests that the render log does
not. Note its output is preceded by a non-JSON banner line, so slice from the
first `{` before `ConvertFrom-Json`.

### Start here next session

1. **Patch Task 2's vendoring instruction** in
   `docs/superpowers/plans/2026-08-03-lowpoly-3d-films.md` — as written it
   reintroduces correction 1 verbatim. This was offered and not yet done.
2. Then Task 2 (vendor Three.js + build the primitives DSL) and on through
   Tasks 3–11 in order.
3. Corrections 3 and 4 land in Tasks 6/7; re-read the spike result before
   writing the gate.

### Unchanged

`FRAME_BACKEND=three` still does not exist — the Story Film toggle still fails
and still warns in amber. Upload has still never executed. No tests were run
this session (nothing in `worker/` was touched), so the suite stands at the 105
from the previous session.
