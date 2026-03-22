"""Work Order App — Streamlit entrypoint.

Run locally:
    streamlit run wo_standalone/app.py

Deploy to Streamlit Cloud:
    Set main file path to: wo_standalone/app.py
    Add secrets in the Streamlit Cloud dashboard (see .streamlit/secrets.toml.example).
"""

from __future__ import annotations

import streamlit as st

from db.migration_runner import assert_schema_ready
from services import property_service
from ui.auth import require_auth
from ui.import_movings_page import render_import_movings
from ui.screens.work_order_validator import render_work_order_validator


@st.cache_resource
def _bootstrap() -> None:
    """Run schema check once per worker process."""
    assert_schema_ready()


def _render_sidebar() -> str:
    """Render sidebar: property selector + page nav. Returns selected page label."""
    with st.sidebar:
        st.markdown(
            "<h2 style='margin-top:-1rem;margin-bottom:0'>Work Order App</h2>"
            "<p style='margin:0 0 .5rem;font-size:.85rem;color:grey'>"
            "Validator · Imports</p>",
            unsafe_allow_html=True,
        )

        properties = property_service.get_all_properties()
        if properties:
            names = [p["name"] for p in properties]
            ids = [p["property_id"] for p in properties]
            current_id = st.session_state.get("property_id")
            default_index = ids.index(current_id) if current_id in ids else 0
            selected_name = st.selectbox("Property", options=names, index=default_index)
            st.session_state.property_id = ids[names.index(selected_name)]
        else:
            st.info("No properties yet — create one below.")
            st.session_state.property_id = None

        new_name = st.text_input("New property", key="wo_new_property", placeholder="Name")
        if st.button("Create property", key="wo_create_property"):
            name = new_name.strip()
            if not name:
                st.warning("Enter a property name.")
            else:
                try:
                    prop = property_service.create_property(name)
                    st.session_state.property_id = prop["property_id"]
                    st.cache_data.clear()
                    st.success(f"Created **{name}**.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Failed to create property: {exc}")

        st.divider()
        page = st.radio(
            "Pages",
            options=["Work Order Validator", "Import movings"],
            label_visibility="collapsed",
        )
    return page


def main() -> None:
    st.set_page_config(page_title="Work Order App", layout="wide")

    # Initialize minimal session state
    st.session_state.setdefault("authenticated", False)
    st.session_state.setdefault("access_mode", None)
    st.session_state.setdefault("property_id", None)

    # Schema check — runs once per worker process via @st.cache_resource
    try:
        _bootstrap()
    except RuntimeError as exc:
        st.error(str(exc))
        st.stop()
        return

    if not require_auth():
        st.stop()
        return

    # Signal to work_order_validator.py that we are running in standalone mode
    st.session_state["_work_order_standalone_app"] = True

    page = _render_sidebar()

    if page == "Work Order Validator":
        render_work_order_validator()
    else:
        render_import_movings()


if __name__ == "__main__":
    main()
