#!/usr/bin/env python3
"""Regenerate the frozen embeddings in clustering.jsonl.

Uses the same input construction as the worker (app.embed.build_embedding_input):
`<title> ×N + first K chars of body`. Writes a new clustering.jsonl with the
`embedding` field filled, leaving all other fields unchanged.

Run this whenever _model.json's values change (model swap, title_weight_repeat,
body_truncate_chars). See tests/fixtures/REGENERATE.md.

Requires `sentence-transformers` (pip install sentence-transformers) — NOT a
worker dependency, intentionally, so the worker image stays lean.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "clustering.jsonl"
MODEL_FILE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "_model.json"


def build_input(title: str, body: str, title_repeat: int, body_chars: int) -> str:
    title = (title or "").strip()
    body = (body or "")[:body_chars]
    return (" ".join([title] * max(1, title_repeat)) + " " + body).strip()


def main() -> int:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print(
            "ERROR: sentence-transformers not installed.\n"
            "  pip install sentence-transformers\n"
            "This is a fixture-maintenance dependency, not a worker dependency.",
            file=sys.stderr,
        )
        return 1

    meta = json.loads(MODEL_FILE.read_text(encoding="utf-8"))
    model_name = meta["model"]
    title_repeat = meta["title_weight_repeat"]
    body_chars = meta["body_truncate_chars"]

    print(f"loading model: {model_name}", file=sys.stderr)
    # gte-small is hosted at thenlper/gte-small on HuggingFace (Supabase's edge
    # function uses the same model weights under the hood).
    model = SentenceTransformer(f"thenlper/{model_name}")

    rows = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines() if line.strip()]
    inputs = [build_input(r["title"], r.get("body", ""), title_repeat, body_chars) for r in rows]
    print(f"embedding {len(rows)} items...", file=sys.stderr)
    vectors = model.encode(inputs, normalize_embeddings=True, show_progress_bar=False)

    out_lines = []
    for row, vec in zip(rows, vectors, strict=True):
        row["embedding"] = [float(x) for x in vec.tolist()]
        out_lines.append(json.dumps(row, ensure_ascii=False))
    FIXTURE.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} rows to {FIXTURE}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
