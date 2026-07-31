import asyncio
import uuid
import datetime
from app.db import get_pool

async def seed_story():
    pool = await get_pool()
    async with pool.connection() as conn:
        # Create a mock source
        source_id = str(uuid.uuid4())
        await conn.execute(
            "INSERT INTO sources (id, kind, url, name, market, active, poll_minutes) VALUES (%s, 'rss', 'http://example.com/rss', 'Mock Source', 'US', true, 60)",
            (source_id,)
        )
        
        # Create a mock item
        item_id = str(uuid.uuid4())
        await conn.execute(
            "INSERT INTO items (id, source_id, title, url, published_at, full_text, hash, warnings) VALUES (%s, %s, 'The Federal Reserve Signals Interest Rate Cuts', 'http://example.com/fed', %s, 'The Federal Reserve has signaled that interest rate cuts are coming in the next quarter...', 'mock_hash', '[]'::jsonb)",
            (item_id, source_id, datetime.datetime.now(datetime.timezone.utc))
        )
        
        # Create a mock story
        story_id = str(uuid.uuid4())
        await conn.execute(
            "INSERT INTO stories (id, headline, status) VALUES (%s, 'Fed Signals Interest Rate Cuts Incoming', 'inbox')",
            (story_id,)
        )
        
        # Link item to story
        await conn.execute(
            "INSERT INTO story_items (story_id, item_id) VALUES (%s, %s)",
            (story_id, item_id)
        )
        
    print(f"Seeded mock story: {story_id}")

if __name__ == "__main__":
    import sys
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(seed_story())
