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


def _normalize_header_label(val: object) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    s = str(val).strip().lower()
    if not s:
        return ""
    s = s.replace(" ", "_").replace("-", "_").replace(":", "_")
    while "__" in s:
        s = s.replace("__", "_")
    return s


def _unit_header_score(norm: str) -> int:
    if not norm or norm.startswith("unnamed"):
        return 0
    if any(x in norm for x in ("previous", "former", "old_unit", "prior")):
        return 0
    if norm in ("unit_number", "unit_code", "unit_id"):
        return 100
    if "unit" in norm and "date" not in norm and "sq" not in norm:
        return 85
    if norm in ("apt", "apartment", "suite", "space"):
        return 70
    if "apt" in norm or "suite" in norm:
        return 65
    return 0


def _date_header_score(norm: str) -> int:
    if not norm or norm.startswith("unnamed"):
        return 0
    if norm in ("moving_date", "move_in_date", "movein_date", "lease_start", "start_date"):
        return 100
    if "move" in norm and "in" in norm:
        return 95
    if "moving" in norm or "move_in" in norm:
        return 90
    if "lease" in norm and ("start" in norm or "begin" in norm):
        return 88
    if "transfer" in norm and "date" in norm:
        return 88
    if "transfer" in norm:
        return 80
    if "occup" in norm and "date" in norm:
        return 78
    if "date" in norm and "birth" not in norm and "due" not in norm:
        return 75
    if norm.endswith("_dt") or norm.endswith("_at"):
        return 50
    return 0


def _detect_unit_and_date_columns(raw: pd.DataFrame) -> tuple[int, int, int] | None:
    """Find header row index and (unit_col, date_col) when the first row is not the header.

    Returns ``(header_row_ix, unit_col_ix, date_col_ix)`` or ``None``.
    """
    max_row = min(45, len(raw))
    ncols = raw.shape[1]
    for i in range(max_row):
        labels = [_normalize_header_label(raw.iat[i, j]) for j in range(ncols)]
        best_u = (0, -1)
        best_d = (0, -1)
        for j, h in enumerate(labels):
            us = _unit_header_score(h)
            ds = _date_header_score(h)
            if us > best_u[0]:
                best_u = (us, j)
            if ds > best_d[0]:
                best_d = (ds, j)
        if best_u[0] >= 45 and best_d[0] >= 45 and best_u[1] != best_d[1]:
            return (i, best_u[1], best_d[1])
    return None


def _dataframe_from_detected_columns(
    raw: pd.DataFrame, header_row: int, unit_col: int, date_col: int
) -> pd.DataFrame:
    body = raw.iloc[header_row + 1 :].copy()
    body = body.dropna(how="all")
    return pd.DataFrame(
        {
            "unit_number": body.iloc[:, unit_col],
            "moving_date": body.iloc[:, date_col],
        }
    )


def _read_movings_table(file_content: bytes, ext: str) -> pd.DataFrame:
    """Read spreadsheet; resolve ``unit_number`` + ``moving_date`` with header detection."""
    if ext in ("xls", "xlsx"):
        buf = io.BytesIO(file_content)
        df_try = pd.read_excel(buf, dtype=object)
        df_try.columns = [_normalize_header_label(c) for c in df_try.columns]
        # pandas names broken headers like "Unnamed: 0" → normalize may not start with unnamed
        broken = all(
            _normalize_header_label(c).startswith("unnamed") or not str(c).strip()
            for c in df_try.columns
        )
        if not broken:
            if "unit_number" not in df_try.columns:
                for alt in ("unit", "unit_code"):
                    if alt in df_try.columns:
                        df_try = df_try.rename(columns={alt: "unit_number"})
                        break
            if "moving_date" not in df_try.columns and "move_in_date" in df_try.columns:
                df_try = df_try.rename(columns={"move_in_date": "moving_date"})
            if "unit_number" in df_try.columns and "moving_date" in df_try.columns:
                return df_try

        raw = pd.read_excel(io.BytesIO(file_content), header=None, dtype=object)
        det = _detect_unit_and_date_columns(raw)
        if det is None:
            cols = ", ".join(str(c) for c in df_try.columns.tolist())
            raise ValueError(
                "Could not find a header row with unit and date columns. "
                "Expected names like Unit / Move-In Date, or unit_number + moving_date. "
                f"Columns found: {cols}"
            )
        hr, uc, dc = det
        logger.info(
            "import_historical_movings: using header row %s, unit col %s, date col %s",
            hr,
            uc,
            dc,
        )
        return _dataframe_from_detected_columns(raw, hr, uc, dc)

    # CSV
    df_try = pd.read_csv(io.BytesIO(file_content), dtype=object)
    df_try.columns = [_normalize_header_label(c) for c in df_try.columns]
    if "unit_number" not in df_try.columns:
        for alt in ("unit", "unit_code"):
            if alt in df_try.columns:
                df_try = df_try.rename(columns={alt: "unit_number"})
                break
    if "moving_date" not in df_try.columns and "move_in_date" in df_try.columns:
        df_try = df_try.rename(columns={"move_in_date": "moving_date"})
    if "unit_number" in df_try.columns and "moving_date" in df_try.columns:
        return df_try

    raw = pd.read_csv(io.BytesIO(file_content), header=None, dtype=object)
    det = _detect_unit_and_date_columns(raw)
    if det is None:
        raise ValueError(
            "Could not find unit and date columns in CSV. "
            f"Found: {', '.join(df_try.columns.tolist())}"
        )
    hr, uc, dc = det
    return _dataframe_from_detected_columns(raw, hr, uc, dc)


def normalize_moving_unit_key(raw: str | None) -> str:
    """Same identity rules as the rest of DMRB (prefix, spacing, case)."""
    if raw is None:
        return ""
    return normalize_unit_code(str(raw))


def import_historical_movings(file_content: bytes, filename: str) -> dict:
    """Import historical movings from an uploaded spreadsheet.

    Expected columns: ``unit_number`` (or ``unit``, ``unit_code``), ``moving_date``
    (or ``move_in_date``). Accepts ``.csv``, ``.xls``, ``.xlsx``.

    Excel files with title rows above the real header are detected automatically
    (first row with recognizable **unit** and **date** column headers).

    Returns {"inserted": int, "skipped": int}.
    """
    ext = filename.rsplit(".", 1)[-1].lower()
    try:
        df = _read_movings_table(file_content, ext)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Unable to parse file: {exc}") from exc

    if "unit_number" not in df.columns or "moving_date" not in df.columns:
        raise ValueError(
            "File must include unit and date columns "
            "(e.g. unit_number + moving_date). "
            f"Found: {', '.join(str(c) for c in df.columns.tolist())}"
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
