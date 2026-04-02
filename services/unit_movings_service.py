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

from db.repository import unit_movings_repository
from domain.unit_identity import normalize_unit_code
from services.pandas_dates import parse_one_date_cell

logger = logging.getLogger(__name__)


def normalize_moving_unit_key(raw: str | None) -> str:
    """Same identity rules as the rest of DMRB (prefix, spacing, case)."""
    if raw is None:
        return ""
    return normalize_unit_code(str(raw))


def import_historical_movings(file_content: bytes, filename: str) -> dict:
    """Import historical movings from an uploaded spreadsheet.

    Expected columns: ``unit_number`` (or ``unit``, ``unit_code``), ``moving_date``
    (or ``move_in_date``). Accepts ``.csv``, ``.xls``, ``.xlsx``.

    Returns {"inserted": int, "skipped": int}.
    """
    ext = filename.rsplit(".", 1)[-1].lower()
    try:
        if ext in ("xls", "xlsx"):
            df = pd.read_excel(io.BytesIO(file_content))
        else:
            df = pd.read_csv(io.BytesIO(file_content))
    except Exception as exc:
        raise ValueError(f"Unable to parse file: {exc}") from exc

    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    if "unit_number" not in df.columns:
        for alt in ("unit", "unit_code"):
            if alt in df.columns:
                df = df.rename(columns={alt: "unit_number"})
                break
    if "moving_date" not in df.columns and "move_in_date" in df.columns:
        df = df.rename(columns={"move_in_date": "moving_date"})
    if "unit_number" not in df.columns or "moving_date" not in df.columns:
        raise ValueError(
            "File must include unit and date columns "
            "(e.g. unit_number + moving_date). "
            f"Found: {', '.join(df.columns.tolist())}"
        )

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

        moving_date = parse_one_date_cell(raw_date)
        if moving_date is None:
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
