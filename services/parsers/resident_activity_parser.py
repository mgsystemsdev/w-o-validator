"""Parser for the OneSite Resident Activity report.

Extracts move-in records from the MOVE-INS sections of the multi-section,
wide-format XLS/XLSX export.

Column positions are isolated in _RA_COLUMNS. Each MOVE-INS section runs
dynamic header detection to find actual column indices; fallback_index values
are used when the header row cannot be located (e.g., format change).
"""

from __future__ import annotations

import io
import logging
from datetime import date

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column mapping — update ONLY this dict if the PMS export format changes.
# ---------------------------------------------------------------------------
_RA_COLUMNS: dict[str, dict] = {
    "unit":     {"search": "Bldg/Unit",    "fallback_index": 13},
    "move_in":  {"search": "Move-in Date", "fallback_index": 65},
    "status":   {"search": "Status",       "fallback_index": 6},
}

_SECTION_KEYWORDS: frozenset[str] = frozenset({
    "MOVE-OUTS",
    "MOVE-INS",
    "NOTICES TO VACATE",
    "LEASES EXPIRING",
    "CANCELLED/DENIED",
    "RENEWALS SIGNED",
    "TRANSFERS",
    "PENDING",
})


def _detect_engine(filename: str) -> str:
    return "xlrd" if filename.lower().endswith(".xls") else "openpyxl"


def _cell_text(value) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def _build_col_map(df: pd.DataFrame, section_row: int) -> dict[str, int]:
    col_map: dict[str, int] = {}
    search_to_field = {v["search"]: k for k, v in _RA_COLUMNS.items()}

    scan_end = min(section_row + 6, len(df))
    for row_idx in range(section_row + 1, scan_end):
        row = df.iloc[row_idx]
        for col_idx, cell in enumerate(row):
            text = _cell_text(cell)
            if text in search_to_field:
                col_map[search_to_field[text]] = col_idx

    for field, cfg in _RA_COLUMNS.items():
        if field not in col_map:
            logger.warning(
                "resident_activity_parser: header '%s' not found in MOVE-INS section "
                "at row %d; using fallback index %d",
                cfg["search"], section_row, cfg["fallback_index"],
            )
            col_map[field] = cfg["fallback_index"]

    return col_map


def _parse_date(value) -> date | None:
    if pd.isna(value):
        return None
    try:
        return pd.to_datetime(value).date()
    except Exception:
        return None


def parse(file_content: bytes, filename: str = "resident_activity.xls") -> list[dict]:
    """Parse a Resident Activity XLS/XLSX file and return all MOVE-IN records.

    Returns a list of dicts:
        {"unit_number": str, "move_in_date": date, "resident_status": str}

    All records are returned (including duplicates per unit). De-duplication
    and current-resident preference is handled in occupancy_service.
    """
    engine = _detect_engine(filename)
    try:
        df = pd.read_excel(io.BytesIO(file_content), header=None, engine=engine)
    except Exception as exc:
        raise ValueError(f"Could not read Resident Activity file: {exc}") from exc

    section_rows: list[int] = []
    for i, row in df.iterrows():
        if _cell_text(row.iloc[0]) == "MOVE-INS":
            section_rows.append(i)

    if not section_rows:
        logger.warning("resident_activity_parser: no MOVE-INS sections found in file")
        return []

    records: list[dict] = []

    for sec_start in section_rows:
        col_map = _build_col_map(df, sec_start)
        data_start = sec_start + 4

        for row_idx in range(data_start, len(df)):
            row = df.iloc[row_idx]
            col0 = _cell_text(row.iloc[0])

            if col0 in _SECTION_KEYWORDS:
                break
            if "continued from previous page" in col0.lower():
                continue

            unit_val = _cell_text(row.iloc[col_map["unit"]])
            movein_val = row.iloc[col_map["move_in"]]
            status_val = _cell_text(row.iloc[col_map["status"]])

            if not unit_val or unit_val == "Bldg/Unit":
                continue

            move_in_date = _parse_date(movein_val)
            if move_in_date is None:
                continue

            records.append({
                "unit_number": unit_val,
                "move_in_date": move_in_date,
                "resident_status": status_val,
            })

    logger.info(
        "resident_activity_parser: extracted %d raw move-in records from %d sections",
        len(records), len(section_rows),
    )
    return records
