"""Database connection — thread-safe, Streamlit-Cloud-compatible.

Uses threading.local() so each Streamlit worker thread gets its own
psycopg2 connection.  @st.cache_resource caches only the DATABASE_URL
string so it is read from secrets exactly once per worker process.

Supabase requirements:
  - Use the Transaction Pooler URL (port 6543), not the direct connection.
  - sslmode=require must be present in the connection string.
  - prepare_threshold=None disables server-side prepared statements,
    which are incompatible with PgBouncer transaction mode.
"""

from __future__ import annotations

import contextlib
import threading

import psycopg2
import streamlit as st

from config.settings import resolve_database_url


_local = threading.local()


@st.cache_resource
def _get_database_url() -> str:
    return resolve_database_url()


def _connect(url: str):
    """psycopg2 connect; prepare_threshold is psycopg3-only on some builds."""
    try:
        return psycopg2.connect(url, prepare_threshold=None)
    except TypeError:
        conn = psycopg2.connect(url)
        if hasattr(conn, "prepare_threshold"):
            conn.prepare_threshold = None
        return conn


def get_connection():
    """Return the thread-local psycopg2 connection, reconnecting if closed."""
    conn = getattr(_local, "conn", None)
    if conn is None or conn.closed:
        url = _get_database_url()
        try:
            _local.conn = _connect(url)
        except psycopg2.OperationalError as exc:
            msg = str(exc).lower()
            if "password authentication failed" in msg:
                raise RuntimeError(
                    "Database password was rejected. In Supabase: Project Settings → "
                    "Database → confirm the **database** password (reset if unsure). "
                    "Either paste the full URI as ``DATABASE_URL``, or use "
                    "``DATABASE_HOST`` + ``DATABASE_PASSWORD`` in secrets (plain password; "
                    "no ``%40`` needed — see ``secrets.toml.example``). "
                    "On IPv4-only networks use the **pooler** host/port from Supabase."
                ) from exc
            if "connection refused" in msg or "could not connect" in msg:
                raise RuntimeError(
                    "Could not reach the database server. If the host is "
                    "``db.*.supabase.co`` on port **5432**, your network may block IPv6 or "
                    "Supabase direct access — use the **pooler** "
                    "(``aws-0-….pooler.supabase.com:6543``, user ``postgres.<ref>``) in "
                    "``.streamlit/secrets.toml``. Also **unset** a shell "
                    "``export DATABASE_URL=…`` if it still points at ``db.*:5432`` (it would "
                    "override secrets before this fix; split keys in secrets now win). "
                    "Restart Streamlit and **Clear cache**."
                ) from exc
            raise RuntimeError(
                "Database connection failed. On Streamlit Cloud, set **Deploy → Secrets** "
                "to match Supabase **Transaction pooler** (port **6543**), user "
                "``postgres.<project-ref>``, and ``sslmode=require``. "
                f"Details: {exc}"
            ) from exc
        except Exception as exc:
            raise RuntimeError(
                "Database connection failed (non-operational error). Check secrets and "
                f"psycopg2 compatibility. Details: {exc}"
            ) from exc
        _local.conn.autocommit = True
    return _local.conn


@contextlib.contextmanager
def transaction():
    """Wrap a block of DB writes in a single all-or-nothing transaction."""
    conn = get_connection()
    conn.autocommit = False
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.autocommit = True
