# Phase 1 — VPS Deploy Runbook (bare process on Ubuntu 24.04)

**Audience:** novice-friendly. Every command says **where** to type it, **what** it
does, and **how to verify** it worked. Work top to bottom; don't skip verify steps.

**Goal:** the fin-content-engine worker running on your VPS (reachable at IP
`160.250.204.73`, public hostname `fce.lamkalabs.com` once DNS is set up in
Phase 8), behind Caddy TLS, talking to local Postgres+pgvector and the cloud
Supabase edge function for embeddings. Zero Railway, zero cloud DB cost.
Co-located on the box alongside your trading desk — isolated via a dedicated
`fce` user, a separate `fce` Postgres database, and a separate systemd service.

**Topology reminder:**
```
Internet → Caddy (TLS) → worker (systemd, :8000) → Postgres+pgvector (:5432)
                                              └→ Supabase cloud (embeddings only)
```

**Two things you'll need before starting:**
- A GitHub account (the free tier is fine; we'll make a private repo).
- A Supabase account (free tier; we only use it for the edge function).

---

## PHASE 0 — Prerequisites (on your Windows machine)

Done on your local PC, before touching the VPS. Collects everything the VPS steps need.

### 0.1 Verify you can SSH into the VPS
**Where:** your Windows machine, Command Prompt or PowerShell.
**What:** confirms you have shell access to the box.
```cmd
ssh khooptong@160.250.204.73
```
(Use whatever username your VPS provider gave you — `khooptong` is the example
from your dashboard. If your provider gave you a different username, use that.)
**Verify:** you see a prompt like `khooptong@desk:~$`. Type `exit` to leave.
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

### 0.3 Create the Supabase project + deploy the edge function
**Where:** your browser (supabase.com) and Command Prompt.
**What:** stands up the embeddings endpoint. This is the ONLY thing we keep
Supabase for.

1. https://supabase.com/dashboard → **New project**. Name: `fin-content-engine`.
   Pick a strong DB password and **save it** (you won't need the DB itself, but
   the project needs one to exist). Wait ~2 min for provisioning.
2. **Project Settings → API** — collect these three values into a notes file:
   - `Project URL` (looks like `https://abcdxyz.supabase.co`)
   - `service_role` secret key (long string; click "Reveal")
   - `Project Ref` (in **Settings → General**, a short hash like `abcdxyz...`)
3. Deploy the edge function from your Windows machine:
   ```cmd
   npm install -g supabase
   supabase login
   ```
   (Browser opens to auth. Approve.)
   ```cmd
   cd "F:\Content Creation Project"
   supabase functions deploy embed --project-ref <your-project-ref>
   ```
4. **Test it works** — in Command Prompt:
   ```cmd
   curl -X POST https://<your-project-ref>.functions.supabase.co/embed -H "Authorization: Bearer <service_role_key>" -H "Content-Type: application/json" -d "{\"text\":\"Tata Sons IPO\"}"
   ```
   **Verify:** you get back `{"embedding":[...a long list of numbers...]}`.
   **If it fails:** check Supabase dashboard → Edge Functions → `embed` → Logs.

✅ **End of Phase 0.** You now have: SSH access, code on GitHub, and a working
embeddings endpoint with its URL + key saved.

---

## PHASE 1 — VPS basics: connect, update, install packages

**Where:** SSH'd into the VPS (run `ssh khooptong@160.250.204.73` first).

### 1.1 Update the system
```bash
sudo apt update && sudo apt upgrade -y
```
**What:** refreshes the package list and applies security updates.
**Verify:** ends without errors. If it asks "restart services automatically?",
say yes.

### 1.2 Install the packages we need
```bash
sudo apt install -y postgresql-16 postgresql-16-pgvector python3.12 python3.12-venv caddy git curl
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
sudo apt install -y postgresql-16-pgvector || sudo apt install -y pgvector
```

✅ **End of Phase 1.** All tools installed.

---

## PHASE 2 — Create the `fce` user and directory structure

**Where:** SSH'd into the VPS.

### 2.1 Create the dedicated user
```bash
sudo useradd --system --create-home --home-dir /opt/fce --shell /usr/sbin/nologin fce
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
sudo mkdir -p /opt/fce/releases
sudo chown -R fce:fce /opt/fce
sudo chmod 750 /opt/fce
```
**What:** makes the releases dir and hands ownership of `/opt/fce` to the `fce`
user. Mode 750 = owner can do everything, group can read, nobody else can see in.

### 2.3 Let the `fce` user fetch from GitHub
The `fce` user has `nologin` shell, so it can't run interactive git. We'll clone
the repo **as your user** into a release dir, then hand ownership to `fce`:
```bash
sudo -u khooptong git clone https://github.com/<you>/fin-content-engine.git /opt/fce/releases/initial
sudo ln -s /opt/fce/releases/initial /opt/fce/current
sudo chown -R fce:fce /opt/fce/releases /opt/fce/current
```
(Replace `<you>` with your GitHub username. If the repo is private, git will
prompt for credentials — use a Personal Access Token as the password.)
**What:** checks out the code into a release dir, makes `/opt/fce/current` a
symlink to it, and gives the `fce` user ownership.
**Verify:**
```bash
ls -la /opt/fce/current/worker/app/main.py
```
Should show the file (the symlink resolves). If "No such file," the clone failed.

✅ **End of Phase 2.** User + code in place.

---

## PHASE 3 — Postgres: database, user, pgvector, light tuning

**Where:** SSH'd into the VPS.

### 3.1 Check Postgres is running
```bash
sudo systemctl status postgresql
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
sudo tee /etc/postgresql/16/main/conf.d/fce-tuning.conf >/dev/null <<'EOF'
shared_buffers = 1GB
effective_cache_size = 4GB
work_mem = 16MB
maintenance_work_mem = 256MB
EOF
sudo systemctl restart postgresql
```
**What:** raises Postgres memory settings from defaults (which assume a tiny
machine). Makes clustering queries faster. Safe because the worker is the only
client.
**Verify:** `sudo systemctl status postgresql` is green again.

### 3.4 Confirm Postgres only listens locally (security check)
```bash
sudo grep -i listen_addresses /etc/postgresql/16/main/postgresql.conf
```
**Verify:** shows `listen_addresses = 'localhost'` (the default). If it says
`'*'`, edit it to `'localhost'` and restart — we do NOT want Postgres reachable
from the internet.

✅ **End of Phase 3.** Database ready.

---

## PHASE 4 — Python environment + dependencies

**Where:** SSH'd into the VPS.

### 4.1 Create the venv as the `fce` user
```bash
sudo -u fce /usr/bin/python3.12 -m venv /opt/fce/.venv
```
**What:** creates an isolated Python environment at `/opt/fce/.venv`.
**Verify:**
```bash
/opt/fce/.venv/bin/python --version
```
Should print `Python 3.12.x`.

### 4.2 Install the worker dependencies
```bash
sudo -u fce /opt/fce/.venv/bin/pip install --upgrade pip
sudo -u fce /opt/fce/.venv/bin/pip install -e /opt/fce/current/worker
```
**What:** installs FastAPI, APScheduler, psycopg3, pgvector, feedparser, etc.
The `-e` (editable) install means code changes under `/opt/fce/current` take
effect on worker restart without reinstalling.
**Verify:** this should print the worker's banner without error:
```bash
/opt/fce/.venv/bin/python -c "from app.main import app; print('import ok')"
```
(If "import ok" prints, every dependency resolved.)
**If it fails:** the error usually names the missing package. Share it and we'll fix.

✅ **End of Phase 4.** Worker can run.

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

## PHASE 6 — The `.env` file (secrets)

**Where:** SSH'd into the VPS.

```bash
sudo tee /opt/fce/.env >/dev/null <<'EOF'
FCE_SUPABASE_URL=https://<your-project-ref>.supabase.co
FCE_SUPABASE_SERVICE_KEY=<service_role_key_from_phase_0>
FCE_DATABASE_URL=postgresql://fce:<DB_PASSWORD>@127.0.0.1:5432/fce
FCE_EDGAR_USER_AGENT=Fin-Content Engine fin-content@lamkalabs.com (Your Name)
FCE_EMBEDDING_EDGE_FUNCTION_URL=https://<your-project-ref>.functions.supabase.co/embed
FCE_EMBED_MOCK=false
FCE_SCHEDULER_MAX_WORKERS=4
FCE_LOG_LEVEL=INFO
EOF
sudo chown fce:fce /opt/fce/.env
sudo chmod 600 /opt/fce/.env
```
**Replace before pasting:**
- `<your-project-ref>` — the short hash from Supabase Phase 0
- `<service_role_key_from_phase_0>` — the long service_role key
- `<DB_PASSWORD>` — the password you set in Phase 3.2
- `(Your Name)` — your actual name (EDGAR requires a human-readable UA)

**What:** writes all config to `/opt/fce/.env`, owned by `fce`, readable only by
`fce` (mode 600 = owner-only). This is option A from the design — one file, one
backup target, no secrets manager overhead.
**Verify:**
```bash
sudo cat /opt/fce/.env
```
(You need `sudo` because mode 600 means even your user can't read it.) Confirm
all values look right. **Do not commit this file — it's gitignored for a reason.**

✅ **End of Phase 6.** Secrets configured.

---

## PHASE 7 — The systemd unit (the worker as a service)

**Where:** SSH'd into the VPS.

### 7.1 Write the unit file
```bash
sudo tee /etc/systemd/system/fce-worker.service >/dev/null <<'EOF'
[Unit]
Description=Fin-Content Engine worker
After=network-online.target postgresql.service
Wants=network-online.target

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
```
**What:** tells systemd how to run the worker: as user `fce`, from the worker
dir, reading env vars from `.env`, listening on `127.0.0.1:8000` (localhost
only — Caddy will be the public face). Restart on crash with 5s backoff.

### 7.2 Enable and start it
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now fce-worker
```
**What:** reloads systemd so it sees the new unit, then enables (start on boot)
and starts it now.

### 7.3 Verify it's running
```bash
sudo systemctl status fce-worker
```
**Verify:** green "active (running)". Then check the logs:
```bash
sudo journalctl -u fce-worker -f
```
( `-f` follows the log like `tail -f`. Ctrl+C to exit.) You should see
`worker_started` and the list of jobs. Look for `db_pool_opened` — that means
it connected to Postgres.

### 7.4 Hit the health endpoint locally
```bash
curl http://127.0.0.1:8000/health
```
**Verify:** `{"process":"up","scheduler_running":true,"db_reachable":true}`.
**If `db_reachable` is false:** check `/opt/fce/.env` has the right DB password
and the `fce` role exists (Phase 3.2).

✅ **End of Phase 7.** Worker is live on localhost.

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
sudo cat /etc/caddy/Caddyfile
```
If it has content, we add to it. If it's the default placeholder, we replace.

To add the fin-content-engine site:
```bash
sudo tee -a /etc/caddy/Caddyfile >/dev/null <<'EOF'

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
sudo systemctl reload caddy
```
**Verify:** Caddy is green:
```bash
sudo systemctl status caddy
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
sudo journalctl -u fce-worker -f
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

**Update the code after a change:**
```bash
sudo -u khooptong git -C /opt/fce/current pull
sudo systemctl restart fce-worker
```

**Check logs:**
```bash
sudo journalctl -u fce-worker -f          # follow
sudo journalctl -u fce-worker --since "1 hour ago"
```

**Restart the worker:**
```bash
sudo systemctl restart fce-worker
```

**Stop / start:**
```bash
sudo systemctl stop fce-worker
sudo systemctl start fce-worker
```

**Roll back to a previous release** (if you set up release dirs in Phase 2):
```bash
sudo rm /opt/fce/current
sudo ln -s /opt/fce/releases/<previous> /opt/fce/current
sudo chown -h fce:fce /opt/fce/current
sudo systemctl restart fce-worker
```

---

## If something breaks

| Symptom | First check |
|---|---|
| `systemctl status` shows "failed" | `sudo journalctl -u fce-worker -n 50` — the traceback is there |
| `/health` returns `db_reachable:false` | `.env` DB password; `fce` role exists; Postgres running |
| `/health` returns `scheduler_running:false` | restart the worker: `sudo systemctl restart fce-worker` |
| `/stats` shows `embedding_health:"degraded"` | Supabase edge function down — check Supabase dashboard logs |
| Caddy returns 502 | worker not running — Phase 7.3 |
| Caddy returns TLS error | DNS not propagated, or port 80/443 blocked by VPS firewall |
| No items appearing | check `audit_log` table for `ingest_error` rows; sources may have auto-disabled |

**Firewall note:** if your VPS has `ufw` enabled, allow Caddy's ports:
```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow ssh
```
Do **not** open 5432 (Postgres) or 8000 (worker) to the internet — Caddy proxies
to them over localhost.
