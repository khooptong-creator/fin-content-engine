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

The owner does not track the installed roster. **On any non-trivial task, before the
first edit, state in one line which skill / agent / MCP you're reaching for — or that
none fits.** Then proceed; it's a recommendation, not a permission request. If the
right tool is disabled below, say so and quote the re-enable line instead of working
around it silently.

Enabled here and worth reaching for:

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

Deliberately **off for this repo** (`.claude/settings.local.json`), to cut ~7k tokens
of fixed overhead from every request: `ecc`, `vercel`, `gitlab`, `resend`,
`code-modernization`, `pr-review-toolkit`, `plugin-dev`, `mcp-server-dev`,
`mcp-tunnels`, `agent-sdk-dev`, `skill-creator`, `project-artifact`,
`frontend-design`, `claude-code-setup`, `ralph-loop`, `cwc-makers`,
`math-olympiad`, `playground`; plus the claude.ai connectors (Gmail/Calendar/Drive)
via `disableClaudeAiConnectors`. `LAMKA_SESSION_LITE=1` trims the SessionStart
injection from ~30 KB to ~1.7 KB — the vault catalog and master-router body become
on-demand (`Skill(lamka-workspace)`), the toolshed digest still loads.

Re-enable one for a session: flip its entry to `true` in `.claude/settings.local.json`.

## Commands
```powershell
cd worker; ..\.venv\Scripts\python.exe -m pytest tests -q
cd worker; ..\.venv\Scripts\python.exe render_local.py --storyboard ..\videos\<board>
```
DB tests error without local Postgres — expected.
