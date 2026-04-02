"""Report screen: moving log import and pending movings ingest."""

from __future__ import annotations

import streamlit as st

from db.repository import property_upload_snapshot_repository
from domain.dates import format_us_datetime
from services import occupancy_service, unit_movings_service
from ui.dataframe_display import dataframe_for_streamlit


@st.cache_data(ttl=60)
def _cached_property_moving_log_bundle(property_id: int) -> dict:
    return unit_movings_service.get_property_moving_log_bundle(property_id)


def _load_moving_log_snapshot(property_id: int) -> dict | None:
    row = property_upload_snapshot_repository.get(
        property_id, property_upload_snapshot_repository.KIND_MOVING_LOG_IMPORT
    )
    return row


def _load_pending_snapshot(property_id: int) -> dict | None:
    return property_upload_snapshot_repository.get(
        property_id, property_upload_snapshot_repository.KIND_PENDING_MOVINGS_IMPORT
    )


def render_report_page() -> None:
    st.title("Report")

    property_id = st.session_state.get("property_id")
    if property_id is None:
        st.info("Select a property in the sidebar. If none are available, contact an administrator.")
        return

    # Pending movings feedback is stored in session when DB snapshot is unavailable (migration 005).
    prev_pid = st.session_state.get("_report_active_property_id")
    if prev_pid != property_id:
        st.session_state["_report_active_property_id"] = property_id
        st.session_state.pop("report_pending_last_result", None)
        st.session_state.pop("report_pending_error", None)
        st.session_state.pop("report_moving_log_error", None)

    tab_moving_log, tab_pending = st.tabs(["Moving Log", "Pending Movings"])

    with tab_moving_log:
        with st.container(border=True):
            st.markdown("**MOVING LOG**")
            st.caption(
                "Import historical moving dates into the global ``unit_movings`` log. "
                "Use a row with clear **unit** and **move / date** column headers (e.g. Unit + Move-In Date); "
                "title rows above the table are skipped automatically. "
                "Does not update move-in dates for WO classification — use **Pending Movings** or "
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
                        property_upload_snapshot_repository.upsert(
                            property_id,
                            property_upload_snapshot_repository.KIND_MOVING_LOG_IMPORT,
                            {**result, "source_filename": ml_file.name},
                        )
                        st.session_state.report_moving_log_error = None
                        _cached_property_moving_log_bundle.clear()
                    except Exception as exc:  # noqa: BLE001
                        st.session_state.report_moving_log_error = str(exc)
                st.rerun()

            ml_err = st.session_state.get("report_moving_log_error")
            if ml_err:
                st.error(f"Import failed: {ml_err}")

            ml_row = _load_moving_log_snapshot(property_id)
            if ml_row:
                ml_res = ml_row["payload"]
                ml_when = format_us_datetime(ml_row["updated_at"])
                fn = ml_res.get("source_filename") or "—"
                st.caption(f"Last moving log file processed: **{fn}** · **{ml_when}**")
                ao = ml_res.get("already_on_file", 0)
                ni = ml_res.get("not_imported", 0)
                st.success(
                    f"**New records added:** {ml_res['inserted']} · "
                    f"**Already on file (official date unchanged):** {ao} · "
                    f"**Not imported:** {ni}"
                )
                st.caption(
                    "Rows that are only spreadsheet titles or KPI lines (e.g. packet summaries) "
                    "are ignored and do not appear in the table below."
                )
                row_results = ml_res.get("row_results") or []
                if row_results:
                    with st.container(border=True):
                        st.markdown("**LAST IMPORT — ROW BY ROW**")
                        st.caption(
                            "Each data row from your file: unit, moving date, and outcome. "
                            "**Already registered** means the system already had this move-in date on file — "
                            "it is retained as the official moving date for that unit. "
                            "Use **Not imported** rows to fix source data and re-import if needed."
                        )
                        _pm = dataframe_for_streamlit(row_results)
                        if not _pm.empty:
                            _pm = _pm.rename(
                                columns={
                                    "unit": "Unit",
                                    "moving_date": "Moving date",
                                    "status": "Outcome",
                                }
                            )
                        st.dataframe(
                            _pm,
                            use_container_width=True,
                            hide_index=True,
                            height=min(420, 28 + 24 * len(row_results)),
                        )

        with st.container(border=True):
            st.markdown("**MOVING LOG ENTRIES**")
            st.caption(
                "Moving dates from ``unit_movings`` that **match units on this property** "
                "(**Units** page unit master). Imports are stored globally by unit label — "
                "if this list is empty after a successful import, those codes may not match "
                "any row in the unit master for the selected property. Newest first."
            )
            bundle = _cached_property_moving_log_bundle(property_id)
            log_table = bundle["rows"]
            if bundle["unit_count"] == 0:
                st.warning(
                    "This property has **no unit roster** (no rows on the **Units** / unit master "
                    "for this property). Moving log lines are matched to that roster — import units "
                    "first, then entries will appear here."
                )
            elif bundle["norm_key_count"] == 0:
                st.warning(
                    "Units exist but no usable **unit codes** were found (empty "
                    "``unit_code_raw`` / ``unit_code_norm``)."
                )
            elif log_table:
                _df = dataframe_for_streamlit(log_table)
                if not _df.empty:
                    _df = _df.rename(
                        columns={
                            "unit": "Unit",
                            "moving_date": "Moving date",
                            "logged_at": "Logged at",
                        }
                    )
                st.dataframe(
                    _df,
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.caption(
                    "No matching rows yet — load a moving log above (see **LAST IMPORT** for what "
                    "was read), use **Pending Movings**, or confirm imported **Units** include the "
                    "same unit codes as the file (after normalization)."
                )

    with tab_pending:
        with st.container(border=True):
            st.markdown("**PENDING MOVINGS**")
            st.caption(
                "OneSite **Pending Move Ins** / pending movings export: table with **Unit** and "
                "**Move-In Date** (``.csv`` / ``.xls`` / ``.xlsx``). Title rows above the header "
                "row are detected automatically for Excel. Same data can use column names "
                "**unit_number** and **move_in_date** (or **moving_date**). Updates "
                "**unit_occupancy_global** for this property and appends matching rows to "
                "**unit_movings**."
            )

            pm_file = st.file_uploader(
                "Pending movings export (.xls / .xlsx / .csv)",
                type=["xls", "xlsx", "csv"],
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
                        st.session_state.report_pending_error = None
                        st.session_state["report_pending_last_result"] = {
                            "property_id": property_id,
                            **result,
                            "source_filename": pm_file.name,
                        }
                        st.cache_data.clear()
                    except Exception as exc:  # noqa: BLE001
                        st.session_state.report_pending_error = str(exc)
                st.rerun()

            pm_err = st.session_state.get("report_pending_error")
            if pm_err:
                st.error(f"Import failed: {pm_err}")

            pm_row = _load_pending_snapshot(property_id)
            last_pm = st.session_state.get("report_pending_last_result")
            if last_pm and last_pm.get("property_id") != property_id:
                last_pm = None

            pm_res: dict | None = None
            pm_when: str | None = None
            pfn = "—"
            session_only = False

            # Prefer session result when present so a failed snapshot upsert does not show stale DB.
            if last_pm:
                pm_res = {
                    "processed": last_pm["processed"],
                    "matched": last_pm["matched"],
                    "unresolved": last_pm["unresolved"],
                    "logged": last_pm["logged"],
                }
                pfn = last_pm.get("source_filename") or "—"
                if pm_row:
                    pm_when = format_us_datetime(pm_row["updated_at"])
                    db_fn = (pm_row.get("payload") or {}).get("source_filename")
                    session_only = db_fn != pfn
                else:
                    session_only = True
            elif pm_row:
                pm_res = pm_row["payload"]
                pm_when = format_us_datetime(pm_row["updated_at"])
                pfn = pm_res.get("source_filename") or "—"

            if pm_res:
                if pm_when:
                    st.caption(
                        f"Last pending movings file processed: **{pfn}** · **{pm_when}**"
                    )
                else:
                    st.caption(f"Last pending movings file processed: **{pfn}**")
                if session_only:
                    st.info(
                        "Import completed, but no **snapshot row** was found in the database "
                        "(often the `property_upload_snapshot` table is missing). "
                        "Apply **`db/migrations/005_property_upload_snapshot.sql`** in the Supabase "
                        "SQL Editor so results persist across sessions; move-in updates from this run "
                        "may still have been saved."
                    )
                st.success(
                    f"**Processed:** {pm_res['processed']} · **Matched:** {pm_res['matched']} · "
                    f"**Unresolved:** {pm_res['unresolved']} · **Logged to movings:** {pm_res['logged']}"
                )
                if pm_res.get("processed", 0) > 0 and pm_res.get("matched", 0) == 0:
                    st.warning(
                        "**No units matched** this property’s unit master. "
                        "Import **Units.csv** on the **Units** page (codes like `4-27-0211` must match "
                        "**Location** / `unit_code` after normalization), then run this import again."
                    )
                st.info(
                    "Move-in preview tables under **Work Order Validator → Move-In Data** reflect "
                    "this property’s occupancy store (cache was refreshed on last run)."
                )
