"""Work Order Validator screen.

Tabs: Move-In Data → Service Requests → Download Reports.
Resident Activity upload feeds unit_occupancy_global; Service Request upload classifies WOs.
"""

from __future__ import annotations

from datetime import date

import streamlit as st

from services import occupancy_service, work_order_validator_service
from services import work_order_excel
from services.report_operations import active_sr_report

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_WO_STATE_KEYS = (
    "wo_report_bytes",
    "wo_report_date",
    "wo_summary",
    "wo_error",
    "wo_west_bytes",
    "wo_east_bytes",
)


def render_work_order_validator() -> None:
    st.title("Work Order Validator")

    property_id = st.session_state.get("property_id")
    if property_id is None:
        if st.session_state.get("_work_order_standalone_app"):
            st.info("Select or create a property in the sidebar.")
        elif st.session_state.get("access_mode") == "validator_only":
            st.info("Select a property in the sidebar, or contact an administrator if none are available.")
        else:
            st.info("Create a property in the Admin tab to begin.")
        return

    tab_movein, tab_sr, tab_download = st.tabs(
        ["Move-In Data", "Service Requests", "Download Reports"]
    )

    with tab_movein:
        with st.container(border=True):
            st.markdown("**LOAD MOVE-IN DATA**")
            st.caption(
                "Upload a Resident Activity export from OneSite to load move-in dates. "
                "Required before generating the first report; re-upload whenever data is stale."
            )

            _render_occupancy_status(property_id)

            ra_file = st.file_uploader(
                "Resident Activity (.xls / .xlsx)",
                type=["xls", "xlsx"],
                key="ra_upload",
            )

            if st.button("Load Move-In Data", key="ra_ingest_btn", disabled=ra_file is None):
                with st.spinner("Parsing and loading move-in records…"):
                    try:
                        result = occupancy_service.ingest_resident_activity(
                            property_id,
                            ra_file.read(),
                            filename=ra_file.name,
                        )
                        st.session_state.ra_ingest_result = result
                        st.session_state.ra_ingest_error = None
                    except Exception as exc:  # noqa: BLE001
                        st.session_state.ra_ingest_result = None
                        st.session_state.ra_ingest_error = str(exc)
                st.rerun()

            ra_result = st.session_state.get("ra_ingest_result")
            ra_error = st.session_state.get("ra_ingest_error")

            if ra_result:
                st.success(
                    f"Loaded **{ra_result['processed']}** records — "
                    f"**{ra_result['matched']}** matched to units, "
                    f"**{ra_result['unresolved']}** unresolved."
                )
            if ra_error:
                st.error(f"Failed to parse file: {ra_error}")

    with tab_sr:
        with st.container(border=True):
            st.markdown("**SERVICE REQUESTS**")
            st.caption(
                "Upload the Active Service Request export. "
                "Each work order will be classified as Make Ready or Service Technician."
            )

            sr_file = st.file_uploader(
                "Active Service Request (.xlsx)",
                type=["xls", "xlsx"],
                key="sr_upload",
            )

            if st.button("Generate Report", key="wo_generate_btn", disabled=sr_file is None):
                with st.spinner("Classifying work orders…"):
                    try:
                        # Read file content once; reuse for both validate and excel builder
                        sr_bytes = sr_file.read()
                        rows = work_order_validator_service.validate(property_id, sr_bytes)
                        report_bytes = work_order_excel.build_work_order_report(rows)
                        summary = work_order_validator_service.get_summary(rows)
                        west_bytes = active_sr_report.build_active_sr_report_from_rows(rows, "WEST")
                        east_bytes = active_sr_report.build_active_sr_report_from_rows(rows, "EAST")

                        st.session_state.wo_report_bytes = report_bytes
                        st.session_state.wo_report_date = date.today().isoformat()
                        st.session_state.wo_summary = summary
                        st.session_state.wo_west_bytes = west_bytes
                        st.session_state.wo_east_bytes = east_bytes
                        st.session_state.wo_error = None
                    except Exception as exc:  # noqa: BLE001
                        for k in _WO_STATE_KEYS:
                            st.session_state[k] = None
                        st.session_state.wo_error = str(exc)
                st.rerun()

            wo_error = st.session_state.get("wo_error")
            if wo_error:
                st.error(f"Report generation failed: {wo_error}")

            report_bytes = st.session_state.get("wo_report_bytes")
            if not report_bytes:
                st.info(
                    "Upload a Service Request file and click **Generate Report**. "
                    "When ready, open **Download Reports** for exports."
                )

    with tab_download:
        with st.container(border=True):
            st.markdown("**DOWNLOAD REPORTS**")
            st.caption(
                "Download the latest classified work order report. "
                "Generate a report from the Service Requests tab first."
            )

            summary = st.session_state.get("wo_summary")
            report_date = st.session_state.get("wo_report_date")
            west_bytes = st.session_state.get("wo_west_bytes")
            east_bytes = st.session_state.get("wo_east_bytes")

            if west_bytes and east_bytes and summary:
                st.success(
                    f"**{summary['total']}** work orders classified — "
                    f"**{summary['make_ready']}** Make Ready, "
                    f"**{summary['service_tech']}** Service Technician."
                )
                if report_date:
                    st.caption(f"Generated on: **{report_date}**")

                c_east, c_west = st.columns(2)
                with c_east:
                    st.download_button(
                        "Download East (Robert)",
                        data=east_bytes,
                        file_name=f"ASR_East_Robert_{report_date or 'report'}.xlsx",
                        mime=_XLSX_MIME,
                        key="wo_download_east_robert",
                        width="stretch",
                    )
                with c_west:
                    st.download_button(
                        "Download West (Mabi)",
                        data=west_bytes,
                        file_name=f"ASR_West_Mabi_{report_date or 'report'}.xlsx",
                        mime=_XLSX_MIME,
                        key="wo_download_west_mabi",
                        width="stretch",
                    )
            else:
                st.info(
                    "No report available yet. Use **Service Requests** to upload and "
                    "click **Generate Report**."
                )


def _render_occupancy_status(property_id: int) -> None:
    """Show last-loaded timestamp and unit count from unit_occupancy_global."""
    try:
        status = occupancy_service.get_occupancy_status(property_id)
        count = status["unit_count"]
        last_updated = status["last_updated"]
        if count and last_updated:
            st.caption(
                f"Move-in data last updated: **{last_updated}** — "
                f"**{count}** units on file."
            )
        else:
            st.caption("No move-in data loaded yet for this property.")
    except Exception:  # noqa: BLE001 — non-critical display
        pass
