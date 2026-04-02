"""Migration runner — read-only schema check for wo_standalone.

Schema is applied via Supabase Dashboard or CLI before first deploy.
This module verifies that core tables exist and raises if any are missing.
``property_upload_snapshot`` (migration 005) is optional at startup: the app
runs without it, but import/report snapshots are not persisted until applied.

Call assert_schema_ready() once at startup (wrapped in @st.cache_resource
in app.py so it runs once per worker process, not on every rerun).
"""

from __future__ import annotations

import logging

from db.connection import get_connection

logger = logging.getLogger(__name__)

_REQUIRED_TABLES = [
    "property",
    "unit",
    "unit_occupancy_global",
    "unit_movings",
    "users",
    "user_properties",
]

# Present on fully migrated DBs; repositories tolerate absence (session-only UX).
_OPTIONAL_TABLES: tuple[tuple[str, str], ...] = (
    ("property_upload_snapshot", "db/migrations/005_property_upload_snapshot.sql"),
)


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

    for table, migration_path in _OPTIONAL_TABLES:
        with conn.cursor() as cur:
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
                logger.warning(
                    "Table '%s' is missing; upload/report snapshots will not persist. "
                    "Apply %s in the Supabase SQL Editor when convenient.",
                    table,
                    migration_path,
                )
