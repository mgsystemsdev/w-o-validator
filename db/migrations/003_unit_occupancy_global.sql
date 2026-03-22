-- Migration 003: unit_occupancy_global — move-in date per unit, property-scoped.
-- Populated via Resident Activity upload through occupancy_service.ingest().
-- Used by WO Validator to compute days_since_move_in and classify work orders.
-- Idempotent — safe to re-run.

CREATE TABLE IF NOT EXISTS unit_occupancy_global (
    property_id  BIGINT NOT NULL REFERENCES property(property_id) ON DELETE CASCADE,
    unit_id      BIGINT NOT NULL,
    move_in_date DATE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (property_id, unit_id),
    CONSTRAINT unit_occupancy_global_unit_fk
        FOREIGN KEY (property_id, unit_id)
        REFERENCES unit(property_id, unit_id)
        ON DELETE CASCADE
);

DROP TRIGGER IF EXISTS unit_occupancy_global_set_updated_at ON unit_occupancy_global;
CREATE TRIGGER unit_occupancy_global_set_updated_at
    BEFORE UPDATE ON unit_occupancy_global
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE unit_occupancy_global IS
    'Latest known move-in date per unit. One row per (property_id, unit_id). '
    'Populated by occupancy_service.ingest() from Resident Activity or other sources.';
