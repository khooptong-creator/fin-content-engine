# Per-Channel Configuration — Design

**Date:** 2026-08-05
**Status:** Approved, awaiting implementation plan
**Scope:** Per-channel script generation config. Uploads are manual and out of scope.

## Problem

The engine assumes one YouTube channel. Two are now needed: a finance channel and
a kids channel, published to separate accounts.

Uploads are performed **manually** by the owner. This spec therefore covers only
what determines the *generated output*, not publishing.

The blocker:

`youtube.py:258` `_generate_script_for_story()` accepts `channel_id` and never
reads it. The script comes from whichever `voice_profiles` entry is globally
active, so the two channels cannot be worked on concurrently. Switching brands
means flipping a global setting in the GUI, and nothing catches a story generated
under the wrong one.

A second issue: the compliance block in the script system prompt is hardcoded
inline. It is correct, and it must keep applying, but it currently sits in a
string literal alongside per-channel content with no guarantee it survives a
refactor or a config edit.

`channel_id` is already threaded from `routes.py:72` through
`generate_youtube_video` to `_record_youtube_draft`, which stores it in the draft
body. The plumbing exists. Only the resolution step is missing.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | Channels are a fixed pair in the `config` table, not a new table | Two channels. A `channels` table plus CRUD buys generality nothing needs. The `config` table is already GUI-editable. |
| 2 | Resolution returns a validated frozen object, not a raw dict | Matches `settings.py`, which validates env into a typed object. Puts the guard in one testable place instead of several call sites. |
| 3 | Fail loud on any missing channel config | The cost of guessing is a toddler script generated in the finance voice, or finance content in a toddler voice. Consistent with `MIN_SCRIPT_FRAMES` and with script generation raising rather than stubbing. |
| 4 | Historical drafts keep their stored `channel_id` verbatim | Existing rows carry `"default"`. Rewriting them to `finance` would fabricate a fact about what was published. They display as *unassigned*. |
| 5 | The `activeProfileId` code path is deleted, not left as a fallback | A retained fallback is a silent wrong-brand path. Values are copied forward first, so no data is lost. |
| 6 | Uploads stay manual; no per-channel OAuth | Owner uploads to each account by hand. Removes per-channel token files, the `made_for_kids` API field, and the whole credential surface from this spec. |
| 7 | **Compliance rules and the base blocklist are code constants, not config** | They must always hold. In config they are one careless GUI edit away from being removed, and that edit leaves no trace. In code they are covered by a test. Channels may *add* terms, never remove them. |

## Compliance floor

Defined in code, applied to every channel unconditionally:

```python
BASE_COMPLIANCE_RULES = (
    "Do not provide financial advice. "
    "Do not recommend buying or selling any specific security or product. "
    "Explain what happened and why it is interesting, never what the viewer should do."
)

BASE_BLOCKLIST = ("buy", "sell", "accumulate", "target price", "multibagger", "sure shot")
```

A channel's effective blocklist is `BASE_BLOCKLIST | channel.extra_blocklist`.
Union, so removal is impossible by construction rather than by validation. There
is no config path, GUI control, or environment variable that disables either
constant.

This applies to the kids channel too. It costs nothing there and means no channel
can ever be created that lacks the floor.

## Data model

New `channels` key in the `config` table:

```json
{
  "finance": {
    "display_name": "Finance",
    "voice_key": "adult_male",
    "script_prompt": "You are a casual, humorous, and informative adult male...",
    "extra_blocklist": []
  },
  "kids": {
    "display_name": "Kids",
    "voice_key": "baby",
    "script_prompt": "You are a humorous, highly intelligent baby...",
    "extra_blocklist": []
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
| `worker/app/channels.py` (new) | `Channel` frozen dataclass, `async resolve(channel_id) -> Channel`, `ChannelConfigError`, `BASE_COMPLIANCE_RULES`, `BASE_BLOCKLIST`. The only interpreter of channel config. | `db.get_config`, `VOICE_MAP` |
| `_generate_script_for_story(story, channel)` | Uses `channel.script_prompt` and `channel.effective_blocklist`. Compliance rules come from the constant. `activeProfileId` lookup removed. | `channels.Channel` |
| `routes.py` | `channel_id` loses its `"default"` value; becomes required. Maps `ChannelConfigError` to HTTP 400. | `channels.resolve` |
| `gui/src/app/settings` | Channel selector; prompt and extra-blocklist fields edit the selected channel. Base blocklist shown read-only. | `/config/channels` |

The config API needs no change: `routes.py:277` already exposes a generic
`GET/PUT /config/{key}`, so `/config/channels` works as soon as the key exists.

`Channel` validates at construction: all fields present and non-empty, and
`voice_key` in `VOICE_MAP`. A partially populated `Channel` cannot be built.

## Data flow

```
POST /youtube/generate {story_id, channel_id}
  -> channels.resolve(channel_id) -> Channel     (fails here or not at all)
  -> _generate_script_for_story(story, channel)  (channel prompt + base rules + union blocklist)
  -> frames -> render -> final MP4 on disk
  -> _record_youtube_draft(channel_id)
  -> owner uploads manually
```

The `Channel` is resolved once at the top of `generate_youtube_video` and passed
down. Nothing downstream re-reads config.

## Error handling

No fallbacks in this path. `ChannelConfigError` is raised for: unknown
`channel_id`, absent `channels` config key, any missing or empty field, and a
`voice_key` not in `VOICE_MAP`. The message names the offending field.
`routes.py` returns 400 and no job is created.

## Testing

Tests must not touch the network; patch `_build_frames`, not a backend.

| Test | Asserts |
|---|---|
| `Channel` construction | Rejects each missing or empty field and an unknown `voice_key`. Pure unit, no DB. |
| `resolve()` | With `db.get_config` patched: returns the right channel, raises on unknown id. |
| Generate without `channel_id` | Request rejected, no job created. |
| **Compliance floor** | A channel whose `extra_blocklist` omits base terms still yields all base terms in `effective_blocklist`. A channel cannot suppress a base term. |
| **Compliance in prompt** | The generated system instruction contains `BASE_COMPLIANCE_RULES` verbatim for every channel, including kids. |
| Two channels | Each resolves to a different prompt and voice key. |

## Migration

1. Read the currently active `voice_profiles` profile.
2. Write it into `channels.finance`, preserving the prompt. Terms already in
   `BASE_BLOCKLIST` are not duplicated into `extra_blocklist`.
3. Add `stories.channel_id`.
4. Delete the `activeProfileId` read path from `_generate_script_for_story`.

Step 4 removes a **code path**, not data. The `voice_profiles` config row stays
in the database untouched after its values are copied forward. Existing draft
rows are not modified.

## Manual upload, and what moves to the owner

Because uploads are manual, the `selfDeclaredMadeForKids` designation is no
longer set by this system. **It becomes the owner's responsibility to mark kids
videos as "Made for kids" in YouTube Studio at upload time.** This is a COPPA
obligation, not a preference.

`youtube.py` retains a `/youtube/publish` path with `selfDeclaredMadeForKids`
hardcoded `False`, reachable from a button on the drafts page. It is now dormant
but not disabled. Recommendation, small and outside this spec's core: gate it
behind `FCE_PUBLISH_ENABLED`, defaulting off, so an unused path cannot publish a
kids video under a false designation by accident.

## Out of scope

Per-channel OAuth and automated upload. Kids topic backlog, kids rendering
approach, 3D animation research. The kids channel cannot produce video until its
rendering path is decided in a separate spec.
