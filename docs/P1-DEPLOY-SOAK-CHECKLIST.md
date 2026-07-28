# Phase 1 — Deploy + Soak Checklist

**Read this before steps 2–4 of the handoff.** This is the account-gated work
that the build session can't do for you. Everything here is concrete and ordered.

---

## Step 2 — Accounts & keys (you, ~30 min)

Create these in order. Each unlocks the next.

### 2a. Supabase project (needed first — everything points at it)
1. https://supabase.com/dashboard → New project. Name it `fin-content-engine`.
2. Set a strong DB password; save it to a password manager immediately.
3. Wait ~2 min for provisioning.
4. In **Project Settings → API**, collect:
   - `Project URL` → this becomes `FCE_SUPABASE_URL`
   - `service_role` key → `FCE_SUPABASE_SERVICE_KEY` (⚠️ this bypasses RLS — treat like a prod secret)
   - `anon` `public` key → not needed for P1 (GUI is P3), but note it.
5. In **Project Settings → Database → Connection string → URI**, collect the
   direct Postgres URL. Substitute your password. → `FCE_DATABASE_URL`
6. Apply migrations: in **SQL Editor**, paste each file in order and Run:
   `supabase/migrations/001_init.sql` → `002_rls.sql` → `003_seed_sources.sql`
   → `004_set_owner.sql` → `005_indexes.sql`. Verify each says "Success".
7. In **Table Editor**, confirm 12 rows in `sources` and 4 rows in `config`.

### 2b. Deploy the embed edge function
1. Install the Supabase CLI: `npm i -g supabase` (you have Node 24).
2. `supabase login` → auth in browser.
3. From the repo root: `supabase functions deploy embed --project-ref <your-ref>`
   (find `<your-ref>` in Project Settings → General → Reference ID).
4. Test it: in **Edge Functions → embed → Logs**, or with curl:
   ```bash
   curl -X POST https://<your-ref>.functions.supabase.co/embed \
     -H "Authorization: Bearer <service_role_key>" \
     -H "Content-Type: application/json" \
     -d '{"text":"Tata Sons IPO"}'
   ```
   Expect `{"embedding":[...384 floats...]}`.
5. The function URL → `FCE_EMBEDDING_EDGE_FUNCTION_URL`.

### 2c. Anthropic key (NOT needed for P1 — LLMs are P2)
Skip for now. You'll need it for P2 (Haiku scoring/drafting/judge).

### 2d. Railway account
1. https://railway.app → sign in with GitHub (you'll push the repo there).
2. New Project → Deploy from GitHub repo. (If the repo isn't on GitHub yet,
   create a private repo and push — `git remote add origin ...` then `git push -u`.)

---

## Step 3 — Deploy the worker to Railway

### 3a. Create `.env` locally (for `make smoke` in step 3c)
Copy `.env.example` to `.env` and fill in the values from step 2:
```
FCE_SUPABASE_URL=https://<your-ref>.supabase.co
FCE_SUPABASE_SERVICE_KEY=<service_role_key>
FCE_DATABASE_URL=postgresql://postgres:<pw>@db.<your-ref>.supabase.co:5432/postgres
FCE_EDGAR_USER_AGENT=Fin-Content Engine fin-content@<your-email> (<Your Name>)
FCE_EMBEDDING_EDGE_FUNCTION_URL=https://<your-ref>.functions.supabase.co/embed
FCE_EMBED_MOCK=false
```
⚠️ `.env` is gitignored. Never commit it.

### 3b. Configure Railway
1. In Railway → your service → **Variables**, add every `FCE_*` from `.env`.
   (Railway reads these at runtime; the worker picks them up via pydantic-settings.)
2. **Settings → Networking → Generate Domain** → gives you a public URL for `/health`.
3. **Settings → Deploy → Start Command**: confirm it's
   `uvicorn app.main:app --host 0.0.0.0 --port $PORT` (Railway injects `$PORT`).
   The Dockerfile already does this; just verify.
4. **Settings → Deploy → Health Check Path**: set to `/health`. Railway will
   only mark the deploy live once `/health` returns 200.
5. Trigger a deploy. Watch the build logs.

### 3c. Run Layer 2 smoke locally first (catches config bugs before trusting the deploy)
```bash
make smoke
```
This runs ONE ingest cycle against **live feeds** into your **local** Docker DB
with the **real** edge function. If it prints `=== SMOKE OK ===`, the wiring
works end-to-end. If not, fix the config before debugging Railway.

### 3d. Verify the deployed worker
1. Once Railway says "Active", hit `https://<your-railway-domain>/health` in a
   browser or curl. Expect `200` with `{"process":"up","scheduler_running":true,"db_reachable":true}`.
2. Hit `/stats`. Expect 12 sources (10 active), 0 items initially, `embedding_health:"ok"`.
3. Wait 30 min (one RSS poll cycle). Hit `/stats` again — `items.total` should grow.

---

## Step 4 — The 24h soak (the real acceptance gate, §5.7 steps 3–7)

**Start this only after step 3d shows items flowing.** It needs 24h of wall-clock.

### 4a. Plan the window
The soak must **span at least one closed-market stretch** (blueprint hardening #1).
Ideal: start Friday evening IST → ends Saturday evening. India markets are closed
all weekend; US markets close Friday 2:30am IST. This exercises quiet-feed /
empty-result / divide-by-zero paths that a weekday-only soak hides.

### 4b. During the soak — the forced-retry hardening (do this once, mid-soak)
This validates the failure-recovery path (blueprint hardening #2):
1. In Railway → Variables, change `FCE_EMBEDDING_EDGE_FUNCTION_URL` to a **bad**
   URL (e.g. append `-broken`). Save. Railway redeploys.
2. Wait for one poll cycle (30 min). In Supabase **Table Editor → items**,
   confirm new items have `embedding = null` and `warnings` includes
   `embedding_failed`. They should still be clustered via keyword fallback.
3. In **audit_log**, confirm an `embedding_degraded` row exists.
4. Restore the correct URL. Railway redeploys.
5. Wait 30 min (one `embed_retry` cycle). Confirm:
   - The previously-null embeddings are now filled.
   - `audit_log` has at least one `embed_retry_success` row.

### 4c. At the 24h mark — run the acceptance checklist (§5.7 steps 4–7)
Hit `/stats` and check, in order:
1. Every **active** source: `last_status = "ok"`, `consecutive_failures = 0`.
2. `embedding_health = "ok"`.
3. `items.orphaned = 0` — **non-negotiable; if >0, P1 is NOT done.**
4. **No auto-disabled sources**: in Supabase SQL Editor run
   `SELECT * FROM audit_log WHERE action = 'ingest_unhealthy';` — expect zero rows.
   (NSE and LE `active=false` is fine — they were seeded inactive.)
5. In Supabase studio, spot-check 5 stories in Table Editor → stories → click
   into story_items. Each should be a sensible cluster; no "TCS Q2 + TCS buyback"
   collapsed into one.
6. Force-idempotency check: `curl -X POST https://<railway>/ingest/trigger?source_id=<an-rss-source-id>`.
   Expect `new: 0` in the response (no duplicate inserts).
7. In audit_log, confirm `worker_start`, multiple `ingest_run`, multiple
   `cluster_new_story`, and the retry events from 4b.

**If all 7 pass: Phase 1 is DONE.** Move to P2 (Brain + Gate) per blueprint §10.

---

## If something breaks

- **`/health` returns 503 with `db_reachable:false`**: Railway can't reach
  Supabase. Check `FCE_DATABASE_URL` — Supabase's pooler vs direct connection
  can differ. The direct connection (port 5432) is needed for some pgvector ops.
- **`embedding_health:"degraded"` for >1 cycle**: the edge function is failing.
  Check Supabase → Edge Functions → embed → Logs. Common cause: the function
  wasn't deployed, or the service-role key in `FCE_SUPABASE_SERVICE_KEY` is wrong.
- **All sources auto-disabled after a few hours**: a feed is consistently
  returning non-200. Check `audit_log` for `ingest_unhealthy` rows, identify
  the source, and either fix its URL in the `sources` table or set `active=false`.
- **`items.orphaned > 0`**: a story creation crashed mid-transaction. This
  shouldn't happen (atomic transaction) — if it does, it's a real bug. Note the
  orphaned item ids and report; don't declare P1 done.

---

## What to hand to the next session (P2)

When the soak is green, the P2 handoff prompt is in `fin-content-engine-FINAL-blueprint.md` §10.
P2 adds: LLM router, Haiku scoring (writes score/angle/vertical/content_archetype),
archetype-aware drafting (two model-variants), L1+L2 compliance gate, voice pack v1.
Bring this repo + the soak evidence + your Anthropic key.
