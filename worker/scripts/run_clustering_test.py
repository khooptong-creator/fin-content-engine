#!/usr/bin/env python3
"""Standalone clustering test runner — prints FP/precision/recall for tuning.

This is the script TUNING.md references. It loads the fixture, runs the same
DI'd clusterer that test_clustering_acceptance.py uses, and prints the numbers
so you can sweep the threshold without editing test code.

Usage:
    python worker/scripts/run_clustering_test.py              # uses config threshold
    python worker/scripts/run_clustering_test.py --threshold 0.90
    python worker/scripts/run_clustering_test.py --sweep      # sweep 0.80-0.96

The fixture must have real gte-small embeddings (run generate_embeddings.py
first if the `embedding` fields are null).
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

# Allow `from tests.conftest import load_fixture` and `from app...`.
WORKER_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKER_ROOT))

from app.cluster import cosine_similarity, extract_tokens  # noqa: E402


def load_fixture() -> list[dict]:
    rows = []
    fx = WORKER_ROOT / "tests" / "fixtures" / "clustering.jsonl"
    for line in fx.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def run(items: list[dict], threshold: float, min_tokens: int = 2) -> dict:
    """Pure-Python clusterer mirroring cluster.cluster_new_items' logic."""
    assignment = {item["id"]: item["id"] for item in items}

    def find(x: str) -> str:
        while assignment[x] != x:
            assignment[x] = assignment[assignment[x]]
            x = assignment[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            assignment[ra] = rb

    seen: list[dict] = []
    for item in items:
        best_match: str | None = None
        best_sim = 0.0
        if item.get("embedding"):
            for s in seen:
                if s.get("embedding"):
                    sim = cosine_similarity(item["embedding"], s["embedding"])
                    if sim >= threshold and sim > best_sim:
                        best_sim = sim
                        best_match = s["id"]
        if best_match is None:
            item_tokens = extract_tokens(item["title"])
            if len(item_tokens) >= min_tokens:
                best_overlap = 0
                for s in seen:
                    overlap = len(item_tokens & extract_tokens(s["title"]))
                    if overlap >= min_tokens and overlap > best_overlap:
                        best_overlap = overlap
                        best_match = s["id"]
        if best_match is not None:
            union(item["id"], best_match)
        seen.append(item)

    pred = {item_id: find(item_id) for item_id in assignment}

    pairs = list(itertools.combinations(items, 2))
    tp = sum(1 for a, b in pairs if _same(a, b) and pred[a["id"]] == pred[b["id"]])
    fp = sum(1 for a, b in pairs if not _same(a, b) and pred[a["id"]] == pred[b["id"]])
    fn = sum(1 for a, b in pairs if _same(a, b) and pred[a["id"]] != pred[b["id"]])
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    return {
        "threshold": threshold,
        "tp": tp, "fp": fp, "fn": fn,
        "precision": precision, "recall": recall,
        "pass": fp <= 2 and precision >= 0.85 and recall >= 0.50,
    }


def _same(a: dict, b: dict) -> bool:
    return a["true_story_id"] == b["true_story_id"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Clustering threshold sweep / single-run.")
    parser.add_argument("--threshold", type=float, default=None, help="single threshold (default: config 0.92)")
    parser.add_argument("--sweep", action="store_true", help="sweep 0.80-0.96")
    args = parser.parse_args()

    items = load_fixture()
    needs_embeddings = any(it.get("embedding") is None for it in items)
    if needs_embeddings:
        print("ERROR: fixture has null embeddings. Run generate_embeddings.py first.", file=sys.stderr)
        return 1

    if args.sweep:
        print(f"{'thresh':>7} {'TP':>3} {'FP':>3} {'FN':>3} {'P':>6} {'R':>6}  result")
        for t in [0.80, 0.82, 0.84, 0.86, 0.88, 0.90, 0.91, 0.92, 0.93, 0.94, 0.95, 0.96]:
            r = run(items, t)
            print(f"{t:>7.2f} {r['tp']:>3} {r['fp']:>3} {r['fn']:>3} "
                  f"{r['precision']:>6.3f} {r['recall']:>6.3f}  {'PASS' if r['pass'] else ''}")
    else:
        t = args.threshold if args.threshold is not None else 0.92
        r = run(items, t)
        print(f"threshold={t} | TP={r['tp']} FP={r['fp']} FN={r['fn']} | "
              f"precision={r['precision']:.3f} recall={r['recall']:.3f} | "
              f"{'PASS' if r['pass'] else 'FAIL'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
