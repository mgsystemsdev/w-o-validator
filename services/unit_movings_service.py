"""Unit Movings service — historical import and lookup for Work Order Validator.

Responsibilities:
  - Bulk-import historical movings from a spreadsheet.
  - Provide a lookup of latest moving date per unit.
"""

from __future__ import annotations

import io
import logging
from datetime import date

import pandas as pd

from db.repository import unit_movings_repository, unit_repository
from domain.unit_identity import normalize_unit_code

logger = logging.getLogger(__name__)


def normalize_moving_unit_key(raw: str | None) -> str:
    """Same identity rules as the rest of DMRB (prefix, spacing, case)."""
    if raw is None:
        return ""
    return normalize_unit_code(str(raw))


def import_historical_movings(file_content: bytes, filename: str) -> dict:
    """Import historical movings from an uploaded spreadsheet.

    Expected columns: unit_number, moving_date (.csv or .xlsx).
    Returns {"inserted": int, "skipped": int}.
    """
    try:
        if filename.endswith(".xlsx"):
            df = pd.read_excel(io.BytesIO(file_content))
        else:
            df = pd.read_csv(io.BytesIO(file_content))
    except Exception as exc:
        raise ValueError(f"Unable to parse file: {exc}") from exc

    inserted = 0
    skipped = 0

    for _, row in df.iterrows():
        unit_number = normalize_moving_unit_key(row.get("unit_number", ""))
        if not unit_number:
            skipped += 1
            continue

        raw_date = row.get("moving_date")
        if pd.isna(raw_date):
            skipped += 1
            continue

        try:
            if isinstance(raw_date, str):
                moving_date = pd.to_datetime(raw_date).date()
            elif isinstance(raw_date, pd.Timestamp):
                moving_date = raw_date.date()
            elif isinstance(raw_date, date):
                moving_date = raw_date
            else:
                moving_date = pd.to_datetime(raw_date).date()
        except Exception:
            skipped += 1
            continue

        result = unit_movings_repository.insert_moving(unit_number, moving_date)
        if result is not None:
            inserted += 1
        else:
            skipped += 1

    return {"inserted": inserted, "skipped": skipped}


def get_latest_movings_lookup() -> dict[str, date]:
    """Return {normalized_unit_key: latest moving_date} for all units."""
    raw = unit_movings_repository.get_latest_movings_by_unit()
    merged: dict[str, date] = {}
    for stored_key, moving_date in raw.items():
        nk = normalize_moving_unit_key(stored_key)
        if not nk:
            continue
        if nk not in merged or moving_date > merged[nk]:
            merged[nk] = moving_date
    return merged


def _norm_keys_and_candidates(units: list[dict]) -> tuple[set[str], list[str]]:
    """Build normalized identity keys and DB string candidates for property units."""
    norm_keys: set[str] = set()
    candidates: set[str] = set()
    for u in units:
        for key in ("unit_code_norm", "unit_code_raw"):
            val = u.get(key)
            if not val:
                continue
            s = str(val).strip()
            if not s:
                continue
            candidates.add(s)
            nk = normalize_unit_code(s)
            if nk:
                norm_keys.add(nk)
                candidates.add(nk)
    return norm_keys, list(candidates)


def get_property_moving_log_bundle(property_id: int) -> tuple[list[dict], list[dict]]:
    """Return (moving log rows, imported-units-shaped rows with moving dates) for a property.

    ``unit_movings`` is global and keyed by free-form ``unit_number`` strings; rows are
    included when :func:`normalize_unit_code` matches an active unit on this property.

    First list: ``unit``, ``moving_date``, ``logged_at`` (chronological, newest first).
    Second list: same fields as ``list_unit_master_import_units`` plus ``latest_moving_date``
    and ``all_moving_dates`` (comma-separated, newest first).
    """
    # Include inactive units so matching aligns with **Imported Units** (all rows for property).
    units = unit_repository.get_by_property(property_id, active_only=False)
    if not units:
        return [], []

    norm_keys, candidates = _norm_keys_and_candidates(units)
    raw_movings = unit_movings_repository.list_movings_for_unit_numbers(candidates)
    movings = [
        m
        for m in raw_movings
        if normalize_unit_code(m["unit_number"]) in norm_keys
    ]
    movings.sort(key=lambda m: (m["moving_date"], m["unit_number"]), reverse=True)

    norm_to_display: dict[str, str] = {}
    for u in units:
        disp = (u.get("unit_code_raw") or u.get("unit_code_norm") or "").strip()
        for key in ("unit_code_raw", "unit_code_norm"):
            val = u.get(key)
            if not val:
                continue
            nk = normalize_unit_code(str(val).strip())
            if nk:
                norm_to_display[nk] = disp or str(val).strip()

    log_rows: list[dict] = []
    for m in movings:
        nk = normalize_unit_code(m["unit_number"])
        log_rows.append(
            {
                "unit": norm_to_display.get(nk, m["unit_number"]),
                "moving_date": m["moving_date"],
                "logged_at": m["created_at"],
            }
        )

    by_norm: dict[str, list[date]] = {}
    for m in movings:
        nk = normalize_unit_code(m["unit_number"])
        by_norm.setdefault(nk, []).append(m["moving_date"])

    import_rows = unit_repository.list_unit_master_import_units(property_id)
    units_out: list[dict] = []
    for row in import_rows:
        nk = normalize_unit_code(str(row.get("unit_code_raw") or "").strip())
        dates = sorted(by_norm.get(nk, []), reverse=True)
        units_out.append(
            {
                **row,
                "latest_moving_date": dates[0] if dates else None,
                "all_moving_dates": ", ".join(str(d) for d in dates) if dates else "",
            }
        )

    return log_rows, units_out
