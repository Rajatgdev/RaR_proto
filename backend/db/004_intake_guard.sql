-- Phase 2 fix: Gate 1 must refuse to confirm while the last candidate intake
-- still has unresolved faulty rows. Persist that count on the job so confirm
-- can enforce it server-side (not just in the UI).

ALTER TABLE job ADD COLUMN IF NOT EXISTS excluded_count INT NOT NULL DEFAULT 0;