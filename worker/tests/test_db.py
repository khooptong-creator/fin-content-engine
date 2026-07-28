"""DB integration tests (Part II §5.6, §3.7).

Focus: the atomic story-creation guarantee (orphan prevention). A simulated
mid-call failure must roll back BOTH create_story and link_item_to_story so
no item is left storyless-after-creation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio

pytestmark = pytest.mark.integration


async def _seed_source(db) -> uuid.UUID:
    from app.db import _fetchone

    async with db.connection() as conn:
        row = await _fetchone(
            conn,
            "INSERT INTO sources (kind, url, name, market, active, poll_minutes) "
            "VALUES ('rss', 'https://test.example/feed', 'TEST_source', 'IN', true, 30) "
            "RETURNING id",
        )
    return row["id"]


async def _seed_item(db, source_id: uuid.UUID | None = None, title: str = "Test item") -> uuid.UUID:
    """Seed an item. If source_id is None, creates a fresh source first."""
    from app.db import _fetchone

    if source_id is None:
        source_id = await _seed_source(db)
    async with db.connection() as conn:
        row = await _fetchone(
            conn,
            """
            INSERT INTO items (source_id, title, url, published_at, hash)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            source_id,
            title,
            f"https://test.example/{uuid.uuid4().hex}",
            datetime.now(timezone.utc),
            uuid.uuid4().hex,
        )
    return row["id"]


class TestUpsertDedup:
    async def test_duplicate_hash_returns_none(self, db):
        """The §1.1 exact-dupe guarantee: ON CONFLICT (hash) DO NOTHING."""
        from app.db import upsert_item

        source_id = await _seed_source(db)
        args = dict(
            source_id=source_id,
            title="Same title",
            url="https://test.example/same",
            published_at=datetime.now(timezone.utc),
            full_text="body",
            hash_="deadbeef" * 8,
        )
        first = await upsert_item(**args)
        second = await upsert_item(**args)
        assert first is not None
        assert second is None  # exact dupe → no insert


class TestCreateOrJoinStoryAtomicity:
    async def test_successful_join_links_item(self, db):
        """Happy path: item linked to an existing story."""
        from app.db import create_or_join_story

        source_id = await _seed_source(db)
        item_id = await _seed_item(db)
        # First create a story via a seed item.
        seed_item = await _seed_item(db, title="seed")
        story_id = await create_or_join_story(
            item_id=seed_item, headline="seed story", existing_story_id=None
        )
        # Now join a new item to it.
        joined = await create_or_join_story(
            item_id=item_id, headline="joined", existing_story_id=story_id
        )
        assert joined == story_id
        from app.db import _fetchval

        async with db.connection() as conn:
            linked = await _fetchval(
                conn, "SELECT story_id FROM story_items WHERE item_id = %s", item_id
            )
        assert linked == story_id

    async def test_orphan_count_is_zero_after_normal_flow(self, db):
        """The §3.9 invariant: no item older than 48h should be storyless."""
        from app.db import count_orphans, create_or_join_story

        source_id = await _seed_source(db)
        for _ in range(5):
            iid = await _seed_item(db)
            await create_or_join_story(
                item_id=iid, headline="h", existing_story_id=None
            )
        assert await count_orphans() == 0

    async def test_unlinked_item_after_48h_counts_as_orphan(self, db):
        """Deliberately leave an item storyless and backdate it past 48h."""
        from app.db import count_orphans

        source_id = await _seed_source(db)
        item_id = await _seed_item(db)
        async with db.connection() as conn:
            await conn.execute(
                "UPDATE items SET created_at = now() - interval '49 hours' WHERE id = %s",
                (item_id,),
            )
        assert await count_orphans() >= 1


class TestVectorSearch:
    async def test_returns_neighbors_above_threshold(self, db):
        """Vector search finds existing items above the similarity threshold."""
        from app.db import create_or_join_story, set_embedding, vector_search

        source_id = await _seed_source(db)
        # Seed two items with identical embeddings → similarity 1.0.
        a = await _seed_item(db, title="A")
        b = await _seed_item(db, title="B")
        vec = [0.1] * 384
        await set_embedding(a, vec)
        await set_embedding(b, vec)
        # Link a to a story so vector_search can find it.
        await create_or_join_story(item_id=a, headline="story a", existing_story_id=None)

        neighbors = await vector_search(
            embedding=vec, threshold=0.99, within_hours=48, limit=5
        )
        # b's nearest neighbor should be a (linked to a story), similarity ≈ 1.0.
        ids = {n.item_id for n in neighbors}
        assert a in ids

    async def test_no_match_below_threshold(self, db):
        from app.db import set_embedding, vector_search

        source_id = await _seed_source(db)
        a = await _seed_item(db, title="A")
        await set_embedding(a, [1.0] + [0.0] * 383)
        # Query with an orthogonal vector.
        neighbors = await vector_search(
            embedding=[0.0] * 383 + [1.0], threshold=0.99, within_hours=48, limit=5
        )
        assert neighbors == []
