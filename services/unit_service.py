"""Unit service — unit master import and listing for wo_standalone.

Stripped to only the functions needed by the WO app. All turnover,
risk, scope, and task service imports from the legacy version are removed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from db.repository import property_repository, unit_repository
from services import property_service

if TYPE_CHECKING:
    import pandas as pd


def list_unit_master_import_units(property_id: int) -> list[dict]:
    """Return importer-written unit fields for the Unit Master Import table."""
    return unit_repository.list_unit_master_import_units(property_id)


def import_unit_master(
    property_id: int,
    df: "pd.DataFrame",
    strict: bool,
) -> dict:
    """Process Unit Master CSV rows: create units/phases/buildings.

    Expected CSV columns:
      unit_code  (required)
      phase      (optional — creates phase if absent)
      building   (optional — creates building if absent)
      Floor Plan / floor_plan  (optional)
      Gross Sq. Ft. / gross_sq_ft  (optional)
      has_carpet, has_wd  (optional booleans)

    Returns {"created": int, "skipped": int, "errors": list[str]}.
    """
    created = 0
    skipped = 0
    errors: list[str] = []

    phase_cache: dict[str, dict] = {}
    for p in property_repository.get_phases(property_id):
        phase_cache[p["phase_code"]] = p

    building_cache: dict[tuple[int, str], dict] = {}
    for phase in phase_cache.values():
        for b in property_repository.get_buildings(phase["phase_id"]):
            building_cache[(phase["phase_id"], b["building_code"])] = b

    for idx, row in df.iterrows():
        raw = str(row.get("unit_code", "")).strip()
        if not raw:
            errors.append(f"Row {idx + 2}: empty unit_code, skipped.")
            continue

        norm = raw.strip().upper()
        existing = unit_repository.get_by_code_norm(property_id, norm)

        if existing:
            skipped += 1
            continue

        if strict:
            errors.append(f"Row {idx + 2}: unit '{norm}' not found (strict mode).")
            continue

        phase_id: int | None = None
        phase_val = str(row.get("phase", "")).strip() if "phase" in df.columns else ""
        if phase_val:
            if phase_val in phase_cache:
                phase_id = phase_cache[phase_val]["phase_id"]
            else:
                new_phase = property_service.create_phase(property_id, phase_val)
                phase_cache[phase_val] = new_phase
                phase_id = new_phase["phase_id"]

        building_id: int | None = None
        bldg_val = str(row.get("building", "")).strip() if "building" in df.columns else ""
        if bldg_val:
            if phase_id is None:
                default_code = "_DEFAULT"
                if default_code not in phase_cache:
                    default_phase = property_service.create_phase(
                        property_id, default_code, name="Default Phase",
                    )
                    phase_cache[default_code] = default_phase
                phase_id = phase_cache[default_code]["phase_id"]

            cache_key = (phase_id, bldg_val)
            if cache_key in building_cache:
                building_id = building_cache[cache_key]["building_id"]
            else:
                new_bldg = property_service.create_building(
                    property_id, phase_id, bldg_val,
                )
                building_cache[cache_key] = new_bldg
                building_id = new_bldg["building_id"]

        floor_plan = _row_str(row, df, "Floor Plan", "floor_plan")
        gross_sq_ft = _row_int(row, df, "Gross Sq. Ft.", "gross_sq_ft")

        has_carpet = (
            str(row.get("has_carpet", "")).strip().lower() in ("true", "1", "yes")
            if "has_carpet" in df.columns
            else False
        )
        has_wd = (
            str(row.get("has_wd", "")).strip().lower() in ("true", "1", "yes")
            if "has_wd" in df.columns
            else False
        )

        try:
            property_service.create_unit(
                property_id=property_id,
                unit_code_raw=raw,
                unit_code_norm=norm,
                unit_identity_key=norm,
                phase_id=phase_id,
                building_id=building_id,
                floor_plan=floor_plan,
                gross_sq_ft=gross_sq_ft,
                has_carpet=has_carpet,
                has_wd_expected=has_wd,
            )
            created += 1
        except Exception as exc:
            errors.append(f"Row {idx + 2} ({norm}): {exc}")

    return {"created": created, "skipped": skipped, "errors": errors}


def _row_str(row, df: "pd.DataFrame", *col_names: str) -> str | None:
    for col in col_names:
        if col in df.columns:
            val = str(row.get(col, "")).strip()
            if val:
                return val
    return None


def _row_int(row, df: "pd.DataFrame", *col_names: str) -> int | None:
    for col in col_names:
        if col in df.columns:
            val = str(row.get(col, "")).strip().replace(",", "")
            if val:
                try:
                    return int(float(val))
                except (ValueError, TypeError):
                    pass
    return None
