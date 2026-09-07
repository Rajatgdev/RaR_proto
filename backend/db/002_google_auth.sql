-- Phase 1: persist the connected Google account's OAuth credentials.
-- Prototype is single-account; we read the most-recently-updated row.
-- credentials holds google Credentials.to_json() (access + refresh token, expiry).

CREATE TABLE IF NOT EXISTS google_account (
    id          BIGSERIAL PRIMARY KEY,
    email       TEXT UNIQUE NOT NULL,
    credentials JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);