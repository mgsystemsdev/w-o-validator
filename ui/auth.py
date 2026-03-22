"""Auth — env-mode only (username + password from Streamlit secrets).

DB-backed auth is not used in wo_standalone. To disable login entirely,
set AUTH_DISABLED = "true" in Streamlit secrets.
"""

from __future__ import annotations

import streamlit as st

from config.settings import APP_PASSWORD, APP_USERNAME, AUTH_DISABLED, VALIDATOR_PASSWORD, VALIDATOR_USERNAME


def require_auth() -> bool:
    """Return True if the user is authenticated; otherwise render the login form."""
    if st.session_state.get("authenticated"):
        return True

    if AUTH_DISABLED:
        st.session_state.authenticated = True
        st.session_state.access_mode = "full"
        return True

    # No credentials configured → open access (local dev without secrets set)
    if not (APP_USERNAME and APP_PASSWORD) and not (VALIDATOR_USERNAME and VALIDATOR_PASSWORD):
        st.session_state.authenticated = True
        st.session_state.access_mode = "full"
        return True

    _, col, _ = st.columns([1, 2, 1])
    with col:
        with st.form("login_form"):
            st.subheader("Work Order App — Login")
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in")

        if submitted:
            if (
                VALIDATOR_USERNAME
                and VALIDATOR_PASSWORD
                and username == VALIDATOR_USERNAME
                and password == VALIDATOR_PASSWORD
            ):
                st.session_state.authenticated = True
                st.session_state.access_mode = "validator_only"
                st.rerun()
            elif username == APP_USERNAME and password == APP_PASSWORD:
                st.session_state.authenticated = True
                st.session_state.access_mode = "full"
                st.rerun()
            else:
                st.error("Invalid username or password.")

    return False
