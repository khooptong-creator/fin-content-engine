import asyncio
import os
from dotenv import load_dotenv

# Load .env
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from app import db
from app.ingest import run_all_sources
from app.cluster import cluster_new_items
from app.ideation import autopilot_job

async def main():
    print("Activating sources...")
    pool = await db.get_pool()
    async with pool.connection() as conn:
        await conn.execute("UPDATE sources SET active = true WHERE name NOT LIKE 'Mock%' AND name NOT LIKE 'TEST%'")
    
    print("Running ingest...")
    await run_all_sources()
    
    print("Running clustering...")
    await cluster_new_items()
    
    print("Running autopilot...")
    await autopilot_job()
    
    print("Done!")

if __name__ == "__main__":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
