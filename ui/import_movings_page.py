"""Import screen: unit master (WO prerequisite) + historical unit movings."""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from services import property_service, unit_service
from services.occupancy_service import ingest_pending_movings
from services.unit_movings_service import import_historical_movings


_UNIT_CODE_ALIASES = {"Unit", "unit", "Unit Number", "unit_number", "UnitCode", "Unit Code"}


def _read_csv_flexible(raw_bytes: bytes) -> pd.DataFrame:
    try:
        return pd.read_csv(io.BytesIO(raw_bytes), dtype=str)
    except Exception:
        pass
    lines = raw_bytes.decode("utf-8", errors="replace").splitlines()
    header_idx = 0
    for i, line in enumerate(lines):
        if line.count(",") >= 1:
            header_idx = i
            break
    return pd.read_csv(io.BytesIO(raw_bytes), skiprows=header_idx, dtype=str)


def _normalize_unit_columns(df: pd.DataFrame) -> pd.DataFrame:
    for alias in _UNIT_CODE_ALIASES:
        if alias in df.columns and "unit_code" not in df.columns:
            return df.rename(columns={alias: "unit_code"})
    return df


def _run_unit_master_import(property_id: int) -> None:
    uploaded = st.session_state.get("wo_um_file")
    if uploaded is None:
        st.warning("Upload a CSV file first.")
        return
    try:
        raw_bytes = uploaded.getvalue()
        df = _normalize_unit_columns(_read_csv_flexible(raw_bytes))
    except Exception as exc:
        st.error(f"Failed to parse CSV: {exc}")
        return
    if "unit_code" not in df.columns:
        st.error(
            "CSV must contain a `unit_code` column. "
            f"Found columns: {', '.join(df.columns.tolist())}"
        )
        return
    strict = st.session_state.get("wo_um_strict", False)
    result = unit_service.import_unit_master(property_id, df, strict)
    created = result["created"]
    skipped = result["skipped"]
    errors = result["errors"]
    parts = [f"**Created:** {created}", f"**Skipped (existing):** {skipped}"]
    if errors:
        parts.append(f"**Errors:** {len(errors)}")
    st.success(" · ".join(parts))
    for err in errors:
        st.warning(err)
    if created:
        st.cache_data.clear()
        st.rerun()


@st.cache_data(ttl=60)
def _cached_list_unit_master_import_units(property_id: int) -> list[dict]:
    return unit_service.list_unit_master_import_units(property_id)


def render_import_movings() -> None:
    st.title("Import movings")

    property_id = st.session_state.get("property_id")
    if property_id is None:
        st.info("Select or create a property in the sidebar.")
        return

    name = _property_name(property_id)
    st.caption(f"Active property: **{name}**")

    with st.container(border=True):
        st.markdown("**UNIT MASTER IMPORT**")
        st.caption(
            "Load **Units.csv** so Service Request **Location** values resolve to units. "
            "Required column: `unit_code`. Optional: `phase`, `building`, `Floor Plan`, `Gross Sq. Ft.`"
        )
        uc1, uc2, uc3 = st.columns([1, 2, 1])
        with uc1:
            st.checkbox(
                "Strict mode",
                value=False,
                key="wo_um_strict",
                help="Skip units not already in the DB — no new creates.",
            )
        with uc2:
            st.file_uploader("Units.csv", type=["csv"], key="wo_um_file")
        with uc3:
            st.write("")
            if st.button("Run Unit Master Import", key="wo_um_run", width="stretch"):
                _run_unit_master_import(property_id)

    with st.container(border=True):
        st.markdown("**IMPORTED UNITS**")
        imported_units = _cached_list_unit_master_import_units(property_id)
        if imported_units:
            st.dataframe(pd.DataFrame(imported_units), use_container_width=True, hide_index=True)
        else:
            st.caption("No units imported yet.")

    with st.container(border=True):
        st.markdown("**PENDING MOVINGS — DAILY UPDATE**")
        st.caption(
            "Upload today's pending move-in list (.csv or .xlsx). "
            "Required columns: **unit_number**, **move_in_date**. "
            "Each row updates **unit_occupancy_global** so the WO Validator "
            "immediately uses the fresh date for classification. "
            "Rows are also appended to the **unit_movings** historical log."
        )
        pm_file = st.file_uploader(
            "Pending Movings file",
            type=["csv", "xlsx"],
            key="wo_pending_movings_file",
        )
        if st.button("Upload Pending Movings", key="wo_pending_movings_run", disabled=pm_file is None):
            if pm_file is not None:
                try:
                    result = ingest_pending_movings(
                        property_id, pm_file.read(), pm_file.name
                    )
                    st.success(
                        f"**Processed:** {result['processed']} · "
                        f"**Updated:** {result['matched']} · "
                        f"**Unresolved:** {result['unresolved']} · "
                        f"**Logged:** {result['logged']}"
                    )
                    if result["unresolved"]:
                        st.warning(
                            f"{result['unresolved']} unit(s) not found in the unit master. "
                            "Run a Unit Master Import first if units are missing."
                        )
                    st.cache_data.clear()
                except ValueError as exc:
                    st.error(str(exc))

    with st.container(border=True):
        st.markdown("**HISTORICAL UNIT MOVINGS**")
        st.caption(
            "Spreadsheet columns: **unit_number**, **moving_date** (.csv or .xlsx). "
            "Rows append to **unit_movings** (global by normalized unit key). "
            "Historical movings are stored but not yet used in classification (parity mode)."
        )
        mov_file = st.file_uploader(
            "Movings file",
            type=["csv", "xlsx"],
            key="wo_movings_file",
        )
        if st.button("Import movings", key="wo_movings_run", disabled=mov_file is None):
            if mov_file is None:
                return
            try:
                result = import_historical_movings(mov_file.read(), mov_file.name)
                st.success(
                    f"**Inserted:** {result['inserted']} · **Skipped:** {result['skipped']}"
                )
            except ValueError as exc:
                st.error(str(exc))


@st.cache_data(ttl=60)
def _property_name(property_id: int) -> str:
    for p in property_service.get_all_properties():
        if p["property_id"] == property_id:
            return p["name"]
    return f"Property {property_id}"
