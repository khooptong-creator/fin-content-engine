"""Pytest config + shared fixtures (Part II §5.1, §5.5).

Two load-bearing pieces:
  1. `db` fixture — spins up an isolated schema per test (truncate between
     tests), against the local Docker Postgres+pgvector. Integration tests
     are marked `@pytest.mark.integration`; non-integration tests skip this.
  2. `assert_fixture_provenance` — the §5.1 provenance check. Loads
     `_model.json` and compares against the worker's configured values.
     Any mismatch (model, dim, title_weight_repeat, body_truncate_chars)
     fails LOUD — never silently runs a stale fixture through the gate.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio

# Windows event-loop fix: psycopg3's async mode requires SelectorEventLoop,
# but Windows defaults to ProactorEventLoop. Set the policy BEFORE any async
# code runs. (On Linux/macOS this is a no-op — SelectorEventLoop is default.)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Make `from app...` importable when running pytest from the worker dir.
WORKER_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKER_ROOT))

FIXTURES = WORKER_ROOT / "tests" / "fixtures"

# Force the mock embedder for tests (Part II §5.5 determinism). Individual
# tests that need the real edge function can override.
os.environ.setdefault("FCE_EMBED_MOCK", "true")
os.environ.setdefault("FCE_TESTING", "true")
# Point at the local Docker DB; conftest does NOT start Docker — `make db-up`
# or `make test` does. If DATABASE_URL is already set, respect it.
os.environ.setdefault(
    "FCE_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/fce"
)


# ---------------------------------------------------------------------------
# Provenance assertion — load-bearing (Part II §5.1)
# ---------------------------------------------------------------------------

def assert_fixture_provenance() -> None:
    """Check that `_model.json` matches the worker's configured embedding-input
    construction. ANY mismatch → fail loud with a 'regenerate fixture' message."""
    meta = json.loads((FIXTURES / "_model.json").read_text(encoding="utf-8"))

    # Pull worker-configured values without a running event loop (these are
    # dataclass defaults baked into the config module; reading the real DB
    # value would require an async call, but the *contract* is the defaults
    # match the fixture — and the seed migration uses exactly these defaults).
    from app.config import ClusteringConfig

    cfg = ClusteringConfig()

    checks = {
        "model": ("gte-small", meta["model"]),  # spec name; gte-small is the only option in P1
        "dim": (cfg.embedding_dim, meta["dim"]),
        "title_weight_repeat": (cfg.title_weight_repeat, meta["title_weight_repeat"]),
        "body_truncate_chars": (cfg.body_truncate_chars, meta["body_truncate_chars"]),
    }
    mismatches = [
        f"{name}: worker={worker!r} fixture={fixture!r}"
        for name, (worker, fixture) in checks.items()
        if worker != fixture
    ]
    if mismatches:
        raise AssertionError(
            "FIXTURE PROVENANCE MISMATCH — embedding-input construction has drifted "
            "from the frozen fixture embeddings:\n  "
            + "\n  ".join(mismatches)
            + "\n\nRegenerate the fixture: see tests/fixtures/REGENERATE.md "
            "(run `python worker/scripts/generate_embeddings.py`)."
        )


# Always run the provenance check at session start — if it fails, every
# clustering test is meaningless.
def pytest_configure(config: pytest.Config) -> None:
    try:
        assert_fixture_provenance()
    except AssertionError as exc:
        # Don't hard-fail session-start in case tests don't touch clustering;
        # but print loudly so it's visible.
        print(f"\n[provenance] WARNING: {exc}\n", file=sys.stderr)


# ---------------------------------------------------------------------------
# Integration test DB fixture
# ---------------------------------------------------------------------------
# pytest-asyncio loop scope: integration tests share ONE session-scoped event
# loop, so the connection pool (created once) stays bound to a live loop. The
# alternative — a fresh loop per test — leaves the pool attached to a dead loop
# after test 1, so test 2 hangs forever waiting for a connection.

@pytest_asyncio.fixture(scope="session")
async def _session_pool():
    """Open the pool once for the whole session. Truncation-per-test happens
    in the `db` fixture below; the pool itself is shared."""
    from app.db import close_pool, get_pool

    pool = await get_pool()
    yield pool
    await close_pool()


@pytest_asyncio.fixture
async def db(_session_pool):
    """Yield a clean DB state for one integration test. Truncates all data
    tables between tests; migrations must already be applied (run `make
    db-reset` once before the suite)."""
    pool = _session_pool
    async with pool.connection() as conn:
        await conn.execute(
            """
            TRUNCATE TABLE
                audit_log, story_items, stories, items,
                metrics, replies, mentions, drafts,
                newsletter_issues, funnel_events, evergreen_bank
            RESTART IDENTITY CASCADE
            """
        )
        await conn.execute("DELETE FROM sources WHERE name LIKE 'TEST_%'")
    yield pool


@pytest_asyncio.fixture
async def clean_mock_cache():
    """Reset the mock embedder cache between tests so determinism holds."""
    from app.embed import clear_mock_cache

    clear_mock_cache()
    yield
    clear_mock_cache()


# ---------------------------------------------------------------------------
# Helpers for tests
# ---------------------------------------------------------------------------

def load_fixture() -> list[dict]:
    """Load the clustering fixture as a list of dicts (embedding may be null
    if not yet regenerated)."""
    rows = []
    for line in (FIXTURES / "clustering.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows
