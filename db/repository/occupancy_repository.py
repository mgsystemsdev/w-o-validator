"""Repository for unit_occupancy_global — latest known move-in date per unit."""

from __future__ import annotations

from datetime import date

from psycopg2.extras import RealDictCursor

from db.connection import get_connection


def upsert(property_id: int, unit_id: int, move_in_date: date | None) -> None:
    """Insert or replace move-in date for (property_id, unit_id). Latest source wins."""
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO unit_occupancy_global (property_id, unit_id, move_in_date)
            VALUES (%s, %s, %s)
            ON CONFLICT (property_id, unit_id)
            DO UPDATE SET
                move_in_date = EXCLUDED.move_in_date,
                updated_at   = NOW()
            """,
            (property_id, unit_id, move_in_date),
        )


def get_all_by_property(property_id: int) -> dict[int, date | None]:
    """Return {unit_id: move_in_date} for all loaded units. Used for bulk in-memory joins."""
    conn = get_connection()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT unit_id, move_in_date
            FROM unit_occupancy_global
            WHERE property_id = %s
            """,
            (property_id,),
        )
        return {row["unit_id"]: row["move_in_date"] for row in cur.fetchall()}


def count_by_property(property_id: int) -> int:
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM unit_occupancy_global WHERE property_id = %s",
            (property_id,),
        )
        return cur.fetchone()[0]


def get_last_updated(property_id: int) -> date | None:
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT MAX(updated_at) FROM unit_occupancy_global WHERE property_id = %s",
            (property_id,),
        )
        result = cur.fetchone()[0]
        return result.date() if result else None


def list_move_in_rows_for_property(property_id: int) -> list[dict]:
    """Occupancy rows joined to unit for Move-In Data tables (property-scoped)."""
    conn = get_connection()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                u.unit_code_raw AS unit,
                o.move_in_date,
                o.updated_at AS record_updated_at
            FROM unit_occupancy_global o
            JOIN unit u
              ON u.property_id = o.property_id AND u.unit_id = o.unit_id
            WHERE o.property_id = %s
            ORDER BY u.unit_code_raw
            """,
            (property_id,),
        )
        return cur.fetchall()
