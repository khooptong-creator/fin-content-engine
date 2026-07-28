# Fin-Content Engine — Memory Note

> Obsidian-style durable note. Drop into your vault under `Projects/Fin-Content Engine/`.
> Capture what was built, what's settled, what's open — so the next session (or
> you in 3 months) doesn't re-litigate decisions or re-discover bugs.

**Project:** AI pipeline for compliant US/India finance content (X + IG).
**Owner:** UMinkoo (sole publish authority).
**Started:** 2026-07-25. **Last update:** 2026-07-28.

---

## What this is

A human-in-the-loop content operation. Automated pipelines read financial news
(US + India), draft posts/threads/carousels/replies in your voice, run every
word through a compliance gate, and queue it in an approval dashboard. Nothing
publishes without your click. You are the editor-in-chief of a newsroom staffed
by three cheap, tireless LLMs.

**Codename:** The Cyborg Desk.
**Source of truth:** `fin-content-engine-FINAL-blueprint.md` (the reconciled
blueprint; everything else defers to it).
**Phase map:** blueprint Part I §6 (P0 through P6).

---

## Non-negotiables (governs every phase)

1. **Never auto-publish.** Your approval click is the compliance backstop AND what keeps you the genuine author.
2. **Compliance wall.** Educator + analyst + commentator, NEVER advisor. Three-layer gate (L1 regex / L2 cross-model judge / L3 human). No links in X post bodies (the $0.20 URL tax). Meter mention-reads.
3. **No trading-signal overlap.** Different universe, different regulator posture. Co-located on the same VPS but fully isolated (separate DB, separate user, separate services).
4. **Resist a third automated LLM layer.** Two models + human is the right depth.

---

## Where we are (2026-07-28)

**Phase 1 (Spine + Reader) — code complete, deploy in progress.**

- Codebase: 33 files, 66/66 tests green.
- Clustering acceptance: FP=0, P=1.0, R=0.64 at threshold 0.92.
- Deploy: SSH ✅, GitHub ✅, VPS package install ✅, `fce` user + repo ✅, Postgres+pgvector on port 5433 ✅.
- **Current blocker:** trading desk Docker stack owns ports 5432/8000/443. Need the desk's `docker-compose.yml` to add a Caddy vhost without breaking it.
- Next: venvs → migrations → .env → systemd units → Caddy vhost → verify → 24h soak.

See `docs/P1-HANDOFF.md` (deploy saga) and `PROGRESS.md` (canonical status).

---

## Architecture decisions that won't change

- **Self-host everything in P1.** No Railway, no Supabase, no cloud DB, no cloud embeddings. Zero external dependencies. (Supabase returns in P3 for GUI auth.)
- **Bare process, not Docker** for worker + embedder. systemd supervises; avoids Docker-to-host-Postgres networking footgun.
- **Host Postgres 16 + pgvector on port 5433.** Timescale owns 5432; Ubuntu's Postgres auto-bumped.
- **Local embedder (Option C):** ~40-line FastAPI app wrapping `sentence-transformers/gte-small`, on `127.0.0.1:8001`. Replaces the Supabase edge function that OOM-killed on the free tier.
- **Worker on port 8002.** Embedder on 8001. (Trading desk's `desk-api` owns 8000.)
- **Co-located with trading desk**, isolated via dedicated `fce` user + separate DB + separate systemd services.
- **Behind the trading desk's existing Caddy** (`desk-caddy-1`) for TLS — can't run two Caddys on 443.
- **Two-tier config:** env vars for secrets/structure, `config` table for tuning.
- **All jobs `async def`**, asserted at registration (decision #22).
- **FP ceiling ≤2** is the load-bearing clustering criterion (decision #23).

---

## VPS access

- **Host:** `160.250.204.73` (SSH as `root`).
- **Domain:** `fce.lamkalabs.com` (DNS A record → 160.250.204.73, via Porkbun/Cloudflare).
- **Trading desk hostname:** `desk.lamkalabs.com` (same box).
- **fce DB password:** stored locally at `F:\Content Creation Project\FCESupa DB PW.txt` (currently `testpassword123` — change before .env).

---

## GitHub

- **Repo:** `khooptong-creator/fin-content-engine` (private).
- **Auth gotcha:** `khooptong-sudo` and `khooptong-creator` are two separate accounts. Push must authenticate as `creator`. Switching `gh` CLI alone doesn't fix Windows Credential Manager — `gh auth setup-git` after switching, or transfer repo ownership to sudo.
- **Security note:** `FCESupa DB PW.txt` was accidentally committed once; scrubbed via `git commit --amend` before push; `.gitignore` hardened (`*PW*.txt`, `*password*.txt`, etc.).

---

## Known bugs that recurred (avoid re-discovering)

1. **psycopg3 ≠ asyncpg.** `conn.fetchrow` / `$1` placeholders / `set_row_factory` don't exist in psycopg3. Use `%s` placeholders, the cursor pattern, `row_factory` as a settable property. Helpers in `db.py`: `_fetchone` / `_fetchall` / `_fetchval`.
2. **Pool configure callback must not leave transactions open.** Don't run `CREATE EXTENSION` or `SET` inside `_configure_conn`; only `register_vector_async` + `row_factory`.
3. **Windows + psycopg3 needs `WindowsSelectorEventLoopPolicy`** (ProactorEventLoop incompatible). Set in `conftest.py`. Deprecated in Python 3.16 — will need rework.
4. **APScheduler 3.11 drift:** `AsyncIOExecutor()` takes no `max_workers` arg; `_job_defaults` is a dict; use `inspect.iscoroutinefunction` (not `asyncio.`).
5. **Clustering threshold 0.92, not 0.78.** gte-small's in-domain baseline cosine is ~0.79; the spec's 0.78 guess merges everything. Tuned via the §5 fixture sweep.

---

## What's NOT in P1 (don't build these yet)

- Scoring, drafting, compliance gate, voice pack → P2.
- Any GUI → P3 (Next.js, provisional).
- Publishers → P4 (X API, IG Graph).
- Reply engine → P5.
- Analytics + feedback loop → P6.
- LE price-table content triggers → P2 (drafting concern).
- NSE scraping → out of scope; ships `active=false` if no RSS.

---

## How to resume

1. Read `PROGRESS.md` for canonical status.
2. Read `docs/P1-HANDOFF.md` for the deploy saga and current blocker.
3. Read `docs/P1-VPS-DEPLOY-RUNBOOK.md` for the step-by-step (Phases 0–9).
4. Read `docs/P1-DEPLOY-SOAK-CHECKLIST.md` for the 24h soak.
5. The blueprint (`fin-content-engine-FINAL-blueprint.md`) is the source of truth for everything after P1.
