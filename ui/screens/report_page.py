"""Report screen: moving log and pending movings."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from services import unit_movings_service


@st.cache_data(ttl=60)
def _cached_moving_log_bundle(property_id: int) -> tuple[list[dict], list[dict]]:
    return unit_movings_service.get_property_moving_log_bundle(property_id)


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
                "When connected, uploads here will feed the moving log (not implemented yet)."
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

        log_rows, units_with_movings = _cached_moving_log_bundle(property_id)

        with st.container(border=True):
            st.markdown("**LOADED MOVING DATA**")
            st.caption(
                "Moving log entries from the database that match units on this property "
                "(same source as historical / pending movings imports)."
            )
            if log_rows:
                st.dataframe(
                    pd.DataFrame(log_rows),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.caption("No moving log rows matched to this property’s units yet.")

        with st.container(border=True):
            st.markdown("**UNITS WITH MOVING DATES**")
            st.caption(
                "Imported units for this property with all matching moving dates "
                "(same columns as **Imported Units** on the Units page, plus moving dates)."
            )
            if units_with_movings:
                st.dataframe(
                    pd.DataFrame(units_with_movings),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.caption("No imported units yet — import a unit master on the Units page first.")

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
