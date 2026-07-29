# Phase 1 Handoff — Fin-Content Engine (updated 2026-07-29)

**Status: code-complete + 60/60 unit tests green; VPS deploy COMPLETE (worker live, public HTTPS pending one final check).**

The original codebase facts (bottom) are unchanged. The top tracks the deploy saga.

---

# DEPLOY CHAPTER (live)

## Deploy architecture (as built)

Self-hosted bare process on the VPS (`desk.lamkalabs.com`, IP `160.250.204.73`),
co-located with the trading desk. Zero external cloud dependencies in P1.

| Component | Where | Port | Notes |
|---|---|---|---|
| **Worker** (FastAPI + APScheduler) | systemd `fce-worker.service` | `0.0.0.0:8002` | Caddy reaches via Docker bridge `172.18.0.1:8002` |
| **Embedder** (sentence-transformers gte-small) | systemd `fce-embedder.service` | `127.0.0.1:8001` | Local; replaces Supabase edge fn |
| **Postgres 16 + pgvector** | host Postgres | `127.0.0.1:5433` | Desk's Timescale owns 5432; host auto-bumped |
| **Caddy** (TLS terminator) | `desk-caddy-1` Docker container | `:80/:443` | Existing desk container; we added one vhost |

**Domain:** `fce.lamkalabs.com` → `160.250.204.73` (Porkbun/Cloudflare A record).

## Deploy progress (all phases done)

| Phase | Status |
|---|---|
| 0.1 SSH as root | ✅ |
| 0.2 GitHub repo (`khooptong-creator/fin-content-engine`) | ✅ |
| 0.3 ~~Supabase edge fn~~ → local embedder (Option C) | ✅ (swapped) |
| 1 apt install (postgres, python, git, curl) | ✅ |
| 2 fce user + `/opt/fce` + repo cloned | ✅ |
| 3 Postgres `fce` DB + pgvector on **port 5433** | ✅ |
| 4 venvs (worker + embedder) + gte-small model | ✅ |
| 5 migrations (15 tables, 12 sources, 4 config) | ✅ |
| 6 `.env` (port 5433, embedder 8001) | ✅ |
| 7 systemd units (embedder 8001 + worker 8002) | ✅ |
| 7.3 live ingest verified (50 items fetched+embedded, `/stats` clean) | ✅ |
| 8 Caddy vhost appended to `/opt/desk/Caddyfile` + reloaded | ✅ |
| 9 public HTTPS `/health` over `https://fce.lamkalabs.com` | ⏳ pending final curl |

## Live-ingest proof (2026-07-29)

Manual trigger of ET Markets source:
```
{"fetched":50,"new":50,"embedded":50,"embed_failures":0,"status":"ok"}
```
`/stats`: `items.total=50, with_embedding=50, without_embedding=0, orphaned=0, embedding_health=ok`.
Full chain (RSS → parse → dedup → embed → DB) operational.

## Bugs found and fixed during deploy (the real list)

Each of these was a real failure that blocked the deploy. All are fixed in the
codebase now; the migration-level ones are in the migrations, the code ones are
in the worker modules. Listed in order encountered, with the one-line root cause
and the fix that landed.

### D1 — Supabase edge function OOM-killed
- **Symptom:** `EarlyDrop` in Supabase logs, 502 from the function, ~10MB memory ceiling hit.
- **Root cause:** Supabase's free-tier edge function runtime can't load gte-small in memory.
- **Fix:** Replaced with local embedder service (`embedder/app.py`, systemd unit). Self-hosted gte-small via `sentence-transformers`; 8GB VPS RAM has no ceiling. Decision: Option C.
- **Code:** `embedder/` (new), `.env.example` updated.

### D2 — Host Postgres on port 5433, not 5432
- **Symptom:** `psql -h 127.0.0.1` failed auth; `ss -tlnp` showed `docker-proxy` on 5432.
- **Root cause:** Trading desk's TimescaleDB container owns 5432; Ubuntu's Postgres auto-bumped to 5433 on install.
- **Fix:** All `psql` commands, the `.env` `FCE_DATABASE_URL`, and the runbook use port 5433. No code change needed (port is in the connection string).

### D3 — DB password contained URL-special characters
- **Symptom:** `failed to resolve host 'ssw0rd…'` at worker startup — Postgres URL parser saw `pass` as password and `word@127.0.0.1` as host.
- **Root cause:** Password had an `@` (URL separator between userinfo and host). psycopg3 parses the connection string per RFC 3986.
- **Fix:** Changed the `fce` role's password to URL-safe chars (letters+digits+hyphens+underscores only). Updated runbook password guidance.
- **Lesson:** connection-string passwords must avoid `@ : / ? # %`. Worth a `.env.example` comment.

### D4 — `permission denied for table config` at worker startup
- **Symptom:** `psycopg.errors.InsufficientPrivilege` on the first `SELECT FROM config`.
- **Root cause:** Migrations ran as the `postgres` superuser, so every table was owned by `postgres`. The `fce` role "owns" the database but Postgres separates DB ownership from table privileges — `fce` had no privileges on the tables inside.
- **Fix:** Added `GRANT ALL PRIVILEGES ON ALL TABLES/SEQUENCES` + `ALTER DEFAULT PRIVILEGES` to `001_init.sql`. The `ALTER DEFAULT PRIVILEGES` lines ensure future migrations (P2+) auto-grant to `fce`, preventing recurrence.
- **Code:** `supabase/migrations/001_init.sql` (GRANT block at end).

### D5 — Lambda wrappers broke the async-def registry invariant
- **Symptom:** `RuntimeError: registry invariant violated: job 'poll_rss' fn is not async def`.
- **Root cause:** `build_job_specs()` wrapped async calls in lambdas (`fn=lambda: run_all_sources(...)`). A `lambda` is never a coroutine function — `inspect.iscoroutinefunction(lambda: ...)` returns `False` — so the decision-#22 invariant correctly rejected them. The unit tests missed it because they used real `async def` functions, not lambdas.
- **Fix:** Replaced lambdas with explicit `async def` wrappers in `build_job_specs()`. Added a regression test (`test_lambda_rejected_even_if_it_calls_async`) that proves the invariant catches this class of bug.
- **Code:** `worker/app/scheduler.py`, `worker/tests/test_scheduler.py`.

### D6 — sentence-transformers loader treated model id as relative path
- **Symptom:** `PermissionError: [Errno 13] Permission denied: 'thenlper/gte-small/modules.json'` when loading the model.
- **Root cause:** sentence-transformers 5.x falls back to treating the model id as a relative local path when Hub resolution hiccups, and reads/writes CWD-relative files during load. Running from `/root` (root's CWD under `sudo -u fce`) hit permission errors.
- **Fix:** Pinned `HF_HOME=/opt/fce/.cache/huggingface` in the systemd unit so the model loads from cache regardless of CWD. WorkingDirectory kept at `/opt/fce/current/embedder` (where `app.py` lives) so uvicorn finds the app.
- **Code:** `embedder/fce-embedder.service`.

### D7 — Deprecated `get_sentence_embedding_dimension`
- **Symptom:** FutureWarning at model load; would break in a future sentence-transformers release.
- **Root cause:** sentence-transformers 5.x renamed the method to `get_embedding_dimension`.
- **Fix:** Use the new name with `getattr` fallback to the old one for forward/back compat.
- **Code:** `embedder/app.py`.

### D8 — Git credential mismatch (`khooptong-sudo` vs `khooptong-creator`)
- **Symptom:** `git push` 403 "Permission denied" — authenticating as `sudo`, repo owned by `creator`.
- **Root cause:** Two separate GitHub accounts; Windows Credential Manager cached `sudo`'s token. Switching `gh` CLI account doesn't fix the credential helper (separate stores).
- **Fix:** User switched the `gh` CLI auth; push ultimately worked. Long-term: pick one canonical account.
- **Not a code bug** — environment/credential issue.

### D9 — Accidental commit of `FCESupa DB PW.txt` (security)
- **Symptom:** Password file staged in the commit.
- **Root cause:** Local notes file in the repo root, not gitignored.
- **Fix:** Scrubbed via `git commit --amend` before push (commit was local-only). `.gitignore` hardened (`*PW*.txt`, `*password*.txt`, `*secret*.txt`, `FCESupa*.txt`). No leak — the Supabase password is moot anyway since we dropped Supabase in P1.

## Decisions made during deploy

1. **Bare process, not Docker** (worker + embedder). systemd is a better supervisor for one Python process; avoids Docker-to-host-Postgres networking footgun.
2. **Self-host Postgres on the VPS** (Option C). Cloud Supabase free tier has pause-on-inactivity + egress caps; local is faster, free, controlled.
3. **Self-host embeddings on the VPS** (Option C). Supabase hosted gte-small OOM-killed; local sentence-transformers has no ceiling.
4. **Share the box with the trading desk**, isolated via dedicated `fce` user + separate DB + separate services.
5. **Co-locate behind the desk's existing Caddy** rather than running a second Caddy. Can't run two Caddys on 443.
6. **Worker binds `0.0.0.0:8002`** (not `127.0.0.1`) so the desk-caddy Docker container can reach it via the bridge gateway `172.18.0.1`. ufw (only 22/80/443 open) blocks external access; only Caddy can get in. Safe.

---

# ORIGINAL HANDOFF (codebase facts, kept for reference)

## What's done (codebase)

### Code
- **Migrations (5):** full unified schema (15 tables), RLS (resilient), seed sources + config, owner-swap stub, indexes. **+ GRANT block (D4).**
- **Embedder:** `embedder/app.py` + `pyproject.toml` + `fce-embedder.service` — local gte-small service (Option C).
- **Worker (13 modules).** Includes the lambda→async-def fix (D5).
- **Tests (8 files).** 60 unit + 7 integration.

### What the suite proves
- Exact dedup = 0.
- Near-dupe clustering passes §5.3 gate: FP=0, P=1.0, R=0.64 at 0.92.
- Cold-start idempotency: second ingest cycle inserts zero new items.
- The `async def` registry invariant is syntax-enforced (and now regression-tested against lambdas — D5).

## Build-phase bugs (the original 10, pre-deploy)

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
