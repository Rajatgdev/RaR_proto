-- Conversational agent (A+B+C): persist every chat turn so the transcript
-- survives tab switches, and so the orchestrator has real history to reason over.
--
-- job_id is NULLABLE: a "New job" chat starts with no job. Pre-job turns are
-- keyed by session_key; when the agent creates the job (via the create_job tool),
-- those turns are re-parented (job_id filled in) so nothing the recruiter said
-- is lost. role: 'user' | 'agent'. card: an inline approval-card payload (gated
-- actions) rendered by the frontend; tool_calls: what the agent invoked (audit).

CREATE TABLE IF NOT EXISTS chat_turn (
    id          BIGSERIAL PRIMARY KEY,
    job_id      BIGINT REFERENCES job(id) ON DELETE CASCADE,   -- nullable pre-job
    session_key TEXT NOT NULL,                                 -- groups a chat before a job exists
    role        TEXT NOT NULL,                                 -- 'user' | 'agent'
    content     TEXT NOT NULL DEFAULT '',
    tool_calls  JSONB,
    card        JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chat_turn_job ON chat_turn (job_id, id);
CREATE INDEX IF NOT EXISTS idx_chat_turn_session ON chat_turn (session_key, id);