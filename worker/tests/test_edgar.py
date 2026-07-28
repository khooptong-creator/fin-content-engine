"""EDGAR source unit tests (Part II §3.4, §5.6).

Accession extraction, form-type filter, mandatory UA presence. The Atom
parsing itself is feedparser's job; we test our glue around it.
"""

from __future__ import annotations

import respx
import httpx
import pytest

from app.sources.edgar import EDGARSource, _extract_accession, _index_url


class _FakeSourceRow:
    def __init__(self, id_="00000000-0000-0000-0000-000000000001"):
        self.id = id_
        self.kind = "edgar"
        self.url = "https://www.sec.gov/cgi-bin/browse-edgar"
        self.name = "EDGAR"
        self.market = "US"
        self.active = True
        self.poll_minutes = 60


class TestAccessionExtraction:
    def test_from_accession_number_param(self):
        entry = {"id": "https://www.sec.gov/...?accession-number=000032019325000123"}
        assert _extract_accession(entry, "") == "000032019325000123"

    def test_from_data_path(self):
        entry = {"id": "", "link": "https://www.sec.gov/Archives/edgar/data/320193/000032019325000123/"}
        assert _extract_accession(entry, "") == "000032019325000123"

    def test_falls_back_to_raw_xml(self):
        entry = {"id": "no-accession-here"}
        raw = '<entry><id>accession-number=000078901925000045</id></entry>'
        assert _extract_accession(entry, raw) == "000078901925000045"

    def test_returns_none_when_not_found(self):
        assert _extract_accession({"id": "nothing"}, "") is None


class TestIndexUrl:
    def test_well_formed_accession(self):
        url = _index_url("0000320193-25-000123")
        assert "Archives/edgar/data" in url
        assert "000032019325000123" in url


class TestUserAgentHeader:
    """The mandatory UA (Part II §3.4): no UA → 403."""

    @respx.mock
    async def test_user_agent_present_on_request(self, monkeypatch):
        # Set the UA via settings.
        monkeypatch.setenv("FCE_EDGAR_USER_AGENT", "Fin-Content Engine test (test@example.com)")
        from app.settings import get_settings

        get_settings.cache_clear()

        # Stub the config loader so this test doesn't need a DB. The UA comes
        # from settings (env), not config (DB table); form_types just needs a
        # value to iterate.
        from app.config import EdgarConfig

        async def fake_edgar_config():
            return EdgarConfig(form_types=("8-K",), company_watch=())

        import app.sources.edgar as edgar_mod

        monkeypatch.setattr(edgar_mod, "get_edgar_config", fake_edgar_config)

        captured = {}

        def _intercept(request):
            captured["user_agent"] = request.headers.get("user-agent")
            return httpx.Response(
                200,
                text="""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>""",
            )

        respx.get(url__regex=r"https://www\.sec\.gov/cgi-bin/browse-edgar.*").mock(side_effect=_intercept)

        source = EDGARSource()
        await source.fetch(_FakeSourceRow())

        assert captured["user_agent"] == "Fin-Content Engine test (test@example.com)"
        get_settings.cache_clear()
