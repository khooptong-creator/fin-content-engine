# Fin-Content Engine — Master Build Blueprint (Reconciled, Final)

**Codename:** The Cyborg Desk
**Owner / Editor-in-chief:** UMinkoo (sole publish authority)
**Architect:** Claude (chat) · **Executor:** Opus / GLM in Claude Code
**Mission (one line):** An AI pipeline that reads the US + India market firehose, drafts compliant, sharp, human-sounding finance commentary for X and Instagram, and parks everything in a dashboard where one human clicks Approve. Nothing publishes without that click.

---

## 0. How to read this document

This blueprint reconciles three prior iterations into one. Understand what each contributed, because the layering is the point:

- **Strategic blueprint (v1 + competitor-teardown Addendum)** — the *what*, *why*, and *in what order*. Goals, the compliance bible, monetization realism, the voice pack, content archetypes, the funnel. This is **Part I** below.
- **Phase 1 Engineering Spec (Fable's design)** — the deep *how* for the first buildable unit: ingest → dedup → embed → cluster → `stories`. Preserved intact. This is **Part II** below. **Do not re-architect it; build it.**

**The one reconciliation that mattered:** both earlier documents numbered their phases 1–6 and meant different things by each number. This document adopts **one canonical phase map** (§6), derived from Fable's decomposition, because "prove clustering on real feeds before building the brain" is the correct de-risking order. Every phase reference in this document uses that map. The Addendum's "promote newsletter to Phase 1.5" intent is preserved as **P2.5** — the earliest point where drafting (its prerequisite) exists.

**Build order for the executor:** build **Part II (Phase 1)** first and completely. Part I governs everything after it. When P1's acceptance gate is green, return to §6/§10 for the P2 handoff.

---

# PART I — PROGRAM & STRATEGY

## 1. What we're building

A human-in-the-loop content operation. Automated pipelines read financial news (US + India), draft posts / threads / carousels / replies in your voice, run every word through a compliance gate, and queue it in an approval dashboard. You are the editor-in-chief of a newsroom staffed by three cheap, tireless LLMs.

### Goals
1. Ship 3–5 approved posts/day on X and 3–4 carousels/week on Instagram with **<30 min/day** of your time.
2. **Zero** published content that recommends buying/selling any specific security, fund, or product — enforced by machine, verified by you.
3. Reach X Creator Revenue Sharing eligibility, then diversify (newsletter, non-securities affiliate, sponsorships).
4. Every layer teaches you something real: scraping, embeddings, LLM orchestration, publishing APIs, funnel analytics.

### Non-goals (v1)
- **Full auto-posting.** Deliberately excluded. Your approval click is the compliance backstop *and* what keeps you the genuine author. No feature may ever publish without it.
- **Trading signals / anything touching the Lamka Trading Terminal.** Different universe, different regulator posture. Kept strictly separate.
- **Video / Reels.** Highest-effort format. Not in scope for v1.
- **Fake engagement** (auto-like, follow/unfollow bots). The fastest route to a platform ban, and the one form of automation platforms actively hunt.

---

## 2. The Compliance Bible (governs every phase)

The persona is **educator + analyst + commentator, never advisor.** This section is law.

### 2.1 The three-layer gate (built in P2, applied everywhere thereafter)

```
Draft ─► [L1: Regex Hard Gate] ─► [L2: LLM Judge] ─► [L3: Human Editor]
            deterministic           cross-model          YOU (final)
            blocklist               rubric, JSON verdict  approve/edit/reject
            BLOCK short-circuits ────┘ (skip L2 on L1 block)
```

- **L0 — System-prompt law.** Every drafting call carries a non-negotiable instruction block: no buy/sell/hold calls; no target prices, entry/exit levels, SL/TP; no "accumulate / book profit / SIP into X"; no allocation advice; no "best fund/stock for you"; no return promises. (Full text in the Voice Pack, §4.)
- **L1 — Regex hard gate (deterministic, free, instant).** Blocklist no LLM mood can bypass: `buy`, `sell`, `accumulate`, `target price`, `TP`, `SL`, `book profit`, `multibagger`, `sure shot`, `guaranteed returns`, `you should invest`, `best stock to`, `add to your portfolio`, plus Hindi/Hinglish equivalents (`kharido`, `becho`, `paisa double`). Also flags ticker/`$SYMBOL` near an imperative verb, and any % return projection tied to a named instrument. Match → auto-reject. **L1 BLOCK short-circuits L2.**
- **L2 — LLM judge.** A *different model than the drafter* (cross-model kills sycophancy). Rubric: directs a reader toward/away from a specific security/product? Implies assured returns? Returns strict JSON: `{verdict: PASS|FLAG|BLOCK, violations:[{quote, rule, severity}], suggested_fix}`. Be strict — false positives are cheap, false negatives are not.
- **L3 — You.** Nothing ships without your click.

**Gate rules (from design review, all P2):**
- L1 short-circuits L2.
- **Replies pass the same gate.**
- **Re-lint after human edit** (lightweight L1 pass on the final edited text).
- **Log blocked/flagged events**, not just published ones.
- **Resist a third automated LLM layer.**

### 2.2 The listicle trap (the sharpest compliance rule — read twice)

The obvious finfluencer format — "10 mutual funds that beat the index," each with a link — is **a recommendation, delivered at scale, by an unregistered person, to an Indian audience.** That is precisely what SEBI's finfluencer framework punishes. The transferable property of a viral listicle is **bookmarkability, not the list-of-instruments format.** So the pipeline generates save-worthy artifacts that contain *zero instruments*:

| Finfluencer format | Compliant equivalent |
|---|---|
| 10 funds/stocks with links | 10 line items in a cash-flow statement people misread |
| "Best fund for X" | How to read the related-party-transactions note |
| Tool/fund roundup | This week's macro calendar |
| Comparison of instruments | Growth vs value vs quality: what each style actually *measures* |
| "New launch alert" | What changed in the latest SEBI/RBI circular, in plain language |

Enforced structurally via **content archetypes** (§5): every draft stamped with a pre-approved archetype; **new archetypes require owner approval before the drafting engine may use them** — so the model can't invent "top 5 funds" at 3 a.m.

### 2.3 SEBI / SEC design rules (verify current guidance at build time)
- SEBI restricts regulated entities from partnering with unregistered finfluencers, and has constrained how "educational" content may use recent price data of specific securities. **Practical rule:** lean on fundamentals, filings, and business analysis rather than price levels + implied action.
- **Mandatory, non-deletable disclaimer footer** on market content (you may rephrase, not remove).
- **Store every published post + source items + compliance report permanently.**
- One professional consult before launch; re-check quarterly. Not legal advice.

### 2.4 Sponsorship & affiliate (relevant from P6; policy written now)
- **Affiliate is a trap in Indian finance.** Do not wire broker/fund referral links. Safe affiliate surface: books, courses, non-securities software, your own digital products.
- **Sponsor allowlist:** software tools, data/screener platforms, books, courses, SaaS. Off-limits: anything soliciting for a specific security/fund/PMS.
- **Disclosure enforcement:** any `is_sponsored` draft must carry a machine-inserted disclosure label; sponsored content without a disclosure token cannot reach publish.

---

## 3. Monetization reality + funnel strategy

- **X Creator Revenue Sharing** requires active X **Premium**, ~**500 verified followers**, ~**5M organic impressions over trailing 3 months**; min payout ~$30 via Stripe. Translation: **months** of consistent posting before the first rupee. A milestone, not a starting line.
- **Instagram** monetization in India is patchy/invite-only. Realistic role: **audience aggregation → funnel to newsletter / X.** Distribution and credibility, not direct payout, in year one.
- **The dependable earlier money is the newsletter.** X is top-of-funnel; the newsletter is the business. A free newsletter (beehiiv recommended — verify India payment support) grown from both platforms, plus **non-securities** affiliate and eventually sponsorships. Finance audiences price higher per subscriber than general-tech audiences.
- **Runway, internalized:** the competitor benchmark took **~4.5 years to reach ~35K followers.** Plan accordingly. The pipeline removes the labor excuse; the edge is editorial taste and consistency.

**Funnel built early, not bolted on.** Every published post carries a UTM-tagged bio/profile path (P2.5). The bio link points at the newsletter. The pinned post is managed inventory, rotated monthly to your best-converting funnel post.

---

## 4. The Voice Pack (versioned in DB)

One master system prompt injected into every drafting call, plus banned lists and few-shot examples. Seeded in **P2**, tunable forever (each save = a new version).

- **Role:** sharp, analytical commentator on US/Indian markets, personal finance, MF/ETF structures, investing styles, basic tax. Explains *what happened and why it's interesting* — never what the reader should do.
- **Tone:** informative, well-researched, easy to digest, attention-grabbing openers. Dry humor and sarcasm as seasoning, not the dish. Never hype, never cocky-finfluencer cadence.
- **Format:** bite-size to mid-length, clean text. **Emojis: default zero on X; at most one on IG, only when it does real work.**
- **Structure:** threads open with a hook and close with a genuine open-ended question. Add a second bookmark-optimized closer variant; A/B them via archetype metrics.
- **Hard bans:** everything in §2.1, plus AI-tells — "delve", "in today's fast-paced world", "let's unpack", "game-changer", exclamation enthusiasm, em-dash pileups, listicle-voice unless the format demands it. Vary sentence rhythm.
- **Few-shot examples:** 8–10 posts *you write/heavily edit by hand* in week one become permanent style anchors. **The single highest-leverage hour you'll spend.** The weekly hand-written post keeps the voice honest.

---

## 5. Content Archetypes (structural compliance + editorial variety)

A `content_archetype` enum stamped on every draft. Each archetype carries its own compliance rubric. **New archetypes require owner approval before use.** Column exists from P1 (full-schema-now, §7); classification at scoring/drafting in P2.

**Starter set (all instrument-free by construction):**
`explainer` · `metric_teardown` · `filing_walkthrough` · `macro_calendar` · `concept_comparison` · `regulatory_update` · `historical_parallel` · `mistake_anatomy` · `glossary_card` · `data_curiosity`

**Evergreen bank (P6):** concept explainers don't expire. Maintain an `evergreen_bank` to fill thin-news days and recycle on 6–9 month rotation.

---

## 6. Canonical Phase Map (THE reconciliation)

| Phase | Deliverable | Notes |
|---|---|---|
| **P0** | Accounts & keys (you, ~half a day) | X Premium + dev app (OAuth2 write); IG Creator + Meta app + `instagram_content_publish`; Supabase; Anthropic/Google/Moonshot keys; Railway + Vercel. **Done when:** one test tweet + one test IG image post via curl succeed. |
| **P1** | **Spine + Reader** | Ingest (RSS/EDGAR/NSE) → dedup → embed → cluster → `stories`. No scoring/drafting/gate/GUI/publisher. **Fully specified in Part II. Build this first.** |
| **P2** | **Brain + Gate** | LLM router; Haiku scoring (writes `score`/`angle`/`vertical`/`content_archetype`); archetype-aware drafting (two model-variants each); L1+L2 compliance gate; Voice Pack v1. |
| **P2.5** | **Newsletter + Funnel** | `newsletter_issue` drafting output; beehiiv integration; UTM funnel tracking; bio + pinned-post setup. |
| **P3** | **Cockpit (GUI)** | Next.js dashboard: Inbox, Drafts queue, Replies, Calendar, Voice tuner, Analytics + Funnel, Settings. Approves into a **dry-run log**. Mobile-first. |
| **P4** | **Publishers** | X API v2 (posts + threads, jittered, retries, needs-attention tray); IG carousel renderer + Graph publisher; kill switch. Flip dry-run to real. |
| **P5** | **Reply engine** | Metered mention polling (hard read budget); classification + drafted replies through the same gate; deflection templates; Replies queue live. |
| **P6** | **Analytics, feedback & hardening** | Metrics ingestion; engagement-weighted scoring; sponsorship disclosure gate + allowlist; evergreen bank; retry/backoff; Telegram alerts; cost report; DB backups. |

---

## 7. Unified Data Model (Supabase Postgres)

Full schema laid down in P1's `001_init.sql`. P1 populates only reader tables; later phases add rows/columns, not new tables.

```
-- Reader (P1-populated) -------------------------------------------------
sources        id, kind[rss|edgar|nse|calendar|internal], url, name,
               market[US|IN], active, poll_minutes
items          id, source_id, title, url, published_at, full_text,
               hash (unique), embedding vector(384), warnings jsonb
stories        id, headline, vertical, score, angle,
               content_archetype,               -- P1 col, P2-populated
               status[inbox|drafting|snoozed|killed|scored], created_at
story_items    story_id, item_id  (composite PK)

-- Brain / publish (later-phase-populated) ------------------------------
drafts         id, story_id, platform[x|ig|newsletter],
               format[post|thread|carousel|caption|newsletter_issue],
               content_archetype, body jsonb, model, prompt_version,
               compliance_status[pass|flag|block], compliance_report jsonb,
               is_sponsored bool, sponsorship jsonb, disclosure_token,
               status[pending|approved|edited|rejected|scheduled|published|failed],
               scheduled_for, published_ids jsonb, editor_notes,
               series text
mentions       id, platform, external_id, author, text, classified_as, fetched_at
replies        id, mention_id, draft_body, status, published_at, external_id
prompts        id, name, version, body, active
voice_profile  id, version, system_prompt, banned_phrases jsonb,
               example_posts jsonb, notes
metrics        id, draft_id, platform, impressions, likes, replies,
               reposts, saves, profile_clicks, captured_at

-- Funnel & newsletter (P2.5) -------------------------------------------
newsletter_issues id, week_of, subject_lines jsonb, sections jsonb,
                  source_draft_ids jsonb, status, compliance_status,
                  sent_at, provider_id
funnel_events     id, source_platform, post_id, utm_campaign,
                  click_at, converted bool

-- Infra ---------------------------------------------------------------
config         key, value jsonb
audit_log      id, actor, action, entity, entity_type, before, after, at
evergreen_bank id, draft_id, archetype, last_used_at, rotation_months  -- P6
```

`sources.kind` includes `calendar`. Regulatory feeds already RSS (SEBI/RBI/SEC press) ship as ordinary `rss` rows in P1. The structured `calendar` fetcher is a P2 forward item.

---

## 8. Tech Stack & Model Routing

| Layer | Choice | Why |
|---|---|---|
| DB / auth / storage / cron | **Supabase (Postgres + pgvector)** | Same spine as your other apps; RLS for free |
| Worker | **Python 3.12 + FastAPI + APScheduler on Railway (single replica, ~$5/mo)** | You know Python; one deployable, no queue infra yet |
| GUI | **Next.js / React + Tailwind on Vercel** | Same as capitals.lamka.net; mobile-first |
| Embeddings | **gte-small (384-dim) via Supabase edge function** | $0, in-DB, no new API surface |
| Image render (IG) | **HTML template → Playwright screenshot** | Branded slides |
| LLMs | **Haiku, Gemini Flash, Kimi** | Per spec |
| Publishing | **X API v2, IG Graph API** | Official routes only |
| Secrets | env vars + Supabase Vault | Never in repo |

**X API cost note (verify in Developer Console):** pay-per-use — ~$0.015/post, **~$0.20 if URL in post**, ~$0.005/read (2M/mo cap). Enforced: **no links in post bodies**; **meter mention-reads to a hard daily budget**. At 3–5 posts/day: a few dollars/month.

**Model routing (config-driven):**

| Task | Primary | Fallback |
|---|---|---|
| Story scoring / classification / archetype | Haiku | Gemini Flash |
| Article summarization | Gemini Flash | Kimi |
| Drafting variant A | Gemini Flash | — |
| Drafting variant B | Kimi | Haiku |
| Compliance judge (L2) | **whichever model did NOT draft** | — |
| Reply classify + draft | Haiku | — |
| Newsletter issue synthesis | Kimi | Gemini Flash |

Kimi's rows point to Gemini Flash until a working Moonshot key is confirmed. LLM spend full cadence: ~$5–15/mo. All-in pre-revenue: **~$35–50/mo.**

---

## 9. Operating Cadence (<30 min/day)

- **Morning (10 min):** queue review, schedule the day (India open).
- **Midday (5 min):** reply-inbox sweep.
- **Evening (10 min):** second queue pass for US hours; reply sweep.
- **Weekly (30 min):** analytics + funnel review, voice-pack tweak, feed pruning, **one hand-written post**.

---

## 10. Handoff prompts (paste into Claude Code, one phase at a time)

**P1 (build now):**
> Build Phase 1 of the fin-content-engine exactly per Part II. Do not re-architect its decisions; implement them. Stack: Python/FastAPI + APScheduler worker (single replica, Railway), Supabase Postgres + pgvector, gte-small embeddings via a Supabase edge function. Lay down the full unified schema from Part I §7 in `001_init.sql`; populate only the reader tables in P1. Implement sources (RSS + EDGAR + NSE-or-disabled), dedup, embedding (inline in ingest — see §3.6), separate clustering job, `/health` + `/stats`, and the full test suite. Ship must pass the P1 acceptance gate in Part II §5 (automated tests green + the 24h soak with its two hardenings). Verify current X API and SEBI specifics at build; encode findings into config, not code.

**P2 (after P1 green):**
> Build Phase 2 per Part I §2, §4, §5, §8. Add the LLM router; Haiku scoring writing `score`/`angle`/`vertical`/`content_archetype`; archetype-aware drafting (two model-variants each); L1 regex gate (short-circuits L2) + L2 cross-model judge; seed `voice_profile` v1 from §4 with empty few-shot slots for the owner. Acceptance: "buy this stock now" bait reliably BLOCKs; 10 stories yield archetype-stamped drafts.

Subsequent phases: hand §6's row plus the referenced Part I sections.

---
---

# PART II — PHASE 1 ENGINEERING SPEC (build this first)

*Fable's design, preserved. Four clarifications from design review folded in and marked ⟢.*

## 1. Scope & acceptance

Phase 1 builds the ingest pipeline: sources (RSS, SEC EDGAR, NSE) → dedup → embedding → clustering → the `stories` table. **No** GUI, scoring, drafting, compliance gate, or publishers. The full schema (Part I §7) is laid down now so later phases add columns, not tables.

### 1.1 Acceptance (made testable)
1. **Exact dedup = 0.** `ON CONFLICT (hash) DO NOTHING` on a SHA-256 over canonicalized title+url. Verified by running ingest twice and asserting zero new inserts on the second run.
2. **Near-dupe clustering.** Verified by precision/recall over a hand-labeled fixture (§5), **tuned to favor under-merging**. Acceptance is an **absolute false-merge ceiling** (§5.3), not a rate target.

### 1.2 Embeddings: gte-small (384-dim) via Supabase edge function
Swap target if the fixture disappoints: Google `text-embedding-004`. **Provenance is load-bearing:** the fixture's frozen embeddings must be produced by the same model *and the same input construction* the worker uses (⟢ §5.1). Column: `embedding vector(384) NULL` on `items`.

### 1.3 Locked decisions
GUI Next.js (provisional, P3). Dry-run publisher (P4). Router config-driven. LE `active=false` in P1. `audit_log` carries `entity_type`. Gate rules are P2 (Part I §2.1).

## 2. Data model & RLS

### 2.1 Full schema now
`001_init.sql` creates every table from Part I §7. P1 populates `sources`, `items`, `stories`, `story_items`, `config`, `audit_log` (ingest events only).

### 2.2 P1 table notes
`items`: `embedding vector(384) NULL`, unique index on `hash`, `full_text` nullable. `stories`: `score`/`angle`/`vertical`/`content_archetype` NULL in P1. `story_items`: composite PK `(story_id, item_id)`. `audit_log`: `entity_type` present.

### 2.3 RLS: placeholder-uid, written now
Worker uses service-role key (bypasses RLS). RLS written now so P3 needs no migration. Hardcoded placeholder (not config-table read) to avoid chicken-and-egg. A `004_set_owner.sql` stub holds the one-time `ALTER POLICY` swap.

### 2.4 Indexes
```sql
CREATE UNIQUE INDEX items_hash_uidx ON items(hash);
CREATE INDEX items_source_published_idx ON items(source_id, published_at DESC);
CREATE INDEX items_embedding_hnsw_idx ON items
  USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX story_items_item_idx ON story_items(item_id);
CREATE INDEX story_items_story_idx ON story_items(story_id);
CREATE INDEX stories_status_created_idx ON stories(status, created_at DESC);
```

### 2.5 Config seed
```json
{"key":"clustering","value":{"similarity_threshold":0.78,"embedding_model":"gte-small",
  "embedding_dim":384,"min_items_for_story":1,"max_story_age_hours":48,
  "title_weight_repeat":2,"keyword_fallback_min_tokens":2,"body_truncate_chars":500}}
{"key":"ingest","value":{"rss_poll_minutes":30,"edgar_poll_minutes":60,"nse_poll_minutes":30,
  "market_hours_only":false,"max_items_per_cycle":50,"max_full_text_fetch_seconds":10,
  "embedding_timeout_seconds":5,"embedding_degraded_threshold":0.20,"embedding_max_retries":3}}
{"key":"edgar","value":{"form_types":["8-K","13F-HR"],"company_watch":[]}}
{"key":"owner_uid","value":{"uid":null}}
```
Two-tier config: secrets + structural in env (`FCE_` prefix); tuning values in `config` table, read at job-fire time.

### 2.6 audit_log shape
`audit_log(actor, action, entity, entity_type, before, after, at)`. P1 events: `ingest_run`, `ingest_error`, `ingest_unhealthy`, `cluster_new_story`, `cluster_merge`, `cluster_embedding_missing`, `advisory_lock_skip`, `embedding_degraded`, ⟢ `embed_retry_success`, `worker_start`, `worker_stop`.

## 3. Sources & ingestion

### 3.1 Source abstraction
One protocol, three implementations. `fetch → normalize → upsert (ON CONFLICT hash DO NOTHING) → embed inline` (⟢ §3.6). `RawItem` pre-cleaning; `NormalizedItem` guarantees cleaned title, canonicalized URL, tz-aware UTC `published_at`, nullable `full_text`, SHA-256 `hash`, `warnings[]`.

### 3.2 Poll cycle
One APScheduler job **per source kind** (not per source): iterate active sources of that kind; a bad source logs + continues. Sequential within a kind.

### 3.3 RSS module — failure modes handled
| Failure | Detection | Handling |
|---|---|---|
| Partial `full_text` | `len < 500` after parse | httpx + readability-lxml, time-boxed 10s; on fail → `full_text=NULL` + warning, continue |
| Encoding gremlins | charset-normalizer on raw bytes | decode + `html.unescape()`; log `encoding_corrected` |
| HTML error page w/ HTTP 200 | content-type sniff + root-element check | `SourceError('not_a_feed')`; skip this cycle |
| Missing/unparseable date | feedparser gives no struct_time | `published_at = fetched_at` + warning; never block insertion |
| URL tracker drift | strip `utm_*`, `ref`, `fbclid`, `gclid`, … | hash on canonicalized URL → exact-dupe guarantee holds |
| HTTP 429/5xx | status | respect `Retry-After`; else backoff `[1,2,4,8]s`; 3 fails → `active=false` + `ingest_unhealthy` |
| Cold-start backlog | count > 50 | newest-first, truncate at cap |

### 3.4 SEC EDGAR module
Current-filings Atom feed (`browse-edgar?action=getcurrent&type=8-K&output=atom`) + a `13F-HR` feed. **Mandatory human-readable User-Agent** from config. **Rate limit 10 req/s, no concurrency** — `asyncio.Semaphore(1)` + 0.1s sleep. Canonical ID = accession number; hash on `accession + form_type`. `full_text` = filing index URL + warning `edgar_index_url_only`. Filter to `config.edgar.form_types`; `company_watch` empty = broad capture.

### 3.5 NSE module — scope-cut
No official API. Scraping rejected. Per-symbol CSV deferred. **P1 ships the third-party/mirror RSS route**; **if no reliable NSE RSS exists at build time, NSE ships `active=false`**, revisited in P2. **P1 will not scrape NSE.** ⟢ The §5.1 fixture is built from RSS+EDGAR items you'll actually have — never from NSE.

### 3.6 Embedding step ⟢ (trigger pinned)
**Embedding is synchronous, inline at the end of each source's ingest** — `fetch → normalize → upsert → embed_new_items(source_id)`. Not a queue, not a separate registry job. Only newly-inserted items embedded.

Input construction: `<title> <title> <first 500 chars of full_text or "">` — title repeated `title_weight_repeat` (2) times. `body_truncate_chars` (500) and `title_weight_repeat` are config values **and are part of the fixture provenance contract** (⟢ §5.1).

Call lives in a Supabase edge function `embed`. Failure: 5xx/timeout(>5s) → one retry w/ 2s backoff → on second failure `embedding IS NULL` + warning `embedding_failed`. If >20% of a cycle fails → `embedding_degraded` in `/stats`. Cold start (500 items × ~200ms ≈ 100s) completes within the poll; clustering (separate job) consolidates by minute 15.

### 3.7 Clustering — separate job (`cluster_new`, every 15 min)
Per unassigned item within 48h:
1. **Embedding similarity (primary).** Vector-search neighbors within `similarity_threshold` (0.78) and `max_story_age_hours` (48). Match → join closest existing story.
2. **Keyword fallback.** Extract `$TICKER` patterns, all-caps tokens (len ≥2), and Capitalized multi-word phrases as composite tokens. Require **≥2 distinct tokens** (`keyword_fallback_min_tokens`) — single "TCS" is too promiscuous. Where cheap, weight distinctive tokens above finance-generic boilerplate.
3. **No match → new story.**

**Atomic story creation:** `create_story` + `link_item_to_story` in one transaction. **Stability rule:** once clustered, the story link is **frozen**; a late embedding is stored but does not re-cluster.

### 3.8 Embedding retry sweep (every 30 min)
Retry `embedding IS NULL AND created_at > now() - 48h`, not permanently failed. Max 3 retries → `embedding_permanently_failed`. ⟢ On success, write `embed_retry_success`. Items aging out of 48h unclustered are **orphans** — surfaced by `/stats`; non-zero = upstream bug.

### 3.9 `/stats`
Per-source `last_run`/`last_status`/`items_new_24h`/`consecutive_failures`; `items.{total,with_embedding,without_embedding,orphaned}`; `stories.{total,created_24h,avg_items_per_story}`; `embedding_health`; `clustering.{precision_last_test,recall_last_test}`. `items.orphaned` is **non-negotiable zero** in steady state.

## 4. Worker, scheduling, deployment

### 4.1 Failure modes → where addressed
A crash-mid-job → §4.3. B redeploy double-fire → §4.2 + §4.6 + idempotent ingest. C health death-spiral → §4.7. D missed fire → §4.3. E starvation → §4.3. F cold-start → §2.5 caps + §4.8.

### 4.2 Process model — single replica, deliberately
Railway `replicas=1`. Container dies → restart ~5–15s → jobs re-register. Advisory locks (§4.6) ship as belt-and-suspenders.

### 4.3 APScheduler config
`AsyncIOScheduler`, `MemoryJobStore`, `AsyncIOExecutor(max_workers=4)`, `job_defaults={coalesce:True, max_instances:1, misfire_grace_time:60}`, `timezone=UTC`.

### 4.4 Job registry — invariant: all jobs `async def`
`poll_rss` (30m), `poll_edgar` (60m), `cluster_new` (15m), `embed_retry` (30m), `db_health` (5m). **Registry invariant (syntax-enforced):** every job is `async def`; `register_jobs` asserts `asyncio.iscoroutinefunction(fn)` and fails at boot **naming the offending job id**.

### 4.5 Startup / shutdown
`startup`: `register_jobs` → `scheduler.start()` → `worker_start` audit. `shutdown` (SIGTERM): `scheduler.shutdown(wait=True)`. Redeploy overlap safe because single-replica + `max_instances=1` + **idempotent ingest**.

### 4.6 Advisory locks
`pg_try_advisory_lock(crc32(job_id))` around each job body; `advisory_lock_skip` audit on contention. ⟢ Exempt `db_health`.

### 4.7 `/health`
Checks `process` + `scheduler_running` + `db_reachable` (SELECT 1) → 200/503. **Not** sources. Runs on the FastAPI event loop, separate from the scheduler executor.

### 4.8 Cold start
First boot, 10 feeds × 50 = 500 items max; serialized embedding ~100s; stories populate by minute 15.

### 4.9 Config & observability
Two-tier config (§2.5). structlog JSON to stdout; `audit_log` for durable events; `/stats` for humans. No metrics exporter in P1.

## 5. Testing & acceptance (closes Phase 1)

### 5.1 Fixture — adversarial by construction
`tests/fixtures/clustering.jsonl`: ~30 items, ~8 true stories, ~6 singletons. **Trap pairs (must NOT merge):** `tcs_q2` vs `tcs_buyback`; two "RBI rate decision" stories from different months; an evergreen "what is an IPO" next to a specific IPO story. **Corroboration pairs (must merge):** same story across outlets with paraphrased headlines. **Ticker-vs-name variants.** Singletons apply false-positive pressure.
⟢ **Provenance (load-bearing):** embeddings pre-computed once with gte-small and frozen. A test-load assertion checks `fixtures/_model.json` — `{model, dim, title_weight_repeat, body_truncate_chars}` — against the worker's configured values; **any change to model *or embedding-input construction* fails loud** with "regenerate fixture," never silently. Procedure in `tests/fixtures/REGENERATE.md`.

### 5.2 Metric — pair-counting
Over all C(N,2) pairs: TP, FP (lost story), FN (safe), TN. Precision = TP/(TP+FP); Recall = TP/(TP+FN).

### 5.3 Pass threshold — under-merge bias, concrete
| Criterion | Value |
|---|---|
| **FP pair ceiling** | **≤ 2** (load-bearing, absolute) |
| Precision floor | ≥ 0.85 |
| Recall floor | ≥ 0.50 |
⟢ **The FP ceiling is N-coupled.** Express intent as "≤ ~5% of true-different pairs wrongly merged, floored at an absolute 2 for small-N," and re-derive when the fixture grows (documented in `TUNING.md`).

### 5.4 Runner
Dependency-injected clusterer: `clusterer.run(items)` takes frozen embeddings, returns assignments, calls neither DB nor edge function → deterministic, <1s, CI-runnable. Asserts provenance, then `fp <= 2`, `precision >= 0.85`, `recall >= 0.50`. ⟢ **Engine caveat:** runner scores exact cosine; production uses HNSW. At P1 scale HNSW ≈ exact (benign) — `TUNING.md` states the assumption is re-checked if corpus grows past tens of thousands.

### 5.5 Cold-start smoke test
**Layer 1 (CI):** respx-mocked feed cassettes → `ingest.run_all_sources()` → assert `items>0`, `stories>0`, `embedding IS NULL == 0`, `orphaned == 0`; run again → assert zero new items/stories (idempotency); `/stats` reflects it. Test DB = local Postgres + pgvector in Docker; embed edge function mocked to return a **deterministic vector per input**.
**Layer 2 (`make smoke`, local, once before deploy):** one cycle against live feeds → confirms cassettes still match reality.

### 5.6 Unit coverage
`sources.rss` (canonicalization, HTML strip, encoding, date fallback); `sources.edgar` (accession extraction, form filter, UA presence); `ingest` (hash stability, cap truncation); `cluster` (≥2-token rule — single "TCS" does NOT merge; title-weighting construction); `db` (`create_or_join_story` transaction rollback).

### 5.7 Acceptance gate
**Automated (green before merge):** all unit tests; `test_clustering_meets_acceptance` (FP≤2, P≥0.85, R≥0.50); `test_cold_start_idempotent` (zero re-inserts, zero orphans, all embedded).
**Manual (once, before declaring P1 done):**
1. Deploy to Railway (single replica, env set).
2. `/health` → 200 within 60s.
3. Run **24h** against real feeds, two hardenings: ⟢ (a) spans at least one **closed-market stretch**; ⟢ (b) **force the retry path** — bad `embedding_edge_function_url`, confirm items land `embedding IS NULL` + keyword-cluster, restore, confirm backfill within 30 min + `embed_retry_success`.
4. `/stats`: every active source `last_status=ok`, `consecutive_failures=0`; `embedding_health=ok`; `items.orphaned=0` (**non-negotiable**). ⟢ **Also confirm no source auto-disabled** — grep `audit_log` for `ingest_unhealthy`. (NSE/LE `active=false` is acceptable.)
5. Spot-check 5 stories in Supabase studio: sensible clusters, no over-merges.
6. `POST /ingest/trigger?source_id=…` → zero new items.
7. `audit_log` shows `worker_start`, `ingest_run`, `cluster_new_story`, and a retry event.

**Phase 1 is done when steps 4–7 pass.**

### 5.8 Scope fence
No scoring/drafting/gate (P2), no GUI (P3), no publishers (P4). NSE may ship disabled; LE ships `active=false`. Embedding stays gte-small unless the fixture proves it inadequate.

## Appendix — Phase 1 Decision Log
1 P1 = Spine+Reader only · 2 GUI Next.js (provisional, P3) · 3 dry-run publisher (P4) · 4 router config-driven · 5 LE `active=false` in P1 · 6 `entity_type` on audit_log · 7 gte-small 384-dim in-DB · 8 RLS placeholder-uid · 9 `min_items_for_story=1` · 10 NSE via RSS, disabled if unavailable · 11 title-weighted embeddings (×2 + 500 chars) · 12 keyword fallback ≥2 tokens · 13 clustering separate from ingest · 14 re-embed via sweep, max 3 · 15 cluster link frozen · 16 atomic story creation · 17 `/stats` orphan counter · 18 single replica + advisory locks · 19 `coalesce`+`misfire_grace_time=60` · 20 `/health` = process+scheduler+DB only · 21 two-tier config · 22 all jobs `async def`, asserted at registration · 23 FP ceiling ≤2 load-bearing, N-coupled · 24 frozen fixture + provenance assertion (⟢ includes input-construction) · 25 24h soak with closed-market stretch + forced retry path · ⟢26 embedding inline in ingest · ⟢27 `db_health` exempt from advisory lock · ⟢28 `embed_retry_success` audit event · ⟢29 auto-disabled-source check in soak · ⟢30 HNSW≈exact caveat documented in TUNING.md
