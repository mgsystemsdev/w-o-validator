"""Auth — Supabase-backed email + password authentication.

First-run bootstrap: if the users table is empty, the login form is replaced
with a "Create first admin" form — no prior auth required.

Session state written on login:
    authenticated            bool
    supabase_user_id         str (UUID)
    supabase_access_token    str
    supabase_refresh_token   str
    supabase_token_expires_at float (epoch seconds)
    user_is_admin            bool
    user_username            str
    user_allowed_properties  list[int]
"""

from __future__ import annotations

import time

import streamlit as st

from config.settings import AUTH_DISABLED
from db.repository import user_repository
from services import auth_service

_AUTH_KEYS = (
    "authenticated",
    "supabase_user_id",
    "supabase_access_token",
    "supabase_refresh_token",
    "supabase_token_expires_at",
    "user_is_admin",
    "user_username",
    "user_allowed_properties",
)


def sign_out_current_user() -> None:
    """Sign out the current user and clear all auth session state."""
    access_token = st.session_state.get("supabase_access_token", "")
    refresh_token = st.session_state.get("supabase_refresh_token", "")
    if access_token and refresh_token:
        auth_service.sign_out(access_token, refresh_token)
    for key in _AUTH_KEYS:
        st.session_state.pop(key, None)
    st.session_state["property_id"] = None


def _populate_session(session_data: dict, user_profile: dict, allowed_properties: list[int]) -> None:
    st.session_state.authenticated = True
    st.session_state.supabase_user_id = session_data["user_id"]
    st.session_state.supabase_access_token = session_data["access_token"]
    st.session_state.supabase_refresh_token = session_data["refresh_token"]
    st.session_state.supabase_token_expires_at = session_data["expires_at"]
    st.session_state.user_is_admin = bool(user_profile["is_admin"])
    st.session_state.user_username = user_profile["username"]
    st.session_state.user_allowed_properties = allowed_properties


def _try_token_refresh() -> bool:
    """Refresh the access token if it expires within 5 minutes.

    Returns False if the refresh fails (session revoked / network error).
    """
    expires_at = st.session_state.get("supabase_token_expires_at", 0.0)
    if time.time() < expires_at - 300:
        return True  # token still valid

    refresh_token = st.session_state.get("supabase_refresh_token", "")
    if not refresh_token:
        return False
    try:
        new_session = auth_service.refresh_session(refresh_token)
        st.session_state.supabase_access_token = new_session["access_token"]
        st.session_state.supabase_refresh_token = new_session["refresh_token"]
        st.session_state.supabase_token_expires_at = new_session["expires_at"]
        return True
    except RuntimeError:
        return False


def _render_first_run_form() -> bool:
    """Render the first-admin setup form. Returns True once admin is created."""
    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.info("No users exist yet. Create the first admin account to get started.")
        with st.form("first_admin_form"):
            st.subheader("Create First Admin")
            email = st.text_input("Email")
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Create Admin Account")

        if submitted:
            email = email.strip()
            username = username.strip()
            if not email or not username or not password:
                st.error("All fields are required.")
                return False
            try:
                user_id = auth_service.create_auth_user(email, password)
                user_repository.create_user(user_id, email, username, is_admin=True)
                session_data = auth_service.sign_in(email, password)
                profile = user_repository.get_user_by_id(user_id)
                _populate_session(session_data, profile, [])
                st.rerun()
            except RuntimeError as exc:
                st.error(f"Setup failed: {exc}")
    return False


def _render_login_form() -> bool:
    """Render the standard login form. Returns False until login succeeds."""
    _, col, _ = st.columns([1, 2, 1])
    with col:
        with st.form("login_form"):
            st.subheader("Work Order App — Login")
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in")

        if submitted:
            email = email.strip()
            try:
                session_data = auth_service.sign_in(email, password)
            except RuntimeError:
                st.error("Invalid email or password.")
                return False

            profile = user_repository.get_user_by_id(session_data["user_id"])
            if profile is None:
                auth_service.sign_out(session_data["access_token"], session_data["refresh_token"])
                st.error("Account not provisioned — contact an administrator.")
                return False
            if not profile["is_active"]:
                auth_service.sign_out(session_data["access_token"], session_data["refresh_token"])
                st.error("Account is deactivated — contact an administrator.")
                return False

            allowed = user_repository.get_user_properties(session_data["user_id"])
            _populate_session(session_data, profile, allowed)
            st.rerun()
    return False


def require_auth() -> bool:
    """Return True if authenticated; otherwise render login (or first-run) form."""
    if AUTH_DISABLED:
        if not st.session_state.get("authenticated"):
            st.session_state.authenticated = True
            st.session_state.user_is_admin = True
            st.session_state.user_username = "dev"
            st.session_state.user_allowed_properties = []
            st.session_state.supabase_user_id = "dev"
        return True

    if st.session_state.get("authenticated"):
        if not _try_token_refresh():
            sign_out_current_user()
            st.warning("Session expired — please log in again.")
            st.rerun()
        return True

    # First-run: no users provisioned yet
    try:
        if user_repository.count_users() == 0:
            return _render_first_run_form()
    except Exception:
        pass  # table may not exist yet — fall through to normal login

    return _render_login_form()
