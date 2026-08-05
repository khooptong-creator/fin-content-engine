# Per-Channel Configuration — Design

**Date:** 2026-08-05
**Status:** Approved, awaiting implementation plan
**Scope:** The channel mechanism only. Kids topic backlog and kids rendering are separate specs.

## Problem

The engine assumes one YouTube channel. Two accounts are now needed: a finance
channel on the owner's personal account, and a kids channel on a second account.

Three concrete blockers exist today:

| # | Location | Problem |
|---|---|---|
| 1 | `youtube.py:45` `_get_youtube_credentials()` | Loads a single token file from `settings.youtube_token_path`. No channel argument. |
| 2 | `youtube.py:258` `_generate_script_for_story()` | Accepts `channel_id` and never reads it. The script comes from whichever `voice_profiles` entry is globally active, so two channels cannot run concurrently. |
| 3 | `youtube.py:896` | `"selfDeclaredMadeForKids": False` is hardcoded. A kids channel publishing under this flag is a COPPA misdeclaration on every upload. |

A fourth, softer issue: the compliance block in the script system prompt is
hardcoded finance language (`"Do not provide financial advice"`, a blocklist of
`buy`/`sell`/`multibagger`) applied to every script regardless of channel.

`channel_id` is already threaded from `routes.py:72` through
`generate_youtube_video` to `_record_youtube_draft`, which stores it in the draft
body. The plumbing exists. Only the resolution step is missing.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | Channels are a fixed pair in the `config` table, not a new table | Two channels. A `channels` table plus CRUD endpoints buys generality nothing currently needs. The `config` table is already GUI-editable. |
| 2 | Resolution returns a validated frozen object, not a raw dict | Matches `settings.py`, which validates env into a typed object rather than reading vars ad hoc. Puts the guard in one testable place instead of four call sites. |
| 3 | Fail loud on any missing channel config | The cost of guessing is a toddler video on the finance account, or a kids video misdeclared under COPPA. Both are worse than a failed job. Consistent with `MIN_SCRIPT_FRAMES` and with script generation raising rather than stubbing. |
| 4 | Historical drafts keep their stored `channel_id` verbatim | Existing rows carry `"default"`. Rewriting them to `finance` would fabricate a fact about what was published. They display as *unassigned*. |
| 5 | The `activeProfileId` code path is deleted, not left as a fallback | A retained fallback is a silent wrong-brand path. Values are copied forward first, so no data is lost. |

## Data model

New `channels` key in the `config` table:

```json
{
  "finance": {
    "display_name": "Finance",
    "youtube_token_file": "token.finance.json",
    "voice_key": "adult_male",
    "script_prompt": "...",
    "blocklist": ["buy", "sell", "accumulate", "target price", "multibagger", "sure shot"],
    "made_for_kids": false
  },
  "kids": {
    "display_name": "Kids",
    "youtube_token_file": "token.kids.json",
    "voice_key": "baby",
    "script_prompt": "...",
    "blocklist": [],
    "made_for_kids": true
  }
}
```

Migration adds `stories.channel_id TEXT` (nullable). Nullable because rows
already exist without one. A story with a null channel is not generatable; it is
not silently assigned.

`voice_key` must be a key of `VOICE_MAP` in `youtube.py`. Note that
`VOICE_MAP["baby"]` currently points at the Jessica voice because ElevenLabs has
no premade child voice. That substitution is a known limitation of the kids
channel, recorded here so it is not rediscovered later.

## Components

| Unit | Responsibility | Depends on |
|---|---|---|
| `worker/app/channels.py` (new) | `Channel` frozen dataclass, `async resolve(channel_id) -> Channel`, `ChannelConfigError`. The only interpreter of channel config. | `db.get_config`, `VOICE_MAP` |
| `_get_youtube_credentials(scopes, channel)` | Reads `channel.youtube_token_file` under `settings.youtube_token_dir`. | `channels.Channel` |
| `_generate_script_for_story(story, channel)` | Uses `channel.script_prompt` and `channel.blocklist`. `activeProfileId` lookup removed. | `channels.Channel` |
| Upload call (`youtube.py` ~:896) | Sets `selfDeclaredMadeForKids` from `channel.made_for_kids`. | `channels.Channel` |
| `routes.py` | `channel_id` loses its `"default"` value; becomes required. Maps `ChannelConfigError` to HTTP 400. | `channels.resolve` |
| `settings.py` | `youtube_token_path` becomes `youtube_token_dir`. | — |
| `gui/src/app/settings` | Channel selector; prompt and blocklist fields edit the selected channel. | `/config/channels` |

The config API needs no change: `routes.py:277` already exposes a generic
`GET/PUT /config/{key}`, so `/config/channels` works as soon as the key exists.

`Channel` validates at construction: all fields present and non-empty,
`voice_key` in `VOICE_MAP`, token file exists on disk. A partially populated
`Channel` cannot be constructed.

## Data flow

```
POST /youtube/generate {story_id, channel_id}
  -> channels.resolve(channel_id) -> Channel        (fails here or not at all)
  -> _generate_script_for_story(story, channel)     (channel prompt + blocklist)
  -> frames -> render
  -> upload(channel)                                (channel token + made_for_kids)
  -> _record_youtube_draft(channel_id)
```

The `Channel` is resolved once at the top of `generate_youtube_video` and passed
down. Nothing downstream re-reads config.

## Error handling

No fallbacks in this path. `ChannelConfigError` is raised for: unknown
`channel_id`, absent `channels` config key, any missing or empty field, a
`voice_key` not in `VOICE_MAP`, and a token file that does not exist. The message
names the offending field. `routes.py` returns 400 and no job is created.

## Testing

Tests must not touch the network; patch `_build_frames`, not a backend.

| Test | Asserts |
|---|---|
| `Channel` construction | Rejects each missing or empty field, unknown `voice_key`, absent token file. Pure unit, no DB. |
| `resolve()` | With `db.get_config` patched: returns the right channel, raises on unknown id. |
| Generate without `channel_id` | Request rejected, no job created. |
| Upload payload | `selfDeclaredMadeForKids` equals the channel's flag. This is the COPPA regression guard. |
| Two channels | Each resolves to a different token file and prompt. |

## Migration

1. Read the currently active `voice_profiles` profile.
2. Write it into `channels.finance`, preserving prompt and blocklist.
3. Add `stories.channel_id`.
4. Delete the `activeProfileId` read path from `_generate_script_for_story`.

Step 4 removes a **code path**, not data. The `voice_profiles` config row stays
in the database untouched after its values are copied forward. Existing draft
rows are not modified.

## Operational prerequisite

The OAuth flow must be run once per Google account, producing
`token.finance.json` and `token.kids.json` in `youtube_token_dir`. The kids token
is only needed when that channel goes live.

## Out of scope

Kids topic backlog, kids rendering approach, 3D animation research. The kids
channel cannot publish until its rendering path is decided in a separate spec.
