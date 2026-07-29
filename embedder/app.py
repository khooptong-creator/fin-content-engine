"""Fin-Content Engine — local embedding service (Option C).

Tiny FastAPI app wrapping `sentence-transformers/gte-small` (384-dim). Runs on
the VPS as its own systemd service (`fce-embedder.service`), listening on
127.0.0.1:8001. Same request/response contract as the Supabase edge function
it replaces — drop-in:

    POST /embed
    {"text": "..."}
    → {"embedding": [0.01, -0.04, ...]}   (384 floats)

Why this exists: Supabase's hosted gte-small runtime OOM-killed on the free tier
(`EarlyDrop`, ~10MB memory ceiling). Self-hosting on the VPS (8GB RAM, the model
is ~130MB resident) removes that failure mode, adds no external dependency,
matches the self-host-Postgres decision, and is ~10ms localhost latency vs
~200ms to cloud.

The model loads once at startup (~3-5s cold start) and stays resident; subsequent
calls are ~10-30ms. This is the right shape: one long-lived process holding the
model, the worker hitting it cheaply over localhost.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

# Match the worker's expected dimensionality (Part II §1.2). If this changes,
# the `items.embedding` column, the fixture, and the worker config all need to
# move together — see tests/fixtures/REGENERATE.md.
EMBEDDING_DIM = 384
MODEL_NAME = os.environ.get("FCE_EMBED_MODEL", "thenlper/gte-small")

_state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load the model once at startup; keep it resident in _state.
    print(f"loading model: {MODEL_NAME}", flush=True)
    _state["model"] = SentenceTransformer(MODEL_NAME)
    # sentence-transformers 5.x renamed get_sentence_embedding_dimension →
    # get_embedding_dimension. Use the new name; fall back for older versions.
    dim_fn = getattr(
        _state["model"],
        "get_embedding_dimension",
        getattr(_state["model"], "get_sentence_embedding_dimension"),
    )
    dim = dim_fn()
    if dim != EMBEDDING_DIM:
        raise RuntimeError(
            f"model {MODEL_NAME} returns {dim}-dim embeddings; "
            f"expected {EMBEDDING_DIM}. Either change the model or update EMBEDDING_DIM + the schema."
        )
    print(f"model ready (dim={dim})", flush=True)
    yield
    _state.clear()


app = FastAPI(title="fce-embedder", version="0.1.0", lifespan=lifespan)


class EmbedRequest(BaseModel):
    text: str


class EmbedResponse(BaseModel):
    embedding: list[float]


@app.post("/embed", response_model=EmbedResponse)
async def embed(req: EmbedRequest) -> EmbedResponse:
    """Embed a single text. Truncate defensively (the worker already truncates
    body to 500 chars + repeats the title; this is a safety net)."""
    if not req.text:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="missing 'text' field")
    text = req.text[:2000]
    # SentenceTransformer.encode is sync (CPU-bound) but fast (~10-30ms at this size);
    # for our volume (hundreds of calls per poll cycle) the GIL cost is negligible.
    vec = _state["model"].encode(text, normalize_embeddings=True, show_progress_bar=False)
    return EmbedResponse(embedding=[float(x) for x in vec.tolist()])


@app.get("/health")
async def health() -> dict:
    """Liveness probe for systemd / the worker's startup check."""
    return {
        "status": "up",
        "model_loaded": "model" in _state,
        "model": MODEL_NAME,
        "dim": EMBEDDING_DIM,
    }
