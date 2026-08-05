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
