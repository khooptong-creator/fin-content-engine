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
