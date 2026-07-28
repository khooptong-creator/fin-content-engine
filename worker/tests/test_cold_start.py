"""Cold-start smoke test — Layer 1 (Part II §5.5).

Mocks feed responses via respx, runs ingest.run_all_sources() against the
local Docker DB, asserts the full chain works end-to-end:
  - items inserted
  - all embedded (inline, §3.6)
  - stories created
  - zero orphans
  - idempotent on re-run (the §1.1 exact-dupe bar)
  - /stats reflects reality

The mock embedder (FCE_EMBED_MOCK=true) returns a deterministic vector per
input string so reruns are stable (§5.5 determinism requirement).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
import respx

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "feeds"


@pytest_asyncio.fixture
async def test_sources(db):
    """Seed two test sources (RSS + EDGAR) with URLs that respx will intercept.
    Deactivate all other (seeded production) sources so run_all_sources() only
    hits the test sources — otherwise respx blocks the real feed URLs."""
    rss_id = uuid.uuid4()
    edgar_id = uuid.uuid4()
    async with db.connection() as conn:
        # Deactivate seeded sources so the test is hermetic.
        await conn.execute("UPDATE sources SET active = false")
        await conn.execute(
            "INSERT INTO sources (id, kind, url, name, market, active, poll_minutes) "
            "VALUES (%s, 'rss', 'https://test.example/rss', 'TEST_cold_start_rss', 'IN', true, 30)",
            (rss_id,),
        )
        await conn.execute(
            "INSERT INTO sources (id, kind, url, name, market, active, poll_minutes) "
            "VALUES (%s, 'edgar', 'https://www.sec.gov/cgi-bin/browse-edgar', 'TEST_cold_start_edgar', 'US', true, 60)",
            (edgar_id,),
        )
    return {"rss": rss_id, "edgar": edgar_id}


@respx.mock
async def test_cold_start_idempotent(test_sources, db, monkeypatch):
    """The §5.5 Layer 1 acceptance test."""
    # Mock the RSS feed response.
    rss_xml = (FIXTURES / "etmarkets.xml").read_text(encoding="utf-8")
    respx.get("https://test.example/rss").mock(
        return_value=httpx.Response(200, content=rss_xml.encode("utf-8"))
    )
    # Mock the EDGAR Atom feed response.
    edgar_atom = (FIXTURES / "edgar.atom").read_text(encoding="utf-8")
    respx.get(url__regex=r"https://www\.sec\.gov/cgi-bin/browse-edgar.*").mock(
        return_value=httpx.Response(200, content=edgar_atom.encode("utf-8"))
    )

    # Ensure mock embedder is on (deterministic).
    monkeypatch.setenv("FCE_EMBED_MOCK", "true")
    from app.settings import get_settings
    get_settings.cache_clear()
    from app.embed import clear_mock_cache
    clear_mock_cache()

    from app.ingest import run_all_sources

    # ---- First ingest cycle ----
    summaries = await run_all_sources()
    assert len(summaries) == 2  # rss + edgar

    # Items inserted + embedded (inline at poll tail, §3.6).
    from app.db import _fetchval

    async with db.connection() as conn:
        item_count = await _fetchval(conn, "SELECT count(*) FROM items")
        unembedded = await _fetchval(
            conn, "SELECT count(*) FROM items WHERE embedding IS NULL"
        )

    assert item_count > 0, "no items inserted on first cycle"
    # All items must be embedded (inline at poll tail, §3.6).
    assert unembedded == 0, f"{unembedded} items have no embedding — inline embed failed"

    # Run clustering (separate job in production, §3.7) → creates stories.
    from app.cluster import cluster_new_items

    await cluster_new_items()

    async with db.connection() as conn:
        story_count = await _fetchval(conn, "SELECT count(*) FROM stories")
    assert story_count > 0, "no stories created after clustering"

    items_v1 = item_count
    stories_v1 = story_count

    # ---- Idempotency: second ingest cycle must insert ZERO new items ----
    clear_mock_cache()
    summaries_2 = await run_all_sources()
    async with db.connection() as conn:
        item_count_2 = await _fetchval(conn, "SELECT count(*) FROM items")
        story_count_2 = await _fetchval(conn, "SELECT count(*) FROM stories")

    assert item_count_2 == items_v1, (
        f"idempotency violated: {item_count_2 - items_v1} new items on second cycle "
        "(ON CONFLICT (hash) DO NOTHING should have suppressed them)"
    )
    # Stories should not churn either.
    assert story_count_2 == stories_v1

    # ---- /stats reflects reality ----
    from app.db import stats
    s = await stats()
    assert s["items"]["total"] == items_v1
    assert s["embedding_health"] == "ok"
    # Orphans must be zero (§3.9 non-negotiable in steady state).
    assert s["items"]["orphaned"] == 0, "orphans present — story creation dropped an item"
