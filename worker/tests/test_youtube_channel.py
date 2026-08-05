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
