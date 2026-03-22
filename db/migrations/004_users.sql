-- Migration 004: Users and property access control.
-- Auth is handled by Supabase Auth (GoTrue); this table stores the app-level
-- profile (username, admin flag, active flag) keyed by the Supabase Auth UUID.
-- Idempotent — safe to re-run.

BEGIN;

-- ─── users ──────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS users (
    user_id    TEXT PRIMARY KEY,
    email      TEXT NOT NULL,
    username   TEXT NOT NULL,
    is_admin   BOOLEAN NOT NULL DEFAULT FALSE,
    is_active  BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT users_email_unique UNIQUE (email),
    CONSTRAINT users_username_unique UNIQUE (username),
    CONSTRAINT users_email_not_blank CHECK (BTRIM(email) <> ''),
    CONSTRAINT users_username_not_blank CHECK (BTRIM(username) <> '')
);

DROP TRIGGER IF EXISTS users_set_updated_at ON users;
CREATE TRIGGER users_set_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ─── user_properties ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS user_properties (
    user_id     TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    property_id BIGINT NOT NULL REFERENCES property(property_id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, property_id)
);

COMMENT ON TABLE users IS
    'App-level user profile. user_id is the Supabase Auth UUID. '
    'Passwords are managed by Supabase Auth — no password_hash stored here.';

COMMENT ON TABLE user_properties IS
    'Maps users to the properties they can access. '
    'Admins (is_admin = true) bypass this and see all properties.';

COMMIT;
