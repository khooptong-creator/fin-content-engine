# Per-Channel Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let one engine generate content for two YouTube channels with different voices and prompts, and ship every rendered video with the title and SEO description needed to upload it by hand.

**Architecture:** A new `worker/app/channels.py` resolves a channel id into a validated frozen `Channel` object once per generation run, and every consumer takes that object instead of a bare string. Compliance rules and the base blocklist live in that module as code constants that a channel can extend but never suppress. The automated publish path is deleted; the frontmatter title and description it used to read are instead extracted at generation time, persisted on the draft, and written to `upload.txt` beside the render.

**Tech Stack:** Python 3.11, FastAPI, psycopg (async pool), pytest + pytest-asyncio, Next.js 15 + React for the GUI, Postgres.

**Spec:** `docs/superpowers/specs/2026-08-05-per-channel-config-design.md`

## Global Constraints

- **Fail loud, no fallbacks.** Missing channel config raises. Never substitute a default channel, a default voice, or a title-for-description.
- **Compliance is a code constant.** `BASE_COMPLIANCE_RULES` and `BASE_BLOCKLIST` live in `channels.py`. A channel's effective blocklist is a union with its `extra_blocklist`. There is no config, env var, or GUI control that removes a base term.
- **Tests must not touch the network.** Patch `_build_frames`, not a backend. Patch `db.get_config`, never require a live Postgres.
- **Never modify existing draft rows.** Historical drafts carry `channel_id: "default"` and keep it.
- **Do not run `pytest` while an end-to-end render is in flight.** DB tests truncate tables.
- **Shell is PowerShell 7.** Commands below are PowerShell. The worker venv is `..\.venv\Scripts\python.exe` relative to `worker/`.
- **Commits carry no `Co-Authored-By` trailer and no "Generated with Claude Code" line.**
- **Naming note:** the spec calls the frontmatter parser `_parse_frontmatter`. Its real name in the codebase is `_parse_storyboard_frontmatter` (`worker/app/youtube.py:1060`). Use the real name.

---

## File Structure

| File | Responsibility |
|---|---|
| `worker/app/channels.py` (new) | Channel config: constants, `Channel`, `resolve()`, `ChannelConfigError`. The only interpreter of the `channels` config key. |
| `worker/tests/test_channels.py` (new) | Unit tests for the above. No DB, no network. |
| `worker/app/youtube.py` (modify) | Consumes `Channel`. Loses the publish path. Gains metadata extraction and `upload.txt`. |
| `worker/app/routes.py` (modify) | `channel_id` becomes required. `ChannelConfigError` maps to 400. Publish route removed. |
| `worker/app/db.py` (modify) | `create_manual_story` accepts a channel. Draft body carries title and description. |
| `supabase/migrations/008_story_channel.sql` (new) | Adds `stories.channel_id`. |
| `worker/scripts/seed_channels.py` (new) | One-time copy of the active voice profile into `channels.finance`. |
| `gui/src/app/settings/page.tsx` (modify) | Channel selector. Base blocklist read-only. |
| `gui/src/app/drafts/page.tsx` (modify) | Publish button removed. Title and description with copy buttons. |

---

### Task 1: Channel config module

**Files:**
- Create: `worker/app/channels.py`
- Test: `worker/tests/test_channels.py`

**Interfaces:**
- Consumes: `app.db.get_config`, `app.youtube.VOICE_MAP`
- Produces:
  - `BASE_COMPLIANCE_RULES: str`
  - `BASE_BLOCKLIST: tuple[str, ...]`
  - `class ChannelConfigError(Exception)`
  - `@dataclass(frozen=True) class Channel` with fields `id: str`, `display_name: str`, `voice_key: str`, `script_prompt: str`, `extra_blocklist: tuple[str, ...]`, and property `effective_blocklist: tuple[str, ...]`
  - `async def resolve(channel_id: str) -> Channel`

**Note on the import direction:** `VOICE_MAP` currently lives in `youtube.py`. Importing it at module scope in `channels.py` would create a cycle once `youtube.py` imports `channels`. Import it inside `_validate` instead, as the codebase already does for `db` and `genai` in `youtube.py`.

- [ ] **Step 1: Write the failing tests**

Create `worker/tests/test_channels.py`:

```python
from unittest.mock import AsyncMock, patch

import pytest

from app.channels import (
    BASE_BLOCKLIST,
    BASE_COMPLIANCE_RULES,
    Channel,
    ChannelConfigError,
    resolve,
)

VALID_CONFIG = {
    "finance": {
        "display_name": "Finance",
        "voice_key": "adult_male",
        "script_prompt": "You are a casual, humorous, informative adult male.",
        "extra_blocklist": ["guaranteed returns"],
    },
    "kids": {
        "display_name": "Kids",
        "voice_key": "baby",
        "script_prompt": "You are a humorous, highly intelligent baby.",
        "extra_blocklist": [],
    },
}


def _channel(**overrides):
    base = {
        "id": "finance",
        "display_name": "Finance",
        "voice_key": "adult_male",
        "script_prompt": "A prompt.",
        "extra_blocklist": (),
    }
    base.update(overrides)
    return Channel(**base)


def test_effective_blocklist_includes_every_base_term():
    channel = _channel(extra_blocklist=())
    for term in BASE_BLOCKLIST:
        assert term in channel.effective_blocklist


def test_extra_blocklist_is_added_not_substituted():
    channel = _channel(extra_blocklist=("guaranteed returns",))
    assert "guaranteed returns" in channel.effective_blocklist
    for term in BASE_BLOCKLIST:
        assert term in channel.effective_blocklist


def test_base_term_cannot_be_removed_by_config():
    # A channel that lists no extras, or lists a base term explicitly, still
    # yields the full base set exactly once.
    channel = _channel(extra_blocklist=("buy",))
    assert channel.effective_blocklist.count("buy") == 1
    for term in BASE_BLOCKLIST:
        assert term in channel.effective_blocklist


def test_compliance_rules_mention_no_advice():
    assert "Do not provide financial advice" in BASE_COMPLIANCE_RULES


@pytest.mark.parametrize("field", ["display_name", "voice_key", "script_prompt"])
def test_empty_required_field_is_rejected(field):
    with pytest.raises(ChannelConfigError) as exc:
        _channel(**{field: ""})
    assert field in str(exc.value)


def test_unknown_voice_key_is_rejected():
    with pytest.raises(ChannelConfigError) as exc:
        _channel(voice_key="nonexistent_voice")
    assert "nonexistent_voice" in str(exc.value)


@pytest.mark.asyncio
async def test_resolve_returns_the_requested_channel():
    with patch("app.channels.db.get_config", AsyncMock(return_value=VALID_CONFIG)):
        channel = await resolve("kids")
    assert channel.id == "kids"
    assert channel.voice_key == "baby"
    assert "baby" in channel.script_prompt.lower()


@pytest.mark.asyncio
async def test_resolve_two_channels_differ():
    with patch("app.channels.db.get_config", AsyncMock(return_value=VALID_CONFIG)):
        finance = await resolve("finance")
        kids = await resolve("kids")
    assert finance.script_prompt != kids.script_prompt
    assert finance.voice_key != kids.voice_key


@pytest.mark.asyncio
async def test_resolve_unknown_channel_raises():
    with patch("app.channels.db.get_config", AsyncMock(return_value=VALID_CONFIG)):
        with pytest.raises(ChannelConfigError) as exc:
            await resolve("does-not-exist")
    assert "does-not-exist" in str(exc.value)


@pytest.mark.asyncio
async def test_resolve_missing_config_key_raises():
    with patch("app.channels.db.get_config", AsyncMock(return_value=None)):
        with pytest.raises(ChannelConfigError):
            await resolve("finance")


@pytest.mark.asyncio
async def test_resolve_empty_channel_id_raises():
    with patch("app.channels.db.get_config", AsyncMock(return_value=VALID_CONFIG)):
        with pytest.raises(ChannelConfigError):
            await resolve("")


@pytest.mark.asyncio
async def test_resolve_missing_field_names_the_field():
    broken = {"finance": {"display_name": "Finance", "voice_key": "adult_male"}}
    with patch("app.channels.db.get_config", AsyncMock(return_value=broken)):
        with pytest.raises(ChannelConfigError) as exc:
            await resolve("finance")
    assert "script_prompt" in str(exc.value)
```

- [ ] **Step 2: Run the tests to verify they fail**

```powershell
Set-Location "F:\Content Creation Project\worker"
..\.venv\Scripts\python.exe -m pytest tests/test_channels.py -v
```

Expected: collection error, `ModuleNotFoundError: No module named 'app.channels'`.

- [ ] **Step 3: Write the implementation**

Create `worker/app/channels.py`:

```python
"""Per-channel configuration.

One engine serves more than one YouTube channel. A channel supplies the voice
and the script prompt; it does not supply the compliance rules. Those are the
constants below, and a channel can only add to the blocklist, never remove from
it, so there is no config edit or GUI control that can switch compliance off.

Config lives in the `config` table under the key `channels`. Read it through
`resolve()`, which validates once and returns a frozen object. Nothing else
should interpret the raw dict.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from app import db

log = structlog.get_logger()

CONFIG_KEY = "channels"

# Applied to every channel, unconditionally. Not configurable by design: in the
# config table this was one careless GUI edit away from removal, and the edit
# would leave no trace.
BASE_COMPLIANCE_RULES = (
    "Do not provide financial advice. "
    "Do not recommend buying or selling any specific security or product. "
    "Explain what happened and why it is interesting, never what the viewer should do."
)

BASE_BLOCKLIST: tuple[str, ...] = (
    "buy",
    "sell",
    "accumulate",
    "target price",
    "multibagger",
    "sure shot",
)

REQUIRED_FIELDS = ("display_name", "voice_key", "script_prompt")


class ChannelConfigError(Exception):
    """Channel config is absent, unknown, or incomplete. Never recovered from."""


@dataclass(frozen=True)
class Channel:
    id: str
    display_name: str
    voice_key: str
    script_prompt: str
    extra_blocklist: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        for name in REQUIRED_FIELDS + ("id",):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ChannelConfigError(
                    f"channel field '{name}' is missing or empty"
                )

        # Imported here, not at module scope: youtube.py imports this module,
        # so a top-level import would be circular.
        from app.youtube import VOICE_MAP

        if self.voice_key not in VOICE_MAP:
            raise ChannelConfigError(
                f"channel '{self.id}' has unknown voice_key '{self.voice_key}'; "
                f"known keys: {', '.join(sorted(VOICE_MAP))}"
            )

    @property
    def effective_blocklist(self) -> tuple[str, ...]:
        """Base terms plus this channel's extras, order-stable and deduplicated.

        A union, not an override. Removing a base term is not expressible.
        """
        seen: list[str] = list(BASE_BLOCKLIST)
        for term in self.extra_blocklist:
            if term not in seen:
                seen.append(term)
        return tuple(seen)


async def resolve(channel_id: str) -> Channel:
    """Load and validate one channel. Raises ChannelConfigError on any problem."""
    if not channel_id or not channel_id.strip():
        raise ChannelConfigError("channel_id is required and was empty")

    config = await db.get_config(CONFIG_KEY)
    if not config:
        raise ChannelConfigError(
            f"no '{CONFIG_KEY}' config found; run worker/scripts/seed_channels.py"
        )

    raw = config.get(channel_id)
    if raw is None:
        raise ChannelConfigError(
            f"unknown channel '{channel_id}'; configured: {', '.join(sorted(config))}"
        )

    missing = [f for f in REQUIRED_FIELDS if not raw.get(f)]
    if missing:
        raise ChannelConfigError(
            f"channel '{channel_id}' is missing required field(s): {', '.join(missing)}"
        )

    channel = Channel(
        id=channel_id,
        display_name=raw["display_name"],
        voice_key=raw["voice_key"],
        script_prompt=raw["script_prompt"],
        extra_blocklist=tuple(raw.get("extra_blocklist") or ()),
    )
    log.info("channel_resolved", channel_id=channel_id, voice_key=channel.voice_key)
    return channel
```

- [ ] **Step 4: Run the tests to verify they pass**

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_channels.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```powershell
git add worker/app/channels.py worker/tests/test_channels.py
git commit -m "Add channel config module with non-suppressible compliance floor"
```

---

### Task 2: Use the channel in script generation

**Files:**
- Modify: `worker/app/youtube.py:258-320` (`_generate_script_for_story`), and the call site at `worker/app/youtube.py:122`
- Test: `worker/tests/test_youtube_channel.py` (new)

**Interfaces:**
- Consumes: `channels.resolve`, `channels.Channel`, `channels.BASE_COMPLIANCE_RULES`
- Produces: `_generate_script_for_story(story: dict, channel: Channel) -> str`, and `generate_youtube_video` resolving the channel once at the top

- [ ] **Step 1: Write the failing tests**

Create `worker/tests/test_youtube_channel.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.channels import BASE_BLOCKLIST, BASE_COMPLIANCE_RULES, Channel

FINANCE = Channel(
    id="finance",
    display_name="Finance",
    voice_key="adult_male",
    script_prompt="You are a casual, humorous, informative adult male.",
    extra_blocklist=(),
)

KIDS = Channel(
    id="kids",
    display_name="Kids",
    voice_key="baby",
    script_prompt="You are a humorous, highly intelligent baby.",
    extra_blocklist=(),
)


def _captured_system_instruction(mock_client) -> str:
    """Pull the system_instruction out of the mocked Gemini call.

    Patch target is `google.genai.Client`, not `app.youtube.genai.Client`:
    `youtube.py` imports genai inside the function body, so there is no
    module-level attribute to patch.
    """
    kwargs = mock_client.return_value.models.generate_content.call_args.kwargs
    return kwargs["config"].system_instruction


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", [FINANCE, KIDS], ids=["finance", "kids"])
async def test_compliance_rules_present_for_every_channel(channel, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    from app import youtube

    with patch("google.genai.Client") as mock_client:
        mock_client.return_value.models.generate_content.return_value = MagicMock(
            text="---\ntitle: T\ndescription: D\n---\n\n# Scene 1\nVoiceover: A\n"
        )
        await youtube._generate_script_for_story({"headline": "H"}, channel)

    instruction = _captured_system_instruction(mock_client)
    assert BASE_COMPLIANCE_RULES in instruction


@pytest.mark.asyncio
async def test_channel_prompt_is_used(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    from app import youtube

    with patch("google.genai.Client") as mock_client:
        mock_client.return_value.models.generate_content.return_value = MagicMock(
            text="---\ntitle: T\ndescription: D\n---\n\n# Scene 1\nVoiceover: A\n"
        )
        await youtube._generate_script_for_story({"headline": "H"}, KIDS)

    instruction = _captured_system_instruction(mock_client)
    assert KIDS.script_prompt in instruction
    assert FINANCE.script_prompt not in instruction


@pytest.mark.asyncio
async def test_blocklist_terms_all_present(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    from app import youtube

    with patch("google.genai.Client") as mock_client:
        mock_client.return_value.models.generate_content.return_value = MagicMock(
            text="---\ntitle: T\ndescription: D\n---\n\n# Scene 1\nVoiceover: A\n"
        )
        await youtube._generate_script_for_story({"headline": "H"}, KIDS)

    instruction = _captured_system_instruction(mock_client)
    for term in BASE_BLOCKLIST:
        assert term in instruction


@pytest.mark.asyncio
async def test_instruction_states_frontmatter_is_covered(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    from app import youtube

    with patch("google.genai.Client") as mock_client:
        mock_client.return_value.models.generate_content.return_value = MagicMock(
            text="---\ntitle: T\ndescription: D\n---\n\n# Scene 1\nVoiceover: A\n"
        )
        await youtube._generate_script_for_story({"headline": "H"}, FINANCE)

    instruction = _captured_system_instruction(mock_client)
    assert "frontmatter" in instruction.lower()


@pytest.mark.asyncio
async def test_no_voice_profiles_lookup_remains(monkeypatch):
    """The activeProfileId path is gone: generation must not read that key."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    from app import youtube

    get_config = AsyncMock(return_value=None)
    with patch("app.db.get_config", get_config), patch("google.genai.Client") as mock_client:
        mock_client.return_value.models.generate_content.return_value = MagicMock(
            text="---\ntitle: T\ndescription: D\n---\n\n# Scene 1\nVoiceover: A\n"
        )
        await youtube._generate_script_for_story({"headline": "H"}, FINANCE)

    for call in get_config.await_args_list:
        assert call.args[0] != "voice_profiles"
```

- [ ] **Step 2: Run the tests to verify they fail**

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_youtube_channel.py -v
```

Expected: FAIL. `_generate_script_for_story` still takes `channel_id: str` and reads `voice_profiles`.

- [ ] **Step 3: Rewrite the function**

In `worker/app/youtube.py`, replace `_generate_script_for_story` (currently lines 258 to roughly 320) with:

```python
async def _generate_script_for_story(story: dict, channel: Channel) -> str:
    """
    Call the LLM to generate the storyboard markdown for one channel.

    The channel supplies voice and prompt. Compliance rules come from
    channels.BASE_COMPLIANCE_RULES and are not channel-overridable.
    """
    headline = story.get("headline", "Default Headline")

    import os
    from google import genai
    from google.genai import types

    blocklist_str = ", ".join(f'"{word}"' for word in channel.effective_blocklist)

    system_instruction = f"""You are generating a script for a faceless YouTube explainer video.
Your Voice & Personality: {channel.script_prompt}

COMPLIANCE RULES (CRITICAL):
{BASE_COMPLIANCE_RULES}
ABSOLUTELY FORBIDDEN WORDS: {blocklist_str}.
These rules and forbidden words apply to the YAML frontmatter, including the
title and description fields, exactly as they apply to the narration.

FORMAT:
You must output a valid markdown document that starts with YAML frontmatter.
Example format:
---
title: "The video title"
description: "A highly detailed, SEO-optimized description of the video. Write this as a human expert. NEVER mention or allude to AI, ChatGPT, or automated generation."
preset: {channel.voice_key}
music: soft upbeat playful
---

# Video direction
A clean, minimal, yet highly descriptive cartoonized explainer video.

# Scene 1
Voiceover: "Welcome to today's topic..."
Visual: "A bright, cute title card..."
"""

    user_prompt = f"Write a video script for the following story headline:\n{headline}"

    log.info("gemini_generation_started", channel_id=channel.id, preset=channel.voice_key)

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable is not set")

    client = genai.Client(api_key=api_key)

    def call_gemini():
        # The SDK is synchronous; off the event loop so the pool keeps serving.
        return client.models.generate_content(
            model='gemini-flash-latest',
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.7,
            ),
        )
```

Keep everything below that point in the original function (the retry loop and the
raise-on-failure behaviour) exactly as it is. Do not reintroduce a stub fallback.

Add the import near the top of `youtube.py`, after the existing imports:

```python
from app.channels import BASE_COMPLIANCE_RULES, Channel
```

Then update the call site. At `worker/app/youtube.py:122`, change:

```python
        script_content = await _generate_script_for_story(story, channel_id)
```

to:

```python
        script_content = await _generate_script_for_story(story, channel)
```

And resolve the channel once, at the top of `generate_youtube_video`, immediately
after the opening `log.info("youtube_generation_started", ...)` call near line 107:

```python
    from app import channels
    channel = await channels.resolve(channel_id)
```

- [ ] **Step 4: Run the tests**

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_youtube_channel.py -v
```

Expected: all PASS.

- [ ] **Step 5: Run the existing youtube tests to see what the signature change broke**

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_youtube.py -v
```

Expected: failures in tests that call `generate_youtube_video`, because `channels.resolve` now runs and there is no config. Fix each by adding a patch:

```python
@patch("app.channels.resolve", AsyncMock(return_value=FINANCE))
```

with `FINANCE` defined in `test_youtube.py` the same way as in `test_youtube_channel.py`. Do not weaken `resolve` to make these pass.

- [ ] **Step 6: Commit**

```powershell
git add worker/app/youtube.py worker/tests/test_youtube_channel.py worker/tests/test_youtube.py
git commit -m "Generate scripts from resolved channel, not the global voice profile"
```

---

### Task 3: Make channel_id required at the API boundary

**Files:**
- Modify: `worker/app/routes.py:78` and the generate endpoint at `worker/app/routes.py:110-125`
- Test: `worker/tests/test_routes_channel.py` (new)

**Interfaces:**
- Consumes: `channels.ChannelConfigError`
- Produces: `POST /youtube/generate` returning 400 with the error message when channel config is bad, 422 when `channel_id` is absent

- [ ] **Step 1: Write the failing tests**

Create `worker/tests/test_routes_channel.py`:

```python
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.channels import ChannelConfigError
from app.main import app

client = TestClient(app)


def test_generate_without_channel_id_is_rejected():
    resp = client.post("/youtube/generate", json={"story_id": "00000000-0000-0000-0000-000000000001"})
    assert resp.status_code == 422


def test_generate_with_unknown_channel_returns_400_and_names_it():
    with patch(
        "app.youtube.generate_youtube_video",
        AsyncMock(side_effect=ChannelConfigError("unknown channel 'nope'; configured: finance, kids")),
    ):
        resp = client.post(
            "/youtube/generate",
            json={"story_id": "00000000-0000-0000-0000-000000000001", "channel_id": "nope"},
        )
    assert resp.status_code == 400
    assert "nope" in resp.json()["detail"]


def test_generate_with_empty_channel_id_is_rejected():
    resp = client.post(
        "/youtube/generate",
        json={"story_id": "00000000-0000-0000-0000-000000000001", "channel_id": ""},
    )
    assert resp.status_code in (400, 422)
```

- [ ] **Step 2: Run the tests to verify they fail**

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_routes_channel.py -v
```

Expected: the first test fails because `channel_id` still defaults to `"default"`.

- [ ] **Step 3: Implement**

In `worker/app/routes.py`, find the request model at line 78 and change:

```python
    channel_id: str = "default"
```

to:

```python
    channel_id: str = Field(min_length=1)
```

Add `Field` to the pydantic import at the top of the file if it is not already imported:

```python
from pydantic import BaseModel, Field
```

Then, in the generate endpoint (around line 110 to 125), wrap the call:

```python
    from app.channels import ChannelConfigError

    try:
        draft_id = await generate_youtube_video(
            story_id=req.story_id,
            channel_id=req.channel_id,
            upload_preference=req.upload_preference,
        )
    except ChannelConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

Keep the surrounding response shape unchanged.

- [ ] **Step 4: Run the tests**

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_routes_channel.py tests/test_routes_modes.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```powershell
git add worker/app/routes.py worker/tests/test_routes_channel.py
git commit -m "Require an explicit channel_id on generate, 400 on bad channel config"
```

---

### Task 4: Add channel to stories

**Files:**
- Create: `supabase/migrations/008_story_channel.sql`
- Modify: `worker/app/db.py:343-352` (`create_manual_story`), `worker/app/routes.py:242-247`
- Test: `worker/tests/test_db_channel.py` (new)

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces: `create_manual_story(headline: str, channel_id: str) -> uuid.UUID`

- [ ] **Step 1: Write the migration**

Create `supabase/migrations/008_story_channel.sql`:

```sql
-- Stories gain a channel so a topic knows which brand it belongs to.
-- Nullable on purpose: rows already exist without one, and they are not
-- reassigned. A story with a NULL channel is simply not generatable.

ALTER TABLE stories ADD COLUMN IF NOT EXISTS channel_id TEXT;

COMMENT ON COLUMN stories.channel_id IS
  'Target channel key, matching a key in the channels config. NULL for rows created before per-channel support; those are not generatable without being assigned one.';
```

- [ ] **Step 2: Write the failing test**

Create `worker/tests/test_db_channel.py`:

```python
import inspect

from app.db import create_manual_story


def test_create_manual_story_requires_a_channel():
    """The signature must force a channel: a topic without one is not generatable."""
    sig = inspect.signature(create_manual_story)
    assert "channel_id" in sig.parameters
    assert sig.parameters["channel_id"].default is inspect.Parameter.empty
```

This is a signature test on purpose. The behavioural test needs Postgres, and
per project convention DB tests are expected to error without a local database.

- [ ] **Step 3: Run it to verify it fails**

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_db_channel.py -v
```

Expected: FAIL, `assert 'channel_id' in sig.parameters`.

- [ ] **Step 4: Implement**

In `worker/app/db.py`, replace `create_manual_story` (lines 343 to 352):

```python
async def create_manual_story(headline: str, channel_id: str) -> uuid.UUID:
    """Create a manual story for one channel, without items, for the autopilot."""
    pool = await get_pool()
    async with pool.connection() as conn:
        row = await _fetchone(
            conn,
            "INSERT INTO stories (headline, status, channel_id) VALUES (%s, 'inbox', %s) RETURNING id",
            headline,
            channel_id,
        )
        return row["id"]
```

In `worker/app/routes.py`, add `channel_id: str = Field(min_length=1)` to
`ManualStoryRequest`, and pass it through at line 246:

```python
    story_id = await create_manual_story(req.headline, req.channel_id)
```

- [ ] **Step 5: Run the tests**

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_db_channel.py -v
```

Expected: PASS.

- [ ] **Step 6: Apply the migration**

```powershell
psql -h localhost -p 5433 -U fce -d fce -f "F:\Content Creation Project\supabase\migrations\008_story_channel.sql"
```

If no local Postgres is running, skip this and note it. The migration must run on
the VPS before generation is used there.

- [ ] **Step 7: Commit**

```powershell
git add supabase/migrations/008_story_channel.sql worker/app/db.py worker/app/routes.py worker/tests/test_db_channel.py
git commit -m "Add stories.channel_id and require a channel on manual stories"
```

---

### Task 5: Seed the channels config from the existing voice profile

**Files:**
- Create: `worker/scripts/seed_channels.py`
- Test: `worker/tests/test_seed_channels.py` (new)

**Interfaces:**
- Consumes: `db.get_config`, `db.set_config`, `channels.BASE_BLOCKLIST`
- Produces: `build_channels_payload(voice_profiles: dict | None) -> dict`

Separating the pure transform from the DB write is what makes this testable
without Postgres.

- [ ] **Step 1: Write the failing tests**

Create `worker/tests/test_seed_channels.py`:

```python
import pytest

from app.channels import BASE_BLOCKLIST
from scripts.seed_channels import build_channels_payload

VOICE_PROFILES = {
    "activeProfileId": "adult_male",
    "profiles": [
        {
            "id": "adult_male",
            "name": "Adult Casual Male",
            "prompt": "You are a casual, humorous, and informative adult male.",
            "blocklist": ["buy", "sell", "guaranteed returns"],
        },
        {
            "id": "baby",
            "name": "Baby",
            "prompt": "You are a humorous, highly intelligent baby.",
            "blocklist": ["buy", "sell"],
        },
    ],
}


def test_finance_channel_takes_the_active_profile():
    payload = build_channels_payload(VOICE_PROFILES)
    assert payload["finance"]["voice_key"] == "adult_male"
    assert payload["finance"]["script_prompt"] == VOICE_PROFILES["profiles"][0]["prompt"]


def test_base_terms_are_not_duplicated_into_extras():
    payload = build_channels_payload(VOICE_PROFILES)
    extras = payload["finance"]["extra_blocklist"]
    for term in BASE_BLOCKLIST:
        assert term not in extras


def test_non_base_terms_are_preserved_as_extras():
    payload = build_channels_payload(VOICE_PROFILES)
    assert "guaranteed returns" in payload["finance"]["extra_blocklist"]


def test_kids_channel_is_created():
    payload = build_channels_payload(VOICE_PROFILES)
    assert payload["kids"]["voice_key"] == "baby"
    assert payload["kids"]["display_name"]


def test_missing_voice_profiles_raises():
    with pytest.raises(ValueError):
        build_channels_payload(None)
```

- [ ] **Step 2: Run to verify failure**

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_seed_channels.py -v
```

Expected: `ModuleNotFoundError: No module named 'scripts.seed_channels'`.

- [ ] **Step 3: Implement**

Create `worker/scripts/__init__.py` as an empty file if it does not exist, then
create `worker/scripts/seed_channels.py`:

```python
"""One-time copy of the active voice profile into the channels config.

Values are carried forward, not recreated, so the finance channel keeps the
prompt that has been producing content. Terms already in BASE_BLOCKLIST are not
duplicated into extra_blocklist: the base set is unioned in at read time.

Run once:  ..\\.venv\\Scripts\\python.exe -m scripts.seed_channels
"""

from __future__ import annotations

import asyncio

from app import db
from app.channels import BASE_BLOCKLIST, CONFIG_KEY


def build_channels_payload(voice_profiles: dict | None) -> dict:
    if not voice_profiles or not voice_profiles.get("profiles"):
        raise ValueError("no voice_profiles config to migrate from")

    profiles = voice_profiles["profiles"]
    active_id = voice_profiles.get("activeProfileId") or profiles[0]["id"]
    active = next((p for p in profiles if p.get("id") == active_id), profiles[0])
    baby = next((p for p in profiles if p.get("id") == "baby"), None)

    def extras(profile: dict) -> list[str]:
        return [t for t in (profile.get("blocklist") or []) if t not in BASE_BLOCKLIST]

    payload = {
        "finance": {
            "display_name": "Finance",
            "voice_key": active["id"],
            "script_prompt": active["prompt"],
            "extra_blocklist": extras(active),
        }
    }

    if baby:
        payload["kids"] = {
            "display_name": "Kids",
            "voice_key": "baby",
            "script_prompt": baby["prompt"],
            "extra_blocklist": extras(baby),
        }

    return payload


async def main() -> None:
    voice_profiles = await db.get_config("voice_profiles")
    payload = build_channels_payload(voice_profiles)
    await db.set_config(CONFIG_KEY, payload)
    print(f"wrote {CONFIG_KEY}: {', '.join(sorted(payload))}")


if __name__ == "__main__":
    asyncio.run(main())
```

The `voice_profiles` row is left in the database untouched. Only the code path
that read it is removed, in Task 2.

- [ ] **Step 4: Run the tests**

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_seed_channels.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```powershell
git add worker/scripts/seed_channels.py worker/scripts/__init__.py worker/tests/test_seed_channels.py
git commit -m "Add one-time seed of channels config from the active voice profile"
```

---

### Task 6: Extract and deliver upload metadata

**Files:**
- Modify: `worker/app/youtube.py:228-243` (after render, before draft registration), `worker/app/youtube.py:367-400` (`_record_youtube_draft`)
- Test: `worker/tests/test_upload_metadata.py` (new)

**Interfaces:**
- Consumes: `_parse_storyboard_frontmatter` (`worker/app/youtube.py:1060`), `Channel`
- Produces:
  - `_write_upload_txt(video_dir: Path, channel: Channel, title: str, description: str) -> Path`
  - `_record_youtube_draft(..., title: str, description: str)` with the two new keyword arguments
  - `upload.txt` in the story directory

**Layout reminder:** `video_dir` is `VIDEOS_DIR / f"story-{story_id}"`. The render
lands at `video_dir / "renders" / "video.mp4"`, and `STORYBOARD.md` sits at
`video_dir / "STORYBOARD.md"`. `upload.txt` goes in `video_dir`, beside the
storyboard.

- [ ] **Step 1: Write the failing tests**

Create `worker/tests/test_upload_metadata.py`:

```python
from pathlib import Path

import pytest

from app.channels import Channel

FINANCE = Channel(
    id="finance",
    display_name="Finance",
    voice_key="adult_male",
    script_prompt="A prompt.",
    extra_blocklist=(),
)

KIDS = Channel(
    id="kids",
    display_name="Kids",
    voice_key="baby",
    script_prompt="A prompt.",
    extra_blocklist=(),
)


def test_upload_txt_contains_title_and_description(tmp_path):
    from app.youtube import _write_upload_txt

    path = _write_upload_txt(tmp_path, FINANCE, "My Title", "My long description.")
    text = path.read_text(encoding="utf-8")

    assert path.name == "upload.txt"
    assert "My Title" in text
    assert "My long description." in text


def test_upload_txt_reminds_about_made_for_kids_on_the_kids_channel(tmp_path):
    from app.youtube import _write_upload_txt

    text = _write_upload_txt(tmp_path, KIDS, "T", "D").read_text(encoding="utf-8")
    assert "Made for kids" in text


def test_upload_txt_has_no_kids_reminder_on_finance(tmp_path):
    from app.youtube import _write_upload_txt

    text = _write_upload_txt(tmp_path, FINANCE, "T", "D").read_text(encoding="utf-8")
    assert "Made for kids" not in text


def test_empty_description_raises(tmp_path):
    """No title-as-description fallback. An empty description is a real failure."""
    from app.youtube import _require_metadata

    with pytest.raises(ValueError) as exc:
        _require_metadata({"title": "T", "description": ""})
    assert "description" in str(exc.value)


def test_missing_title_raises():
    from app.youtube import _require_metadata

    with pytest.raises(ValueError) as exc:
        _require_metadata({"title": "", "description": "D"})
    assert "title" in str(exc.value)


def test_valid_metadata_returns_both():
    from app.youtube import _require_metadata

    title, description = _require_metadata({"title": "T", "description": "D"})
    assert (title, description) == ("T", "D")
```

- [ ] **Step 2: Run to verify failure**

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_upload_metadata.py -v
```

Expected: `ImportError: cannot import name '_write_upload_txt'`.

- [ ] **Step 3: Implement the two helpers**

Add to `worker/app/youtube.py`, next to `_parse_storyboard_frontmatter` near line 1060:

```python
def _require_metadata(frontmatter: dict[str, str]) -> tuple[str, str]:
    """Return (title, description) or raise.

    The old publish path read `frontmatter.get("description") or title`, so a
    generation that produced no description silently yielded a one-line title in
    the description box. That fallback is gone: an empty field is a generation
    failure and should be visible.
    """
    title = (frontmatter.get("title") or "").strip()
    description = (frontmatter.get("description") or "").strip()

    missing = [n for n, v in (("title", title), ("description", description)) if not v]
    if missing:
        raise ValueError(
            f"storyboard frontmatter is missing: {', '.join(missing)}"
        )

    return title, description


def _write_upload_txt(
    video_dir: Path, channel: Channel, title: str, description: str
) -> Path:
    """Write the paste-ready metadata beside the storyboard.

    Uploads are manual, so this file is how the metadata reaches YouTube. It also
    means the metadata survives a database reset and travels with the folder.
    """
    lines = [
        f"CHANNEL: {channel.display_name}",
        "",
        "TITLE",
        "-----",
        title,
        "",
        "DESCRIPTION",
        "-----------",
        description,
        "",
    ]

    if channel.id == "kids":
        lines += [
            "REMINDER",
            "--------",
            "Tick \"Made for kids\" in YouTube Studio before publishing. This is a",
            "COPPA requirement and nothing in this pipeline sets it for you.",
            "",
        ]

    path = video_dir / "upload.txt"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
```

- [ ] **Step 4: Run the helper tests**

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_upload_metadata.py -v
```

Expected: all PASS.

- [ ] **Step 5: Wire the helpers into generation**

In `worker/app/youtube.py`, immediately after `mp4_path = video_dir / "renders" / "video.mp4"` at line 228, insert:

```python
    frontmatter = _parse_storyboard_frontmatter(video_dir / "STORYBOARD.md")
    title, description = _require_metadata(frontmatter)
    _write_upload_txt(video_dir, channel, title, description)
```

Then extend the `_record_youtube_draft` call at line 236:

```python
    draft_id = await _record_youtube_draft(
        story_id=story_id,
        channel_id=channel_id,
        upload_preference=upload_preference,
        file_path=str(mp4_path),
        status=status,
        external_id=external_id,
        title=title,
        description=description,
    )
```

And in `_record_youtube_draft` (line 367), add the two parameters and put them in
the body dict alongside `channel_id`:

```python
async def _record_youtube_draft(
    story_id: uuid.UUID,
    channel_id: str,
    upload_preference: str,
    file_path: str,
    status: str,
    external_id: str | None,
    title: str,
    description: str,
) -> uuid.UUID | None:
```

Inside, add `"title": title` and `"description": description` to the body
dictionary that already carries `"channel_id"`.

- [ ] **Step 6: Add the integration test**

Append to `worker/tests/test_upload_metadata.py`:

```python
import uuid
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
@patch("app.youtube._fetch_story_details")
@patch("app.youtube._record_youtube_draft")
@patch("app.youtube._generate_script_for_story")
@patch("app.youtube._generate_frame_audio")
@patch("app.youtube._build_frames")
@patch("app.youtube.subprocess.run")
async def test_generation_writes_upload_txt_and_records_metadata(
    mock_run, mock_frames, mock_audio, mock_script, mock_record, mock_fetch, tmp_path
):
    from app import youtube

    story_id = uuid.uuid4()
    mock_fetch.return_value = {"headline": "Test Story"}
    mock_script.return_value = (
        "---\ntitle: Real Title\ndescription: A real SEO description.\npreset: adult_male\n---\n\n"
        "# Scene 1\nVoiceover: A\n\n# Scene 2\nVoiceover: B\n\n"
        "# Scene 3\nVoiceover: C\n\n# Scene 4\nVoiceover: D\n"
    )
    mock_record.return_value = uuid.uuid4()
    mock_run.return_value = MagicMock(stdout="mocked")
    mock_audio.return_value = []
    mock_frames.return_value = []

    with patch("app.youtube.VIDEOS_DIR", tmp_path), patch(
        "app.channels.resolve", AsyncMock(return_value=FINANCE)
    ):
        await youtube.generate_youtube_video(
            story_id=story_id, channel_id="finance", upload_preference="manual"
        )

    upload_txt = tmp_path / f"story-{story_id}" / "upload.txt"
    assert upload_txt.exists()
    assert "Real Title" in upload_txt.read_text(encoding="utf-8")

    kwargs = mock_record.call_args.kwargs
    assert kwargs["title"] == "Real Title"
    assert kwargs["description"] == "A real SEO description."
```

- [ ] **Step 7: Run the full file**

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_upload_metadata.py -v
```

Expected: all PASS. The storyboard is written to `video_dir / "STORYBOARD.md"` at
`worker/app/youtube.py:126`, which is the path the new code reads, so no
adjustment should be needed.

- [ ] **Step 8: Commit**

```powershell
git add worker/app/youtube.py worker/tests/test_upload_metadata.py
git commit -m "Extract title and description at generation time, write upload.txt"
```

---

### Task 7: Delete the publish path

**Files:**
- Modify: `worker/app/youtube.py` (remove `publish_youtube_draft`, `_upload_to_youtube`, `_upload_thumbnail`, `_get_youtube_credentials`), `worker/app/routes.py` (remove the publish route), `worker/tests/test_youtube.py` (remove publish tests and imports)
- Modify: `worker/app/settings.py` (remove `youtube_token_path`, `youtube_client_secrets_path`)

**Interfaces:**
- Consumes: nothing
- Produces: nothing. This task only removes code.

**Keep, do not delete:** `_parse_storyboard_frontmatter` (now called from
generation, Task 6), `_generate_thumbnail` (see Step 4), and
`get_youtube_analytics` with its `/youtube/analytics` route, which reads existing
draft rows.

- [ ] **Step 1: Remove the route**

In `worker/app/routes.py`, delete the `@router.post("/youtube/publish")` endpoint
and its `publish_youtube_draft` import.

- [ ] **Step 2: Remove the functions**

In `worker/app/youtube.py`, delete `publish_youtube_draft` (line 1079 onward),
`_upload_to_youtube` (line 874), `_upload_thumbnail`, and
`_get_youtube_credentials` (line 45). Remove any now-unused imports of
`google.oauth2.credentials`, `google.auth.transport.requests`, and
`googleapiclient.discovery.build` that were only used by those functions.

Check for stragglers before committing:

```powershell
Select-String -Path "worker\app\*.py" -Pattern "publish_youtube_draft|_upload_to_youtube|_get_youtube_credentials|_upload_thumbnail"
```

Expected: no matches.

- [ ] **Step 3: Remove the settings**

In `worker/app/settings.py`, delete the `youtube_token_path` and
`youtube_client_secrets_path` fields (lines 48 and 49). Leave
`youtube_channel_id` alone for now; it is unrelated to this path and removing it
is a separate decision.

- [ ] **Step 4: Move thumbnail generation to generation time**

`_generate_thumbnail` was called only from the publish path, so deleting publish
would orphan it, and a manual upload still wants a thumbnail. **This is an
addition beyond the written spec, flagged rather than assumed.** In
`worker/app/youtube.py`, after the `_write_upload_txt` call added in Task 6:

```python
    thumbnail_path = video_dir / "thumbnail.jpg"
    if not thumbnail_path.exists():
        await _generate_thumbnail(title, str(thumbnail_path))
```

If the reviewer decides thumbnails are out of scope, delete `_generate_thumbnail`
in this task instead and skip this step. Do not leave it defined and uncalled.

- [ ] **Step 5: Fix the tests**

In `worker/tests/test_youtube.py`, remove `publish_youtube_draft` and
`_get_youtube_credentials` from the import block at lines 7 to 12, and delete the
tests that exercise them.

- [ ] **Step 6: Run the whole suite**

```powershell
..\.venv\Scripts\python.exe -m pytest tests -q
```

Expected: PASS, except DB tests that error without a local Postgres, which is
the documented normal state.

- [ ] **Step 7: Commit**

```powershell
git add worker/app/youtube.py worker/app/routes.py worker/app/settings.py worker/tests/test_youtube.py
git commit -m "Delete the automated publish path; uploads are manual"
```

---

### Task 8: GUI — channel selector and copy buttons

**Files:**
- Modify: `gui/src/app/settings/page.tsx`
- Modify: `gui/src/app/drafts/page.tsx`

**Interfaces:**
- Consumes: `GET/PUT /config/channels` (the generic `/config/{key}` route at `worker/app/routes.py:277`, no API change needed), `GET /drafts` now returning `title` and `description` in the body
- Produces: no new API surface

**Before writing any code here, read the guidance in `gui/AGENTS.md`:** this is a
Next.js version whose conventions may differ from training data, and the file
directs you to `node_modules/next/dist/docs/` for the current API.

- [ ] **Step 1: Replace the settings page types and fetch**

In `gui/src/app/settings/page.tsx`, replace the `VoiceProfile` and `ConfigData`
types (lines 6 to 16) with:

```tsx
type ChannelConfig = {
  display_name: string;
  voice_key: string;
  script_prompt: string;
  extra_blocklist: string[];
};

type ChannelsConfig = Record<string, ChannelConfig>;

// Mirrors BASE_BLOCKLIST in worker/app/channels.py. Displayed read-only: these
// terms always apply and cannot be edited away from the GUI.
const BASE_BLOCKLIST = [
  "buy",
  "sell",
  "accumulate",
  "target price",
  "multibagger",
  "sure shot",
];
```

Change the two fetch URLs at lines 63 and 131 from
`http://localhost:8000/config/voice_profiles` to
`http://localhost:8000/config/channels`. Delete the `DEFAULT_PROFILES` constant
at lines 18 to 49; the channels config is seeded by
`worker/scripts/seed_channels.py`, not by the GUI.

- [ ] **Step 2: Add the channel selector and read-only base list**

Replace the active-profile selector with a channel selector driven by
`Object.keys(channels)`, and render the base blocklist above the editable extras:

```tsx
<div className="mb-4">
  <label className="block text-sm font-medium mb-1">Channel</label>
  <select
    value={selectedChannel}
    onChange={(e) => setSelectedChannel(e.target.value)}
    className="w-full rounded border px-3 py-2"
  >
    {Object.entries(channels).map(([key, c]) => (
      <option key={key} value={key}>{c.display_name}</option>
    ))}
  </select>
</div>

<div className="mb-4">
  <label className="block text-sm font-medium mb-1">
    Always blocked (not editable)
  </label>
  <div className="flex flex-wrap gap-2 opacity-70">
    {BASE_BLOCKLIST.map((term) => (
      <span key={term} className="rounded bg-neutral-200 px-2 py-1 text-xs dark:bg-neutral-700">
        {term}
      </span>
    ))}
  </div>
</div>
```

The editable blocklist control now edits `extra_blocklist` on the selected
channel. Keep the existing add and remove handlers, pointed at that array.

- [ ] **Step 3: Remove the publish button from drafts**

In `gui/src/app/drafts/page.tsx`, delete the handler that posts to
`/api/youtube/publish` (around line 74) and the button that calls it.

- [ ] **Step 4: Add title and description with copy buttons**

Add to the draft card in `gui/src/app/drafts/page.tsx`:

```tsx
function CopyField({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className="mb-3">
      <div className="flex items-center justify-between mb-1">
        <span className="text-sm font-medium">{label}</span>
        <button
          onClick={copy}
          className="text-xs rounded border px-2 py-1"
          disabled={!value}
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <p className="whitespace-pre-wrap text-sm opacity-80">
        {value || "Not generated"}
      </p>
    </div>
  );
}
```

Render `<CopyField label="Title" value={draft.title} />` and
`<CopyField label="Description" value={draft.description} />` in each card. Add
`title` and `description` to the draft type.

`navigator.clipboard` requires a secure context. On `localhost` that is
satisfied; if the GUI is ever served over plain HTTP from another host, the copy
button will silently do nothing, which is why the text stays visible and
selectable on the page.

- [ ] **Step 5: Confirm the drafts query returns the new fields**

`worker/app/db.py:588` and `:607` select specific keys out of the draft body with
`d.body->>'channel_id'`. Add the same treatment for the two new fields:

```sql
d.body->>'title' AS title,
d.body->>'description' AS description,
```

- [ ] **Step 6: Build the GUI**

```powershell
Set-Location "F:\Content Creation Project\gui"
npm run build
```

Expected: build succeeds with no type errors.

- [ ] **Step 7: Commit**

```powershell
git add gui/src/app/settings/page.tsx gui/src/app/drafts/page.tsx worker/app/db.py
git commit -m "GUI: channel selector, read-only compliance floor, metadata copy buttons"
```

---

## Post-implementation verification

- [ ] Run the whole suite: `Set-Location "F:\Content Creation Project\worker"; ..\.venv\Scripts\python.exe -m pytest tests -q`
- [ ] Seed the config once: `..\.venv\Scripts\python.exe -m scripts.seed_channels`
- [ ] Apply migration `008_story_channel.sql` on the VPS Postgres (port 5433)
- [ ] Generate one finance video end to end and confirm `upload.txt` exists beside `STORYBOARD.md` with a real description
- [ ] Confirm the settings page lists both channels and shows the base blocklist as non-editable

## Known follow-ups, deliberately not in this plan

- `upload_preference="auto"` marks a draft `published` without anything being uploaded (`worker/app/youtube.py:233`). Pre-existing, and more visibly wrong now that publishing is gone.
- `GET /youtube/analytics` will report nothing new, since no video ids are recorded any more.
- `settings.youtube_channel_id` is now unused but left in place.
- The kids channel cannot render until its visual pipeline is specified. `VOICE_MAP["baby"]` still resolves to an adult voice.
