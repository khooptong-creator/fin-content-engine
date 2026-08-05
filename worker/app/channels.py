"""Per-channel configuration.

One engine serves more than one YouTube channel. A channel supplies the voice
and the script prompt; it does not supply the compliance rules. Those are the
constants below, and a channel can only add to the blocklist, never remove from
it, so there is no config edit or GUI control that can switch compliance off.

Config lives in the `config` table under the key `channels`. Read it through
`resolve()`, which validates once and returns a frozen object. Nothing else
should interpret the raw dict.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from app import db

log = structlog.get_logger()

CONFIG_KEY = "channels"

# Applied to every channel, unconditionally. Not configurable by design: in the
# config table this was one careless GUI edit away from removal, and the edit
# would leave no trace.
BASE_COMPLIANCE_RULES = (
    "Do not provide financial advice. "
    "Do not recommend buying or selling any specific security or product. "
    "Explain what happened and why it is interesting, never what the viewer should do."
)

BASE_BLOCKLIST: tuple[str, ...] = (
    "buy",
    "sell",
    "accumulate",
    "target price",
    "multibagger",
    "sure shot",
)

REQUIRED_FIELDS = ("display_name", "voice_key", "script_prompt")


class ChannelConfigError(Exception):
    """Channel config is absent, unknown, or incomplete. Never recovered from."""


@dataclass(frozen=True)
class Channel:
    id: str
    display_name: str
    voice_key: str
    script_prompt: str
    extra_blocklist: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        for name in REQUIRED_FIELDS + ("id",):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ChannelConfigError(
                    f"channel field '{name}' is missing or empty"
                )

        # Imported here, not at module scope: youtube.py imports this module,
        # so a top-level import would be circular.
        from app.youtube import VOICE_MAP

        if self.voice_key not in VOICE_MAP:
            raise ChannelConfigError(
                f"channel '{self.id}' has unknown voice_key '{self.voice_key}'; "
                f"known keys: {', '.join(sorted(VOICE_MAP))}"
            )

    @property
    def effective_blocklist(self) -> tuple[str, ...]:
        """Base terms plus this channel's extras, order-stable and deduplicated.

        A union, not an override. Removing a base term is not expressible.
        """
        seen: list[str] = list(BASE_BLOCKLIST)
        for term in self.extra_blocklist:
            if term not in seen:
                seen.append(term)
        return tuple(seen)


async def resolve(channel_id: str) -> Channel:
    """Load and validate one channel. Raises ChannelConfigError on any problem."""
    if not channel_id or not channel_id.strip():
        raise ChannelConfigError("channel_id is required and was empty")

    config = await db.get_config(CONFIG_KEY)
    if not config:
        raise ChannelConfigError(
            f"no '{CONFIG_KEY}' config found; run worker/scripts/seed_channels.py"
        )

    raw = config.get(channel_id)
    if raw is None:
        raise ChannelConfigError(
            f"unknown channel '{channel_id}'; configured: {', '.join(sorted(config))}"
        )

    missing = [f for f in REQUIRED_FIELDS if not raw.get(f)]
    if missing:
        raise ChannelConfigError(
            f"channel '{channel_id}' is missing required field(s): {', '.join(missing)}"
        )

    channel = Channel(
        id=channel_id,
        display_name=raw["display_name"],
        voice_key=raw["voice_key"],
        script_prompt=raw["script_prompt"],
        extra_blocklist=tuple(raw.get("extra_blocklist") or ()),
    )
    log.info("channel_resolved", channel_id=channel_id, voice_key=channel.voice_key)
    return channel
