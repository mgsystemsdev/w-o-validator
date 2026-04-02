"""Units screen: unit master import (WO prerequisite)."""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from services import property_service, unit_service

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


def render_units() -> None:
    st.title("Units")

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
            st.dataframe(
                dataframe_for_streamlit(imported_units),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("No units imported yet.")


@st.cache_data(ttl=60)
def _property_name(property_id: int) -> str:
    for p in property_service.get_all_properties():
        if p["property_id"] == property_id:
            return p["name"]
    return f"Property {property_id}"
