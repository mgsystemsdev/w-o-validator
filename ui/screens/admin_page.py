"""Admin page — user management (admin-only).

Allows admins to:
  - Create users (Supabase Auth + public.users + user_properties)
  - Deactivate / reactivate users
  - Assign / remove properties per user
"""

from __future__ import annotations

import streamlit as st

from db.repository import user_repository
from services import auth_service, property_service


def render_admin_page() -> None:
    if not st.session_state.get("user_is_admin"):
        st.error("Access denied.")
        return

    st.title("Admin — User Management")
    _render_create_user_section()
    st.divider()
    _render_user_table()


def _render_create_user_section() -> None:
    st.subheader("Create User")
    all_properties = property_service.get_all_properties()
    prop_options = {p["name"]: p["property_id"] for p in all_properties}

    with st.form("create_user_form"):
        col1, col2 = st.columns(2)
        with col1:
            email = st.text_input("Email")
            username = st.text_input("Username")
        with col2:
            password = st.text_input("Password", type="password")
            is_admin = st.checkbox("Admin")
        selected_names = st.multiselect("Assign properties", options=list(prop_options.keys()))
        submitted = st.form_submit_button("Create User")

    if submitted:
        email = email.strip()
        username = username.strip()
        if not email or not username or not password:
            st.error("Email, username, and password are required.")
            return
        try:
            user_id = auth_service.create_auth_user(email, password)
            user_repository.create_user(user_id, email, username, is_admin)
            property_ids = [prop_options[n] for n in selected_names]
            if property_ids:
                user_repository.set_user_properties(user_id, property_ids)
            st.success(f"Created user **{username}** ({email}).")
        except RuntimeError as exc:
            st.error(f"Failed to create user: {exc}")


def _render_user_table() -> None:
    st.subheader("Users")
    users = user_repository.list_all_users_with_properties()
    if not users:
        st.info("No users yet.")
        return

    all_properties = property_service.get_all_properties()
    prop_name_by_id = {p["property_id"]: p["name"] for p in all_properties}
    prop_options = {p["name"]: p["property_id"] for p in all_properties}

    current_user_id = st.session_state.get("supabase_user_id")

    for user in users:
        uid = str(user["user_id"])
        is_self = uid == current_user_id

        label = f"**{user['username']}** — {user['email']}"
        if user["is_admin"]:
            label += " *(admin)*"
        if not user["is_active"]:
            label += " — inactive"

        with st.expander(label, expanded=False):
            col_status, col_props = st.columns([1, 2])

            with col_status:
                if is_self:
                    st.caption("(your account)")
                elif user["is_active"]:
                    if st.button("Deactivate", key=f"deactivate_{uid}"):
                        user_repository.set_user_active(uid, False)
                        st.rerun()
                else:
                    if st.button("Reactivate", key=f"reactivate_{uid}"):
                        user_repository.set_user_active(uid, True)
                        st.rerun()

            with col_props:
                current_prop_ids = list(user["property_ids"])
                current_prop_names = [
                    prop_name_by_id[pid]
                    for pid in current_prop_ids
                    if pid in prop_name_by_id
                ]
                new_names = st.multiselect(
                    "Properties",
                    options=list(prop_options.keys()),
                    default=current_prop_names,
                    key=f"props_{uid}",
                )
                if st.button("Save properties", key=f"save_props_{uid}"):
                    new_ids = [prop_options[n] for n in new_names]
                    user_repository.set_user_properties(uid, new_ids)
                    if is_self:
                        st.session_state.user_allowed_properties = new_ids
                    st.success("Properties updated.")
                    st.rerun()
