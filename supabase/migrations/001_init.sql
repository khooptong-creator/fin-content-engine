-- Fin-Content Engine — full unified schema (Part I §7).
-- Laid down in P1 so later phases add columns, not tables. P1 populates only:
--   sources, items, stories, story_items, config, audit_log (ingest events only).
-- Idempotent: safe to re-run.

CREATE EXTENSION IF NOT EXISTS vector;       -- pgvector
CREATE EXTENSION IF NOT EXISTS pgcrypto;     -- gen_random_uuid()

-- =========================================================================
-- Reader (P1-populated)
-- =========================================================================

CREATE TABLE IF NOT EXISTS sources (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind           text NOT NULL CHECK (kind IN ('rss','edgar','nse','calendar','internal')),
    url            text NOT NULL,
    name           text NOT NULL,
    market         text NOT NULL DEFAULT 'IN' CHECK (market IN ('US','IN')),
    active         boolean NOT NULL DEFAULT true,
    poll_minutes   integer NOT NULL DEFAULT 30,
    -- bookkeeping for failure handling (§3.3: 3 fails → auto-disable)
    consecutive_failures integer NOT NULL DEFAULT 0,
    last_run_at    timestamptz,
    last_status    text,    -- 'ok' | 'error' | 'not_a_feed' | null
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS items (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id      uuid NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    title          text NOT NULL,
    url            text NOT NULL,
    published_at   timestamptz NOT NULL,            -- tz-aware UTC
    full_text      text,                            -- nullable: extraction may fail
    hash           text NOT NULL,
    embedding      vector(384),                     -- pgvector; NULL until embedded
    warnings       jsonb NOT NULL DEFAULT '[]'::jsonb,
    retry_count    integer NOT NULL DEFAULT 0,
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS stories (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    headline        text NOT NULL,
    vertical        text,                           -- P2-populated
    score           double precision,               -- P2-populated
    angle           text,                           -- P2-populated
    content_archetype text,                         -- P2-populated (Part I §5)
    status          text NOT NULL DEFAULT 'inbox'
                    CHECK (status IN ('inbox','drafting','snoozed','killed','scored')),
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS story_items (
    story_id    uuid NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
    item_id     uuid NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    PRIMARY KEY (story_id, item_id)
);

-- =========================================================================
-- Brain / publish (later-phase-populated; created now, empty)
-- =========================================================================

CREATE TABLE IF NOT EXISTS drafts (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    story_id            uuid REFERENCES stories(id) ON DELETE SET NULL,
    platform            text CHECK (platform IN ('x','ig','newsletter')),
    format              text CHECK (format IN ('post','thread','carousel','caption','newsletter_issue')),
    content_archetype   text,
    body                jsonb NOT NULL DEFAULT '{}'::jsonb,
    model               text,
    prompt_version      text,
    compliance_status   text CHECK (compliance_status IN ('pass','flag','block')),
    compliance_report   jsonb,
    is_sponsored        boolean NOT NULL DEFAULT false,
    sponsorship         jsonb,
    disclosure_token    text,
    status              text NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending','approved','edited','rejected','scheduled','published','failed')),
    scheduled_for       timestamptz,
    published_ids       jsonb,
    editor_notes        text,
    series              text,
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mentions (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    platform        text NOT NULL,
    external_id     text NOT NULL,
    author          text,
    text            text NOT NULL,
    classified_as   text,
    fetched_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS replies (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    mention_id    uuid NOT NULL REFERENCES mentions(id) ON DELETE CASCADE,
    draft_body    text,
    status        text NOT NULL DEFAULT 'pending',
    published_at  timestamptz,
    external_id   text
);

CREATE TABLE IF NOT EXISTS prompts (
    id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name    text NOT NULL,
    version integer NOT NULL,
    body    text NOT NULL,
    active  boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (name, version)
);

CREATE TABLE IF NOT EXISTS voice_profile (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    version       integer NOT NULL,
    system_prompt text NOT NULL,
    banned_phrases jsonb NOT NULL DEFAULT '[]'::jsonb,
    example_posts jsonb NOT NULL DEFAULT '[]'::jsonb,
    notes         text,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS metrics (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    draft_id          uuid REFERENCES drafts(id) ON DELETE CASCADE,
    platform          text NOT NULL,
    impressions       bigint NOT NULL DEFAULT 0,
    likes             bigint NOT NULL DEFAULT 0,
    replies           bigint NOT NULL DEFAULT 0,
    reposts           bigint NOT NULL DEFAULT 0,
    saves             bigint NOT NULL DEFAULT 0,
    profile_clicks    bigint NOT NULL DEFAULT 0,
    captured_at       timestamptz NOT NULL DEFAULT now()
);

-- =========================================================================
-- Funnel & newsletter (P2.5)
-- =========================================================================

CREATE TABLE IF NOT EXISTS newsletter_issues (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    week_of             date NOT NULL,
    subject_lines       jsonb NOT NULL DEFAULT '[]'::jsonb,
    sections            jsonb NOT NULL DEFAULT '[]'::jsonb,
    source_draft_ids    jsonb NOT NULL DEFAULT '[]'::jsonb,
    status              text NOT NULL DEFAULT 'pending',
    compliance_status   text,
    sent_at             timestamptz,
    provider_id         text,
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS funnel_events (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_platform   text NOT NULL,
    post_id           text,
    utm_campaign      text,
    click_at          timestamptz NOT NULL DEFAULT now(),
    converted         boolean NOT NULL DEFAULT false
);

-- =========================================================================
-- Infra
-- =========================================================================

CREATE TABLE IF NOT EXISTS config (
    key    text PRIMARY KEY,
    value  jsonb NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          bigserial PRIMARY KEY,
    actor       text NOT NULL,
    action      text NOT NULL,
    entity      text,        -- id as text (may be null for system-wide events)
    entity_type text NOT NULL,
    before      jsonb,
    after       jsonb,
    at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS evergreen_bank (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    draft_id        uuid REFERENCES drafts(id) ON DELETE CASCADE,
    archetype       text NOT NULL,
    last_used_at    timestamptz,
    rotation_months integer NOT NULL DEFAULT 6
);

-- =========================================================================
-- Privileges
-- =========================================================================
-- Migrations run as the `postgres` superuser, so every table above is owned
-- by `postgres`. The worker connects as the `fce` role (per FCE_DATABASE_URL),
-- which "owns" the database but has NO privileges on tables inside it by
-- default — Postgres separates database ownership from table privileges.
-- Without these GRANTs the worker fails at startup with
-- `permission denied for table config`. Caught on first prod deploy.

-- Grant fce full privileges on every existing table + sequence.
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO fce;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO fce;

-- Default privileges: any table created by postgres via FUTURE migrations is
-- auto-granted to fce. Prevents the same bug from recurring on the next
-- migration (P2+, when new tables or columns get added).
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO fce;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO fce;
