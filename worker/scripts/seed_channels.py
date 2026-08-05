"""One-time copy of the active voice profile into the channels config.

Values are carried forward, not recreated, so the finance channel keeps the
prompt that has been producing content. Terms already in BASE_BLOCKLIST are not
duplicated into extra_blocklist: the base set is unioned in at read time.

Run once:  ..\\.venv\\Scripts\\python.exe -m scripts.seed_channels
"""

from __future__ import annotations

import asyncio
import sys

from app import db
from app.channels import BASE_BLOCKLIST, CONFIG_KEY


def build_channels_payload(voice_profiles: dict | None) -> dict:
    from app.youtube import VOICE_MAP

    if not voice_profiles or not voice_profiles.get("profiles"):
        raise ValueError("no voice_profiles config to migrate from")

    profiles = voice_profiles["profiles"]
    active_id = voice_profiles.get("activeProfileId") or profiles[0]["id"]
    active = next((p for p in profiles if p.get("id") == active_id), profiles[0])
    baby = next((p for p in profiles if p.get("id") == "baby"), None)

    def extras(profile: dict) -> list[str]:
        return [t for t in (profile.get("blocklist") or []) if t not in BASE_BLOCKLIST]

    def check_voice_key(voice_key: str) -> str:
        if voice_key not in VOICE_MAP:
            valid = ", ".join(sorted(VOICE_MAP))
            raise ValueError(
                f"voice_key {voice_key!r} is not a recognized voice; valid keys: {valid}"
            )
        return voice_key

    payload = {
        "finance": {
            "display_name": "Finance",
            "voice_key": check_voice_key(active["id"]),
            "script_prompt": active["prompt"],
            "extra_blocklist": extras(active),
        }
    }

    if baby:
        payload["kids"] = {
            "display_name": "Kids",
            "voice_key": check_voice_key("baby"),
            "script_prompt": baby["prompt"],
            "extra_blocklist": extras(baby),
        }

    return payload


async def main() -> None:
    voice_profiles = await db.get_config("voice_profiles")
    payload = build_channels_payload(voice_profiles)
    await db.set_config(CONFIG_KEY, payload)
    print(f"wrote {CONFIG_KEY}: {', '.join(sorted(payload))}")


if __name__ == "__main__":
    # psycopg's async pool cannot run on the ProactorEventLoop, Python's default
    # on Windows, and times out after 30s with "Psycopg cannot use the
    # 'ProactorEventLoop' to run in async mode". run_worker.py documents the same
    # problem; an explicit loop_factory is what works.
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    asyncio.run(main(), loop_factory=loop_factory)
