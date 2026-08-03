-- Progress for long-running generation runs, so the GUI can show a stage
-- rather than a spinner.
--
-- Rows are kept rather than deleted on completion: a failed run's stage and
-- error message are the first thing anyone asks for, and they are the only
-- record of *where* a pipeline that logs to stdout gave up.

CREATE TABLE IF NOT EXISTS jobs (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind        text NOT NULL,
    story_id    uuid REFERENCES stories(id) ON DELETE CASCADE,
    stage       text NOT NULL DEFAULT 'queued',
    done        int  NOT NULL DEFAULT 0,
    total       int  NOT NULL DEFAULT 0,
    error       text,
    draft_id    uuid,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS jobs_created_idx ON jobs (created_at DESC);
