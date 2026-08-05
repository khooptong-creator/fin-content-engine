import inspect

from app.db import create_manual_story, get_pending_stories


def test_pending_stories_projection_includes_channel_id():
    """The autopilot generates each story under its own channel, so the inbox
    query has to actually return the column migration 008 added. Source-level
    because asserting on real rows would need Postgres."""
    source = inspect.getsource(get_pending_stories)
    select = source[source.index("SELECT"):source.index("FROM stories")]
    assert "channel_id" in select


def test_create_manual_story_requires_a_channel():
    """The signature must force a channel: a topic without one is not generatable."""
    sig = inspect.signature(create_manual_story)
    assert "channel_id" in sig.parameters
    assert sig.parameters["channel_id"].default is inspect.Parameter.empty
