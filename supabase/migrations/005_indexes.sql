-- Fin-Content Engine — indexes (Part II §2.4).
-- Split from 001_init so 001 stays pure schema. Idempotent via IF NOT EXISTS.

-- Dedup guarantee (the §1.5 exact-dupe bar): enforced at write time via this unique index.
CREATE UNIQUE INDEX IF NOT EXISTS items_hash_uidx ON items(hash);

-- Poller's "recent items from this source" lookup.
CREATE INDEX IF NOT EXISTS items_source_published_idx ON items(source_id, published_at DESC);

-- Clustering: approximate nearest-neighbor search over embeddings.
-- HNSW over ivfflat: no training step, works at our scale (low thousands of rows).
CREATE INDEX IF NOT EXISTS items_embedding_hnsw_idx ON items
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Story link table lookups (both directions).
CREATE INDEX IF NOT EXISTS story_items_item_idx ON story_items(item_id);
CREATE INDEX IF NOT EXISTS story_items_story_idx ON story_items(story_id);

-- Future Inbox query (P2) — cheap to add now.
CREATE INDEX IF NOT EXISTS stories_status_created_idx ON stories(status, created_at DESC);
