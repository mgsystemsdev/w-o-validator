"""Persist per-property upload / report UI state — survives Streamlit session loss."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any

from psycopg2.extras import RealDictCursor

from db.connection import get_connection

logger = logging.getLogger(__name__)

_SNAPSHOT_MIGRATION = "db/migrations/005_property_upload_snapshot.sql"

KIND_MOVING_LOG_IMPORT = "moving_log_import"
KIND_PENDING_MOVINGS_IMPORT = "pending_movings_import"
KIND_RESIDENT_ACTIVITY_INGEST = "resident_activity_ingest"
KIND_SERVICE_REQUEST_REPORT = "service_request_report"
KIND_UNIT_MASTER_IMPORT = "unit_master_import"


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def upsert(
    property_id: int,
    snapshot_kind: str,
    payload: dict[str, Any],
    *,
    blob_west: bytes | None = None,
    blob_east: bytes | None = None,
) -> None:
    raw = json.dumps(payload, default=_json_default)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO property_upload_snapshot (
                    property_id, snapshot_kind, payload, blob_west, blob_east, updated_at
                )
                VALUES (%s, %s, %s::jsonb, %s, %s, NOW())
                ON CONFLICT (property_id, snapshot_kind)
                DO UPDATE SET
                    payload    = EXCLUDED.payload,
                    blob_west  = EXCLUDED.blob_west,
                    blob_east  = EXCLUDED.blob_east,
                    updated_at = NOW()
                """,
                (property_id, snapshot_kind, raw, blob_west, blob_east),
            )
    except pg_errors.UndefinedTable:
        conn.rollback()
        logger.warning(
            "Table property_upload_snapshot is missing; snapshots are skipped. "
            "Apply %s in Supabase SQL Editor.",
            _SNAPSHOT_MIGRATION,
        )
        return


def get(property_id: int, snapshot_kind: str) -> dict[str, Any] | None:
    """Return row dict with ``payload``, ``updated_at``, optional ``blob_*``; or None."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT payload, updated_at, blob_west, blob_east
                FROM property_upload_snapshot
                WHERE property_id = %s AND snapshot_kind = %s
                """,
                (property_id, snapshot_kind),
            )
            row = cur.fetchone()
    except pg_errors.UndefinedTable:
        conn.rollback()
        logger.warning(
            "Table property_upload_snapshot is missing; snapshot reads return empty. "
            "Apply %s in Supabase SQL Editor.",
            _SNAPSHOT_MIGRATION,
        )
        return None
    if not row:
        return None
    out: dict[str, Any] = {
        "payload": dict(row["payload"]),
        "updated_at": row["updated_at"],
    }
    if row.get("blob_west") is not None:
        out["blob_west"] = bytes(row["blob_west"])
    if row.get("blob_east") is not None:
        out["blob_east"] = bytes(row["blob_east"])
    return out
