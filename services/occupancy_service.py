"""Occupancy service — load and manage move-in dates in unit_occupancy_global.

Core design: the ingest() function is source-agnostic. It accepts plain
[{"unit_number": str, "move_in_date": date}] records from any source.

Adding a new data source only requires:
  1. Transform source data into that record shape.
  2. Call occupancy_service.ingest(property_id, records).

No changes needed in the repository, validator, or output layer.
"""

from __future__ import annotations

import csv
import logging
from datetime import date

import io

import pandas as pd

from db.repository import (
    occupancy_repository,
    property_upload_snapshot_repository,
    unit_movings_repository,
    unit_repository,
)
from domain.unit_identity import normalize_unit_code
from services.pandas_dates import coerce_datetime_series
from services.parsers import resident_activity_parser
from services.unit_movings_service import (
    _dataframe_from_detected_columns,
    _detect_unit_and_date_columns,
    _normalize_header_label,
)

logger = logging.getLogger(__name__)


def _pending_normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [_normalize_header_label(c) for c in df.columns]
    if "unit_number" not in df.columns:
        for alt in ("unit", "unit_code", "building_unit", "bldg_unit"):
            if alt in df.columns:
                df = df.rename(columns={alt: "unit_number"})
                break
    if "move_in_date" not in df.columns and "moving_date" in df.columns:
        df = df.rename(columns={"moving_date": "move_in_date"})
    return df


def _pending_csv_ragged_to_dataframe(file_content: bytes) -> pd.DataFrame:
    """Build a grid from ragged exports (title lines + wide data rows) without dropping rows."""
    text = None
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = file_content.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError("Could not decode CSV (tried UTF-8 and Latin-1).")

    rows: list[list[str]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = next(csv.reader([line]))
        except csv.Error:
            continue
        rows.append([str(c).strip() for c in row])

    if not rows:
        raise ValueError("CSV contained no readable rows.")

    max_w = max(len(r) for r in rows)
    padded = [r + [""] * (max_w - len(r)) for r in rows]
    return pd.DataFrame(padded, dtype=str)


def _read_pending_movings_csv(file_content: bytes) -> pd.DataFrame:
    """Read Pending Movings CSV when exports have title rows or uneven lines (PMS exports)."""
    encodings = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
    seps = (",", ";", "\t")

    for encoding in encodings:
        for sep in seps:
            try:
                df = pd.read_csv(
                    io.BytesIO(file_content),
                    dtype=str,
                    sep=sep,
                    encoding=encoding,
                    engine="python",
                    on_bad_lines="skip",
                )
                if df.shape[1] < 2:
                    continue
                df = _pending_normalize_columns(df)
                if "unit_number" in df.columns and "move_in_date" in df.columns:
                    return df
            except Exception:
                continue

    for encoding in encodings:
        for sep in seps:
            try:
                raw = pd.read_csv(
                    io.BytesIO(file_content),
                    header=None,
                    dtype=str,
                    sep=sep,
                    encoding=encoding,
                    engine="python",
                    on_bad_lines="skip",
                )
                if raw.shape[1] < 2:
                    continue
                det = _detect_unit_and_date_columns(raw)
                if det is None:
                    continue
                hr, uc, dc = det
                out = _dataframe_from_detected_columns(raw, hr, uc, dc).rename(
                    columns={"moving_date": "move_in_date"}
                )
                logger.info(
                    "occupancy_service._read_pending_movings_csv: header row %s, "
                    "unit col %s, date col %s, sep=%r encoding=%s",
                    hr,
                    uc,
                    dc,
                    sep,
                    encoding,
                )
                return out
            except Exception:
                continue

    try:
        raw = _pending_csv_ragged_to_dataframe(file_content)
        if raw.shape[1] >= 2:
            det = _detect_unit_and_date_columns(raw)
            if det is not None:
                hr, uc, dc = det
                out = _dataframe_from_detected_columns(raw, hr, uc, dc).rename(
                    columns={"moving_date": "move_in_date"}
                )
                logger.info(
                    "occupancy_service._read_pending_movings_csv: ragged parse, "
                    "header row %s, unit col %s, date col %s",
                    hr,
                    uc,
                    dc,
                )
                return out
    except ValueError:
        raise
    except Exception:
        pass

    raise ValueError(
        "Could not parse this CSV. Typical fixes: export again as comma-separated UTF-8, "
        "or remove title rows above the column headers so the first table row names "
        "the unit and move-in date columns (e.g. Unit / Move-In Date)."
    )


def _pending_excel_engine(filename: str) -> str | None:
    """Use xlrd for legacy ``.xls`` (same as Resident Activity / moving log readers)."""
    return "xlrd" if filename.lower().endswith(".xls") else None


def _read_pending_movings_dataframe(file_content: bytes, filename: str) -> pd.DataFrame:
    """Load Pending Move Ins / pending movings spreadsheets and CSV.

    Excel exports often have title rows (property name, as-of date) above the real
    header. When row 0 is not ``Unit`` + ``Move-In Date``, we scan like the moving
    log import (``_detect_unit_and_date_columns``).
    """
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext in ("xls", "xlsx"):
        engine = _pending_excel_engine(filename)
        buf = io.BytesIO(file_content)
        df_try = pd.read_excel(buf, dtype=str, engine=engine)
        df_try.columns = [_normalize_header_label(c) for c in df_try.columns]
        broken = all(
            _normalize_header_label(c).startswith("unnamed") or not str(c).strip()
            for c in df_try.columns
        )
        if not broken:
            df_norm = _pending_normalize_columns(df_try)
            if "unit_number" in df_norm.columns and "move_in_date" in df_norm.columns:
                return df_norm

        raw = pd.read_excel(
            io.BytesIO(file_content), header=None, dtype=str, engine=engine
        )
        det = _detect_unit_and_date_columns(raw)
        if det is None:
            raise ValueError(
                "Could not find a header row with unit and move-in date columns. "
                "Use the OneSite **Pending Move Ins** / pending movings export "
                "(columns like Unit and Move-In Date), or CSV with those headers."
            )
        hr, uc, dc = det
        logger.info(
            "occupancy_service._read_pending_movings_dataframe: excel header row %s, "
            "unit col %s, date col %s",
            hr,
            uc,
            dc,
        )
        return _dataframe_from_detected_columns(raw, hr, uc, dc).rename(
            columns={"moving_date": "move_in_date"}
        )

    return _read_pending_movings_csv(file_content)


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
    result = ingest(property_id, clean_records)
    try:
        property_upload_snapshot_repository.upsert(
            property_id,
            property_upload_snapshot_repository.KIND_RESIDENT_ACTIVITY_INGEST,
            {**result, "source_filename": filename},
        )
    except Exception:
        logger.exception("occupancy_service: could not persist resident activity snapshot")
    return result


def ingest_pending_movings(
    property_id: int,
    file_content: bytes,
    filename: str,
) -> dict:
    """Parse a Pending Movings file and update unit_occupancy_global + unit_movings.

    Expected columns: ``unit_number``, ``move_in_date`` (date-parseable string).
    CSV (``.csv``) and Excel (``.xls`` / ``.xlsx``) are accepted.

    Each row:
      1. Upserts ``unit_occupancy_global`` via :func:`ingest` so the WO validator
         immediately sees the fresh move-in date.
      2. Appends to ``unit_movings`` as a historical log entry
         (ON CONFLICT DO NOTHING — duplicates are silently skipped).

    Returns:
        {\"processed\": int, \"matched\": int, \"unresolved\": int, \"logged\": int}
    """
    try:
        df = _read_pending_movings_dataframe(file_content, filename)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Could not parse file '{filename}': {exc}") from exc

    df = _pending_normalize_columns(df)

    missing = [c for c in ("unit_number", "move_in_date") if c not in df.columns]
    if missing:
        raise ValueError(
            f"File is missing required columns: {', '.join(missing)}. "
            f"Found: {', '.join(df.columns.tolist())}"
        )

    df = df[["unit_number", "move_in_date"]].dropna(subset=["unit_number"])
    df["move_in_date"] = coerce_datetime_series(df["move_in_date"]).dt.date

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
    out = {**result, "logged": logged}
    try:
        property_upload_snapshot_repository.upsert(
            property_id,
            property_upload_snapshot_repository.KIND_PENDING_MOVINGS_IMPORT,
            {**out, "source_filename": filename},
        )
    except Exception:
        logger.exception("occupancy_service: could not persist pending movings snapshot")
    return out


def get_all_occupancy(property_id: int) -> dict[int, date | None]:
    """Return {unit_id: move_in_date} for all loaded units in this property."""
    return occupancy_repository.get_all_by_property(property_id)


def get_occupancy_status(property_id: int) -> dict:
    """Return summary info for the UI status display.

    Returns:
        {"unit_count": int, "last_updated": date | None, "last_updated_at": datetime | None}
    """

    return {
        "unit_count": occupancy_repository.count_by_property(property_id),
        "last_updated": occupancy_repository.get_last_updated(property_id),
        "last_updated_at": occupancy_repository.get_last_updated_at(property_id),
    }


def get_move_in_tables_bundle(property_id: int) -> tuple[list[dict], list[dict]]:
    """Data for Move-In Data tab tables: loaded occupancy + units overlay.

    Reads ``unit_occupancy_global`` (same store as Resident Activity upload), not
    ``unit_movings``.

    Returns:
        (log_rows, units_with_move_in) — log_rows have unit, move_in_date,
        record_updated_at; second list matches **Imported Units** columns plus move_in_date.
    """
    raw_rows = occupancy_repository.list_move_in_rows_for_property(property_id)
    log_rows = [
        {
            "unit": r["unit"],
            "move_in_date": r["move_in_date"],
            "record_updated_at": r["record_updated_at"],
        }
        for r in raw_rows
    ]

    by_unit_norm: dict[str, date | None] = {}
    for r in raw_rows:
        nk = normalize_unit_code(str(r["unit"] or ""))
        if nk:
            by_unit_norm[nk] = r["move_in_date"]

    import_rows = unit_repository.list_unit_master_import_units(property_id)
    units_out: list[dict] = []
    for row in import_rows:
        nk = normalize_unit_code(str(row.get("unit_code_raw") or "").strip())
        units_out.append(
            {
                **row,
                "move_in_date": by_unit_norm.get(nk),
            }
        )

    return log_rows, units_out
