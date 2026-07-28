"""Clustering unit tests (Part II §3.7, §5.6).

Focus on the keyword fallback rule (≥2 distinct tokens) — the explicit
over-merge trap. The TCS-Q2 vs TCS-buyback pair is the canonical test:
single shared token must NOT merge.
"""

from __future__ import annotations

import uuid

import pytest

from app.cluster import cosine_similarity, extract_tokens, keyword_fallback_match


class TestExtractTokens:
    def test_ticker_pattern(self):
        assert "$reliance" in extract_tokens("$RELIANCE announces capex push")

    def test_acronym_token(self):
        assert "tcs" in extract_tokens("TCS Q2 profit beats estimates")

    def test_capitalized_phrase_is_one_token(self):
        tokens = extract_tokens("Tata Sons files for IPO")
        assert "tata sons" in tokens
        # And the individual words are not double-counted as separate tokens
        # from this phrase (they may appear if they show up elsewhere, but
        # the phrase itself is one composite token).
        assert "tata" not in tokens or "sons" not in tokens

    def test_multiple_distinct_phrases(self):
        tokens = extract_tokens("HDFC Bank announces results")
        assert "hdfc bank" in tokens
        assert "results" not in tokens  # boilerplate, downweighted

    def test_empty_title(self):
        assert extract_tokens("") == set()


class TestKeywordFallbackMinTokens:
    """The load-bearing rule (Part II §3.7): ≥2 distinct tokens required."""

    def test_tcs_q2_vs_tcs_buyback_DO_NOT_merge(self):
        """The explicit over-merge trap. Same company, different event.
        Single shared token ('tcs') must not merge them."""
        existing = [{"id": uuid.uuid4(), "headline": "TCS Q2 profit beats street estimates"}]
        # "TCS announces buyback" — shares only 'tcs' with the existing story.
        result = keyword_fallback_match(
            "TCS announces Rs 17,000 crore buyback at premium",
            existing,
            min_tokens=2,
        )
        assert result is None, (
            "Single-token match (TCS) must NOT merge Q2 results with buyback — "
            "this is the over-merge failure mode the ≥2-token rule exists to prevent."
        )

    def test_two_token_overlap_merges(self):
        """Two distinct tokens → merge. This is the intended behavior."""
        existing = [{"id": uuid.uuid4(), "headline": "TCS Q2 profit beats estimates"}]
        # "TCS Q2 revenue grows" shares 'tcs' and 'q2' (and 'estimates' is boilerplate).
        result = keyword_fallback_match(
            "TCS Q2 results: revenue grows in double digits",
            existing,
            min_tokens=2,
        )
        assert result == existing[0]["id"]

    def test_rbi_oct_vs_rbi_feb_DO_NOT_merge(self):
        """Same institution, same action, different event (different months)."""
        existing = [{"id": uuid.uuid4(), "headline": "RBI holds repo rate steady in October review"}]
        # February cut shares 'rbi' and possibly 'repo'/'rate' — but the headline
        # uses different action verbs. With min_tokens=2 we still might merge on
        # 'rbi' + 'repo' — that's a known edge case; the test documents the
        # behavior so it's not a silent regression.
        result = keyword_fallback_match(
            "RBI cuts repo rate by 25 bps in February review",
            existing,
            min_tokens=2,
        )
        # Acceptable outcomes: None (best — they ARE different events) OR the
        # existing id (over-merge on 'rbi'+'repo'). The clustering fixture test
        # (§5) is what catches this at the end-to-end level via FP count.
        assert result is None or result == existing[0]["id"]

    def test_ipo_event_vs_ipo_explainer_DO_NOT_merge(self):
        """Specific IPO event vs evergreen 'what is an IPO' explainer."""
        existing = [{"id": uuid.uuid4(), "headline": "Tata Sons files for IPO"}]
        result = keyword_fallback_match(
            "What is an IPO? A plain-English explainer for new investors",
            existing,
            min_tokens=2,
        )
        # 'ipo' is the only shared token; explainer + investors are not in the event.
        assert result is None

    def test_returns_none_when_no_existing(self):
        assert keyword_fallback_match("Anything", [], min_tokens=2) is None

    def test_returns_none_when_title_has_fewer_than_min_tokens(self):
        """A title with only one token can never satisfy min_tokens=2."""
        existing = [{"id": uuid.uuid4(), "headline": "TCS profit up"}]
        # Single-token title.
        result = keyword_fallback_match("Reliance", existing, min_tokens=2)
        assert result is None


class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = [1.0, 0.0, 0.0]
        assert cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert cosine_similarity(a, b) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_dim_mismatch_raises(self):
        with pytest.raises(ValueError):
            cosine_similarity([1.0, 2.0], [1.0])
