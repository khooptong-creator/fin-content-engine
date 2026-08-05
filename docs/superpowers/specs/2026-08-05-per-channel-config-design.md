# Per-Channel Configuration — Design

**Date:** 2026-08-05
**Status:** Approved, awaiting implementation plan
**Scope:** Per-channel script generation config, plus the upload metadata a manual
upload needs. Automated publishing is removed.

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
| 8 | The publish path is removed, not gated | Uploads are manual. A dormant button that hardcodes `selfDeclaredMadeForKids: False` is a live hazard, and a disabled-by-default flag is a compatibility layer around dead code. Delete it. |
| 9 | Upload metadata is delivered two ways | The drafts page is where the owner works, so copy buttons belong there. The text file means metadata survives a database reset and travels with the MP4. |



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

## Upload metadata

Every generated video must arrive with the text needed to upload it by hand.

The generator already produces this. `_generate_script_for_story` instructs the
model to emit YAML frontmatter containing `title` and a *"highly detailed,
SEO-optimized description"* (`youtube.py:306`), and `_parse_frontmatter`
(`youtube.py:1063`) extracts both. The defect is the call site: extraction
happens only inside the publish path at `youtube.py:1113`, so with publishing
removed the description would be generated and then discarded.

The fix moves extraction earlier and persists the result:

1. After the script is generated, parse `title` and `description` from
   frontmatter.
2. Store both in the draft body alongside `channel_id`.
3. Write `upload.txt` into the task directory, next to the final MP4, containing
   the title and description as plain text ready to paste.
4. Show both on the drafts page with copy buttons.

If `description` is absent or empty, the draft records the failure rather than
substituting the title. A silent title-as-description fallback exists today at
`youtube.py:1113` (`description = frontmatter.get("description") or title`) and
is removed with the rest of that path. An empty description is a generation
problem worth seeing, not worth papering over.

**Compliance applies to the description.** It is produced by the same LLM call,
under the same system instruction, so `BASE_COMPLIANCE_RULES` and the effective
blocklist already govern it. The instruction is made explicit that the forbidden
terms cover frontmatter as well as narration, and a test asserts it.

A post-generation blocklist scan of the description is deliberately **not**
added. The script has no such scan, so adding one for the description alone
would be inconsistent, and naive substring matching produces false positives on
ordinary words (`buyback`, `sell-off`). If a scan is wanted later it should cover
both fields, match on word boundaries, and be specified in its own change.

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
| `_parse_frontmatter` | Unchanged, but called from `generate_youtube_video` instead of the publish path. Its `or title` fallback is dropped. | — |
| `upload.txt` writer (new, in `youtube.py`) | Writes title and description into the task directory beside the MP4. | `_parse_frontmatter` |
| `gui/src/app/drafts` | Publish button removed. Title and description displayed with copy buttons. | `/drafts` |
| **Removed:** `routes.py:/youtube/publish`, `_upload_to_youtube`, `_get_youtube_credentials` | Dead once uploads are manual. | — |

The config API needs no change: `routes.py:277` already exposes a generic
`GET/PUT /config/{key}`, so `/config/channels` works as soon as the key exists.

`Channel` validates at construction: all fields present and non-empty, and
`voice_key` in `VOICE_MAP`. A partially populated `Channel` cannot be built.

## Data flow

```
POST /youtube/generate {story_id, channel_id}
  -> channels.resolve(channel_id) -> Channel     (fails here or not at all)
  -> _generate_script_for_story(story, channel)  (channel prompt + base rules + union blocklist)
  -> _parse_frontmatter(script) -> title, description
  -> frames -> render -> final MP4 on disk
  -> write upload.txt beside the MP4
  -> _record_youtube_draft(channel_id, title, description)
  -> owner uploads manually, pasting title + description, ticking Made for kids
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
| **Compliance in prompt** | The generated system instruction contains `BASE_COMPLIANCE_RULES` verbatim for every channel, including kids, and states that forbidden terms cover frontmatter as well as narration. |
| Two channels | Each resolves to a different prompt and voice key. |
| Metadata extraction | `title` and `description` are parsed from frontmatter and stored on the draft. |
| Empty description | A script whose frontmatter has no description records the failure. It does not fall back to the title. |
| `upload.txt` | Written into the task directory, contains the title and description. |

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
longer set by this system. **It becomes the owner's responsibility to tick "Made
for kids" in YouTube Studio when uploading toddler content.** This is a COPPA
obligation, not a preference. `upload.txt` carries a reminder line for the kids
channel.

The publish path is deleted: the drafts-page button, the `/youtube/publish`
route, `_upload_to_youtube`, and `_get_youtube_credentials` all go, along with
the `google-auth` upload imports they pull in.

`GET /youtube/analytics` is left in place. It reads `published_ids` from existing
draft rows, which is data already written, but it will show nothing new because
nothing records a video id any more. Whether to feed it manually entered ids, or
remove it, is a separate decision and not part of this spec.

## Out of scope

Per-channel OAuth and automated upload. A post-generation blocklist scan. Kids
topic backlog, kids rendering approach, 3D animation research. The kids channel
cannot produce video until its rendering path is decided in a separate spec.
