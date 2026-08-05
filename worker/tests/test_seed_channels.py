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


def test_unrecognized_voice_id_raises():
    bad_profiles = {
        "activeProfileId": "custom_voice",
        "profiles": [
            {
                "id": "custom_voice",
                "name": "Custom",
                "prompt": "You are a custom voice.",
                "blocklist": [],
            }
        ],
    }
    with pytest.raises(ValueError, match="custom_voice"):
        build_channels_payload(bad_profiles)
