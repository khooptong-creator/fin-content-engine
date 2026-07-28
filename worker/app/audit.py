"""audit_log helper (Part II §2.6).

The audit_log is the durable event trail. P1 writes ingest/clustering events;
P2 will write compliance events into the same table (convention only, no
migration needed — the schema already accommodates it).
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from app.db import get_pool

log = structlog.get_logger()


async def audit_log(
    *,
    actor: str,
    action: str,
    entity: str | None,
    entity_type: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    """Append a durable event to audit_log. Never raises — failures are logged."""
    pool = await get_pool()
    try:
        async with pool.connection() as conn:
            await conn.execute(
                """
                INSERT INTO audit_log (actor, action, entity, entity_type, before, after)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb)
                """,
                (
                    actor,
                    action,
                    entity,
                    entity_type,
                    _to_json(before),
                    _to_json(after),
                ),
            )
    except Exception as exc:  # noqa: BLE001 — audit must never break the caller
        log.error(
            "audit_log_write_failed",
            actor=actor,
            action=action,
            entity=entity,
            error=str(exc),
        )


def _to_json(value: dict[str, Any] | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, default=str)
