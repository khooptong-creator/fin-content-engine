# Fin-Content Engine — Phase 1 Design

**Codename:** The Cyborg Desk · Phase 1 (Spine + Reader)
**Date:** 2026-07-25
**Parent blueprint:** `Fin-Content Engine — Master Build Blueprint v1.0` (the "v1.0 blueprint")
**Scope of this document:** Phase 1 only. Phases 2–6 are out of scope here; this design defers to the v1.0 blueprint for their treatment.

---

## 0. Purpose & scope boundary

Phase 1 builds the **ingest pipeline**: sources (RSS, SEC EDGAR, NSE) → dedup → embedding → clustering → the `stories` table. **No GUI, no drafting, no compliance gate, no publishers in this phase.** The full schema is laid down now so later phases add columns, not tables.

### 0.1 Acceptance (the v1.0 bar, made testable)

> v1.0: *"stories table fills itself daily with clustered, deduped stories and zero duplicate spam."*

This decomposes into two distinct jobs with two distinct acceptance bars:

- **Exact dedup = 0.** Enforced by `ON CONFLICT (hash) DO NOTHING` on a SHA-256 over canonicalized title+url. Free, deterministic, non-negotiable. Verified by running ingest twice and asserting zero new inserts on the second run.
- **Near-dupe clustering.** The same story across outlets (Reuters + ET + Mint) is *corroboration, not spam* — it must merge into one story. Verified by precision/recall over a hand-labeled fixture (§5). Tuned to **favor under-merging**: a visible duplicate in the Inbox costs one Snooze click; a silently-eaten story costs you ever seeing it. The acceptance criterion is an absolute false-merge ceiling, not a rate target (§5.3).

### 0.2 What's deferred (scope fence)

| Component | Phase |
|---|---|
| Haiku scoring, drafting engine, compliance gate, voice pack | P2 |
| GUI (Next.js — to be confirmed at P3) | P3 |
| X + IG publishers | P4 |
| Reply engine | P5 |
| Analytics + feedback loop | P6 |
| LE price-table content triggers (movers, breadth, new highs/lows) | P2 — these are drafting concerns |
| NSE scraping | Out of scope entirely (§3.5); NSE may ship as `active=false` if no reliable RSS exists at build time |

### 0.3 Locked decisions from design review

These were settled during brainstorming and are not re-litigated here:

1. **GUI stack:** Next.js (provisional — confirmed at P3, no GUI in P1).
2. **Dry-run publisher pattern:** adopted for P4; not present in P1 code.
3. **Model router:** config-driven, defaults to Haiku + Gemini Flash. Kimi's rows remain in config but point to Flash until a Moonshot key exists. Not exercised in P1 (no LLM calls in P1).
4. **LE source:** registered as a config-driven source row in P1 with `active=false`. No poller logic. P1 acceptance does **not** depend on LE data being clean.
5. **Audit-log convention for compliance events (P2):** `audit_log(actor, action, entity, entity_type, before, after, at)` — the schema accommodates `('system','compliance_block','<draft_id>','draft', …)` with no migration in P2. P1 only writes ingest/clustering events.
6. **Gate rules for P2** (folded into the v1.0 blueprint, not part of P1 implementation): L1 short-circuits L2; replies go through the same gate; re-lint after human edit; log blocked/flagged events; resist a third automated LLM layer.

---

## 1. Architecture

Two deployables share one DB. **In P1 only the worker exists; the GUI deployable is added in P3.**

```
┌─────────────────────────────────┐
│  WORKER (Python 3.12 / FastAPI  │
│  + APScheduler, single replica) │
│                                 │
│  Cron jobs:                     │
│   - poll_rss     (30 min)       │
│   - poll_edgar   (60 min)       │
│   - cluster_new  (15 min)       │
│   - embed_retry  (30 min)       │
│   - db_health    (5 min)        │
│                                 │
│  HTTP: /health, /stats,         │
│        /ingest/trigger          │
└──────────────┬──────────────────┘
               │
               ▼
       ┌────────────────┐
       │  Supabase      │
       │  Postgres +    │
       │  pgvector      │
       │  + Edge Fn     │
       │  `embed`       │
       └────────────────┘
```

### 1.1 Why single-replica in P1

Multi-replica + in-process APScheduler is a footgun: two instances fire the same cron and race on every shared resource. Single replica removes that failure class at the deploy layer. If HA is ever needed, the answer is Postgres advisory locks (§4.6) — belt-and-suspenders, already shipped in P1 — but P1 targets `replicas=1`.

### 1.2 Embeddings: gte-small (384-dim) via Supabase edge function

| Model | Dim | Cost | Notes |
|---|---|---|---|
| **gte-small (chosen)** | 384 | $0, in-DB | News clustering doesn't need frontier embeddings. Zero new API surface. |
| text-embedding-004 (Google) | 768 | Free-tier generous | Swap target if fixture test disappoints. One-migration change. |
| text-embedding-3-small (OpenAI) | 1536 | Non-zero | New vendor + key. Rejected for P1. |

The embedding call lives in a Supabase Edge Function (`embed`) invoked from the worker over HTTP. Worker stays pure-Python; the model lives in the DB ecosystem. **Provenance assertion (load-bearing for §5):** the fixture's frozen embeddings must have been produced by the *same model* the worker uses. If the edge function model ever changes (Supabase upgrades `gte-small`, we swap to `text-embedding-004`), the fixture embeddings must be regenerated before the test is trustworthy again. This is documented in `tests/fixtures/REGENERATE.md` and asserted at test-load time (§5.1).

---

## 2. Data model & RLS

### 2.1 Full schema, laid down now

Migration `001_init.sql` creates **all** v1.0 §6 tables. P1 populates: `sources`, `items`, `stories`, `story_items`, `config`, `audit_log` (ingest events only). The rest exist empty so P2–P6 add columns, not tables.

### 2.2 P1-relevant tables

| Table | P1 status | Deviations from v1.0 §6 |
|---|---|---|
| `sources` | populated | Seeded in `003_seed_sources.sql`. LE row present with `active=false`. NSE row may be `active=false` per §3.5. |
| `items` | populated | Added `embedding vector(384) NULL` (pgvector). `hash` gets unique index. `full_text` nullable. |
| `stories` | populated | `score`, `angle`, `vertical` left NULL in P1 — they are P2 outputs. P1 sets `headline`, `status='inbox'`, `created_at`. |
| `story_items` | populated | Composite PK `(story_id, item_id)`. |
| `drafts`, `mentions`, `replies`, `prompts`, `metrics` | empty | Columns present; populated in later phases. |
| `config` | populated | Seeded: clustering, ingest, owner_uid (informational). See §2.6. |
| `audit_log` | populated (ingest only) | Added `entity_type` column (v1.0 had `entity` only — without `entity_type`, the `entity` column is an ambiguous polymorphic string). |

### 2.3 RLS: placeholder-uid, written now

P1 has no GUI and no exercised auth — the worker uses the Supabase **service-role key**, which bypasses RLS. RLS policies are written now so P3 doesn't need a migration:

```sql
-- 002_rls.sql
CREATE POLICY owner_only_select ON items FOR SELECT TO authenticated
  USING (auth.uid() = '<OWNER_UID>'::uuid);
-- … one policy per table …
-- REPLACE <OWNER_UID> after first magic-link login (P3).
```

Hardcoded placeholder chosen over a `config`-table read because `config` is itself RLS-protected — reading the owner uid from it creates a chicken-and-egg. One `ALTER POLICY` (or a `004_set_owner.sql` migration) swaps the placeholder after first login. Ugly but unambiguous and one-time.

### 2.4 Indexes

```sql
CREATE UNIQUE INDEX items_hash_uidx ON items(hash);
CREATE INDEX items_source_published_idx ON items(source_id, published_at DESC);
CREATE INDEX items_embedding_hnsw_idx ON items
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);
CREATE INDEX story_items_item_idx ON story_items(item_id);
CREATE INDEX story_items_story_idx ON story_items(story_id);
CREATE INDEX stories_status_created_idx ON stories(status, created_at DESC);
```

HNSW over ivfflat: no training step, works well at our scale (low thousands of rows). ivfflat wants `ANALYZE`-tuned lists which is premature.

### 2.5 Config seed

```json
{"key": "clustering", "value": {
  "similarity_threshold": 0.78,
  "embedding_model": "gte-small",
  "embedding_dim": 384,
  "min_items_for_story": 1,
  "max_story_age_hours": 48,
  "title_weight_repeat": 2,
  "keyword_fallback_min_tokens": 2
}}
{"key": "ingest", "value": {
  "rss_poll_minutes": 30,
  "edgar_poll_minutes": 60,
  "nse_poll_minutes": 30,
  "market_hours_only": false,
  "max_items_per_cycle": 50,
  "max_full_text_fetch_seconds": 10,
  "embedding_timeout_seconds": 5,
  "embedding_degraded_threshold": 0.20,
  "embedding_max_retries": 3
}}
{"key": "edgar", "value": {
  "form_types": ["8-K", "13F-HR"],
  "company_watch": []
}}
{"key": "owner_uid", "value": {"uid": null}}
```

`similarity_threshold: 0.78` is a starting guess; the fixture test (§5) sets the real value. `edgar.form_types` and `edgar.company_watch` live in the config table (not env) per the two-tier principle — the watchlist especially is a tune-often value. `edgar_user_agent` stays in env (it carries your email, is structural, rarely changes).

### 2.6 audit_log shape

```
audit_log(actor, action, entity, entity_type, before, after, at)
```

P1 events:
- `('system', 'ingest_run', '<source_id>', 'source', …, {items_fetched, items_new}, …)`
- `('system', 'ingest_error', '<source_id>', 'source', …, {error}, …)`
- `('system', 'ingest_unhealthy', '<source_id>', 'source', …, {consecutive_failures}, …)`
- `('system', 'cluster_new_story', '<story_id>', 'story', …, {seed_item_id}, …)`
- `('system', 'cluster_merge', '<story_id>', 'story', …, {item_ids_merged}, …)`
- `('system', 'cluster_embedding_missing', '<item_id>', 'item', …, {fallback:'keyword'}, …)`
- `('system', 'embedding_failed', '<item_id>', 'item', …, {reason, retries_left}, …)`
- `('system', 'embed_retry_success', '<item_id>', 'item', …, {was_null_for_minutes}, …)`
- `('system', 'advisory_lock_skip', '<key>', 'job', …, …)`
- `('system', 'embedding_degraded', null, 'cycle', …, {failed_fraction}, …)`
- `('system', 'worker_start', null, 'worker', …, {jobs:[...]}, …)`
- `('system', 'worker_stop', null, 'worker', …, …)`

P2 events (convention documented now, written in P2): `compliance_block`, `compliance_flag`, `approve`, `edit`, `reject`.

---

## 3. Sources & ingestion

### 3.1 Source abstraction

```python
# worker/app/sources/base.py
class Source(Protocol):
    kind: str   # "rss" | "edgar" | "nse" | "internal"
    async def fetch(self, source_row: SourceRow) -> list[RawItem]: ...
    async def normalize(self, raw: RawItem) -> NormalizedItem: ...
```

`RawItem` is pre-cleaning; `NormalizedItem` is what we store (cleaned title, canonicalized url, tz-aware UTC published_at, nullable full_text, SHA-256 hash, warnings list). The orchestrator (`worker/app/ingest.py`) does: `fetch → normalize → upsert (ON CONFLICT hash DO NOTHING) → embed new items inline (synchronous, within the poll job — see §3.6)`. There is **no embedding queue and no separate `embed_new` scheduled job.** Embeddings are computed as the tail step of each poll job, so by the time a poll returns, all newly-inserted items for that source are embedded (modulo transient failures, which the §3.8 retry sweep handles). This is why `test_cold_start_idempotent` (§5.5) can assert `embedding IS NULL == 0` immediately after `run_all_sources()` returns.

### 3.2 Poll cycle — one APScheduler job per source kind

One job iterates active sources of its kind; a bad source logs + continues, never killing the loop. Sequential within a kind (simpler; avoids hammering one feed). Promote to bounded-concurrency only if measured slow.

### 3.3 RSS module — failure modes handled

| Failure | Detection | Handling |
|---|---|---|
| Partial `full_text` (RSS gives 2-line summary) | `len < 500` chars after parse | Fetch article URL with `httpx` + `readability-lxml`, **time-boxed 10s**. On fail → `full_text=NULL`, `warnings=['full_text_extraction_failed']`, continue (item still clusterable by title). |
| Encoding gremlins | `charset-normalizer` on raw bytes | Decode + `html.unescape()`. Log `encoding_corrected` if detection disagreed with declared. |
| HTML error page with HTTP 200 | Content-type sniff + root element check | `SourceError('not_a_feed')`; skip source this cycle. |
| Missing/unparseable date | `feedparser` returns no struct_time | `published_at = fetched_at`, `warnings=['date_missing']`. Never block insertion. |
| URL tracker-param drift | Strip `utm_*`, `ref`, `fbclid`, `gclid`, …; lowercase host; strip trailing slash | Hash is computed on canonicalized URL → exact-dupe guarantee holds across tracker-laden URLs. |
| HTTP 429/5xx | Status | Respect `Retry-After`; else backoff `[1,2,4,8]s`. 3 fails in a row → `active=false` + `audit_log('ingest_unhealthy')` + continue. |
| Cold-start backlog | `count > max_items_per_cycle` (50) | Process newest-first; truncate at cap. |

URL canonicalization is explicit (see `canonicalize_url` in §3.3 of the design discussion) and applied **before** hashing.

### 3.4 SEC EDGAR module

- **Endpoint:** EDGAR current-filings Atom feed (`.../browse-edgar?action=getcurrent&type=8-K&output=atom`), plus a second feed for `13F-HR`.
- **Mandatory User-Agent** (EDGAR policy): `"Fin-Content Engine fin-content@<domain> (<name>)"`, from config, not hardcoded. No UA → 403.
- **Rate limit (10 req/s, no concurrency):** `asyncio.Semaphore(1)` + `0.1s` sleep. Nowhere near this in P1 but baked in.
- **Canonical ID:** accession number extracted from URL; hash on `accession + form_type`.
- **`full_text`:** store the filing index URL as `full_text` (authoritative landing page), `warnings=['edgar_index_url_only']`. Deep-fetching the document body is a P2 concern (drafter needs it; reader doesn't).
- **Filters:** forms in `config.edgar.form_types` (default `['8-K','13F-HR']`); filer name in `config.edgar.company_watch` (default empty → broad capture, you tune). Without the company filter, EDGAR floods the clusterer.

### 3.5 NSE module — scope-cut

NSE has no official announcements API. Three routes considered:

| Route | Verdict |
|---|---|
| Scrape HTML announcements page | **Rejected.** NSE blocks scrapers (403 + JS challenges), HTML drift, hostile ToS. Not worth the arms race. |
| Per-symbol CSV endpoint | Workable but narrow — requires pre-listed watchlist, catches nothing new. Deferred. |
| Third-party RSS / mirror | **Recommended for P1.** Inherits §3.3 hardening for free. |

**Decision:** P1 ships the RSS route. If no reliable NSE RSS exists at build time, **NSE ships `active=false`** with a documented comment, and the per-symbol CSV / scraping are revisited in P2. **P1 will not scrape NSE.** This is a deliberate scope-cut to protect the milestone; "Phase 1 has NSE" may overstate what ships if no RSS is available.

### 3.6 Embedding step

Embeddings computed **inline, at the tail of each poll job, only for newly-inserted items from that poll.** No separate queue, no separate `embed_new` scheduled job. The poll interval (30 min) ≫ worst-case embed time (cold start ~100s one-time, steady-state trivial), so inline embedding does not risk job overlap (`max_instances=1` backstops this regardless). The separate `embed_retry` job (§3.8) exists **only** for the failure-recovery path — it does not handle first-pass embedding.

```python
# worker/app/ingest.py — tail of each poll job
async def run_for_source(source_row):
    raw_items = await source.fetch(source_row)
    for raw in raw_items:
        normalized = await source.normalize(raw)
        item_id = db.upsert_item(normalized)         # ON CONFLICT (hash) DO NOTHING
        if item_id:                                   # None means dupe, already exists
            try:
                vec = await embed(title_weighted_text(normalized))
                db.set_embedding(item_id, vec)
            except EmbedError:
                db.append_warning(item_id, "embedding_failed")
                audit_log("system", "embedding_failed", item_id, "item", ...)
    # ↑ on return, every new item is embedded or marked failed-and-retryable
```

**Title-weighting:** embedding input is `<title> <title> <first 500 chars of full_text or "">`. Title repeated `title_weight_repeat` times (default 2). Article titles carry most of the "is this the same story" signal; bodies add outlet-specific noise. Biggest single lever on precision. **Both `title_weight_repeat` and the 500-char truncation are part of the embedding-input construction and are covered by the §5.1 provenance assertion** — changing either trips the same loud "regenerate fixture" failure as a model swap.

**Failure handling:** edge function 5xx or timeout (>5s) → retry once with 2s backoff; on second failure → `embedding IS NULL` + `warnings=['embedding_failed']` + `audit_log('embedding_failed')`. Item is still stored and clusterable by the keyword fallback (§3.7). If `>20%` of a cycle's new items fail → `audit_log('embedding_degraded')`, visible in `/stats`.

### 3.7 Clustering — algorithm

Separate APScheduler job (`cluster_poll_minutes=15`, cheaper than ingest, runs more often). Per-item:

1. **Embedding similarity (primary).** If embedding present, vector-search neighbors within `similarity_threshold` (0.78 start) and `max_story_age_hours=48`. Match → join closest existing story.
2. **Keyword fallback** (no embedding or no match). Extract tokens from the title: (a) `$TICKER` patterns (`$RELIANCE`, `$TSLA`), (b) all-caps tokens of length ≥2 (`TCS`, `RBI` — but not `A`, `I`), (c) Capitalized multi-word phrases matched as **single composite tokens** ("Tata Sons" = 1 token, "Tata Motors" = a *different* 1 token). Match against existing story headlines in last 48h; require **`keyword_fallback_min_tokens=2`** *distinct* tokens to match. Single-token match (e.g., "TCS" alone) is too promiscuous — that's the TCS-Q2-vs-buyback failure mode, and it's the explicit unit-test trap in §5.6. No match → new story.
3. **No match → new story.** `db.create_story(headline=item.title, status='inbox')` + `audit_log('cluster_new_story')`.

**Atomic story creation (orphan prevention):** `create_story` + `link_item_to_story` wrapped in a single DB transaction. A crash between the two calls now rolls both back — no storyless-after-creation items.

```python
async def create_or_join_story(item):
    async with db.transaction():
        story_id = existing_match or db.create_story(...)
        db.link_item_to_story(item.id, story_id)
```

**Stability rule:** once an item is clustered (by embedding or keyword), its story link is **frozen**. A late-arriving embedding (from the retry sweep) is stored (P2 scoring uses it) but does **not** trigger re-clustering. Re-clustering creates churn — an item flickering between stories as embeddings arrive is worse than a slightly-imperfect initial placement.

### 3.8 Embedding retry sweep

A periodic job (every 30 min) retries items with `embedding IS NULL AND created_at > now() - interval '48 hours'` and not already marked permanently failed. This is the **failure-recovery path only** — first-pass embedding happens inline in the poll job (§3.6). Max `embedding_max_retries=3`; on the 3rd failure, `warnings += ['embedding_permanently_failed']` and the item is keyword-clustered forever.

**Retry success is auditable, not just retryable.** A successful backfill emits `audit_log('system', 'embed_retry_success', '<item_id>', 'item', {was_null_for_minutes: …})`. The soak's forced-recovery hardening (§5.7 step 3b) needs to be *provable after the fact*, not just watchable in `/stats` — same "count the drops *and* the recoveries" principle applied to orphans.

Items that age out of the 48h window unclustered are **orphans** — surfaced by `/stats` (§3.9). Non-zero orphan count = upstream bug.

### 3.9 `/stats` (the P1 "is it alive" surface)

```json
{
  "sources": [
    {"name":"ET Markets","kind":"rss","active":true,
     "last_run":"...","last_status":"ok","items_new_24h":14,"consecutive_failures":0}
  ],
  "items": {"total":1240,"with_embedding":1187,"without_embedding":53,"orphaned":0},
  "stories": {"total":312,"created_24h":28,"avg_items_per_story":1.4},
  "embedding_health": "ok",
  "clustering": {"precision_last_test": null, "recall_last_test": null}
}
```

`items.orphaned` is **non-negotiable zero in steady state.** Non-zero = upstream bug. `clustering.*_last_test` populated by the §5 fixture runner; null until first run.

---

## 4. Worker skeleton, scheduling, deployment

### 4.1 Failure modes addressed

| # | Mode | Where addressed |
|---|---|---|
| A | Container crash mid-job | §4.3 (in-memory jobstore, jobs re-register at boot) |
| B | Rolling redeploy mid-cycle (double-fire) | §4.2 (single replica) + §4.6 (advisory locks) + idempotent ingest |
| C | Health-check death spiral | §4.7 (fast `/health`, separate from scheduler executor) |
| D | Missed fire during downtime | §4.3 (`coalesce=True`, `misfire_grace_time=60`) |
| E | Job starvation | §4.3 (`AsyncIOExecutor(max_workers=4)`) |
| F | Cold-start thundering herd | §3.8 caps + §4.8 |

### 4.2 Process model — single replica, deliberately

Railway/Fly `replicas=1`. Container dies → platform restarts in ~5–15s → jobs re-register from code. Good enough for a content pipeline where a 15s gap is invisible. Multi-replica needs advisory locks as load-bearing (not belt-and-suspenders); out of scope for P1.

### 4.3 APScheduler configuration

```python
scheduler = AsyncIOScheduler(
    jobstores={"default": MemoryJobStore()},
    executors={"default": AsyncIOExecutor(max_workers=4)},
    job_defaults={
        "coalesce": True,
        "max_instances": 1,
        "misfire_grace_time": 60,
    },
    timezone="UTC",
)
```

- **`MemoryJobStore`:** jobs are static (defined in code), not user-created. Re-register at boot; no DB table to drift.
- **`AsyncIOExecutor(max_workers=4)`:** slow EDGAR fetch doesn't block RSS polling. Addresses starvation.
- **`coalesce=True`:** if process was down and 3 polls were "missed," run one catch-up, not three. Prevents backlog storms on restart.
- **`max_instances=1`:** same job never runs twice concurrently — the in-process double-fire guard.
- **`misfire_grace_time=60`:** a fire >60s late is skipped entirely. A 30-min poll missing one cycle is invisible; running 5 catch-ups in a burst is not.

### 4.4 Job registry — invariant: all jobs are `async def`

```python
JOBS = [
    ("poll_rss",    "interval", {"minutes": 30}, sources.poll_rss_sources),
    ("poll_edgar",  "interval", {"minutes": 60}, sources.poll_edgar),
    ("cluster_new", "interval", {"minutes": 15}, cluster.cluster_new_items),
    ("embed_retry", "interval", {"minutes": 30}, cluster.embed_retry_sweep),
    ("db_health",   "interval", {"minutes": 5},  db.health_ping),
]
```

**Note on what's deliberately absent:** there is no `embed_new` job. First-pass embedding happens inline at the tail of each `poll_*` job (§3.6); `embed_retry` exists only for the failure-recovery path (§3.8). A future maintainer reading this registry will look for the embedding job and not find one — this comment is the breadcrumb that prevents a wrong-footed "I'll add the missing job" PR.

> **REGISTRY INVARIANT (load-bearing, syntax-enforced).**
> Every job function in `JOBS` MUST be `async def`. APScheduler with `AsyncIOExecutor` runs coroutine jobs on the event loop; a plain `def` job is either silently dispatched to a thread pool that doesn't exist under this executor, or — worse and more concretely — a plain `def` containing `await` is a **`SyntaxError` at parse time** and the module won't import. Either way, do not mix. The `register_jobs` helper asserts `asyncio.iscoroutinefunction(fn)` at registration time, failing fast at boot rather than at first fire.

This invariant is enforced by a `register_jobs` helper that asserts `asyncio.iscoroutinefunction(fn)` for every entry — a build-time guarantee, not a code-review hope.

### 4.5 Startup / shutdown

```python
@app.on_event("startup")
async def startup():
    register_jobs(scheduler)   # asserts async; idempotent on job IDs
    scheduler.start()
    audit_log("system", "worker_start", None, "worker",
              {"jobs": [j.id for j in scheduler.get_jobs()]})

@app.on_event("shutdown")
async def shutdown():
    scheduler.shutdown(wait=True)
    audit_log("system", "worker_stop", None, "worker", {})
```

SIGTERM (Railway/Fly's redeploy signal) triggers shutdown: scheduler stops accepting new fires, waits for in-flight jobs (capped by platform grace period, ~30s).

**Redeploy race (failure mode B), walked end-to-end:**

1. Push deploy → Railway boots new instance.
2. New instance passes `/health` → marked ready.
3. Railway sends `SIGTERM` to old instance.
4. Old instance's `shutdown()` waits for in-flight jobs.
5. Overlap window: new up + old still finishing.

Why this is safe in P1:
- Single replica target → platform won't run two instances except during rolling swap.
- `max_instances=1` + job IDs → in-process concurrency guard.
- **Idempotent ingest (the real backstop):** `ON CONFLICT (hash) DO NOTHING` makes double-ingest a no-op. `story_items` composite PK makes re-link a no-op. Double-embedding overwrites itself harmlessly.
- Advisory locks (§4.6) — belt-and-suspenders for the rare non-idempotent operation.

Worst case in the overlap: wasted work, never corrupted state.

### 4.6 Advisory locks

```python
async def with_advisory_lock(key: str, fn):
    key_hash = zlib.crc32(key.encode()) & 0x7FFFFFFF
    got = await db.execute(f"SELECT pg_try_advisory_lock({key_hash})")
    if not got:
        audit_log("system", "advisory_lock_skip", key, "job", {})
        return None
    try:
        return await fn()
    finally:
        await db.execute(f"SELECT pg_advisory_unlock({key_hash})")
```

Each job wraps its body in `with_advisory_lock(job_id, …)`. Cost: 2 DB round-trips per job. Negligible at our job count. Turns the rare simultaneous-fire case into a clean skip with audit trail.

**`db_health` is exempt.** A liveness probe that needs two DB round-trips to acquire an advisory lock will fail *for the wrong reason* when the DB is degraded — exactly the condition the probe exists to detect. The health check runs raw `SELECT 1` with no lock; since it's read-only, idempotent, and writes nothing, the double-fire risk it forgoes is harmless.

### 4.7 `/health`

```python
@app.get("/health")
async def health():
    checks = {
        "process": "up",
        "scheduler_running": scheduler.running,
        "db_reachable": await db.ping(),
    }
    ok = all(checks.values())
    return Response(status=200 if ok else 503, content=json.dumps(checks))
```

Checks process + scheduler + DB, **not sources.** A dead RSS feed is a `/stats` concern, not a liveness concern — it shouldn't restart your worker. `/health` is on the FastAPI event loop, separate from the scheduler executor → a stuck job doesn't block it. Platform timeout (Railway kills if `/health` doesn't respond in N seconds) catches a wedged event loop that the body can't.

### 4.8 Cold start

First-ever boot, empty DB, 10 feeds × 50 items: 500 items max in first cycle. Embedding happens inline at the tail of the poll (§3.6): ~200ms per item, serialized (no concurrency flood on the edge function) → ~100s. The poll job's `max_instances=1` guard ensures no overlap risk despite the cold-start latency. Done within the first cluster cycle — stories populate by the minute-15 `cluster_new` run. No special "cold start mode" — §3.8 caps handle it.

### 4.9 Config (two-tier)

- **`worker/app/settings.py`** (pydantic-settings, `.env` / Railway env vars): secrets and structural config changed rarely. Includes `supabase_url`, `supabase_service_key`, `edgar_user_agent`, `embedding_edge_function_url`, `scheduler_max_workers`, `log_level`. Prefix `FCE_`.
- **`config` table:** tuning values changed often (clustering threshold, poll cadences, caps, EDGAR form types / company watchlist). Read at job-fire time, not boot time. Tunable without redeploy.

`.env.example` documents every var. No secrets in repo, ever.

### 4.10 Observability

- **Structured logs** (`structlog`, JSON to stdout). Every job logs start/end/duration/item-count.
- **`audit_log`** for durable events.
- **`/stats`** for human-facing liveness.
- No metrics exporter in P1. Revisit in P5 hardening if needed.

---

## 5. Testing & acceptance

This section closes Phase 1. The acceptance gate has numbers, not vibes.

### 5.1 The fixture — adversarial by construction

`worker/tests/fixtures/clustering.jsonl`, one record per item:

```json
{"id":"fx_001","source":"reuters","title":"Tata Sons files for $100M IPO",
 "body":"Tata Sons privately held...","true_story_id":"tata_ipo","embedding":[0.012, …]}
```

**Composition:**

- ~30 items, ~8 true stories, ~6 singletons (no true sibling).
- **Trap pairs (must NOT merge):** `tcs_q2` vs `tcs_buyback` (same company, different event); two "RBI rate decision" stories from different months; an evergreen "what is an IPO" explainer next to a specific IPO news story.
- **Corroboration pairs (must merge):** same Tata Sons IPO across Reuters/ET/Livemint with varied (paraphrased) headlines — tests surface-form diversity survival.
- **Ticker-vs-name variants:** `$RELIANCE` headline vs "Reliance Industries" headline for the same event.
- **Singletons:** false-positive pressure — a singleton drifting into any story is a pure FP.

**Provenance assertion (load-bearing):** the `embedding` field is pre-computed once with `gte-small` and frozen. The test must be deterministic and not depend on the edge function being up. **A test-load assertion checks `fixtures/_model.json` against the worker's configured embedding-input construction — not just model + dim, but the full construction.** The file contains:

```json
{
  "model": "gte-small",
  "dim": 384,
  "title_weight_repeat": 2,
  "body_truncate_chars": 500
}
```

Any mismatch — model swap, dim change, `title_weight_repeat` tuned from 2 to 3, body truncation changed from 500 to 1000 — trips the same loud "regenerate the fixture" failure as a model swap. **The provenance contract is "fixture and production embed the same way," and "the same way" includes the input construction, not just the model.** Checking only `{model, dim}` was a blind spot — tuning `title_weight_repeat` would silently change production's embedding input while the frozen fixture stayed stale, and the guard would wave it through green. This closes that hole. Maintenance procedure documented in `tests/fixtures/REGENERATE.md`.

### 5.2 Precision/recall — pair-counting

For all C(N,2) pairs in the fixture (N≈30 → ~435 pairs):

|  | Predicted same | Predicted different |
|---|---|---|
| Truly same | TP | FN (safe failure) |
| Truly different | FP (**lost story**) | TN |

- Precision = TP / (TP + FP)
- Recall = TP / (TP + FN)

Pair-counting (not story-counting) because story-count precision/recall is ill-defined when predicted vs true story counts differ.

### 5.3 Pass threshold — under-merge bias, concretely

| Criterion | Value | Guarantees |
|---|---|---|
| **FP pair ceiling** | **≤ 2** | Hard cap on wrongly-merged pairs. The under-merge guarantee, expressed absolutely so it survives small-N jitter. |
| **Precision floor** | **≥ 0.85** | Supporting rate criterion; redundant with FP ceiling in most cases. |
| **Recall floor** | **≥ 0.50** | Lenient — we accept missing half the available merges. Splitting corroboration costs a Snooze click; merging two real stories costs a scoop. |

> **Why the FP ceiling is the load-bearing criterion (and why N-coupled).** With ~8 true stories averaging ~3.5 items, the fixture yields ~40 true-positive pairs available and ~395 true-negative pairs. At that N, a stray FP moves precision by ~2–3% — rates alone can mask a real failure. Worse, **FPs are N-coupled to the dangerous outcome**: a single bad merge of story *A* into story *B* doesn't just produce one FP pair — it can silently eliminate story *B* from the Inbox entirely (its items now belong to *A*). At our fixture scale, **≤2 FP pairs bounds the worst case to at most 1–2 silently-eaten stories**, which is the line. Three or more FPs in a 30-item sample is the threshold where "the clusterer is eating real stories" becomes plausible rather than paranoia. The ceiling is N-coupled: if the fixture grows, the ceiling must be re-derived against the new pair count, not carried over as a constant.

So: **the dangerous failure (FP) is bounded absolutely; the safe failure (FN) is tolerated generously.** That's the concrete asymmetric criterion.

### 5.4 Clustering test runner

```python
# worker/tests/test_clustering.py
def test_clustering_meets_acceptance(clusterer, fixture):
    items = load_fixture("clustering.jsonl")
    assert fixture_model_matches_worker()   # provenance assertion (§5.1)
    predicted = clusterer.run(items)        # returns {item_id: predicted_story_id}

    pairs = all_pairs(items)
    tp = sum(1 for a,b in pairs if same_truth(a,b) and same_pred(a,b,predicted))
    fp = sum(1 for a,b in pairs if not same_truth(a,b) and same_pred(a,b,predicted))
    fn = sum(1 for a,b in pairs if same_truth(a,b) and not same_pred(a,b,predicted))

    precision = tp / (tp + fp) if (tp+fp) else 1.0
    recall = tp / (tp + fn) if (tp+fn) else 1.0

    assert fp <= 2,           f"FP ceiling violated: {fp} wrongly-merged pairs"
    assert precision >= 0.85, f"Precision floor: {precision}"
    assert recall >= 0.50,    f"Recall floor: {recall}"
```

The clusterer is **dependency-injected.** `clusterer.run()` takes items (with frozen embeddings) and returns assignments. It does NOT call the DB or the edge function. Test is deterministic, <1s, CI-runnable without infrastructure.

**Threshold tuning workflow** (documented in `tests/fixtures/TUNING.md`): run → observe FP/precision/recall → raise threshold if FP>2 → lower threshold if recall<0.50 *and* FP headroom allows → commit the threshold/fixture pair together.

> **HNSW-vs-exact-cosine assumption (documented, not assumed).** The DI'd clusterer in this test computes similarity in-memory (exact cosine); production (§3.7) enforces the same `similarity_threshold` over a pgvector **HNSW** index, which is *approximate* nearest-neighbor. So the threshold is tuned in one engine and enforced in another. At P1 scale (low thousands of rows, `m=16, ef_construction=64`), HNSW recall is near-exact and the two engines agree for practical purposes — but this is a thing written down, not assumed. TUNING.md records: (a) the gate assumes HNSW≈exact at P1 scale, (b) the live smoke (§5.5 Layer 2) is where real divergence would surface in practice, (c) if the corpus ever grows past ~10k rows, HNSW recall must be re-measured and the threshold re-validated against pgvector directly. Don't let the number that gates the whole phase quietly live in two engines.

### 5.5 Cold-start smoke test — full chain, no live feeds

Two layers:

**Layer 1: HTTP-mocked integration test (CI).**

```python
# worker/tests/test_cold_start.py
def test_cold_start_idempotent(respx_mock, test_db):
    respx_mock.get("https://etmarkets.com/rss").mock(recorded_cassette("etmarkets.xml"))
    respx_mock.get("https://www.sec.gov/...").mock(recorded_cassette("edgar.atom"))
    # … one cassette per seeded source …

    ingest.run_all_sources()
    items_v1 = test_db.count("items")
    stories_v1 = test_db.count("stories")
    assert items_v1 > 0
    assert stories_v1 > 0
    assert test_db.count_where("items", "embedding IS NULL") == 0
    assert test_db.count_orphans() == 0   # §3.7 orphan counter

    # Idempotency (the §0.1 exact-dupe bar)
    ingest.run_all_sources()
    assert test_db.count("items") == items_v1
    assert test_db.count("stories") == stories_v1

    stats = client.get("/stats").json()
    assert stats["embedding_health"] == "ok"
    assert stats["items"]["orphaned"] == 0
```

Recorded cassettes in `tests/fixtures/feeds/*.xml` — real feed payloads captured once, replayed forever. Test DB: **local Postgres + pgvector in Docker** (not Supabase) — CI-runnable, no network, no free-tier burn. The only Supabase-specific surface (the `embed` edge function) is mocked here; its real behavior validated by the manual soak (§5.7).

**Mock embed determinism.** The mock embed function returns a deterministic 384-dim vector per input string (derived from a hash of the input), not a random vector. Without this, reruns of `test_cold_start_idempotent` would cluster differently each time, making the test subtly flaky even though it primarily asserts idempotency/orphans rather than clustering quality. Deterministic mock = reproducible run-to-run.

**Layer 2: live smoke (your machine, once before deploy).**

```
make smoke    # boots worker + local Postgres via docker-compose, one cycle against real feeds
```

Hits live RSS for one cycle against a local DB. ~60s. Confirms cassettes still match reality (feeds haven't changed shape) before trusting the deploy. If a feed's live response diverges from its cassette, the unit test passes but live smoke fails — early warning to refresh the cassette.

### 5.6 Unit coverage

| Module | What's unit-tested |
|---|---|
| `sources.rss` | URL canonicalization (every tracking-param case), HTML stripping, encoding correction, date fallback |
| `sources.edgar` | Accession extraction from URL, form-type filter, UA header presence |
| `ingest` | Hash stability (same input → same hash across runs), `max_items_per_cycle` truncation |
| `cluster` | Keyword-fallback ≥2-token rule (explicit trap: single "TCS" token does NOT merge), title-weighting input construction |
| `db` | `create_or_join_story` transaction rollback on simulated mid-call failure (orphan-prevention guarantee) |

Cheap, fast (<5s total), high regression value during P2–P6.

### 5.7 P1 acceptance gate

**Automated (must be green in CI before merge):**

- All unit tests pass.
- `test_clustering_meets_acceptance` passes (FP ≤ 2, precision ≥ 0.85, recall ≥ 0.50).
- `test_cold_start_idempotent` passes (zero re-inserts, zero orphans, all embedded).

**Manual (you run once, before declaring Phase 1 done):**

1. Deploy worker to Railway (single replica, env vars set).
2. Confirm `/health` returns 200 within 60s of boot.
3. **Let it run 24 hours against real feeds.** Two hardenings of this soak, because a single clean weekday tells you almost nothing about robustness:
   - **The 24h must span at least one closed-market stretch** (an Indian market close → open transition, ideally a full weekend if feasible). Closed-market is when sources go quiet, poll cadences have nothing to do, and subtle bugs (empty-result handling, advisory-lock release on no-op cycles, `/stats` dividing by zero when `items_new_24h=0`) surface. A soak that only covers market hours hides these.
   - **You must force the retry path at least once.** Temporarily point `embedding_edge_function_url` at a bad URL (or `Supabase` env var to a junk value), confirm items land with `embedding IS NULL` + `warnings=['embedding_failed']` and cluster via keyword fallback, then restore the URL and confirm `embed_retry_sweep` backfills the missing embeddings within 30 minutes. The retry path is only real if you've watched it recover.
4. Check `/stats`:
   - Every active source: `last_status=ok`, `consecutive_failures=0`. (NSE and LE may be `active=false` per §0.2/§3.5 — acceptable.)
   - **No source auto-disabled during the soak.** Grep `audit_log` for `action='ingest_unhealthy'`; investigate every hit. The auto-disable-after-3-failures rule (§3.3) means a source that 5xx'd for 45 minutes over the weekend is now `active=false` and would *pass* the "every active source is healthy" check by virtue of no longer being active. A source can die during the soak and the gate stays green unless you explicitly look for the disable event.
   - `embedding_health = ok`.
   - `items.orphaned = 0` — **non-negotiable; if >0, Phase 1 is not done.**
5. Spot-check 5 stories in Supabase studio: each is a sensible cluster of 1–N items, no over-merges (no "TCS Q2 + TCS buyback" collapsed).
6. Re-trigger one source's ingest manually (`POST /ingest/trigger?source_id=…`); confirm zero new items inserted (production idempotency).
7. Confirm `audit_log` has `worker_start`, `ingest_run`, `cluster_new_story`, and (from the retry-path hardening) at least one `embedding_degraded` / `cluster_embedding_missing` event.

**Phase 1 is done when steps 4–7 pass.** Not "when the code is written." The 24h soak is honest — "stories fill themselves daily" cannot be proven faster than daily, and the two hardenings make the soak actually exercise the failure paths rather than gliding through a lucky 24h.

### 5.8 What "done" explicitly excludes (scope fence)

- No scoring, drafting, compliance gate (P2).
- No GUI (P3).
- No publishers (P4).
- NSE may ship disabled (§3.5) — acceptable.
- LE source row exists but `active=false` — acceptable.
- Embedding model is gte-small unless the fixture test proves it inadequate — swap is a documented one-migration change.

---

## 6. Open items for P2 (forward references, not P1 work)

- **Scoring rubric + Haiku classifier** consuming `stories` and writing `score/angle/vertical`.
- **Compliance gate** (L1 lint + L2 cross-model judge), with the gate rules from §0.3.6: L1 short-circuits L2, replies through the same gate, re-lint after edit, log blocked/flagged into `audit_log`.
- **Voice pack v1** seeded from the v1.0 §8.1 skeleton.
- **LE content triggers** — flip the LE `sources` row to `active=true`, add the movers/breadth/new-highs poller. Decouple from LE's own P1 hardening timeline.
- **NSE** — if P1 shipped it disabled, decide between per-symbol CSV (with a real watchlist) and a third-party RSS that proved reliable.

---

## Appendix A — Decision log (settled during brainstorming)

| # | Decision | Rationale |
|---|---|---|
| 1 | Phase 1 = v1.0 "Spine + Reader" only | Each v1.0 phase is independently verifiable; clustering on real feeds de-risks P2. |
| 2 | GUI stack Next.js (provisional, P3) | Match PMS-portal muscle memory; confirmed at P3. |
| 3 | Dry-run publisher pattern (P4) | Develop + approve against a log; flip env for real publish. |
| 4 | Model router config-driven, Haiku+Flash defaults | Kimi's India access is a non-blocker. |
| 5 | LE registered `active=false` in P1 | Plumbing cheap, brain deferred to P2; decouple from LE P1 timeline. |
| 6 | `entity_type` added to `audit_log` | `entity` alone is an ambiguous polymorphic string. |
| 7 | gte-small (384-dim) in-DB embeddings | $0, no new API surface; swap target reserved if fixture disappoints. |
| 8 | RLS placeholder-uid | Avoids `config`-table chicken-and-egg. |
| 9 | `min_items_for_story=1` | A single strong item can seed a story. |
| 10 | NSE via RSS, ships disabled if unavailable | NSE hostility makes scraping/CSV not worth P1 scope. |
| 11 | Title-weighted embeddings (title ×2 + 500 chars body) | Biggest lever on clustering precision. |
| 12 | Keyword fallback ≥2 tokens | Single-token match is the over-merge failure mode. |
| 13 | Clustering as separate job from ingest | I/O-bound vs DB-bound; failure isolation. |
| 14 | Re-embed via periodic sweep, max 3 retries | Failed embeddings are recoverable, not permanent. |
| 15 | Cluster link frozen after first assignment | Stability over theoretical optimality. |
| 16 | Atomic story creation (transaction) | Orphan prevention; crash between create+link rolls back. |
| 17 | `/stats` orphan counter | "Count the drops, not just the survivors." |
| 18 | Single replica + advisory locks | Removes double-fire race at deploy layer. |
| 19 | `coalesce=True`, `misfire_grace_time=60` | Skip missed fires, run one catch-up. |
| 20 | `/health` checks process+scheduler+DB only | Source health is `/stats`, not liveness. |
| 21 | Two-tier config (env + `config` table) | Secrets/structure vs tuning. |
| 22 | All jobs `async def`, asserted at registration | AsyncIOExecutor runs coroutines; mixing is silent failure or SyntaxError. |
| 23 | FP ceiling ≤ 2 is load-bearing | Under-merge bias bounded absolutely; N-coupled to lost-story outcome. |
| 24 | Frozen fixture embeddings + provenance assertion | Deterministic tests; mismatch fails loud, not silent. |
| 25 | 24h soak with closed-market stretch + forced retry path | Soak must exercise failure paths, not glide through a lucky day. |
| 26 | Embedding inline at poll tail, no separate `embed_new` job | Poll interval ≫ embed time; `embed_retry` is failure-path only; §5.5's `embedding IS NULL == 0` assertion depends on this. |
| 27 | Provenance covers `{model, dim, title_weight_repeat, body_truncate_chars}` | Tuning embedding-input construction changes production behavior; the guard must catch that, not just model swaps. |
| 28 | HNSW-vs-exact-cosine gap documented in TUNING.md, re-check trigger at ~10k rows | Threshold tuned in one engine, enforced in another; benign at P1 scale, must be re-measured if corpus grows. |
| 29 | Soak checklist greps `audit_log` for `ingest_unhealthy` | Auto-disabled sources pass the "active sources healthy" check by virtue of being inactive; the disable event must be seen explicitly. |
| 30 | `db_health` exempt from advisory lock | A probe needing 2 lock-acquisition round-trips fails for the wrong reason when DB is degraded — exactly the condition it exists to detect. |
| 31 | `embed_retry_success` audit event | Recovery is provable after the fact, not just watchable in `/stats`; same principle as the orphan counter. |
| 32 | Mock embed returns deterministic hash-derived vector | Prevents run-to-run flakiness in `test_cold_start_idempotent`. |
