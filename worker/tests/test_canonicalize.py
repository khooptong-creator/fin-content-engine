"""URL canonicalization unit tests (Part II §3.3, §5.6).

The hash is computed on the canonicalized URL, so canonicalization IS dedup.
Every case in §3.3's failure table for URL tracker drift is covered here.
"""

from __future__ import annotations

from app.sources.canonicalize import canonicalize_url


class TestSchemeAndHost:
    def test_upgrades_http_to_https(self):
        assert canonicalize_url("http://example.com/a").startswith("https://")

    def test_lowercases_host(self):
        assert canonicalize_url("https://Example.COM/x") == "https://example.com/x"

    def test_strips_www_prefix(self):
        assert canonicalize_url("https://www.example.com/x") == "https://example.com/x"

    def test_preserves_subdomain(self):
        assert canonicalize_url("https://markets.example.com/x") == "https://markets.example.com/x"


class TestPath:
    def test_strips_trailing_slash(self):
        assert canonicalize_url("https://example.com/a/") == "https://example.com/a"

    def test_preserves_root_slash(self):
        assert canonicalize_url("https://example.com/") == "https://example.com/"

    def test_preserves_internal_path(self):
        assert canonicalize_url("https://example.com/a/b/c") == "https://example.com/a/b/c"


class TestTrackingParams:
    def test_strips_utm_source(self):
        out = canonicalize_url("https://example.com/a?utm_source=rss")
        assert "utm_source" not in out
        assert out == "https://example.com/a"

    def test_strips_all_utm(self):
        url = "https://example.com/a?utm_source=t&utm_medium=m&utm_campaign=c&utm_term=x&utm_content=y"
        assert canonicalize_url(url) == "https://example.com/a"

    def test_strips_fbclid_gclid(self):
        url = "https://example.com/a?fbclid=abc&gclid=def"
        assert canonicalize_url(url) == "https://example.com/a"

    def test_preserves_meaningful_params(self):
        url = "https://example.com/a?id=123&sort=asc"
        out = canonicalize_url(url)
        assert "id=123" in out
        assert "sort=asc" in out

    def test_sorts_remaining_params(self):
        # Same params in different order → same canonical URL.
        a = canonicalize_url("https://example.com/a?b=2&a=1")
        b = canonicalize_url("https://example.com/a?a=1&b=2")
        assert a == b


class TestDedupEquivance:
    """The whole point: two URLs for the same article collapse to one hash."""

    def test_tracker_laden_variants_collapse(self):
        base = canonicalize_url("https://etmarkets.com/markets/tata-sons-ipo")
        with_utms = canonicalize_url(
            "https://etmarkets.com/markets/tata-sons-ipo?utm_source=rss&utm_medium=feed"
        )
        with_ref = canonicalize_url(
            "https://etmarkets.com/markets/tata-sons-ipo/?ref=twitter&fbclid=xyz"
        )
        assert base == with_utms == with_ref

    def test_http_and_https_collapse(self):
        assert canonicalize_url("http://example.com/a") == canonicalize_url(
            "https://example.com/a"
        )


class TestEdgeCases:
    def test_empty_returns_empty(self):
        assert canonicalize_url("") == ""

    def test_whitespace_stripped(self):
        assert canonicalize_url("  https://example.com/a  ") == "https://example.com/a"

    def test_preserves_fragment(self):
        # Fragments are client-side; preserve them (rare in feeds but possible).
        out = canonicalize_url("https://example.com/a#section")
        assert "#section" in out
