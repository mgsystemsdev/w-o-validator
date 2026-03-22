"""Occupancy service — load and manage move-in dates in unit_occupancy_global.

Core design: the ingest() function is source-agnostic. It accepts plain
[{"unit_number": str, "move_in_date": date}] records from any source.

Adding a new data source only requires:
  1. Transform source data into that record shape.
  2. Call occupancy_service.ingest(property_id, records).

No changes needed in the repository, validator, or output layer.
"""

from __future__ import annotations

import logging
from datetime import date

import io

import pandas as pd

from db.repository import occupancy_repository, unit_repository, unit_movings_repository
from domain.unit_identity import normalize_unit_code
from services.parsers import resident_activity_parser

logger = logging.getLogger(__name__)


def ingest(property_id: int, records: list[dict]) -> dict:
    """Core ingestion entry point — source-agnostic.

    Args:
        property_id: The property to scope all writes to.
        records: List of dicts with keys "unit_number" (str) and
                 "move_in_date" (date). No other fields required.

    Returns:
        {"processed": int, "matched": int, "unresolved": int}
    """
    processed = len(records)
    matched = 0
    unresolved = 0

    for rec in records:
        raw_unit = rec.get("unit_number", "")
        move_in: date | None = rec.get("move_in_date")

        if not raw_unit:
            unresolved += 1
            continue

        unit_norm = normalize_unit_code(raw_unit)
        unit_row = unit_repository.get_by_code_norm(property_id, unit_norm)

        if unit_row is None:
            logger.debug(
                "occupancy_service.ingest: unit '%s' (norm: '%s') not found for property %d",
                raw_unit, unit_norm, property_id,
            )
            unresolved += 1
            continue

        occupancy_repository.upsert(property_id, unit_row["unit_id"], move_in)
        matched += 1

    logger.info(
        "occupancy_service.ingest: property=%d processed=%d matched=%d unresolved=%d",
        property_id, processed, matched, unresolved,
    )
    return {"processed": processed, "matched": matched, "unresolved": unresolved}


def ingest_resident_activity(
    property_id: int,
    file_content: bytes,
    filename: str = "resident_activity.xls",
) -> dict:
    """Parse a Resident Activity file and ingest move-in dates.

    Handles de-duplication: prefers "Current resident" rows; when multiple
    current residents exist for the same unit, uses the latest move_in_date.

    Returns:
        {"processed": int, "matched": int, "unresolved": int}
    """
    raw_records = resident_activity_parser.parse(file_content, filename)

    by_unit: dict[str, dict] = {}
    for rec in raw_records:
        key = rec["unit_number"]
        status = rec.get("resident_status", "")
        existing = by_unit.get(key)

        if existing is None:
            by_unit[key] = rec
            continue

        existing_status = existing.get("resident_status", "")
        is_current = status == "Current resident"
        existing_is_current = existing_status == "Current resident"

        if is_current and not existing_is_current:
            by_unit[key] = rec
        elif is_current == existing_is_current:
            if rec["move_in_date"] > existing["move_in_date"]:
                by_unit[key] = rec

    clean_records = [
        {"unit_number": r["unit_number"], "move_in_date": r["move_in_date"]}
        for r in by_unit.values()
    ]

    logger.info(
        "occupancy_service.ingest_resident_activity: %d raw records → %d after de-duplication",
        len(raw_records), len(clean_records),
    )
    return ingest(property_id, clean_records)


def ingest_pending_movings(
    property_id: int,
    file_content: bytes,
    filename: str,
) -> dict:
    """Parse a Pending Movings file and update unit_occupancy_global + unit_movings.

    Expected columns: ``unit_number``, ``move_in_date`` (date-parseable string).
    Both CSV and Excel (.xlsx) are accepted.

    Each row:
      1. Upserts ``unit_occupancy_global`` via :func:`ingest` so the WO validator
         immediately sees the fresh move-in date.
      2. Appends to ``unit_movings`` as a historical log entry
         (ON CONFLICT DO NOTHING — duplicates are silently skipped).

    Returns:
        {\"processed\": int, \"matched\": int, \"unresolved\": int, \"logged\": int}
    """
    ext = filename.rsplit(".", 1)[-1].lower()
    try:
        if ext in ("xls", "xlsx"):
            df = pd.read_excel(io.BytesIO(file_content), dtype=str)
        else:
            df = pd.read_csv(io.BytesIO(file_content), dtype=str)
    except Exception as exc:
        raise ValueError(f"Could not parse file '{filename}': {exc}") from exc

    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    # Accept move_in_date or moving_date as the date column
    if "move_in_date" not in df.columns and "moving_date" in df.columns:
        df = df.rename(columns={"moving_date": "move_in_date"})

    missing = [c for c in ("unit_number", "move_in_date") if c not in df.columns]
    if missing:
        raise ValueError(
            f"File is missing required columns: {', '.join(missing)}. "
            f"Found: {', '.join(df.columns.tolist())}"
        )

    df = df[["unit_number", "move_in_date"]].dropna(subset=["unit_number"])
    df["move_in_date"] = pd.to_datetime(df["move_in_date"], errors="coerce").dt.date

    records: list[dict] = []
    for _, row in df.iterrows():
        unit_number = str(row["unit_number"]).strip()
        move_in: date | None = row["move_in_date"] if pd.notna(row["move_in_date"]) else None
        if unit_number:
            records.append({"unit_number": unit_number, "move_in_date": move_in})

    if not records:
        raise ValueError("No valid rows found in the uploaded file.")

    # 1. Update unit_occupancy_global (drives WO classification)
    result = ingest(property_id, records)

    # 2. Append to unit_movings historical log
    logged = 0
    for rec in records:
        if rec["move_in_date"] is None:
            continue
        try:
            unit_movings_repository.insert_moving(
                rec["unit_number"], rec["move_in_date"]
            )
            logged += 1
        except Exception:
            pass  # ON CONFLICT DO NOTHING handles duplicates; other errors are non-fatal

    logger.info(
        "occupancy_service.ingest_pending_movings: property=%d processed=%d "
        "matched=%d unresolved=%d logged=%d",
        property_id, result["processed"], result["matched"], result["unresolved"], logged,
    )
    return {**result, "logged": logged}


def get_all_occupancy(property_id: int) -> dict[int, date | None]:
    """Return {unit_id: move_in_date} for all loaded units in this property."""
    return occupancy_repository.get_all_by_property(property_id)


def get_occupancy_status(property_id: int) -> dict:
    """Return summary info for the UI status display.

    Returns:
        {"unit_count": int, "last_updated": date | None}
    """
    return {
        "unit_count": occupancy_repository.count_by_property(property_id),
        "last_updated": occupancy_repository.get_last_updated(property_id),
    }
