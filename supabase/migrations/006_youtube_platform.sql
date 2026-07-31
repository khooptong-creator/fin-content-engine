-- Migration 006: Add YouTube platform and formats for video generation

-- 1. Drop existing check constraints dynamically because they were created anonymously
DO $$
DECLARE
    r record;
BEGIN
    FOR r IN (
        SELECT conname 
        FROM pg_constraint 
        WHERE conrelid = 'drafts'::regclass AND contype = 'c'
    ) LOOP
        -- Simple check to see if the constraint enforces platform or format
        IF r.conname LIKE '%platform%' OR r.conname LIKE '%format%' THEN
            EXECUTE 'ALTER TABLE drafts DROP CONSTRAINT ' || quote_ident(r.conname);
        END IF;
    END LOOP;
END $$;

-- 2. Add the new constraints including 'youtube' and 'video'
ALTER TABLE drafts ADD CONSTRAINT drafts_platform_check 
    CHECK (platform IN ('x', 'ig', 'newsletter', 'youtube'));

ALTER TABLE drafts ADD CONSTRAINT drafts_format_check 
    CHECK (format IN ('post', 'thread', 'carousel', 'caption', 'newsletter_issue', 'video'));

-- 3. Add new columns for the YouTube pipeline
ALTER TABLE drafts ADD COLUMN IF NOT EXISTS channel_id text;
ALTER TABLE drafts ADD COLUMN IF NOT EXISTS upload_preference text DEFAULT 'manual' CHECK (upload_preference IN ('manual', 'auto'));
