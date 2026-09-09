-- Phase 5: single follow-up + cron sweep support.
ALTER TABLE job ADD COLUMN IF NOT EXISTS followup_after_min INT NOT NULL DEFAULT 2;
ALTER TABLE candidate ADD COLUMN IF NOT EXISTS followup_sent_at TIMESTAMPTZ;