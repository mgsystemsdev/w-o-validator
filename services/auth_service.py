"""Supabase Auth service — wraps the supabase-py GoTrue client.

Two cached singletons per worker process:
  - anon client  : user-facing sign-in / sign-out / token refresh
  - admin client : admin operations (create_auth_user)

The JWT session (access_token, refresh_token) is stored in st.session_state
by the caller — this module is stateless.
"""

from __future__ import annotations

import time

import streamlit as st
from supabase import create_client, Client

from config.settings import SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL


@st.cache_resource
def get_client() -> Client:
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_ANON_KEY must be set in .streamlit/secrets.toml"
        )
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


@st.cache_resource
def get_admin_client() -> Client:
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .streamlit/secrets.toml"
        )
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


def sign_in(email: str, password: str) -> dict:
    """Sign in with email + password.

    Returns:
        {user_id, access_token, refresh_token, expires_at}
    Raises:
        RuntimeError on invalid credentials or Supabase error.
    """
    try:
        response = get_client().auth.sign_in_with_password({"email": email, "password": password})
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc

    session = response.session
    user = response.user
    if session is None or user is None:
        raise RuntimeError("Sign-in failed — no session returned.")

    return {
        "user_id": str(user.id),
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "expires_at": time.time() + (session.expires_in or 3600),
    }


def refresh_session(refresh_token: str) -> dict:
    """Refresh using the refresh token. Returns same shape as sign_in().

    Raises RuntimeError if the session is revoked or the token is expired.
    """
    try:
        response = get_client().auth.refresh_session(refresh_token)
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc

    session = response.session
    user = response.user
    if session is None or user is None:
        raise RuntimeError("Token refresh failed.")

    return {
        "user_id": str(user.id),
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "expires_at": time.time() + (session.expires_in or 3600),
    }


def sign_out(access_token: str, refresh_token: str) -> None:
    """Sign out the current user. Silently ignores errors."""
    try:
        client = get_client()
        client.auth.set_session(access_token, refresh_token)
        client.auth.sign_out()
    except Exception:
        pass


def create_auth_user(email: str, password: str) -> str:
    """Create a new Supabase Auth user via the admin API.

    Returns the new user's UUID as a string.
    Raises RuntimeError on failure.
    """
    try:
        response = get_admin_client().auth.admin.create_user(
            {
                "email": email,
                "password": password,
                "email_confirm": True,
            }
        )
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc

    if response.user is None:
        raise RuntimeError("User creation failed — no user returned.")

    return str(response.user.id)
