-- Phase 4a: Gate 2 approves the outreach template + the slot pool, once.
-- Store the approved template and a flag so send is gated on it.
-- outreach table (candidate_id, thread_id, kind, sent_at, followup_due_at)
-- already exists from migration 003.

ALTER TABLE job ADD COLUMN IF NOT EXISTS outreach_subject TEXT;
ALTER TABLE job ADD COLUMN IF NOT EXISTS outreach_body TEXT;
ALTER TABLE job ADD COLUMN IF NOT EXISTS outreach_approved BOOLEAN NOT NULL DEFAULT false;