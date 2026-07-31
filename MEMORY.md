# Fin-Content Engine — Memory Note

> Obsidian-style durable note. Drop into your vault under `Projects/Fin-Content Engine/`.
> Capture what was built, what's settled, what's open — so the next session (or
> you in 3 months) doesn't re-litigate decisions or re-discover bugs.

**Project:** AI pipeline for compliant US/India finance content (X + IG).
**Owner:** UMinkoo (sole publish authority).
**Started:** 2026-07-25. **Last update:** 2026-07-29.

---

## What this is

A human-in-the-loop content operation. Automated pipelines read financial news
(US + India), draft posts/threads/carousels/replies in your voice, run every
word through a compliance gate, and queue it in an approval dashboard. Nothing
publishes without your click. You are the editor-in-chief of a newsroom staffed
by three cheap, tireless LLMs.

**Codename:** The Cyborg Desk.
**Source of truth:** `fin-content-engine-FINAL-blueprint.md`.
**Phase map:** blueprint Part I §6 (P0 through P6).

---

## Non-negotiables (governs every phase)

1. **Never auto-publish.** Your approval click is the compliance backstop AND what keeps you the genuine author.
2. **Compliance wall.** Educator + analyst + commentator, NEVER advisor. Three-layer gate (L1 regex / L2 cross-model judge / L3 human).
3. **No trading-signal overlap.** Co-located on the same VPS but fully isolated (separate DB on port 5433, separate `fce` user, separate services).
4. **Resist a third automated LLM layer.** Two models + human is the right depth.

---

## Where we are (2026-07-29)

**Phase 1 (Spine + Reader) — DEPLOYED. Worker live on the VPS.**

- Codebase: 60/60 unit tests green; live ingest verified (50 items fetched + embedded in one trigger).
- Deploy: all 9 phases done except the final public-HTTPS curl.
- Topology: bare process worker + embedder, host Postgres, behind the desk's Caddy.
- See `docs/P1-HANDOFF.md` (full deploy saga + bug list), `PROGRESS.md` (canonical status).

**YouTube Pipeline (Phase B) — IN PROGRESS (Local / Worker)**
- AI Scripting (Phase 2): Integrated `google-genai` using Gemini 1.5 Flash. Scripts are generated in valid Markdown with YAML frontmatter, strict compliance rules applied via DB configs.
- Voice/Audio TTS (Phase 3): Integrated ElevenLabs API. Worker parses Markdown to extract `Voiceover:` lines, maps personas (Teen boy, Adult Female, etc.) to ElevenLabs voice IDs, and synthesizes `audio.mp3`.
- Next: YouTube API Auto-Upload (Phase 4).

---

## Architecture decisions that won't change

- **Self-host everything in P1.** No Railway, no Supabase, no cloud DB, no cloud embeddings. Zero external dependencies.
- **Bare process, not Docker** for worker + embedder. systemd supervises.
- **Host Postgres 16 + pgvector on port 5433.** Timescale owns 5432; Ubuntu auto-bumped.
- **Local embedder (Option C):** `embedder/app.py` + systemd unit, `127.0.0.1:8001`, gte-small via sentence-transformers.
- **Worker on `0.0.0.0:8002`.** Caddy reaches via Docker bridge gateway `172.18.0.1`. ufw (22/80/443 only) blocks external.
- **Co-located with trading desk**, isolated via dedicated `fce` user + separate DB + separate systemd services.
- **Behind the trading desk's existing Caddy** (`desk-caddy-1`) — additive vhost, not a second Caddy.
- **Two-tier config:** env vars for secrets/structure, `config` table for tuning.
- **All jobs `async def`**, asserted at registration (decision #22). Regression-tested against lambda wrappers.
- **FP ceiling ≤2** is the load-bearing clustering criterion (decision #23).
- **Clustering threshold 0.92** (not the spec's 0.78 guess) — empirically tuned.

---

## VPS access

- **Host:** `160.250.204.73` (SSH as `root`).
- **Public domain:** `fce.lamkalabs.com` (DNS A record via Porkbun/Cloudflare).
- **Trading desk hostname:** `desk.lamkalabs.com` (same box).
- **fce DB password:** URL-safe (letters+digits+hyphens+underscores only — never `@:/?#%`). Stored locally at `F:\Content Creation Project\FCESupa DB PW.txt`.
- **Ports:** worker 8002, embedder 8001, Postgres 5433. Trading desk owns 5432/8000/443.

## Day-to-day ops (on the VPS, as root)

```bash
# Check services
systemctl status fce-worker --no-pager
systemctl status fce-embedder --no-pager

# Health + stats
curl http://127.0.0.1:8002/health
curl http://127.0.0.1:8002/stats
curl https://fce.lamkalabs.com/health     # public

# Update code after a change
sudo -u fce git -C /opt/fce/current pull
systemctl restart fce-worker
systemctl restart fce-embedder            # only if embedder code changed

# Logs
journalctl -u fce-worker -f
journalctl -u fce-embedder -f

# Reload Caddy after Caddyfile change
docker exec desk-caddy-1 caddy validate --config /etc/caddy/Caddyfile
docker exec desk-caddy-1 caddy reload --config /etc/caddy/Caddyfile
```

---

## GitHub

- **Repo:** `khooptong-creator/fin-content-engine` (private).
- **Auth gotcha:** `khooptong-sudo` and `khooptong-creator` are two separate accounts. Push must authenticate as `creator`.
- **Security:** `FCESupa DB PW.txt` was accidentally committed once; scrubbed via `git commit --amend` before push; `.gitignore` hardened.

---

## Known bugs that recurred (avoid re-discovering)

### Build phase (pre-deploy)
1. **psycopg3 ≠ asyncpg.** Use `%s` placeholders (not `$1`), cursor pattern, `row_factory` as a property. Helpers: `_fetchone`/`_fetchall`/`_fetchval`.
2. **Pool configure callback must not leave transactions open.** Only `register_vector_async` + `row_factory`.
3. **Windows + psycopg3 needs `WindowsSelectorEventLoopPolicy`** (deprecated in 3.16).
4. **APScheduler 3.11 drift:** `AsyncIOExecutor()` takes no `max_workers`; `_job_defaults` is a dict; use `inspect.iscoroutinefunction`.
5. **Clustering threshold 0.92, not 0.78.** gte-small's in-domain baseline cosine is ~0.79.

### Deploy phase
6. **DB password must be URL-safe** (no `@:/?#%`) — psycopg3 parses the connection string per RFC 3986.
7. **Migrations run as `postgres` → tables owned by `postgres` → worker as `fce` gets `permission denied`.** Fix: GRANT block in `001_init.sql` + `ALTER DEFAULT PRIVILEGES`.
8. **Lambda wrappers break the async-def invariant.** `inspect.iscoroutinefunction(lambda: ...)` is `False`. Use explicit `async def` wrappers in `build_job_specs()`.
9. **sentence-transformers loader needs `HF_HOME` pinned** in the systemd unit, or it treats the model id as a relative path and fails on permissions.
10. **Host Postgres on 5433, not 5432** — Timescale owns 5432; every `psql`/`.env` must use `-p 5433`.

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
2. Read `docs/P1-HANDOFF.md` for the full deploy saga + bug list.
3. Read `docs/P1-VPS-DEPLOY-RUNBOOK.md` for the step-by-step (Phases 0–9).
4. Read `docs/P1-DEPLOY-SOAK-CHECKLIST.md` for the 24h soak.
5. The blueprint (`fin-content-engine-FINAL-blueprint.md`) is the source of truth for everything after P1.
6. The YouTube expansion is detailed in `docs/youtube/YT-STRATEGY-OS-FINANCE.md`, `docs/youtube/YT-STRATEGY-OS-BABY.md`, and `docs/youtube/YT-HANDOFF.md`.
