# Fin-Content Engine — Progress Tracker

**Project:** AI pipeline for compliant US/India finance content (X + IG).
**Source of truth:** `fin-content-engine-FINAL-blueprint.md`.
**Canonical phase map:** blueprint Part I §6.

---

## Phase status

| Phase | Status | Acceptance | Notes |
|---|---|---|---|
| **P0 — Accounts & keys** | 🟡 Partial | — | GitHub ✅, Supabase ❌ (dropped in P1), Anthropic ⬜ (not needed until P2), Railway ❌ (dropped — using VPS), X/Meta ⬜ (not needed until P4) |
| **P1 — Spine + Reader** | 🟡 Code done, deploy in progress | automated gates ✅ (66/66 tests); 24h soak ⬜ | see `docs/P1-HANDOFF.md` for the deploy saga |
| **P2 — Brain + Gate** | ⬜ Not started | — | handoff prompt in blueprint §10 |
| **P2.5 — Newsletter + Funnel** | ⬜ Not started | — | |
| **P3 — Cockpit (GUI)** | ⬜ Not started | — | Next.js (provisional) |
| **P4 — Publishers** | ⬜ Not started | — | |
| **P5 — Reply engine** | ⬜ Not started | — | |
| **P6 — Analytics & hardening** | ⬜ Not started | — | |

---

## P1 deploy sub-status (live)

| # | Step | Status |
|---|---|---|
| 0.1 | SSH as `root@160.250.204.73` | ✅ |
| 0.2 | GitHub repo (`khooptong-creator/fin-content-engine`) | ✅ |
| 0.3 | ~~Supabase edge fn~~ → local embedder (Option C) | ✅ (swapped) |
| 1 | apt install (postgres, python, caddy, git, curl) | ✅ |
| 2 | `fce` user + `/opt/fce` + repo cloned | ✅ |
| 3 | Postgres `fce` DB + pgvector on **port 5433** | ✅ |
| 4 | venvs (worker + embedder) | ⬜ **next** |
| 5 | migrations | ⬜ |
| 6 | `.env` (port 5433, embedder 8001) | ⬜ |
| 7 | systemd units (worker 8002, embedder 8001) | ⬜ |
| 8 | Caddy vhost on `desk-caddy-1` (NOT a new Caddy) | ⬜ |
| 9 | end-to-end verify | ⬜ |

**Blocker:** trading desk Docker stack owns ports 5432 / 8000 / 443. Need to see
the desk's `docker-compose.yml` to add our Caddy vhost without breaking the desk.

---

## Decisions log (cumulative)

| # | Decision | Date | Rationale |
|---|---|---|---|
| 1 | Phase 1 = v1.0 "Spine + Reader" only | brainstorm | Each phase independently verifiable; clustering de-risks P2 |
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
| 30 | HNSW≈exact caveat documented in TUNING.md | review | threshold tuned in one engine, enforced in another; benign at scale, must re-check past ~10k rows |
| 31 | Clustering threshold 0.78 → **0.92** | build | gte-small's in-domain baseline cosine is ~0.79; 0.78 merges nearly everything |
| 32 | Self-host Postgres on VPS (Option C) | deploy | Supabase free tier has pause-on-inactivity + egress caps; local is faster, free, controlled |
| 33 | Self-host embeddings on VPS (Option C) | deploy | Supabase hosted gte-small OOM-killed; local sentence-transformers has no ceiling |
| 34 | Bare process, not Docker | deploy | Docker-to-host-Postgres networking footgun; systemd is a better supervisor for one Python process |
| 35 | Worker on port 8002, embedder on 8001 | deploy | 5432/8000/443 owned by trading desk Docker stack |
| 36 | Add Caddy vhost to `desk-caddy-1`, not a new Caddy | deploy | can't run two Caddys on 443 |

---

## Cost reality (steady state, pre-revenue)

| Item | Monthly | Notes |
|---|---|---|
| VPS | $0 marginal | already paying for the trading desk |
| Postgres | $0 | host Postgres, no cloud DB |
| Embeddings | $0 | local gte-small, no cloud API |
| LLMs (P2+) | ~$5–15 | Haiku + Gemini Flash + (eventually) Kimi |
| **Total (P1)** | **~$0** | |

---

## Open questions / risks

- Trading desk Caddy reload procedure — additive vhost shouldn't break existing sites, but reload has a brief TLS blip.
- Host Postgres on port 5433 survives reboots? Confirm `postgresql.conf` pins it.
- Python 3.14 deprecations (`WindowsSelectorEventLoopPolicy`, `set_event_loop_policy`, `iscoroutinefunction`) — all handled, but will need rework before 3.16.
