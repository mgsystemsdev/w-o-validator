"""Work Order Validator screen.

Tabs: Move-In Data → Service Requests → Download Reports.
Resident Activity upload feeds unit_occupancy_global; Service Request upload classifies WOs.
"""

from __future__ import annotations

from datetime import date

import streamlit as st

from db.repository import property_upload_snapshot_repository
from domain.dates import format_us_date, format_us_datetime
from services import occupancy_service, work_order_validator_service
from services import work_order_excel
from services.report_operations import active_sr_report
from ui.dataframe_display import dataframe_for_streamlit

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_SR_PREVIEW_CAP = 1200

_WO_STATE_KEYS = (
    "wo_report_bytes",
    "wo_report_date",
    "wo_summary",
    "wo_error",
    "wo_west_bytes",
    "wo_east_bytes",
    "wo_preview_rows",
)


def _load_sr_snapshot(property_id: int) -> dict | None:
    return property_upload_snapshot_repository.get(
        property_id, property_upload_snapshot_repository.KIND_SERVICE_REQUEST_REPORT
    )


def _load_ra_snapshot(property_id: int) -> dict | None:
    return property_upload_snapshot_repository.get(
        property_id, property_upload_snapshot_repository.KIND_RESIDENT_ACTIVITY_INGEST
    )


@st.cache_data(ttl=60)
def _cached_move_in_tables(property_id: int) -> tuple[list[dict], list[dict]]:
    return occupancy_service.get_move_in_tables_bundle(property_id)


def render_work_order_validator() -> None:
    st.title("Work Order Validator")

    property_id = st.session_state.get("property_id")
    if property_id is None:
        st.info("Select a property in the sidebar. If none are available, contact an administrator.")
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
                        occupancy_service.ingest_resident_activity(
                            property_id,
                            ra_file.read(),
                            filename=ra_file.name,
                        )
                        st.session_state.ra_ingest_error = None
                        _cached_move_in_tables.clear()
                    except Exception as exc:  # noqa: BLE001
                        st.session_state.ra_ingest_error = str(exc)
                st.rerun()

            ra_error = st.session_state.get("ra_ingest_error")
            if ra_error:
                st.error(f"Failed to parse file: {ra_error}")

            ra_row = _load_ra_snapshot(property_id)
            if ra_row:
                ra_result = ra_row["payload"]
                st.success(
                    f"Loaded **{ra_result['processed']}** records — "
                    f"**{ra_result['matched']}** matched to units, "
                    f"**{ra_result['unresolved']}** unresolved."
                )
                rfn = ra_result.get("source_filename") or "—"
                st.caption(
                    f"Resident Activity file **{rfn}** processed "
                    f"**{format_us_datetime(ra_row['updated_at'])}** (saved per property; "
                    "persists after you leave this page or sign out)."
                )

        _render_move_in_tables(property_id)

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
                        sr_bytes = sr_file.read()
                        rows = work_order_validator_service.validate(property_id, sr_bytes)
                        report_bytes = work_order_excel.build_work_order_report(rows)
                        summary = work_order_validator_service.get_summary(rows)
                        west_bytes = active_sr_report.build_active_sr_report_from_rows(rows, "WEST")
                        east_bytes = active_sr_report.build_active_sr_report_from_rows(rows, "EAST")
                        preview_full = work_order_validator_service.rows_for_preview(rows)
                        preview_rows = preview_full[:_SR_PREVIEW_CAP]

                        st.session_state.wo_report_bytes = report_bytes
                        st.session_state.wo_report_date = format_us_date(date.today())
                        st.session_state.wo_summary = summary
                        st.session_state.wo_west_bytes = west_bytes
                        st.session_state.wo_east_bytes = east_bytes
                        st.session_state.wo_preview_rows = preview_full
                        st.session_state.wo_error = None

                        try:
                            property_upload_snapshot_repository.upsert(
                                property_id,
                                property_upload_snapshot_repository.KIND_SERVICE_REQUEST_REPORT,
                                {
                                    "summary": summary,
                                    "report_date": st.session_state.wo_report_date,
                                    "preview_rows": preview_rows,
                                    "preview_truncated": len(preview_full) > _SR_PREVIEW_CAP,
                                    "total_row_count": len(preview_full),
                                    "source_filename": sr_file.name,
                                },
                                blob_west=west_bytes,
                                blob_east=east_bytes,
                            )
                        except Exception:
                            pass
                    except Exception as exc:  # noqa: BLE001
                        for k in _WO_STATE_KEYS:
                            st.session_state[k] = None
                        st.session_state.wo_error = str(exc)
                st.rerun()

            wo_error = st.session_state.get("wo_error")
            if wo_error:
                st.error(f"Report generation failed: {wo_error}")

            sr_snap = _load_sr_snapshot(property_id)
            if sr_snap:
                p = sr_snap["payload"]
                st.caption(
                    f"Last Service Request file: **{p.get('source_filename') or '—'}** · "
                    f"report saved **{format_us_datetime(sr_snap['updated_at'])}** "
                    "(preview and East/West downloads persist for this property)."
                )

            report_bytes = st.session_state.get("wo_report_bytes")
            if not report_bytes and not sr_snap:
                st.info(
                    "Upload a Service Request file and click **Generate Report**. "
                    "When ready, open **Download Reports** for exports."
                )

        _render_wo_preview_section(property_id)

    with tab_download:
        with st.container(border=True):
            st.markdown("**DOWNLOAD REPORTS**")
            st.caption(
                "East and West workbooks are stored for this property after each successful run "
                "(including after sign-in again)."
            )

            snap = _load_sr_snapshot(property_id)
            summary = None
            report_date = None
            west_bytes = None
            east_bytes = None
            if snap:
                p = snap["payload"]
                summary = p.get("summary")
                report_date = p.get("report_date")
                west_bytes = snap.get("blob_west")
                east_bytes = snap.get("blob_east")
            if summary is None:
                summary = st.session_state.get("wo_summary")
            if report_date is None:
                report_date = st.session_state.get("wo_report_date")
            if west_bytes is None:
                west_bytes = st.session_state.get("wo_west_bytes")
            if east_bytes is None:
                east_bytes = st.session_state.get("wo_east_bytes")

            report_file_slug = (
                report_date.replace("/", "-") if isinstance(report_date, str) else "report"
            )

            if west_bytes and east_bytes and summary:
                st.success(
                    f"**{summary['total']}** work orders classified — "
                    f"**{summary['make_ready']}** Make Ready, "
                    f"**{summary['service_tech']}** Service Technician."
                )
                if snap:
                    st.caption(
                        f"Generated **{report_date or '—'}** · file saved "
                        f"**{format_us_datetime(snap['updated_at'])}**"
                    )
                elif report_date:
                    st.caption(f"Generated on: **{report_date}**")

                _render_wo_preview_section(property_id)

                c_east, c_west = st.columns(2)
                with c_east:
                    st.download_button(
                        "Download East (Robert)",
                        data=east_bytes,
                        file_name=f"ASR_East_Robert_{report_file_slug}.xlsx",
                        mime=_XLSX_MIME,
                        key="wo_download_east_robert",
                        width="stretch",
                    )
                with c_west:
                    st.download_button(
                        "Download West (Mabi)",
                        data=west_bytes,
                        file_name=f"ASR_West_Mabi_{report_file_slug}.xlsx",
                        mime=_XLSX_MIME,
                        key="wo_download_west_mabi",
                        width="stretch",
                    )
            else:
                st.info(
                    "No report on file for this property yet. Use **Service Requests** to upload "
                    "and click **Generate Report**."
                )
                _render_wo_preview_section(property_id)


def _render_wo_preview_section(property_id: int) -> None:
    """Preview from DB snapshot (persistent) or current session."""
    preview = st.session_state.get("wo_preview_rows")
    total_note = None
    if not preview:
        snap = _load_sr_snapshot(property_id)
        if snap:
            p = snap["payload"]
            preview = p.get("preview_rows")
            if p.get("preview_truncated"):
                total_note = p.get("total_row_count")

    with st.container(border=True):
        st.markdown("**CLASSIFIED WORK ORDERS (PREVIEW)**")
        st.caption(
            "Matches the latest generated report. East/West downloads split rows by phase inside "
            "each file."
        )
        if preview:
            if total_note:
                st.caption(
                    f"Showing **{len(preview)}** of **{total_note}** work orders "
                    f"(preview capped at {_SR_PREVIEW_CAP} rows for storage)."
                )
            else:
                st.caption(f"**{len(preview)}** work orders.")
            st.dataframe(
                dataframe_for_streamlit(preview),
                use_container_width=True,
                hide_index=True,
                height=400,
            )
        else:
            st.caption("Generate a report from **Service Requests** to see a preview here.")


def _render_move_in_tables(property_id: int) -> None:
    """Show move-in data from ``unit_occupancy_global`` (Resident Activity load)."""
    log_rows, units_with_move_in = _cached_move_in_tables(property_id)

    with st.container(border=True):
        st.markdown("**LOADED MOVE-IN DATA**")
        st.caption(
            "Rows currently stored for this property from **Load Move-In Data** "
            "(`unit_occupancy_global`)."
        )
        if log_rows:
            st.dataframe(
                dataframe_for_streamlit(log_rows),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("No move-in rows on file yet — upload Resident Activity above.")

    with st.container(border=True):
        st.markdown("**UNITS WITH MOVE-IN DATES**")
        st.caption(
            "Imported units (same columns as **Imported Units** on the Units page) "
            "with the loaded **move_in_date** when present."
        )
        if units_with_move_in:
            st.dataframe(
                dataframe_for_streamlit(units_with_move_in),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("No imported units yet — import a unit master on the Units page first.")


def _render_occupancy_status(property_id: int) -> None:
    """Show last-loaded timestamp and unit count from unit_occupancy_global."""
    try:
        status = occupancy_service.get_occupancy_status(property_id)
        count = status["unit_count"]
        last_at = status.get("last_updated_at")
        if count and last_at:
            st.caption(
                f"Move-in data last updated: **{format_us_datetime(last_at)}** — "
                f"**{count}** units on file."
            )
        elif count:
            lu = status.get("last_updated")
            st.caption(
                f"Move-in data last updated: **{format_us_date(lu)}** — **{count}** units on file."
            )
        else:
            st.caption("No move-in data loaded yet for this property.")
    except Exception:  # noqa: BLE001 — non-critical display
        pass
