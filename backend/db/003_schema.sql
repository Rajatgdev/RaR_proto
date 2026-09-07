-- Phase 2: the locked prototype schema. Small and flat on purpose.
-- Drops the Phase 0 ping scaffold now that real tables exist.
-- google_account (Phase 1) is left untouched.

DROP TABLE IF EXISTS ping;

CREATE TABLE IF NOT EXISTS session (
    id                BIGSERIAL PRIMARY KEY,
    parent_session_id BIGINT REFERENCES session(id),  -- null in Mode B; present for later Mode A
    actor             TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS job (
    id          BIGSERIAL PRIMARY KEY,
    session_id  BIGINT NOT NULL REFERENCES session(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    description TEXT,
    timezone    TEXT NOT NULL DEFAULT 'Europe/London',
    params      JSONB,          -- the approved parameter card
    status      TEXT NOT NULL DEFAULT 'draft',  -- draft | confirmed
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS candidate (
    id        BIGSERIAL PRIMARY KEY,
    job_id    BIGINT NOT NULL REFERENCES job(id) ON DELETE CASCADE,
    name      TEXT,
    email     TEXT,
    phone     TEXT,
    timezone  TEXT,
    status    TEXT NOT NULL DEFAULT 'not_contacted',
    UNIQUE (job_id, email)  -- dedupe on email within a job
);

CREATE TABLE IF NOT EXISTS interviewer (
    id            BIGSERIAL PRIMARY KEY,
    job_id        BIGINT NOT NULL REFERENCES job(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL,
    calendar_id   TEXT NOT NULL,
    working_hours JSONB           -- {"start":"09:00","end":"17:00"} override; null = job default
);

CREATE TABLE IF NOT EXISTS slot (
    id              BIGSERIAL PRIMARY KEY,
    job_id          BIGINT NOT NULL REFERENCES job(id) ON DELETE CASCADE,
    interviewer_id  BIGINT NOT NULL REFERENCES interviewer(id) ON DELETE CASCADE,
    start_ts        TIMESTAMPTZ NOT NULL,
    end_ts          TIMESTAMPTZ NOT NULL,
    status          TEXT NOT NULL DEFAULT 'available',  -- available | held | booked
    hold_id         UUID,
    hold_owner      BIGINT REFERENCES candidate(id),
    hold_expires_at TIMESTAMPTZ,
    version         INT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_slot_status_expiry ON slot (status, hold_expires_at);

CREATE TABLE IF NOT EXISTS offer (
    id           BIGSERIAL PRIMARY KEY,
    candidate_id BIGINT NOT NULL REFERENCES candidate(id) ON DELETE CASCADE,
    slot_id      BIGINT NOT NULL REFERENCES slot(id) ON DELETE CASCADE,
    offered_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS booking (
    id           BIGSERIAL PRIMARY KEY,
    candidate_id BIGINT NOT NULL REFERENCES candidate(id) ON DELETE CASCADE,
    slot_id      BIGINT NOT NULL UNIQUE REFERENCES slot(id),  -- double-booking backstop
    gcal_event_id TEXT,
    meet_link    TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS outreach (
    id              BIGSERIAL PRIMARY KEY,
    candidate_id    BIGINT NOT NULL REFERENCES candidate(id) ON DELETE CASCADE,
    thread_id       TEXT,
    kind            TEXT NOT NULL,   -- outreach | followup
    sent_at         TIMESTAMPTZ,
    followup_due_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS event_log (
    id         BIGSERIAL PRIMARY KEY,
    session_id BIGINT REFERENCES session(id) ON DELETE CASCADE,
    ts         TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor      TEXT NOT NULL,   -- 'agent' | 'recruiter'
    action     TEXT NOT NULL,
    detail     JSONB
);