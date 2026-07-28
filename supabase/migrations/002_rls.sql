-- Fin-Content Engine — RLS policies (Part II §2.3).
--
-- Single-user design: every policy restricts to <OWNER_UID>.
-- REPLACE owner_uid below with the owner's auth.uid() after first magic-link login (P3).
-- The swap lives in 004_set_owner.sql (committed-empty stub).
--
-- RESILIENCE: this migration must not fail if the `auth` schema or
-- `authenticated` role don't exist yet. In production Supabase, both are
-- provisioned automatically before user migrations run; in the local Docker
-- test DB (vanilla Postgres + pgvector), they don't exist. We check for them
-- and skip policy creation gracefully — the worker uses the service-role key
-- (bypasses RLS), so P1/P2 (no GUI) are unaffected. When P3 lands and you
-- deploy to a real Supabase project, `auth` exists and policies get created.

DO $$
DECLARE
    owner_uid uuid := '00000000-0000-0000-0000-000000000000';
    t text;
    auth_schema_exists boolean;
    auth_role_exists boolean;
BEGIN
    SELECT EXISTS(SELECT 1 FROM information_schema.schemata WHERE schema_name = 'auth')
        INTO auth_schema_exists;
    SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname = 'authenticated')
        INTO auth_role_exists;

    IF NOT (auth_schema_exists AND auth_role_exists) THEN
        RAISE NOTICE 'Skipping RLS policies: auth schema or authenticated role not present (local dev DB). Policies will be created on real Supabase deploy.';
        RETURN;
    END IF;

    FOREACH t IN ARRAY ARRAY[
        'sources','items','stories','story_items','drafts','metrics',
        'mentions','replies','newsletter_issues','funnel_events','evergreen_bank'
    ] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY;', t);
        EXECUTE format($f$
            DROP POLICY IF EXISTS owner_only_select ON public.%I;
            CREATE POLICY owner_only_select ON public.%I
                FOR SELECT TO authenticated
                USING (auth.uid() = %L::uuid);
        $f$, t, t, owner_uid);
    END LOOP;
END $$;
