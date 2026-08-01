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
- Never publish a degraded video. Three independent guards in `youtube.py`, all
  needed because each failure produces something that renders and validates
  cleanly: `MIN_SCRIPT_FRAMES` (a stubbed script scores 100% on every ratio),
  `MAX_SILENT_RATIO`, `MAX_PLACEHOLDER_RATIO`.
- Never fabricate a script when the LLM fails. It becomes a publishable draft.
- Tests must not touch the network. Patch `_build_frames`, not a backend.
- Don't run `pytest` while an end-to-end run is in flight — the DB tests
  truncate tables and will delete the story mid-render.
- Commit source only. Rendered `mp4`/`mp3`/`wav`, `renders/`, `assets/voice/`
  are gitignored.
- Assistant commits and pushes; never leave that to the user.

## Tooling — say what you're using, before you use it

The rule and the workspace-wide plugin/overhead trim live in `~/.claude/CLAUDE.md`
("Tooling: name it before you use it" + "Session overhead is trimmed on purpose").
**One line naming the skill / agent / MCP, before the first edit, every non-trivial
task.** What follows is only this repo's mapping.

| Need | Reach for |
|---|---|
| Any bug, test failure, unexplained render output | `superpowers:systematic-debugging` |
| New pipeline stage / feature, before writing code | `superpowers:brainstorming`, then `writing-plans` |
| Guard or ratio logic — the class of bug that ships a degraded video | `superpowers:test-driven-development` |
| Reviewing a change before commit | `/code-review`, `/security-review` |
| Commit + push (assistant always does this) | `commit-commands:commit` |
| Editing this file or the memory files | `claude-md-management`, `update-config` |
| "Where does X live", cross-project facts, recording a lesson | `lamka-workspace`, `mcp__vault-graph__*` |
| Video/animation composition work | `hyperframes*` skills |
| A tool you suspect exists but isn't listed | toolshed digest → `[[Toolshed - Registry]]` → `find-skills` |

Off **here specifically**, on top of the global trim: `vercel` and `frontend-design`
— this repo renders MP4s, it ships no web UI. Re-enable either by flipping it to
`true` in `.claude/settings.local.json`.

## Commands
```powershell
cd worker; ..\.venv\Scripts\python.exe -m pytest tests -q
cd worker; ..\.venv\Scripts\python.exe render_local.py --storyboard ..\videos\<board>
```
DB tests error without local Postgres — expected.
