# Phase 1 Handoff — Fin-Content Engine (updated 2026-07-28)

**Status: code-complete + 66/66 tests green; VPS deploy IN PROGRESS (~Phase 3 of 9).**

The original codebase facts (below, preserved) are unchanged. The top of this
file tracks the deploy saga; the bottom keeps the build-handoff content.

---

# DEPLOY CHAPTER (live)

## Deploy architecture (revised mid-deploy)

**Original plan:** Railway + cloud Supabase. **Revised:** self-hosted bare
process on a VPS co-located with the trading desk. Drivers: Railway cost;
Supabase edge function OOM-killed on the free tier.

**Final topology (in progress):**
- **Worker** → `127.0.0.1:8002` (systemd unit `fce-worker.service`)
- **Embedder** → `127.0.0.1:8001` (systemd unit `fce-embedder.service`, local gte-small)
- **Postgres 16 + pgvector** → host Postgres on `127.0.0.1:5433` (the `fce` DB)
- **Caddy** → **the existing `desk-caddy-1` container** (NOT a new Caddy) serves
  `fce.lamkalabs.com` and proxies to 8002
- **No Supabase in P1.** Replaced by local embedder. Supabase returns in P3 for GUI auth.

**Why each port:**
- 5432 = trading desk's TimescaleDB (Docker). Host Postgres auto-bumped to 5433.
- 8000 = trading desk's `desk-api` (Docker). Our worker can't use it.
- 8001 = our embedder. 8002 = our worker. Free ports, no conflicts.
- 443 = trading desk's Caddy container. We add a vhost to it, not a competing Caddy.

## Deploy progress

| Phase | Status | Notes |
|---|---|---|
| 0.1 SSH as root | ✅ Done | `ssh root@160.250.204.73`, username is `root` (not `khooptong`) |
| 0.2 GitHub repo | ✅ Done | `khooptong-creator/fin-content-engine` (private). Push of the embedder commit required `gh auth setup-git` after switching `gh` CLI to creator account. |
| 0.3 Supabase edge fn | ❌ DROPPED | OOM-killed (`EarlyDrop`, ~10MB ceiling). Replaced with local embedder (Option C). |
| 1 apt install | ✅ Done | postgresql-16, postgresql-16-pgvector, python3.12, caddy (later: not used — desk Caddy instead), git, curl |
| 2 fce user + repo | ✅ Done | `/opt/fce` with `current` symlink → `releases/initial`; embedder pulled via `sudo -u fce git -C /opt/fce/current pull` |
| 3 Postgres + pgvector | ✅ Done | `fce` role + DB + `vector` extension on **port 5433** (NOT 5432 — Timescale owns it). Password set via `ALTER ROLE` inside psql. **Password stored at `F:\Content Creation Project\FCESupa DB PW.txt` locally.** Currently `testpassword123` (diagnostic) — must be changed before .env. |
| 4 venvs (worker + embedder) | ⬜ Not done | Next after the port conflict is resolved |
| 5 migrations | ⬜ Not done | |
| 6 .env | ⬜ Not done | Must use port **5433** and embedder URL **127.0.0.1:8001** |
| 7 systemd units | ⬜ Not done | Worker on **8002**, not 8000 |
| 8 Caddy/TLS | ⬜ Not done | Add vhost to `desk-caddy-1`, NOT a new Caddy |
| 9 verify | ⬜ Not done | |

## Current blocker (2026-07-28)

The trading desk runs as a Docker Compose stack claiming ports 5432 (Timescale),
8000 (desk-api), 443/80 (desk-caddy). Our original runbook assumed we'd install a
fresh Caddy and bind 8000/5432 — all three collide. Before resuming Phase 4, we
need to **see the desk's `docker-compose.yml`** to add a vhost to the existing
Caddy (the only additive change that won't break the desk). Awaiting user input.

## Decisions made during deploy

1. **Bare process, not Docker** (worker + embedder). Avoids Docker-to-host-Postgres networking footgun; systemd is a better supervisor for one Python process than a container.
2. **Self-host Postgres on the VPS** (Option C). Cloud Supabase free tier has pause-on-inactivity + egress caps; local is faster, free, fully controlled.
3. **Self-host embeddings** (Option C). Supabase's hosted gte-small OOM-killed; local sentence-transformers on 8GB RAM has no such ceiling.
4. **Share the box with the trading desk**, isolated via dedicated `fce` user + separate DB + separate services. Resource contention risk accepted (worker is tiny).
5. **Co-locate behind the desk's existing Caddy** rather than running a second Caddy. Can't run two Caddys on 443.
6. **Git credential note:** `khooptong-sudo` and `khooptong-creator` are two separate GitHub accounts; git push must authenticate as `creator`. Switching `gh` CLI account alone doesn't fix Windows Credential Manager — required `gh auth setup-git`.
7. **Security incident (resolved):** the local file `FCESupa DB PW.txt` was accidentally committed to git. Scrubbed via `git commit --amend` before push; `.gitignore` hardened. The commit was local-only before amend, so no leak. The Supabase DB password in it is moot (we dropped Supabase in P1).

## Open risks for resume

- **Host Postgres on 5433** is unconventional; if the box reboots and something else grabs 5433 first, we have a problem. Mitigation: pin the port explicitly in `postgresql.conf` (worth confirming it survives reboots).
- **Trading desk Caddy reload** — adding our vhost requires editing the desk's compose/Caddyfile and reloading. Brief blip on the desk's TLS during reload. Need to confirm the desk's Caddy is configured for graceful reload.
- **Password for `fce`** — currently `testpassword123` (from the diagnostic). Must be changed to a real strong password before the `.env` is written.

---

# ORIGINAL HANDOFF (codebase facts, kept for reference)

## What's done (codebase)

### Code (33 files)
- **Migrations (5):** full unified schema (15 tables), RLS (resilient — skips on local vanilla Postgres), seed sources + config, owner-swap stub, indexes. Applied and verified against Docker `pgvector/pgvector:pg16`.
- **Edge function:** `supabase/functions/embed/index.ts` — wraps Supabase's built-in gte-small, 384-dim (kept for reference; not used in P1 after the Option C swap).
- **Embedder:** `embedder/app.py` + `pyproject.toml` + `fce-embedder.service` — local gte-small service (Option C, replaces Supabase edge fn).
- **Worker (13 modules):** `settings`, `config`, `db`, `audit`, `embed`, `ingest`, `cluster`, `scheduler`, `routes`, `main`, sources (`base`, `canonicalize`, `rss`, `edgar`, `nse`).
- **Tests (8 files, 66 tests):** unit + integration.
- **Fixtures:** adversarial 30-item clustering set with real gte-small embeddings.

### What the suite proves
- Exact dedup = 0.
- Near-dupe clustering passes §5.3 gate: FP=0, P=1.0, R=0.64 at 0.92.
- The trap pairs hold: TCS-Q2 vs TCS-buyback stay separate; RBI-Oct vs RBI-Feb stay separate.
- Cold-start idempotency: second ingest cycle inserts zero new items, zero orphans.
- The `async def` registry invariant is syntax-enforced.

## Bugs found and fixed during the build

1. **psycopg3 vs asyncpg API mismatch.** Fixed via `_fetchone`/`_fetchall`/`_fetchval` helpers.
2. **Pool configure callback leaving transactions open.** Fixed: only `register_vector_async` + `row_factory`.
3. **Clustering threshold 0.78 → 0.92.** Empirically tuned.
4. **Windows + psycopg3 requires `WindowsSelectorEventLoopPolicy`.**
5. **APScheduler 3.11 API drift.**
6. **vector_search SQL join-ordering bug.** Fixed with explicit CROSS JOIN.
7. **stats() subquery scope bug.** Rewrote as scalar subqueries.
8. **charset_normalizer `detect()` returns dict, not object.**
9. **EDGAR Atom `author` is dict or string.**
10. **NSE `active=false` by design (§3.5 scope-cut).**
