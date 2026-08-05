-- Stories gain a channel so a topic knows which brand it belongs to.
-- Nullable on purpose: rows already exist without one, and they are not
-- reassigned. A story with a NULL channel is simply not generatable.

ALTER TABLE stories ADD COLUMN IF NOT EXISTS channel_id TEXT;

COMMENT ON COLUMN stories.channel_id IS
  'Target channel key, matching a key in the channels config. NULL for rows created before per-channel support; those are not generatable without being assigned one.';
