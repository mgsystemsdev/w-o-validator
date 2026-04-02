"""Migration runner — read-only schema check for wo_standalone.

Schema is applied via Supabase Dashboard or CLI before first deploy.
This module only verifies that the required tables exist and raises a
clear error if they are missing.

Call assert_schema_ready() once at startup (wrapped in @st.cache_resource
in app.py so it runs once per worker process, not on every rerun).
"""

from __future__ import annotations

from db.connection import get_connection


_REQUIRED_TABLES = [
    "property",
    "unit",
    "unit_occupancy_global",
    "unit_movings",
    "users",
    "user_properties",
    "property_upload_snapshot",
]


def assert_schema_ready() -> None:
    """Raise RuntimeError if any required WO table is missing."""
    conn = get_connection()
    with conn.cursor() as cur:
        for table in _REQUIRED_TABLES:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_name = %s
                )
                """,
                (table,),
            )
            if not cur.fetchone()[0]:
                raise RuntimeError(
                    f"Required table '{table}' not found in Supabase. "
                    "Apply the migrations in db/migrations/ via Supabase Dashboard "
                    "or CLI before deploying."
                )
