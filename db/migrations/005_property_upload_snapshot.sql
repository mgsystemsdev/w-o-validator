-- Per-property UI snapshots (import results, previews, optional report binaries).
-- Survives logout / new browser session. Apply manually in Supabase SQL Editor.

BEGIN;

CREATE TABLE IF NOT EXISTS property_upload_snapshot (
    property_id   BIGINT NOT NULL REFERENCES property(property_id) ON DELETE CASCADE,
    snapshot_kind TEXT NOT NULL,
    payload       JSONB NOT NULL DEFAULT '{}'::jsonb,
    blob_west     BYTEA,
    blob_east     BYTEA,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (property_id, snapshot_kind)
);

CREATE INDEX IF NOT EXISTS property_upload_snapshot_updated_at_idx
    ON property_upload_snapshot (property_id, updated_at DESC);

COMMIT;
