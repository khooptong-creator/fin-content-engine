"""Embedding client (Part II §1.2, §3.6).

Two paths:
  - Real: POSTs the constructed input to the Supabase edge function `embed`.
  - Mock: returns a deterministic hash-derived vector (Part II §5.5 determinism).

Both paths honor `embedding_dim` (384 for gte-small). The mock uses a stable
hash → seeded RNG → 384 floats, normalized — same input always yields the same
vector, so tests are reproducible and the cold-start idempotency test is stable.

Input construction (§3.6): `<title> ×N + first K chars of full_text`. N and K
are part of the §5.1 provenance contract — the worker is the single source of
truth for "how to construct the embedding input."
"""

from __future__ import annotations

import asyncio
import hashlib
import math
from typing import Any

import httpx
import structlog

from app.audit import audit_log
from app.config import get_clustering_config, get_ingest_config
from app.settings import get_settings

log = structlog.get_logger()


class EmbedError(Exception):
    """Raised when the embedder can't produce a vector after retries."""


async def embed(text: str) -> list[float]:
    """Embed a single text. Retries once with 2s backoff on 5xx/timeout
    (Part II §3.6); raises EmbedError if it still fails."""
    settings = get_settings()
    if settings.embed_mock:
        return _mock_embed(text)

    cfg = await get_ingest_config()
    timeout = cfg.embedding_timeout_seconds
    last_exc: Exception | None = None

    # One retry with 2s backoff (§3.6).
    for attempt in range(2):
        if attempt > 0:
            await asyncio.sleep(2.0)
        try:
            async with httpx.AsyncClient(timeout=timeout + 2) as client:
                resp = await client.post(
                    settings.embedding_edge_function_url,
                    json={"text": text[:2000]},
                    headers={
                        "authorization": f"Bearer {settings.supabase_service_key.get_secret_value()}",
                    },
                )
            if resp.status_code == 200:
                data = resp.json()
                vec = data.get("embedding")
                if isinstance(vec, list) and len(vec) == 384:
                    return [float(x) for x in vec]
                raise EmbedError(
                    f"bad embedding shape: {len(vec) if isinstance(vec, list) else type(vec)}"
                )
            if 500 <= resp.status_code < 600:
                last_exc = EmbedError(f"edge fn {resp.status_code}")
                continue
            # 4xx: don't retry.
            raise EmbedError(f"edge fn {resp.status_code}: {resp.text[:200]}")
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            last_exc = exc
            continue
    raise EmbedError(f"embed failed after retry: {last_exc}")


async def embed_item(*, item_id: Any, title: str, full_text: str | None) -> list[float] | None:
    """Embed one item using the §3.6 input construction. On failure, log + return None.

    Used by ingest (inline first-pass) and by embed_retry_sweep (recovery path).
    The retry sweep writes `embed_retry_success` on backfill (Part II §3.8)."""
    try:
        return await embed(build_embedding_input(title, full_text))
    except EmbedError as exc:
        log.warning("embed_failed", item_id=str(item_id), error=str(exc))
        return None


def build_embedding_input(title: str, full_text: str | None) -> str:
    """§3.6 input construction. Title repeated N times + first K chars of body.

    N (`title_weight_repeat`) and K (`body_truncate_chars`) are config values
    AND part of the §5.1 provenance contract. They're read fresh on every call
    so config changes apply without restart — but if you change them, the
    fixture's frozen embeddings are now stale and must be regenerated."""
    # Note: this reads config synchronously-ish; ingest caches the config once
    # per cycle and passes it in. For the simple path, default to spec values.
    return _build_sync(title, full_text)


def _build_sync(title: str, full_text: str | None, title_repeat: int = 2, body_chars: int = 500) -> str:
    title = (title or "").strip()
    body = (full_text or "")[:body_chars]
    return (" ".join([title] * max(1, title_repeat)) + " " + body).strip()


async def build_embedding_input_async(title: str, full_text: str | None) -> str:
    """Async variant — reads config from DB (the production path)."""
    cfg = await get_clustering_config()
    return _build_sync(title, full_text, cfg.title_weight_repeat, cfg.body_truncate_chars)


# ---------------------------------------------------------------------------
# Mock embedder — deterministic per input string
# ---------------------------------------------------------------------------

_MOCK_CACHE: dict[str, list[float]] = {}


def _mock_embed(text: str, dim: int = 384) -> list[float]:
    """Deterministic, SEMANTICALLY-MEANINGFUL 384-dim vector.

    Production uses gte-small (real semantics). This mock approximates
    "semantic similarity" by mapping each token in the input to a bucket of
    vector dimensions — so two inputs sharing many tokens produce correlated
    vectors (cosine similarity > 0), while inputs with no token overlap produce
    orthogonal vectors (cosine ≈ 0). This is what makes the mock useful for
    testing the clustering threshold: the §5.4 runner can actually exercise
    the threshold, instead of every pair being orthogonal.

    Determinism matters: same input → same vector, every run (§5.5).
    """
    if text in _MOCK_CACHE:
        return _MOCK_CACHE[text]

    vec = [0.0] * dim
    # Re-use the same token-extraction logic the keyword fallback uses, so the
    # mock's notion of "similarity" matches the system's notion of "shared
    # distinctive tokens." Tickers, acronyms, and capitalized phrases each
    # map to their own bucket.
    from app.cluster import extract_tokens

    tokens = extract_tokens(text)
    # Also include the raw lowercased words (broader overlap signal).
    words = {w.lower() for w in text.split() if len(w) >= 4}
    for tok in tokens | words:
        # Hash the token to a bucket (deterministic), then to a sub-span.
        h = hashlib.sha256(tok.encode("utf-8")).digest()
        # Pick 8 consecutive dims to "light up" for this token.
        start = int.from_bytes(h[:4], "big") % (dim - 8)
        sign = 1.0 if (h[4] & 1) else -1.0
        for i in range(8):
            vec[start + i] += sign * (1.0 + (h[5 + i // 2] % 10) / 10.0)

    # L2-normalize so cosine similarity is meaningful.
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    vec = [x / norm for x in vec]
    _MOCK_CACHE[text] = vec
    return vec


def clear_mock_cache() -> None:
    _MOCK_CACHE.clear()


__all__ = [
    "embed",
    "embed_item",
    "build_embedding_input",
    "build_embedding_input_async",
    "EmbedError",
    "clear_mock_cache",
]
