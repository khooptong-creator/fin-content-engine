# Fin Content Engine

Automated finance/kids YouTube pipeline: news → story → script → narration →
frames → rendered MP4 → upload. Worker is Python/FastAPI in `worker/`.

## Answering style
Short and to the point. Lead with the outcome. ≤6 lines of prose, then use a
table. No preamble, no re-summarising the question, no unasked-for option lists.
Go long only when asked to explain.

## Local vs cloud (deliberate split)

Local is the default because it removes quota and billing as failure modes.
Cloud is used only where local can't reach the quality bar.

| Stage | Runs | Why |
|---|---|---|
| Frame design | **Local** — Ollama `qwen2.5:7b` on the RTX 3070 | Free, no rate limit. Model picks an archetype + fills slots (~dozens of tokens), never writes HTML |
| Frame HTML | **Local** — `archetypes.py` templates | Pre-validated templates can't emit an invalid composition |
| Render | **Local** — HyperFrames + ffmpeg | No render credits |
| Postgres | **Local / VPS** | Supabase free tier pauses |
| Embeddings | **Local** — gte-small | Supabase hosted OOM-killed |
| Narration | **Cloud** — ElevenLabs | No local TTS at this quality |
| Story/script text | **Cloud** — Gemini/Haiku | Long-form reasoning beyond a 7B |
| Upload | **Cloud** — YouTube Data API | — |

`FRAME_BACKEND` (`youtube.py`) selects the frame path: `local` (default) or
`gemini`. Keys live in `worker/.env` (gitignored).

## Rules
- Ollama at `127.0.0.1:11434`, never `localhost` — Windows resolves ::1 first and
  Ollama binds IPv4 only.
- Frame generation is sequential: one GPU serves one request at a time.
- Never publish a video that is mostly placeholder frames — guard in
  `youtube.py` aborts above a 0.5 ratio.
- Tests must not touch the network. Patch `_build_frames`, not a backend.
- Commit source only. Rendered `mp4`/`mp3`/`wav`, `renders/`, `assets/voice/`
  are gitignored.
- Assistant commits and pushes; never leave that to the user.

## Commands
```powershell
cd worker; ..\.venv\Scripts\python.exe -m pytest tests -q
cd worker; ..\.venv\Scripts\python.exe render_local.py --storyboard ..\videos\<board>
```
DB tests error without local Postgres — expected.
