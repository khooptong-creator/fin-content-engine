# Regenerating the clustering fixture embeddings

The frozen embeddings in `clustering.jsonl` are the contract between this test
and the worker's embedding pipeline. **They must be regenerated whenever ANY
of these change** (see `_model.json`):

- `model` — swapping gte-small for text-embedding-004 (Part II §1.2 swap target)
- `dim` — embedding dimensionality
- `title_weight_repeat` — how many times the title is repeated in the input
- `body_truncate_chars` — how many body characters are included

The provenance assertion in `tests/conftest.py::assert_fixture_provenance()`
checks `_model.json` against the worker's configured values and **fails loud**
on mismatch — it will not let you silently run a stale fixture.

## When to regenerate

If the assertion fails with a "regenerate fixture" message, do this:

```bash
# 1. Install the model locally (one-time):
#    pip install sentence-transformers
# 2. Regenerate:
python worker/scripts/generate_embeddings.py
# 3. Re-run the test — it should pass now.
```

The script writes a fresh `clustering.jsonl` with the `embedding` field filled.
It does NOT change `id`, `title`, `body`, `true_story_id`, or `source`.

## Why we freeze instead of calling the edge function in tests

1. **Determinism.** Same input → same frozen vector, every run. Calling the
   edge function would couple the test to network + Supabase uptime.
2. **CI-runnable.** No credentials, no Docker for the embedding model.
3. **The fixture tests the threshold + algorithm, not the model.** gte-small
   is a black box we trust until the fixture proves it wrong. If precision/
   recall on the fixture is bad, *then* we consider swapping models.

The trade-off: regeneration is a manual step on model/construction change.
The provenance assertion exists precisely so this trade-off can't silently
let a stale fixture pass the gate.
