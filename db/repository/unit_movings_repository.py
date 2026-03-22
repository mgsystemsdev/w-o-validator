from __future__ import annotations

from datetime import date

from psycopg2.extras import RealDictCursor

from db.connection import get_connection


def insert_moving(unit_number: str, moving_date: date) -> dict | None:
    conn = get_connection()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            INSERT INTO unit_movings (unit_number, moving_date)
            VALUES (%s, %s)
            ON CONFLICT (unit_number, moving_date) DO NOTHING
            RETURNING *
            """,
            (unit_number, moving_date),
        )
        return cur.fetchone()


def get_latest_movings_by_unit() -> dict[str, date]:
    """Return {unit_number: latest moving_date} for all units.

    Uses DISTINCT ON (valid Postgres / Supabase) — no rewrite needed.
    """
    conn = get_connection()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (unit_number)
                   unit_number, moving_date
            FROM unit_movings
            ORDER BY unit_number, moving_date DESC
            """
        )
        rows = cur.fetchall()
    return {row["unit_number"]: row["moving_date"] for row in rows}
