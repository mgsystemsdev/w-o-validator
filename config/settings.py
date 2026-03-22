"""Application configuration resolver."""

from __future__ import annotations

import os
from typing import Any


def _load_streamlit_secrets() -> dict[str, Any]:
    try:
        import streamlit as st

        return dict(st.secrets)
    except Exception:
        return {}


def get_setting(key: str, default: Any = None) -> Any:
    value = os.getenv(key)
    if value is not None:
        out = value.strip()
        return out if out else default
    raw = _load_streamlit_secrets().get(key, default)
    if isinstance(raw, str):
        s = raw.strip()
        return s if s else default
    return raw


def _truthy(val: Any) -> bool:
    if val is None:
        return False
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def _normalize_explicit_url(url: str) -> str:
    import re
    url = url.strip()
    # psycopg2 rejects ``pgbouncer=true`` (not a libpq param); strip it.
    url = re.sub(r"[?&]pgbouncer=[^&]*", "", url)
    if url.endswith("?") or url.endswith("&"):
        url = url[:-1]
    if "sslmode=" not in url.lower():
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


def _build_split_dsn(
    host: str,
    password: str,
    *,
    user: str,
    port: str,
    dbname: str,
    sslmode: str,
) -> str:
    """Build a libpq key=value DSN — avoids URL-encoding pitfalls with ``@`` in passwords."""
    pw = str(password)
    if not pw.strip():
        raise RuntimeError("DATABASE_PASSWORD is empty.")

    def _kv_escape(val: str) -> str:
        return "'" + val.replace("\\", "\\\\").replace("'", "\\'") + "'"

    return (
        f"host={_kv_escape(host.strip())} "
        f"port={_kv_escape(str(port).strip())} "
        f"dbname={_kv_escape(dbname)} "
        f"user={_kv_escape(str(user))} "
        f"password={_kv_escape(pw)} "
        f"sslmode={_kv_escape(sslmode or 'require')}"
    )


def resolve_database_url() -> str:
    """Return a Postgres connection string (libpq key=value DSN or URI).

    **Precedence** (avoids a shell ``DATABASE_URL`` overriding ``.streamlit/secrets.toml``):

    1. If ``DATABASE_HOST`` and ``DATABASE_PASSWORD`` are set in **Streamlit secrets**,
       build a libpq key=value DSN (safe for passwords containing ``@``).
    2. Else if ``DATABASE_URL`` is set in **Streamlit secrets**, use it as a URI.
    3. Else fall back to environment variables, then non-DB Streamlit keys:
       ``DATABASE_URL``, or split keys via :func:`get_setting`.
    """
    secrets = _load_streamlit_secrets()

    shost = secrets.get("DATABASE_HOST")
    spwd = secrets.get("DATABASE_PASSWORD")
    if isinstance(shost, str) and shost.strip() and spwd is not None and str(spwd).strip():
        user = (secrets.get("DATABASE_USER") or "postgres").strip() or "postgres"
        port = str(secrets.get("DATABASE_PORT") or "5432").strip() or "5432"
        dbname = (secrets.get("DATABASE_NAME") or "postgres").strip() or "postgres"
        sslmode = (secrets.get("DATABASE_SSLMODE") or "require").strip() or "require"
        return _build_split_dsn(
            shost.strip(),
            str(spwd),
            user=user,
            port=port,
            dbname=dbname,
            sslmode=sslmode,
        )

    surl = secrets.get("DATABASE_URL")
    if isinstance(surl, str) and surl.strip():
        return _normalize_explicit_url(surl)

    explicit = os.getenv("DATABASE_URL")
    if explicit and explicit.strip():
        return _normalize_explicit_url(explicit)

    host = get_setting("DATABASE_HOST")
    password = get_setting("DATABASE_PASSWORD")
    if not host or password is None:
        raise RuntimeError(
            "Database not configured: set ``DATABASE_URL`` in ``.streamlit/secrets.toml``, "
            "or set ``DATABASE_HOST`` and ``DATABASE_PASSWORD`` (see ``secrets.toml.example``)."
        )
    user = get_setting("DATABASE_USER", "postgres") or "postgres"
    port = get_setting("DATABASE_PORT", "5432") or "5432"
    dbname = get_setting("DATABASE_NAME", "postgres") or "postgres"
    sslmode = get_setting("DATABASE_SSLMODE", "require") or "require"
    return _build_split_dsn(
        host,
        str(password),
        user=user,
        port=str(port),
        dbname=dbname,
        sslmode=sslmode,
    )


def is_truthy_setting(key: str) -> bool:
    v = get_setting(key, "")
    if v is None:
        return False
    s = str(v).strip().lower()
    return s in ("1", "true", "yes", "on")


DATABASE_URL = get_setting("DATABASE_URL", "")
APP_USERNAME = get_setting("APP_USERNAME", "")
APP_PASSWORD = get_setting("APP_PASSWORD", "")
VALIDATOR_USERNAME = get_setting("VALIDATOR_USERNAME", "")
VALIDATOR_PASSWORD = get_setting("VALIDATOR_PASSWORD", "")
AUTH_DISABLED = is_truthy_setting("AUTH_DISABLED")
