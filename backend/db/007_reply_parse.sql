-- Phase 4b: store each inbound reply parse for event_log explainability
-- ("why did you propose that time?"). No change to slot/booking/offer.
-- candidate.status reuses existing values plus 'needs_attention' (low-conf).

CREATE TABLE IF NOT EXISTS reply_parse (
    id           BIGSERIAL PRIMARY KEY,
    candidate_id BIGINT NOT NULL REFERENCES candidate(id) ON DELETE CASCADE,
    thread_id    TEXT,
    raw_text     TEXT,
    windows      JSONB,
    confidence   REAL,
    note         TEXT,
    outcome      TEXT,          -- 'confirmed' | 'escalated' | 'edited'
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);