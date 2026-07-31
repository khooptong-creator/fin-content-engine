import asyncio
import os
import uuid
import structlog
from dotenv import load_dotenv

load_dotenv()

# Ensure you have GEMINI_API_KEY exported in your terminal before running this.
from app.youtube import _generate_script_for_story
from app import db

async def main():
    if not os.environ.get("GEMINI_API_KEY"):
        print("Please set GEMINI_API_KEY environment variable.")
        return

    # Mock story
    story = {
        "headline": "Federal Reserve Cuts Interest Rates by 50 Basis Points"
    }
    
    print(f"Generating script for: {story['headline']}")
    
    # Needs db pool connection since _generate_script_for_story fetches config
    db.pool = await db.get_pool()
    
    script_content = await _generate_script_for_story(story, channel_id="test")
    
    print("\n--- GENERATED SCRIPT ---")
    print(script_content)

if __name__ == "__main__":
    import sys
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
