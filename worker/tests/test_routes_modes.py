"""Format toggle -> frame backend. No DB, no network."""

import pytest

from app.routes import MODE_BACKENDS, backend_for_mode


def test_film_selects_the_three_backend():
    assert backend_for_mode("film") == "three"


def test_short_falls_through_to_the_configured_default():
    """None means 'whatever FRAME_BACKEND says', which is what a Short wants."""
    assert backend_for_mode("short") is None


def test_absent_mode_falls_through_too():
    assert backend_for_mode(None) is None


@pytest.mark.parametrize("bad", ["cinema", "3d", "Film", ""])
def test_unknown_mode_raises_rather_than_defaulting(bad):
    """Defaulting a typo would ship a portrait 2D video under a film's headline."""
    with pytest.raises(ValueError, match="unknown mode"):
        backend_for_mode(bad)


def test_every_declared_mode_is_resolvable():
    assert all(backend_for_mode(mode) == MODE_BACKENDS[mode] for mode in MODE_BACKENDS)
