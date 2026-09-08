-- Phase 3: soft-hold TTL. Config value on the job so it's tunable per run.
-- Slot table (status/hold_id/hold_owner/hold_expires_at/version) already exists
-- from migration 003; nothing to add there.

ALTER TABLE job ADD COLUMN IF NOT EXISTS hold_ttl_min INT NOT NULL DEFAULT 30;