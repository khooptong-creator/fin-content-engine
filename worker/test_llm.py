"""Standalone smoke check for script generation. Not part of the pytest suite.

Run it by hand with GEMINI_API_KEY set. It builds a Channel inline rather than
resolving one from the database, so it needs no Postgres:

    ..\\.venv\\Scripts\\python.exe test_llm.py
"""

import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

from app.channels import Channel
from app.youtube import _generate_script_for_story

# A stand-in for a resolved channel. Kept in sync with the real config only in
# shape — the point is to exercise the LLM call, not the config path.
SMOKE_CHANNEL = Channel(
    id="smoke",
    display_name="Smoke Test",
    voice_key="adult_male",
    script_prompt=(
        "You are a casual, humorous, and informative adult male narrator "
        "explaining finance news."
    ),
    extra_blocklist=(),
)


async def main():
    if not os.environ.get("GEMINI_API_KEY"):
        print("Please set GEMINI_API_KEY environment variable.")
        return

    story = {"headline": "Federal Reserve Cuts Interest Rates by 50 Basis Points"}

    print(f"Generating script for: {story['headline']}")
    script_content = await _generate_script_for_story(story, SMOKE_CHANNEL)

    print("\n--- GENERATED SCRIPT ---")
    print(script_content)


if __name__ == "__main__":
    import sys

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
