# Clustering threshold tuning notes

## Pass threshold (Part II §5.3)

| Criterion | Value |
|---|---|
| **FP pair ceiling** | **≤ 2** (load-bearing, absolute) |
| Precision floor | ≥ 0.85 |
| Recall floor | ≥ 0.50 |

**Under-merge bias is the design.** A visible duplicate costs one Snooze
click; a silently-eaten story costs you ever seeing it. The FP ceiling is
absolute precisely because at small N, rates are jittery (one stray FP moves
precision by ~2-3%).

### The FP ceiling is N-coupled

Express intent as: **"≤ ~5% of true-different pairs wrongly merged, floored
at an absolute 2 for small-N."** At the current fixture (N=30, 421 true-diff
pairs), 5% = 21, so the absolute floor of 2 dominates. When the fixture grows
past ~80 items (where 5% exceeds 2), re-derive the ceiling as `ceil(0.05 *
true_diff_pairs)` and update both this doc and `test_clustering_acceptance.py`.

## Tuning workflow

```bash
python worker/scripts/run_clustering_test.py   # prints FP / P / R
```

1. If `FP > 2`: raise `clustering.similarity_threshold` in the `config` table
   (or `003_seed_sources.sql` for a fresh DB). Re-run.
2. If `recall < 0.50` AND FP headroom allows: lower the threshold. Re-run.
3. If neither moves the needle, the issue is the embedding model or input
   construction — regenerate the fixture (see REGENERATE.md) after changing
   `title_weight_repeat` or `body_truncate_chars`.
4. **Commit the threshold and the fixture together.** They're a matched pair;
   a threshold without its fixture is meaningless.

## HNSW vs exact-cosine assumption (engine caveat — Part II §5.4 ⟢)

The acceptance runner scores **exact cosine in-memory** (deterministic, no DB).
Production enforces the same `similarity_threshold` over a pgvector **HNSW**
index, which is *approximate* nearest-neighbor. The threshold is tuned in one
engine and enforced in another.

At P1 scale (low thousands of rows, `m=16, ef_construction=64`), HNSW recall
is near-exact and the two engines agree for practical purposes. **This is
written down, not assumed:**

- (a) The gate assumes HNSW ≈ exact at P1 scale.
- (b) The live smoke (`make smoke`, §5.5 Layer 2) is where real divergence
  would surface in practice — it runs through the real DB.
- (c) **If the corpus grows past ~10k rows**, HNSW recall must be re-measured
  (run a query, compare to a brute-force cosine over the same embeddings) and
  the threshold re-validated against pgvector directly. Do not let the number
  that gates the whole phase quietly live in two engines.

The two-engine gap is benign today; the discipline is checking it stays
benign as the system grows.
