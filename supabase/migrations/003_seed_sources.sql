-- Fin-Content Engine — seed sources + config (Part II §2.5, §3.4, §3.5).
-- Idempotent: ON CONFLICT DO NOTHING so re-running is safe.

-- ====================== sources ======================
-- RSS feeds for India markets (§3.3 hardening applies to all of these).
INSERT INTO sources (kind, url, name, market, active, poll_minutes) VALUES
    ('rss', 'https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms',  'ET Markets',           'IN', true, 30),
    ('rss', 'https://www.moneycontrol.com/rss/latestnews.xml',                         'Moneycontrol',         'IN', true, 30),
    ('rss', 'https://www.livemint.com/rss/markets.xml',                                'Livemint Markets',     'IN', true, 30),
    ('rss', 'https://www.business-standard.com/rss/markets-106.rss',                   'Business Standard Markets', 'IN', true, 30),
    ('rss', 'https://www.livemint.com/rss/companies.xml',                              'Livemint Companies',   'IN', true, 30),
    ('rss', 'https://economictimes.indiatimes.com/prime/rssfeeds/81584893.cms',        'ET Prime',             'IN', true, 30)
ON CONFLICT DO NOTHING;

-- RSS feeds for US markets + regulatory (§3.3).
INSERT INTO sources (kind, url, name, market, active, poll_minutes) VALUES
    ('rss', 'https://feeds.reuters.com/reuters/businessNews',     'Reuters Business',   'US', true, 30),
    ('rss', 'https://feeds.content.dowjones.io/public/rss/SB1000', 'WSJ Markets',       'US', true, 30),
    ('rss', 'https://www.sec.gov/rss/press.xml',                  'SEC Press Releases', 'US', true, 30)
ON CONFLICT DO NOTHING;

-- SEC EDGAR structured source (§3.4). Poll hourly; the worker appends form_type query.
INSERT INTO sources (kind, url, name, market, active, poll_minutes) VALUES
    ('edgar', 'https://www.sec.gov/cgi-bin/browse-edgar', 'SEC EDGAR current filings', 'US', true, 60)
ON CONFLICT DO NOTHING;

-- NSE corporate announcements (§3.5 — scope-cut).
-- P1 ships the third-party/mirror RSS route. THIS URL IS A PLACEHOLDER — at build
-- time, either (a) replace with a working NSE-RSS mirror URL and set active=true,
-- or (b) leave active=false and revisit in P2. P1 will NOT scrape NSE.
INSERT INTO sources (kind, url, name, market, active, poll_minutes) VALUES
    ('nse', 'https://example.invalid/nse-announcements-rss', 'NSE Announcements (PLACEHOLDER — see comment)', 'IN', false, 30)
ON CONFLICT DO NOTHING;

-- LE internal source (Part I §1.3 / decision 5): registered as a row, NOT active
-- in P1. Content triggers (movers, breadth, new highs) are a P2 drafting concern.
-- The 'internal' kind exists so P2 can flip this row to active without a migration.
INSERT INTO sources (kind, url, name, market, active, poll_minutes) VALUES
    ('internal', 'supabase://lamka-equities', 'Lamka Equities (LE price tables)', 'IN', false, 60)
ON CONFLICT DO NOTHING;

-- ====================== config ======================
-- Two-tier config (§2.5): tuning values live here, secrets/structural in env.
INSERT INTO config (key, value) VALUES
    ('clustering', '{
        "similarity_threshold": 0.92,
        "embedding_model": "gte-small",
        "embedding_dim": 384,
        "min_items_for_story": 1,
        "max_story_age_hours": 48,
        "title_weight_repeat": 2,
        "body_truncate_chars": 500,
        "keyword_fallback_min_tokens": 2
    }'::jsonb),
    ('ingest', '{
        "rss_poll_minutes": 30,
        "edgar_poll_minutes": 60,
        "nse_poll_minutes": 30,
        "market_hours_only": false,
        "max_items_per_cycle": 50,
        "max_full_text_fetch_seconds": 10,
        "embedding_timeout_seconds": 5,
        "embedding_degraded_threshold": 0.20,
        "embedding_max_retries": 3
    }'::jsonb),
    ('edgar', '{
        "form_types": ["8-K", "13F-HR"],
        "company_watch": []
    }'::jsonb),
    ('owner_uid', '{"uid": null}'::jsonb)
ON CONFLICT (key) DO NOTHING;
