"""Report screen: moving log import and pending movings ingest."""

from __future__ import annotations

import streamlit as st

from services import occupancy_service, unit_movings_service


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
                "Import historical moving dates into the global ``unit_movings`` log "
                "(columns: **unit_number**, **moving_date** — or **unit** / **move_in_date**). "
                "Does not update move-in dates for WO classification; use **Pending Movings** or "
                "**Work Order Validator → Move-In Data** for that."
            )

            ml_file = st.file_uploader(
                "Moving log source (.xls / .xlsx / .csv)",
                type=["xls", "xlsx", "csv"],
                key="report_moving_log_upload",
            )

            if st.button(
                "Load moving log",
                key="report_moving_log_ingest_btn",
                disabled=ml_file is None,
            ):
                with st.spinner("Importing moving log…"):
                    try:
                        result = unit_movings_service.import_historical_movings(
                            ml_file.getvalue(),
                            filename=ml_file.name,
                        )
                        st.session_state.report_moving_log_result = result
                        st.session_state.report_moving_log_error = None
                    except Exception as exc:  # noqa: BLE001
                        st.session_state.report_moving_log_result = None
                        st.session_state.report_moving_log_error = str(exc)
                st.rerun()

            ml_err = st.session_state.get("report_moving_log_error")
            ml_res = st.session_state.get("report_moving_log_result")
            if ml_err:
                st.error(f"Import failed: {ml_err}")
            if ml_res:
                st.success(
                    f"**Inserted:** {ml_res['inserted']} · **Skipped:** {ml_res['skipped']} "
                    "(duplicates or invalid rows count as skipped)."
                )

    with tab_pending:
        with st.container(border=True):
            st.markdown("**PENDING MOVINGS**")
            st.caption(
                "Upload a Pending Movings export with **unit_number** and **move_in_date** "
                "(or **moving_date**). Updates **unit_occupancy_global** for this property and "
                "appends matching rows to **unit_movings**."
            )

            pm_file = st.file_uploader(
                "Pending movings export (.xls / .xlsx)",
                type=["xls", "xlsx"],
                key="report_pending_movings_upload",
            )

            if st.button(
                "Load pending movings",
                key="report_pending_refresh_btn",
                disabled=pm_file is None,
                help="Parses file and applies occupancy + moving log for the selected property.",
            ):
                with st.spinner("Loading pending movings…"):
                    try:
                        result = occupancy_service.ingest_pending_movings(
                            property_id,
                            pm_file.getvalue(),
                            filename=pm_file.name,
                        )
                        st.session_state.report_pending_result = result
                        st.session_state.report_pending_error = None
                        st.cache_data.clear()
                    except Exception as exc:  # noqa: BLE001
                        st.session_state.report_pending_result = None
                        st.session_state.report_pending_error = str(exc)
                st.rerun()

            pm_err = st.session_state.get("report_pending_error")
            pm_res = st.session_state.get("report_pending_result")
            if pm_err:
                st.error(f"Import failed: {pm_err}")
            if pm_res:
                st.success(
                    f"**Processed:** {pm_res['processed']} · **Matched:** {pm_res['matched']} · "
                    f"**Unresolved:** {pm_res['unresolved']} · **Logged to movings:** {pm_res['logged']}"
                )
                st.info(
                    "Move-in preview tables under **Work Order Validator → Move-In Data** were "
                    "refreshed (cache cleared)."
                )
