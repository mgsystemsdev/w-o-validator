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


# Rows where a KPI / title string was parsed into the unit column (ignore entirely).
_SUMMARY_UNIT_SUBSTRINGS: tuple[str, ...] = (
    "packets submitted",
    "packets pending",
    "packets approved",
    "total packets",
    "move ins for week",
    "move in pending",
    "pending approval",
    "submitted for current week",
    "approved / move in",
    "approved this week",
    "from previous weeks",
)


def _is_summary_or_title_row(unit_str: str) -> bool:
    """True when the cell is sheet chrome (headers, totals), not a unit code row."""
    u = (unit_str or "").strip().lower()
    if not u:
        return False
    if any(s in u for s in _SUMMARY_UNIT_SUBSTRINGS):
        return True
    # Long prose in the unit column (typical codes are short; KPI lines are sentences).
    if len(u) > 48 and u.count(" ") >= 3:
        return True
    return False


def import_historical_movings(file_content: bytes, filename: str) -> dict:
    """Import historical movings from an uploaded spreadsheet.

    Expected columns: ``unit_number`` (or ``unit``, ``unit_code``), ``moving_date``
    (or ``move_in_date``). Accepts ``.csv``, ``.xls``, ``.xlsx``.

    Excel files with title rows above the real header are detected automatically
    (first row with recognizable **unit** and **date** column headers).

    Returns:
        ``inserted``, ``already_on_file``, ``not_imported``, ``skipped`` (latter two sum),
        and ``row_results`` (data rows only — no sheet title lines).
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
    already_on_file = 0
    not_imported = 0
    row_results: list[dict] = []

    for _, row in df.iterrows():
        raw_unit = row.get("unit_number", "")
        unit_str = "" if raw_unit is None or (isinstance(raw_unit, float) and pd.isna(raw_unit)) else str(raw_unit).strip()
        raw_date = row.get("moving_date")

        if _is_summary_or_title_row(unit_str):
            continue

        unit_number = normalize_moving_unit_key(raw_unit if unit_str else "")

        status = ""
        parsed_date: date | None = None

        if not unit_number:
            not_imported += 1
            status = "Not imported — unit code is missing or could not be read."
            row_results.append(
                {"unit": unit_str or "(blank)", "moving_date": None, "status": status}
            )
            continue

        if pd.isna(raw_date) or (
            isinstance(raw_date, str) and not str(raw_date).strip()
        ):
            not_imported += 1
            status = "Not imported — moving date is missing in this row."
            row_results.append(
                {"unit": unit_str, "moving_date": None, "status": status}
            )
            continue

        moving_date = parse_one_date_cell(raw_date)
        if moving_date is None:
            not_imported += 1
            status = "Not imported — moving date could not be read from the file."
            row_results.append(
                {"unit": unit_str, "moving_date": None, "status": status}
            )
            continue

        parsed_date = moving_date
        result = unit_movings_repository.insert_moving(unit_number, moving_date)
        if result is not None:
            inserted += 1
            status = (
                "Recorded — this move-in date is now in the moving log and will be used "
                "as the official date for this unit."
            )
        else:
            already_on_file += 1
            status = (
                "Already registered — this unit and move-in date are already on file; "
                "that date remains the official moving date for this unit."
            )

        row_results.append(
            {"unit": unit_str, "moving_date": parsed_date, "status": status}
        )

    skipped = already_on_file + not_imported
    return {
        "inserted": inserted,
        "skipped": skipped,
        "already_on_file": already_on_file,
        "not_imported": not_imported,
        "row_results": row_results,
    }


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


def _moving_log_rows_for_units(units: list[dict], movings: list[dict]) -> list[dict]:
    """Map matched ``movings`` rows to display dicts using the property roster."""
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

    rows: list[dict] = []
    for m in movings:
        nk = normalize_moving_unit_key(m["unit_number"])
        rows.append(
            {
                "unit": norm_to_display.get(nk, m["unit_number"]),
                "moving_date": m["moving_date"],
                "logged_at": m["created_at"],
            }
        )
    return rows


def get_property_moving_log_bundle(property_id: int) -> dict:
    """Moving log rows for the property plus roster context for the UI.

    Returns:
        ``rows``: newest-first entries from ``unit_movings`` whose normalized unit
        matches a unit on this property.
        ``unit_count``: number of units on the property (including inactive).
        ``norm_key_count``: roster codes that normalize to a non-empty key (0 if
        the roster has no usable unit codes).
    """
    units = unit_repository.get_by_property(property_id, active_only=False)
    unit_count = len(units)
    if not units:
        return {"rows": [], "unit_count": 0, "norm_key_count": 0}

    norm_keys, _ = _norm_keys_and_candidates(units)
    norm_key_count = len(norm_keys)
    if not norm_keys:
        return {"rows": [], "unit_count": unit_count, "norm_key_count": 0}

    # Match on normalized identity so DB strings need not exactly match roster strings.
    all_movings = unit_movings_repository.list_all_movings()
    movings = [
        m
        for m in all_movings
        if normalize_moving_unit_key(m["unit_number"]) in norm_keys
    ]
    movings.sort(key=lambda m: (m["moving_date"], m["unit_number"]), reverse=True)
    rows = _moving_log_rows_for_units(units, movings)
    return {
        "rows": rows,
        "unit_count": unit_count,
        "norm_key_count": norm_key_count,
    }


def get_property_moving_log_rows(property_id: int) -> list[dict]:
    """Rows from ``unit_movings`` that match units on this property (newest dates first).

    Each dict: ``unit`` (display code), ``moving_date``, ``logged_at``.
    """
    return get_property_moving_log_bundle(property_id)["rows"]
