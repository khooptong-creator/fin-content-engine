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
