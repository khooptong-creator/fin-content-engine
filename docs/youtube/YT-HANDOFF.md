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
