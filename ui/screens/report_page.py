"""Report screen: moving log and pending movings (UI scaffold)."""

from __future__ import annotations

import streamlit as st


def render_report_page() -> None:
    st.title("Report")

    property_id = st.session_state.get("property_id")
    if property_id is None:
        st.info("Select a property in the sidebar. If none are available, contact an administrator.")
        return

    tab_moving_log, tab_pending = st.tabs(["Moving Log", "Pending Movings"])

    with tab_moving_log:
        with st.container(border=True):
            st.markdown("**MOVING LOG**")
            st.caption(
                "View or import moving history for this property. "
                "Moving log tables live under **Work Order Validator → Move-In Data**."
            )

            st.file_uploader(
                "Moving log source (.xls / .xlsx / .csv)",
                type=["xls", "xlsx", "csv"],
                key="report_moving_log_upload",
                disabled=True,
            )

            st.button(
                "Load moving log",
                key="report_moving_log_ingest_btn",
                disabled=True,
                help="Placeholder — no ingestion wired yet.",
            )

            st.info(
                "Loaded moving data and units-with-dates tables are on the **Move-In Data** tab."
            )

    with tab_pending:
        with st.container(border=True):
            st.markdown("**PENDING MOVINGS**")
            st.caption(
                "Review moves that are scheduled or in progress. "
                "When connected, this area will list pending movings and actions (not implemented yet)."
            )

            st.file_uploader(
                "Pending movings export (.xls / .xlsx)",
                type=["xls", "xlsx"],
                key="report_pending_movings_upload",
                disabled=True,
            )

            st.button(
                "Refresh pending list",
                key="report_pending_refresh_btn",
                disabled=True,
                help="Placeholder — no backend yet.",
            )

            st.info(
                "Pending movings are not connected yet. "
                "This tab mirrors the Work Order Validator layout for a future workflow."
            )
