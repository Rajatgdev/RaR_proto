-- Phase 0: skeleton round-trip only.
-- The locked 9-table schema (session, job, candidate, interviewer, slot,
-- offer, booking, outreach, event_log) lands in a later migration when
-- Phase 2+ code first uses it. Nothing speculative here.

CREATE TABLE IF NOT EXISTS ping (
    id   BIGSERIAL PRIMARY KEY,
    note TEXT NOT NULL,
    ts   TIMESTAMPTZ NOT NULL DEFAULT now()
);
