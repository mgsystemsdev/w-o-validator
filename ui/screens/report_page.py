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


@st.cache_data(ttl=60)
def _cached_report_move_in_log_rows(property_id: int) -> list[dict]:
    log_rows, _ = occupancy_service.get_move_in_tables_bundle(property_id)
    return log_rows


def _dataframe_move_in_log(rows: list[dict]) -> tuple:
    cols = ("Unit", "Move-in date", "Record updated")
    if not rows:
        return pd.DataFrame(columns=list(cols)), 0
    _df = dataframe_for_streamlit(rows)
    return (
        _df.rename(
            columns={
                "unit": "Unit",
                "move_in_date": "Move-in date",
                "record_updated_at": "Record updated",
            }
        ),
        len(rows),
    )


def _dataframe_moving_log_rows(rows: list[dict]) -> tuple:
    cols = ("Unit", "Moving date", "Logged at")
    if not rows:
        return pd.DataFrame(columns=list(cols)), 0
    _df = dataframe_for_streamlit(rows)
    return (
        _df.rename(
            columns={
                "unit": "Unit",
                "moving_date": "Moving date",
                "logged_at": "Logged at",
            }
        ),
        len(rows),
    )


def _render_move_in_dates_table(property_id: int) -> None:
    rows = _cached_report_move_in_log_rows(property_id)
    st.markdown("**Move-in dates (this property)**")
    st.caption(
        "Loaded into ``unit_occupancy_global`` (Resident Activity, Pending Movings, etc.). "
        "Sorted by unit code."
    )
    df, n = _dataframe_move_in_log(rows)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        height=min(420, 28 + 24 * max(n, 6)),
    )


def _render_moving_log_entries_table(property_id: int) -> None:
    bundle = _cached_property_moving_log_bundle(property_id)
    rows = bundle["rows"]
    st.markdown("**Moving log (this property)**")
    st.caption(
        "Rows in ``unit_movings`` whose unit matches this property’s **Units** roster. Newest first."
    )
    if bundle["unit_count"] == 0:
        st.caption("No unit master for this property — import **Units** first; then imports can match.")
    elif bundle["norm_key_count"] == 0:
        st.caption("Roster has no usable unit codes in ``unit_code_raw`` / ``unit_code_norm``.")
    df, n = _dataframe_moving_log_rows(rows)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        height=min(420, 28 + 24 * max(n, 6)),
    )


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
                "Spreadsheet with **unit** + **move / date** columns → global ``unit_movings``. "
                "Does not set WO move-in dates; use **Pending Movings** for that."
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
                st.caption("Title/KPI lines in the file are skipped.")
                row_results = ml_res.get("row_results") or []
                if row_results:
                    with st.container(border=True):
                        st.markdown("**Last import — row outcomes**")
                        st.caption("Per-row result from the file you loaded.")
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
            _render_move_in_dates_table(property_id)

        with st.container(border=True):
            _render_moving_log_entries_table(property_id)

    with tab_pending:
        with st.container(border=True):
            st.markdown("**PENDING MOVINGS**")
            st.caption(
                "**Pending Move Ins** / similar export: **Unit** + **Move-In Date** "
                "(``.csv`` / ``.xls`` / ``.xlsx``). Updates occupancy for WO classification and "
                "appends ``unit_movings``."
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
                st.success(
                    f"**Processed:** {pm_res['processed']} · **Matched:** {pm_res['matched']} · "
                    f"**Unresolved:** {pm_res['unresolved']} · **Logged to movings:** {pm_res['logged']}"
                )
                if session_only:
                    st.caption(
                        "Import counts above are from this session only (DB snapshot row missing). "
                        "Data is still saved; run ``005_property_upload_snapshot.sql`` to persist "
                        "this banner after logout."
                    )
                if pm_res.get("processed", 0) > 0 and pm_res.get("matched", 0) == 0:
                    st.warning(
                        "**No units matched** this property’s unit master. "
                        "Import **Units.csv** on the **Units** page (codes like `4-27-0211` must match "
                        "**Location** / `unit_code` after normalization), then run this import again."
                    )

        with st.container(border=True):
            _render_move_in_dates_table(property_id)

        with st.container(border=True):
            _render_moving_log_entries_table(property_id)
