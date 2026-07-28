"""RSS source tests (Part II §3.3, §5.6).

URL canonicalization is tested separately (test_canonicalize.py); here we test
the source-level concerns: HTML stripping, date fallback, partial-full_text
handling, not_a_feed detection.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
import respx

from app.sources.base import RawItem, SourceError
from app.sources.rss import RSSSource, _strip_html


class TestStripHtml:
    def test_strips_tags(self):
        assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_unescapes_entities(self):
        assert _strip_html("Tom &amp; Jerry &lt;3") == "Tom & Jerry <3"

    def test_collapses_whitespace(self):
        assert _strip_html("<p>a\n\n  b</p>") == "a b"

    def test_empty(self):
        assert _strip_html("") == ""


class _FakeRow:
    def __init__(self, url):
        self.id = "00000000-0000-0000-0000-000000000002"
        self.kind = "rss"
        self.url = url
        self.name = "test"
        self.market = "IN"
        self.active = True
        self.poll_minutes = 30


class TestNotAFeedDetection:
    @respx.mock
    async def test_html_page_with_200_raises_source_error(self):
        respx.get("https://test.example/html").mock(
            return_value=httpx.Response(
                200,
                content=b"<html><body>404 not found</body></html>",
            )
        )
        source = RSSSource()
        with pytest.raises(SourceError, match="not_a_feed"):
            await source.fetch(_FakeRow("https://test.example/html"))


class TestNormalize:
    async def test_date_missing_warning(self):
        source = RSSSource()
        raw = RawItem(
            source_id="s",
            raw_title="Title",
            raw_url="https://example.com/a",
            raw_published_at=None,
            raw_html_or_xml="<p>body</p>",
            fetch_meta={},
        )
        # Stub out the rescue-full_text path so the test doesn't make HTTP calls.
        import app.sources.rss as rss_mod

        async def fake_rescue(url):
            return None

        monkeypatch_attr = getattr(rss_mod, "_rescue_full_text", None)
        rss_mod._rescue_full_text = fake_rescue
        try:
            item = await source.normalize(raw)
        finally:
            if monkeypatch_attr is not None:
                rss_mod._rescue_full_text = monkeypatch_attr
        assert "date_missing" in item.warnings
        assert item.published_at is not None  # defaulted to now

    async def test_keeps_full_text_when_present(self):
        source = RSSSource()
        body = "x" * 600  # above MIN_FULL_TEXT_CHARS
        raw = RawItem(
            source_id="s",
            raw_title="Title",
            raw_url="https://example.com/a",
            raw_published_at=datetime(2025, 7, 22, tzinfo=timezone.utc),
            raw_html_or_xml=f"<p>{body}</p>",
            fetch_meta={},
        )
        item = await source.normalize(raw)
        assert item.full_text is not None
        assert len(item.full_text) >= 600
