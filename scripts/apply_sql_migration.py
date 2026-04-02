#!/usr/bin/env python3
"""Run a migration SQL file against Postgres using app DB settings.

Reads credentials the same way as the Streamlit app:
  1. Existing environment variables (``DATABASE_URL`` or split ``DATABASE_*`` keys).
  2. If ``DATABASE_HOST`` is still unset, loads ``.streamlit/secrets.toml`` (flat keys).

Usage (from repo root):

  python3 scripts/apply_sql_migration.py db/migrations/005_property_upload_snapshot.sql

Requires: ``psycopg2-binary`` (see ``requirements.txt``). Uses the **transaction pooler**
(``6543``) when that is what you have in secrets — same as the app.

This does not run automatically at startup; run it when you add a new migration.
"""

from __future__ import annotations

import argparse
import os
import sys
import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _hydrate_env_from_streamlit_secrets() -> None:
    path = _REPO_ROOT / ".streamlit" / "secrets.toml"
    if not path.is_file():
        return
    if os.getenv("DATABASE_URL") or os.getenv("DATABASE_HOST"):
        return
    data = tomllib.loads(path.read_text())
    if not isinstance(data, dict):
        return
    for key in (
        "DATABASE_URL",
        "DATABASE_HOST",
        "DATABASE_PASSWORD",
        "DATABASE_USER",
        "DATABASE_PORT",
        "DATABASE_NAME",
        "DATABASE_SSLMODE",
    ):
        val = data.get(key)
        if val is not None and str(val).strip():
            os.environ.setdefault(key, str(val).strip())


def _split_sql_statements(sql: str) -> list[str]:
    lines: list[str] = []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        lines.append(line)
    blob = "\n".join(lines)
    parts: list[str] = []
    for chunk in blob.split(";"):
        piece = chunk.strip()
        if piece:
            parts.append(piece + ";")
    return parts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "sql_path",
        type=Path,
        help="Path to .sql file (e.g. db/migrations/005_property_upload_snapshot.sql)",
    )
    args = parser.parse_args()
    sql_path = args.sql_path if args.sql_path.is_absolute() else _REPO_ROOT / args.sql_path
    if not sql_path.is_file():
        print(f"File not found: {sql_path}", file=sys.stderr)
        return 1

    _hydrate_env_from_streamlit_secrets()
    sys.path.insert(0, str(_REPO_ROOT))

    from config.settings import resolve_database_url

    try:
        url = resolve_database_url()
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    import psycopg2

    sql_text = sql_path.read_text()
    statements = _split_sql_statements(sql_text)
    if not statements:
        print("No SQL statements found in file.", file=sys.stderr)
        return 1

    try:
        conn = psycopg2.connect(url, prepare_threshold=None)
    except TypeError:
        conn = psycopg2.connect(url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            for stmt in statements:
                cur.execute(stmt)
    finally:
        conn.close()

    print(f"Applied {len(statements)} statement(s) from {sql_path.relative_to(_REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
