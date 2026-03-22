-- Migration 004: Supabase Auth integration — user profiles and property access
-- Apply via Supabase Dashboard SQL Editor or CLI before first deploy.
-- Depends on 001_schema.sql (uses set_updated_at function and property table).
-- Idempotent — safe to re-run.

BEGIN;

-- ─── users ───────────────────────────────────────────────────────────────────
-- user_id matches auth.users.id from Supabase Auth (UUID, not BIGINT).
-- No FK to auth.users — that schema is inaccessible via Transaction Pooler.

CREATE TABLE IF NOT EXISTS public.users (
    user_id    UUID        PRIMARY KEY,
    email      TEXT        NOT NULL UNIQUE,
    username   TEXT        NOT NULL UNIQUE,
    is_admin   BOOLEAN     NOT NULL DEFAULT false,
    is_active  BOOLEAN     NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT users_email_not_blank    CHECK (BTRIM(email) <> ''),
    CONSTRAINT users_username_not_blank CHECK (BTRIM(username) <> '')
);

DROP TRIGGER IF EXISTS users_set_updated_at ON public.users;
CREATE TRIGGER users_set_updated_at
    BEFORE UPDATE ON public.users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ─── user_properties ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.user_properties (
    user_id     UUID   NOT NULL REFERENCES public.users(user_id) ON DELETE CASCADE,
    property_id BIGINT NOT NULL REFERENCES public.property(property_id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, property_id)
);

COMMIT;
