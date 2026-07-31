import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load env vars
load_dotenv()

from app.youtube import _generate_audio_for_script

async def main():
    script_content = """---
title: "TTS Test"
preset: adult_male
---

# Video direction
A clean explainer video.

# Scene 1
Voiceover: "Hello! This is a test of the ElevenLabs integration."
Visual: A smiling face.

# Scene 2
**Voiceover:** "We are ensuring the markdown parser correctly picks up these lines."
Visual: A checklist.

# Scene 3
Voiceover: "And this should be the final line spoken."
"""
    
    output_path = Path("test_audio.mp3")
    if output_path.exists():
        output_path.unlink()
        
    print("Generating audio...")
    await _generate_audio_for_script(script_content, output_path)
    
    if output_path.exists():
        size = output_path.stat().st_size
        print(f"Success! Audio file generated at {output_path} ({size} bytes)")
    else:
        print("Failure: Audio file was not created.")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
