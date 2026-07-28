# Phase 1 — VPS Deploy Runbook (bare process on Ubuntu 24.04)

**Audience:** novice-friendly. Every command says **where** to type it, **what** it
does, and **how to verify** it worked. Work top to bottom; don't skip verify steps.

**Goal:** the fin-content-engine worker running on your VPS (reachable at IP
`160.250.204.73`, public hostname `fce.lamkalabs.com` via DNS), behind Caddy
TLS, talking to local Postgres+pgvector and a local embedder service
(self-hosted gte-small). **Zero external cloud dependencies in P1** — no
Railway, no cloud DB, no cloud embeddings. Co-located on the box alongside your
trading desk — isolated via a dedicated `fce` user, a separate `fce` Postgres
database, and two separate systemd services (worker + embedder).

**Topology:**
```
                        Internet
                           │
                           ▼
            ┌──────────────────────────────┐
            │  Caddy  (TLS for fce.lamkalabs.com)
            │  → 127.0.0.1:8000 (worker)   │
            └──────────────────────────────┘
                           │ localhost
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
   ┌─────────┐      ┌──────────────┐    ┌──────────────┐
   │ worker  │ ───→ │  embedder    │    │  Postgres 16 │
   │ :8000   │ ───→ │  :8001       │    │  + pgvector  │
   │ systemd │      │  gte-small   │    │  db: fce     │
   └─────────┘      └──────────────┘    └──────────────┘
```

**What you need before starting:**
- A GitHub account (free tier; we make a private repo).
- SSH access to the VPS (Phase 0.1 confirms this).
- The repo pushed to GitHub (Phase 0.2).
- DNS pointed at the box (Phase 8 — already done: `fce.lamkalabs.com` → `160.250.204.73`).

**No Supabase account needed in P1.** Supabase comes back in P3 for GUI auth.

---

## PHASE 0 — Prerequisites (on your Windows machine)

Done on your local PC, before touching the VPS. Collects everything the VPS steps need.

### 0.1 Verify you can SSH into the VPS
**Where:** your Windows machine, Command Prompt or PowerShell.
**What:** confirms you have shell access to the box.
```cmd
ssh root@160.250.204.73
```
**Verify:** you see a prompt like `root@desk:~#`. Type `exit` to leave.
**If it fails:** your VPS provider's dashboard should show SSH credentials or
let you reset them. Some providers also offer a web console as a fallback.

### 0.2 Create a private GitHub repo and push the code
**Where:** your Windows machine, in the project folder.
**What:** puts your code somewhere the VPS can pull it from. Also your backup.
```cmd
cd "F:\Content Creation Project"
```
Then on github.com: New repository → name it `fin-content-engine` → **Private** →
don't add README/gitignore (we have them). Copy the URL it gives you
(`https://github.com/<you>/fin-content-engine.git`).

Back in Command Prompt:
```cmd
git remote add origin https://github.com/<you>/fin-content-engine.git
git push -u origin main
```
(GitHub will ask for credentials the first time; use a Personal Access Token as
the password if asked — GitHub no longer accepts account passwords over HTTPS.)
**Verify:** refresh the GitHub repo page; you should see all 51 files.

### 0.3 Embeddings — self-hosted on the VPS (no Supabase in P1)
**Where:** nothing to do in Phase 0 — the embedder is built into the repo
(`embedder/app.py`) and we install it as part of the VPS setup (Phase 4).

**Why no Supabase:** the original plan was to use Supabase's hosted gte-small
edge function for embeddings. In testing it OOM-killed on the free tier
(`EarlyDrop` — 10MB memory ceiling too small to load the model). We replaced
it with a local embedder service on the VPS: a ~40-line FastAPI app wrapping
`sentence-transformers/gte-small`, running on `127.0.0.1:8001` as its own
systemd service (`fce-embedder.service`).

This is Option C from the deploy design — self-host the heavy stuff on the VPS.
Consequence: **P1 has zero external cloud dependencies.** No Supabase project,
no API keys, no egress costs, no pause-on-inactivity. Supabase comes back in
P3 for the GUI's auth (magic-link login).

✅ **End of Phase 0.** You now have: SSH access, DNS pointed, code on GitHub.
That's all the prerequisites — the embedder ships with the repo.

---

## PHASE 1 — VPS basics: connect, update, install packages

**Where:** SSH'd into the VPS (run `ssh root@160.250.204.73` first).

### 1.1 Update the system
```bash
apt update && apt upgrade -y
```
**What:** refreshes the package list and applies security updates.
**Verify:** ends without errors. If it asks "restart services automatically?",
say yes.

### 1.2 Install the packages we need
```bash
apt install -y postgresql-16 postgresql-16-pgvector python3.12 python3.12-venv caddy git curl
```
**What:** installs Postgres 16 + the pgvector extension, Python 3.12 + venv
support, the Caddy web server (handles TLS automatically), git, and curl.
**Verify each:**
```bash
psql --version               # should say 16.x
python3.12 --version         # should say Python 3.12.x
caddy version                # should print a version string
git --version
```
**If pgvector package isn't found:** Ubuntu 24.04 should have it, but if not:
```bash
apt install -y postgresql-16-pgvector || apt install -y pgvector
```

✅ **End of Phase 1.** All tools installed.

---

## PHASE 2 — Create the `fce` user and directory structure

**Where:** SSH'd into the VPS.

### 2.1 Create the dedicated user
```bash
useradd --system --create-home --home-dir /opt/fce --shell /usr/sbin/nologin fce
```
**What:** creates an unprivileged system user called `fce` whose home is
`/opt/fce`. The worker will run as this user — never as root, never as your
personal login. The `nologin` shell means nobody can SSH in as `fce`.
**Verify:**
```bash
id fce
```
Should print something with `uid=...($fce)`. If it errors "user does not exist,"
the command failed — re-run it.

### 2.2 Create the deploy directory layout
```bash
mkdir -p /opt/fce/releases
chown -R fce:fce /opt/fce
chmod 750 /opt/fce
```
**What:** makes the releases dir and hands ownership of `/opt/fce` to the `fce`
user. Mode 750 = owner can do everything, group can read, nobody else can see in.

### 2.3 Clone the repo into the deploy dir
```bash
git clone https://github.com/<you>/fin-content-engine.git /opt/fce/releases/initial
ln -s /opt/fce/releases/initial /opt/fce/current
mkdir -p /opt/fce/embedder
chown -R fce:fce /opt/fce/releases /opt/fce/current /opt/fce/embedder
```
(Replace `<you>` with your GitHub username. If the repo is private, git will
prompt for credentials — use a Personal Access Token as the password.)
**What:** checks out the code into a release dir, makes `/opt/fce/current` a
symlink to it, and gives the `fce` user ownership. The extra `/opt/fce/embedder`
dir is for the embedder service's venv (Phase 4.2) — it lives outside `current`
so it survives release rollbacks.
**Verify:**
```bash
ls -la /opt/fce/current/worker/app/main.py
ls -la /opt/fce/current/embedder/app.py
```
Both should show files (the symlink resolves). If "No such file," the clone failed.

✅ **End of Phase 2.** User + code in place.

---

## PHASE 3 — Postgres: database, user, pgvector, light tuning

**Where:** SSH'd into the VPS.

### 3.1 Check Postgres is running
```bash
systemctl status postgresql
```
**Verify:** green "active (running)". If not: `sudo systemctl enable --now postgresql`.

### 3.2 Create the database role + database + extension
```bash
sudo -u postgres psql
```
(You're now in the Postgres prompt, looks like `postgres=#`.) Paste this — but
**first pick a strong DB password** and replace `<DB_PASSWORD>`:
```sql
CREATE ROLE fce LOGIN PASSWORD '<DB_PASSWORD>';
CREATE DATABASE fce OWNER fce;
\c fce
CREATE EXTENSION IF NOT EXISTS vector;
GRANT ALL PRIVILEGES ON DATABASE fce TO fce;
\q
```
**What:** creates a DB login role `fce` with the password you chose, a database
called `fce` owned by it, enables the pgvector extension in that DB.
**Verify:** back at the shell, this should work (it'll ask for the password):
```bash
psql "postgresql://fce:<DB_PASSWORD>@127.0.0.1:5432/fce" -c "SELECT extname FROM pg_extension;"
```
Should list `vector` (and `plpgsql`). **Save `<DB_PASSWORD>` somewhere safe.**

### 3.3 (Optional but recommended) Light tuning for 8GB RAM
```bash
tee /etc/postgresql/16/main/conf.d/fce-tuning.conf >/dev/null <<'EOF'
shared_buffers = 1GB
effective_cache_size = 4GB
work_mem = 16MB
maintenance_work_mem = 256MB
EOF
systemctl restart postgresql
```
**What:** raises Postgres memory settings from defaults (which assume a tiny
machine). Makes clustering queries faster. Safe because the worker is the only
client.
**Verify:** `sudo systemctl status postgresql` is green again.

### 3.4 Confirm Postgres only listens locally (security check)
```bash
grep -i listen_addresses /etc/postgresql/16/main/postgresql.conf
```
**Verify:** shows `listen_addresses = 'localhost'` (the default). If it says
`'*'`, edit it to `'localhost'` and restart — we do NOT want Postgres reachable
from the internet.

✅ **End of Phase 3.** Database ready.

---

## PHASE 4 — Python environments + dependencies (worker AND embedder)

**Where:** SSH'd into the VPS.

There are **two** Python services: the worker (FastAPI + APScheduler, reads
feeds and clusters) and the embedder (FastAPI + sentence-transformers, serves
gte-small embeddings). Each gets its own venv so dependency upgrades don't
cross-contaminate.

### 4.1 Worker venv
```bash
sudo -u fce /usr/bin/python3.12 -m venv /opt/fce/.venv
sudo -u fce /opt/fce/.venv/bin/pip install --upgrade pip
sudo -u fce /opt/fce/.venv/bin/pip install -e /opt/fce/current/worker
```
**What:** creates the worker's venv at `/opt/fce/.venv` and installs FastAPI,
APScheduler, psycopg3, pgvector, feedparser, etc. The `-e` (editable) install
means code changes under `/opt/fce/current` take effect on worker restart.
**Verify:**
```bash
/opt/fce/.venv/bin/python --version          # Python 3.12.x
/opt/fce/.venv/bin/python -c "from app.main import app; print('import ok')"
```
If "import ok" prints, every worker dependency resolved.

### 4.2 Embedder venv + pre-download the model
```bash
sudo -u fce /usr/bin/python3.12 -m venv /opt/fce/embedder/.venv
sudo -u fce /opt/fce/embedder/.venv/bin/pip install --upgrade pip
sudo -u fce /opt/fce/embedder/.venv/bin/pip install -e /opt/fce/current/embedder
```
**What:** creates the embedder's venv and installs `sentence-transformers`
(which pulls `torch` — a ~800MB download, this step takes a few minutes).
**Pre-warm the model** so the first real request isn't slow:
```bash
sudo -u fce /opt/fce/embedder/.venv/bin/python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('thenlper/gte-small')"
```
This downloads `gte-small` (~130MB) from Hugging Face and caches it. The first
time takes ~30s; subsequent loads are instant.
**Verify:** the command finishes without error. (If it can't reach
`huggingface.co`, check the VPS's outbound network — some providers block
default routes.)

✅ **End of Phase 4.** Both services can run.

---

## PHASE 5 — Run the migrations

**Where:** SSH'd into the VPS.

```bash
for f in /opt/fce/current/supabase/migrations/001_init.sql \
         /opt/fce/current/supabase/migrations/002_rls.sql \
         /opt/fce/current/supabase/migrations/003_seed_sources.sql \
         /opt/fce/current/supabase/migrations/004_set_owner.sql \
         /opt/fce/current/supabase/migrations/005_indexes.sql; do
    echo "=== applying $f ==="
    sudo -u postgres psql -d fce -v ON_ERROR_STOP=1 -f "$f"
done
```
**What:** runs all five migrations in order. `ON_ERROR_STOP=1` means if any one
fails, it stops immediately (rather than silently leaving a half-built schema).
**Verify:**
```bash
sudo -u postgres psql -d fce -c "\dt"
```
Should list 15 tables (`sources`, `items`, `stories`, ... `evergreen_bank`).
```bash
sudo -u postgres psql -d fce -c "SELECT count(*) FROM sources;"
```
Should say `12`. And:
```bash
sudo -u postgres psql -d fce -c "SELECT count(*) FROM config;"
```
Should say `4`.

✅ **End of Phase 5.** Schema + seed data in place.

---

## PHASE 6 — The `.env` file (worker config)

**Where:** SSH'd into the VPS.

```bash
tee /opt/fce/.env >/dev/null <<'EOF'
FCE_DATABASE_URL=postgresql://fce:<DB_PASSWORD>@127.0.0.1:5432/fce
FCE_EDGAR_USER_AGENT=Fin-Content Engine fin-content@lamkalabs.com (Your Name)
FCE_EMBEDDING_EDGE_FUNCTION_URL=http://127.0.0.1:8001/embed
FCE_EMBED_MOCK=false
FCE_SCHEDULER_MAX_WORKERS=4
FCE_LOG_LEVEL=INFO
EOF
chown fce:fce /opt/fce/.env
chmod 600 /opt/fce/.env
```
**Replace before pasting:**
- `<DB_PASSWORD>` — the password you set in Phase 3.2
- `(Your Name)` — your actual name (EDGAR requires a human-readable UA)

**Note:** no Supabase values in P1. Embeddings point at the local embedder
service (`127.0.0.1:8001`), which we set up in Phase 4.2 and start in Phase 7.
Supabase URLs/keys aren't needed until P3 (GUI auth); leave them out.

**What:** writes the worker's config to `/opt/fce/.env`, owned by `fce`,
readable only by `fce` (mode 600 = owner-only). One file, one backup target,
no secrets-manager overhead.
**Verify:**
```bash
cat /opt/fce/.env
```
As root you can read it directly. Confirm all values look right. **Do not
commit this file — it's gitignored for a reason.**

✅ **End of Phase 6.** Secrets configured.

---

## PHASE 7 — systemd units (embedder + worker as services)

**Where:** SSH'd into the VPS.

Two services to install: the **embedder** first (the worker depends on it for
embeddings), then the **worker**.

### 7.1 Install the embedder unit
```bash
cp /opt/fce/current/embedder/fce-embedder.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now fce-embedder
```
**What:** copies the embedder's unit file from the repo into systemd, reloads,
then enables + starts it. The unit (from `embedder/fce-embedder.service`) runs
the embedder as user `fce` on `127.0.0.1:8001`, restarts on failure.
**Verify it's running and the model loaded:**
```bash
systemctl status fce-embedder
curl http://127.0.0.1:8001/health
```
`status` should show green "active (running)". The `/health` response should
include `"model_loaded": true`. **First start takes ~5s** (loading gte-small);
if `/health` says `model_loaded: false`, wait 10s and retry.
**Test an actual embedding:**
```bash
curl -X POST http://127.0.0.1:8001/embed -H "Content-Type: application/json" -d '{"text":"Tata Sons IPO"}'
```
Should return `{"embedding":[...384 numbers...]}`. If this works, the embedder
is fully operational — the hardest piece is done.

### 7.2 Install the worker unit
```bash
tee /etc/systemd/system/fce-worker.service >/dev/null <<'EOF'
[Unit]
Description=Fin-Content Engine worker
After=network-online.target postgresql.service fce-embedder.service
Wants=network-online.target
Requires=fce-embedder.service

[Service]
Type=simple
User=fce
Group=fce
WorkingDirectory=/opt/fce/current/worker
EnvironmentFile=/opt/fce/.env
ExecStart=/opt/fce/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=5

# Hardening — the worker doesn't need these privileges
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now fce-worker
```
**What:** writes the worker's unit file (note `Requires=fce-embedder.service` —
systemd won't start the worker until the embedder is up), reloads, enables,
starts. Restart on crash with 5s backoff.

### 7.3 Verify the worker is running
```bash
systemctl status fce-worker
journalctl -u fce-worker -f
```
(`-f` follows the log like `tail -f`. Ctrl+C to exit.) You should see
`worker_started` and the list of jobs. Look for `db_pool_opened` — that means
it connected to Postgres.

### 7.4 Hit the health endpoint locally
```bash
curl http://127.0.0.1:8000/health
```
**Verify:** `{"process":"up","scheduler_running":true,"db_reachable":true}`.
**If `db_reachable` is false:** check `/opt/fce/.env` has the right DB password
and the `fce` role exists (Phase 3.2).

✅ **End of Phase 7.** Both services are live on localhost.

---

## PHASE 8 — Caddy: TLS + public domain

**Where:** SSH'd into the VPS. Needs DNS done first.

### 8.1 Point DNS at the box
In your DNS provider (wherever `lamkalabs.com` is managed), add an A record:
- **Host:** `fce` (so the full domain is `fce.lamkalabs.com`)
- **Type:** A
- **Value:** `160.250.204.73` (your VPS IP from the dashboard)
- **TTL:** default

**Verify:** wait 1–5 min, then from your Windows machine:
```cmd
nslookup fce.lamkalabs.com
```
Should resolve to `160.250.204.73`. Don't proceed until it does.

### 8.2 Write the Caddyfile
If Caddy is already configured for other sites, **append** to the existing
Caddyfile rather than overwriting. Check first:
```bash
cat /etc/caddy/Caddyfile
```
If it has content, we add to it. If it's the default placeholder, we replace.

To add the fin-content-engine site:
```bash
tee -a /etc/caddy/Caddyfile >/dev/null <<'EOF'

fce.lamkalabs.com {
    reverse_proxy 127.0.0.1:8000
}
EOF
```
(The leading blank line separates it from whatever's already there.)
**What:** tells Caddy to serve `fce.lamkalabs.com`, auto-provision a Let's Encrypt
TLS cert for it, and proxy all requests to the worker on localhost:8000.

### 8.3 Reload Caddy
```bash
systemctl reload caddy
```
**Verify:** Caddy is green:
```bash
systemctl status caddy
```
Then, from your Windows machine (give TLS ~30s to provision on first hit):
```cmd
curl https://fce.lamkalabs.com/health
```
**Verify:** `{"process":"up",...}` over HTTPS. If it 502's, the worker isn't
running — check Phase 7.3. If it times out, DNS hasn't propagated — wait.

✅ **End of Phase 8.** Public HTTPS endpoint live.

---

## PHASE 9 — Verify the full chain end-to-end

**Where:** your Windows machine (browser/curl) + VPS (logs).

### 9.1 Watch the worker ingest
```bash
journalctl -u fce-worker -f
```
Within 30 min you should see `ingest_done` lines for the active sources, with
`new=N embedded=N`. Items are flowing.

### 9.2 Check /stats
From your Windows machine:
```cmd
curl https://fce.lamkalabs.com/stats
```
**Verify:** `items.total` grows over time; `embedding_health` is `"ok"`;
`items.orphaned` stays `0`.

### 9.3 If everything's green, you're deployed
This replaces the "deploy to Railway" step from the original handoff. The 24h
soak (P1-DEPLOY-SOAK-CHECKLIST.md steps 4a–4c) now runs against *this* box.

---

## Day-to-day operations (cheat sheet)

**Update the worker code after a change:**
```bash
git -C /opt/fce/current pull
systemctl restart fce-worker
```

**Update the embedder code after a change:**
```bash
git -C /opt/fce/current pull
systemctl restart fce-embedder
```

**Check logs:**
```bash
journalctl -u fce-worker -f          # follow worker
journalctl -u fce-embedder -f        # follow embedder
journalctl -u fce-worker --since "1 hour ago"
```

**Restart the worker / embedder:**
```bash
systemctl restart fce-worker
systemctl restart fce-embedder
```

**Stop / start:**
```bash
systemctl stop fce-worker
systemctl start fce-worker
# (same for fce-embedder)
```

**Roll back to a previous release** (if you set up release dirs in Phase 2):
```bash
rm /opt/fce/current
ln -s /opt/fce/releases/<previous> /opt/fce/current
chown -h fce:fce /opt/fce/current
systemctl restart fce-embedder
systemctl restart fce-worker
```

---

## If something breaks

| Symptom | First check |
|---|---|
| `systemctl status fce-worker` shows "failed" | `journalctl -u fce-worker -n 50` — the traceback is there |
| `systemctl status fce-embedder` shows "failed" | `journalctl -u fce-embedder -n 50` — usually a model-load failure or OOM |
| `/health` returns `db_reachable:false` | `.env` DB password; `fce` role exists; Postgres running |
| `/health` returns `scheduler_running:false` | restart the worker: `systemctl restart fce-worker` |
| `/stats` shows `embedding_health:"degraded"` | embedder not running or erroring — `curl http://127.0.0.1:8001/health`; check `journalctl -u fce-embedder -n 50` |
| `curl 127.0.0.1:8001/embed` returns 5xx | embedder crashed mid-model; `systemctl restart fce-embedder`; if it loops, the model file may be corrupt — re-run Phase 4.2's pre-warm step |
| Caddy returns 502 | worker not running — Phase 7.3 |
| Caddy returns TLS error | DNS not propagated, or port 80/443 blocked by VPS firewall |
| No items appearing | check `audit_log` table for `ingest_error` rows; sources may have auto-disabled |

**Firewall note:** if your VPS has `ufw` enabled, allow Caddy's ports:
```bash
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow ssh
```
Do **not** open 5432 (Postgres) or 8000 (worker) to the internet — Caddy proxies
to them over localhost.
