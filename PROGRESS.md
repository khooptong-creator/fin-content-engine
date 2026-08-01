# Fin-Content Engine — Progress Tracker

**Project:** AI pipeline for compliant US/India finance content (X + IG).
**Source of truth:** `fin-content-engine-FINAL-blueprint.md`.
**Canonical phase map:** blueprint Part I §6.

---

## Phase status

| Phase | Status | Notes |
|---|---|---|
| **P0 — Accounts & keys** | 🟡 Partial | GitHub ✅, Supabase ❌ (dropped in P1), Anthropic ⬜ (P2), Railway ❌ (dropped — VPS), X/Meta ⬜ (P4) |
| **P1 — Spine + Reader** | ✅ **DEPLOYED** | Worker live on VPS, live ingest verified (50 items), public HTTPS pending final curl. See `docs/P1-HANDOFF.md`. |
| **P2 — Brain + Gate** | ⬜ Not started | handoff prompt in blueprint §10 |
| **P2.5 — Newsletter + Funnel** | ⬜ Not started | |
| **P3 — Cockpit (GUI)** | ⬜ Not started | Next.js (provisional) |
| **P4 — Publishers** | ⬜ Not started | |
| **P5 — Reply engine** | ⬜ Not started | |
| **P6 — Analytics & hardening** | ⬜ Not started | |
| **YT P1/P2 — Scripting & Audio** | ✅ Completed | LLM Markdown scripts (Gemini) + ElevenLabs TTS integrated in Worker. |
| **YT P4 — YouTube API Upload** | ⏳ In Progress | Planning phase |

---

## P1 deploy sub-status (complete)

| # | Step | Status |
|---|---|---|
| 0.1 | SSH as `root@160.250.204.73` | ✅ |
| 0.2 | GitHub repo (`khooptong-creator/fin-content-engine`) | ✅ |
| 0.3 | ~~Supabase edge fn~~ → local embedder (Option C) | ✅ |
| 1 | apt install (postgres, python, git, curl) | ✅ |
| 2 | `fce` user + `/opt/fce` + repo cloned | ✅ |
| 3 | Postgres `fce` DB + pgvector on **port 5433** | ✅ |
| 4 | venvs (worker + embedder) + gte-small model | ✅ |
| 5 | migrations (15 tables, 12 sources, 4 config) | ✅ |
| 6 | `.env` (port 5433, embedder 8001) | ✅ |
| 7 | systemd units (embedder 8001 + worker 8002) | ✅ |
| 7.3 | live ingest verified (50 items fetched+embedded) | ✅ |
| 8 | Caddy vhost on `desk-caddy-1` | ✅ |
| 9 | public HTTPS `/health` | ⏳ final curl pending |

**Live-ingest proof:** `{"fetched":50,"new":50,"embedded":50,"embed_failures":0}` from ET Markets. `/stats`: items=50, embedding_health=ok, orphaned=0.

---

## Deploy bugs (the full list — 9 found, all fixed)

| # | Bug | Fix landed in |
|---|---|---|
| D1 | Supabase edge fn OOM-killed (`EarlyDrop`, 10MB ceiling) | New local embedder (`embedder/`, Option C) |
| D2 | Host Postgres on 5433 not 5432 (Timescale owns 5432) | All `psql`/`.env` use 5433 |
| D3 | DB password had `@` → URL parser broke (`failed to resolve host 'ssw0rd'`) | URL-safe password; runbook guidance updated |
| D4 | Migrations owned by `postgres` → `permission denied for table config` | GRANT block in `001_init.sql` |
| D5 | Lambda wrappers broke async-def invariant (`job 'poll_rss' fn is not async def`) | Explicit `async def` wrappers in `scheduler.py` + regression test |
| D6 | sentence-transformers treated model id as relative path (`PermissionError`) | `HF_HOME` pinned in `fce-embedder.service` |
| D7 | Deprecated `get_sentence_embedding_dimension` | `getattr` fallback to new `get_embedding_dimension` in `app.py` |
| D8 | Git credential mismatch (`khooptong-sudo` vs `khooptong-creator`) | User switched `gh` auth; not a code bug |
| D9 | `FCESupa DB PW.txt` accidentally committed | Scrubbed via `git commit --amend` pre-push; `.gitignore` hardened |

---

## Decisions log (cumulative — full list)

| # | Decision | Phase | Rationale |
|---|---|---|---|
| 1 | Phase 1 = v1.0 "Spine + Reader" only | brainstorm | Each phase independently verifiable |
| 2 | GUI Next.js (provisional, P3) | brainstorm | match PMS-portal muscle memory |
| 3 | Dry-run publisher (P4) | brainstorm | develop against a log; flip env for real publish |
| 4 | Model router config-driven | brainstorm | Kimi India access non-blocker |
| 5 | LE `active=false` in P1 | brainstorm | plumbing cheap, brain in P2 |
| 6 | `entity_type` on audit_log | brainstorm | `entity` alone is ambiguous |
| 7 | gte-small 384-dim in-DB | brainstorm | $0, no new API surface |
| 8 | RLS placeholder-uid | brainstorm | avoids config-table chicken-and-egg |
| 9 | `min_items_for_story=1` | brainstorm | a single strong item can seed a story |
| 10 | NSE via RSS, disabled if unavailable | brainstorm | NSE hostility makes scraping/CSV not worth P1 scope |
| 11 | Title-weighted embeddings | brainstorm | biggest lever on clustering precision |
| 12 | Keyword fallback ≥2 tokens | brainstorm | single-token = over-merge failure mode |
| 13 | Clustering separate from ingest | brainstorm | I/O-bound vs DB-bound; failure isolation |
| 14 | Re-embed via sweep, max 3 | brainstorm | failed embeddings recoverable, not permanent |
| 15 | Cluster link frozen after assignment | brainstorm | stability over theoretical optimality |
| 16 | Atomic story creation | brainstorm | orphan prevention |
| 17 | `/stats` orphan counter | brainstorm | count drops, not just survivors |
| 18 | Single replica + advisory locks | brainstorm | removes double-fire race at deploy layer |
| 19 | `coalesce` + `misfire_grace_time=60` | brainstorm | skip missed fires, run one catch-up |
| 20 | `/health` = process+scheduler+DB only | brainstorm | source health is `/stats`, not liveness |
| 21 | Two-tier config (env + config table) | brainstorm | secrets/structure vs tuning |
| 22 | All jobs `async def`, asserted at registration | brainstorm | AsyncIOExecutor runs coroutines; mixing is silent failure |
| 23 | FP ceiling ≤2 load-bearing, N-coupled | brainstorm | under-merge bias bounded absolutely |
| 24 | Frozen fixture + provenance assertion | brainstorm | deterministic tests; mismatch fails loud |
| 25 | 24h soak with closed-market stretch + forced retry | brainstorm | soak must exercise failure paths |
| 26 | Embedding inline in ingest | review | not a queue; `embed_retry` is failure-path only |
| 27 | `db_health` exempt from advisory lock | review | a probe needing the DB to acquire a lock fails for the wrong reason |
| 28 | `embed_retry_success` audit event | review | recovery provable after the fact |
| 29 | Auto-disabled-source check in soak | review | a source can die by auto-disabling and pass the gate invisibly |
| 30 | HNSW≈exact caveat documented in TUNING.md | review | threshold tuned in one engine, enforced in another |
| 31 | Clustering threshold 0.78 → **0.92** | build | gte-small's in-domain baseline cosine is ~0.79 |
| 32 | Self-host Postgres on VPS (Option C) | deploy | Supabase free tier pause + egress caps |
| 33 | Self-host embeddings on VPS (Option C) | deploy | Supabase hosted gte-small OOM-killed |
| 34 | Bare process, not Docker | deploy | systemd > Docker for one Python process |
| 35 | Worker on port 8002, embedder on 8001 | deploy | 5432/8000/443 owned by trading desk |
| 36 | Add Caddy vhost to `desk-caddy-1`, not a new Caddy | deploy | can't run two Caddys on 443 |
| 37 | Worker binds `0.0.0.0:8002` + ufw 22/80/443 only | deploy | Caddy reaches via Docker bridge; external blocked |
| 38 | Frame design local (Ollama `qwen2.5:7b`), story text cloud | youtube | model picks an archetype + fills slots, never writes HTML — a 7B is enough and quota stops being a failure mode |
| 39 | Archetype templates, not LLM-authored HTML | youtube | a pre-validated template cannot emit an invalid composition |
| 40 | `MIN_SCRIPT_FRAMES` alongside the ratio guards | youtube | ratios score a one-frame stub at 100%; a failed script was becoming a publishable draft |
| 41 | Script generation raises instead of falling back to a stub | youtube | there is no safe fabricated script; the caller must abort |

---

## Cost reality (steady state, pre-revenue)

| Item | Monthly | Notes |
|---|---|---|
| VPS | $0 marginal | already paying for the trading desk |
| Postgres | $0 | host Postgres, no cloud DB |
| Embeddings | $0 | local gte-small, no cloud API |
| LLMs (P2+) | ~$5–15 | Haiku + Gemini Flash + (eventually) Kimi |
| **Total (P1)** | **~$0** | |
