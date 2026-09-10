-- Salient Replica — Database initialization
-- Milestone 1: Core tables for agent state, tool actions, and authorization artifacts

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── Tool actions (the execution evidence chain) ──────────────────────────
CREATE TABLE IF NOT EXISTS tool_actions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    action_id       TEXT NOT NULL UNIQUE,       -- idempotency key
    conversation_id TEXT NOT NULL,
    turn_id         TEXT NOT NULL,
    customer_id     TEXT NOT NULL,
    action_type     TEXT NOT NULL,              -- schedule_payment, update_phone, etc.
    status          TEXT NOT NULL DEFAULT 'PROPOSED',
                    -- PROPOSED | NORMALIZED | VALIDATED | AUTHORIZED
                    -- | EXECUTING | CONFIRMED | REJECTED | UNKNOWN
    intent          JSONB NOT NULL,             -- normalized intent payload
    authorization_ref TEXT,                     -- versioned consent artifact ID
    policy_context_version TEXT,
    provider_request_id  TEXT,                  -- stored BEFORE waiting for response
    provider_response    JSONB,                 -- authoritative provider confirmation
    error_message        TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_tool_actions_conversation ON tool_actions(conversation_id);
CREATE INDEX idx_tool_actions_customer ON tool_actions(customer_id);
CREATE INDEX idx_tool_actions_status ON tool_actions(status);

-- ── Authorization artifacts (versioned consent) ──────────────────────────
CREATE TABLE IF NOT EXISTS authorization_artifacts (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    artifact_id     TEXT NOT NULL UNIQUE,
    customer_id     TEXT NOT NULL,
    action_type     TEXT NOT NULL,
    actor           JSONB NOT NULL,             -- {customer_id, auth_level}
    bound_values    JSONB NOT NULL,             -- {amount, date, method_token, ...}
    disclosures     JSONB NOT NULL,             -- what the customer was told
    version         INTEGER NOT NULL DEFAULT 1,
    is_valid        BOOLEAN NOT NULL DEFAULT TRUE,
    invalidated_reason TEXT,                    -- why it was invalidated (e.g., "amount changed")
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    invalidated_at  TIMESTAMPTZ
);

CREATE INDEX idx_auth_artifacts_customer ON authorization_artifacts(customer_id);
CREATE INDEX idx_auth_artifacts_valid ON authorization_artifacts(is_valid) WHERE is_valid = TRUE;

-- ── Session state (conversation runtime) ─────────────────────────────────
CREATE TABLE IF NOT EXISTS sessions (
    conversation_id   TEXT PRIMARY KEY,
    customer_id       TEXT NOT NULL,
    auth_level        TEXT NOT NULL DEFAULT 'anonymous',
    locale            TEXT NOT NULL DEFAULT 'en-US',
    channel           TEXT NOT NULL,            -- sms | chat | voice
    collected_slots   JSONB NOT NULL DEFAULT '{}',
    pending_confirmation JSONB,
    state_version     INTEGER NOT NULL DEFAULT 1,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Audit log (immutable evidence) ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_events (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id TEXT NOT NULL,
    turn_id         TEXT NOT NULL,
    customer_id     TEXT NOT NULL,
    event_type      TEXT NOT NULL,              -- tool_call, policy_decision, auth_granted, etc.
    event_data      JSONB NOT NULL,
    model_version   TEXT,
    config_version  TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_conversation ON audit_events(conversation_id);
CREATE INDEX idx_audit_customer ON audit_events(customer_id);

-- ── Updated trigger for tool_actions ─────────────────────────────────────
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_tool_actions_updated
    BEFORE UPDATE ON tool_actions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_sessions_updated
    BEFORE UPDATE ON sessions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
