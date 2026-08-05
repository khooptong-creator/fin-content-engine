import inspect

from app.db import create_manual_story


def test_create_manual_story_requires_a_channel():
    """The signature must force a channel: a topic without one is not generatable."""
    sig = inspect.signature(create_manual_story)
    assert "channel_id" in sig.parameters
    assert sig.parameters["channel_id"].default is inspect.Parameter.empty
