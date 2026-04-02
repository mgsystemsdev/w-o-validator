"""Work Order Validator service.

Classifies active service request work orders as "Make Ready" or
"Service Technician" based on move-in timing and SR text fields.

Classification rules — a row is **Make Ready** if **either**:

- **Move-in window:** unit is known, move-in and created date exist, and
  ``days_since_move_in = created_date - move_in_date`` is between ``-7`` and ``15`` (inclusive).

- **Service Category / Issue:** either column (case-insensitive) contains
  ``inspection and make ready`` or ``make ready`` (e.g. category
  "Inspection and make ready", issue "Make Ready" or
  "Make ready/move-out inspection"). Applies even outside the move-in window and
  skips Service Tech location refinement.

Otherwise → base **Service Technician**, refined by Location:

    Location matches unit pattern (phase-building-unit)  →  "Service Technician"
    Else if Location contains Fitness, Clubhouse, Game Room, or Dining
        →  "Service Tech – Amenities"
    Else if Location contains Pool, Grounds, or Exterior
        →  "Service Tech – Common Area"
    Else  →  "Service Technician"
"""

from __future__ import annotations

import io
import logging
from datetime import date

import pandas as pd

from db.repository import unit_repository
from domain.dates import format_us_date
from domain.unit_identity import normalize_unit_code, parse_unit_parts
from services import occupancy_service
from services import work_order_excel
from services.pandas_dates import coerce_datetime_series

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Classification thresholds
# ---------------------------------------------------------------------------
MAKE_READY_MIN_DAYS = -7   # pre-move-in prep window
MAKE_READY_MAX_DAYS = 15   # post-move-in grace window

# ---------------------------------------------------------------------------
# Phase → manager group mapping
# ---------------------------------------------------------------------------
MABI_PHASES: frozenset[str] = frozenset({"3", "4", "4C", "4S"})
ROBERT_PHASES: frozenset[str] = frozenset({"5", "7", "8"})

_AMENITY_LOCATION_SUBSTRINGS: tuple[str, ...] = (
    "Fitness",
    "Clubhouse",
    "Game Room",
    "Dining",
)
_COMMON_AREA_LOCATION_SUBSTRINGS: tuple[str, ...] = (
    "Pool",
    "Grounds",
    "Exterior",
)

# Substrings in "Service Category" / "Issue" that force Make Ready (case-insensitive).
_MAKE_READY_TEXT_MARKERS: tuple[str, ...] = (
    "inspection and make ready",
    "make ready",
)


def _excel_cell_str(val: object) -> str:
    """Normalize an Excel cell for text matching; empty if missing or NaN."""
    if val is None or pd.isna(val):
        return ""
    return str(val).strip()


def _is_make_ready_by_service_category_or_issue(rec: dict) -> bool:
    """True when Service Category or Issue indicates inspection / make-ready work."""
    sc = _excel_cell_str(rec.get("Service Category")).casefold()
    issue = _excel_cell_str(rec.get("Issue")).casefold()
    return any(m in sc or m in issue for m in _MAKE_READY_TEXT_MARKERS)


def _matches_unit_pattern(location: str) -> bool:
    parts = parse_unit_parts(normalize_unit_code(location))
    return parts["phase_code"] is not None and parts["building_code"] is not None


def _refine_service_technician_label(location: str) -> str:
    if _matches_unit_pattern(location):
        return "Service Technician"
    loc_lower = location.casefold()
    for sub in _AMENITY_LOCATION_SUBSTRINGS:
        if sub.casefold() in loc_lower:
            return "Service Tech – Amenities"
    for sub in _COMMON_AREA_LOCATION_SUBSTRINGS:
        if sub.casefold() in loc_lower:
            return "Service Tech – Common Area"
    return "Service Technician"


def _classify(days_since: int | None, move_in_date: date | None, unit_found: bool) -> str:
    if not unit_found:
        return "Service Technician"
    if move_in_date is None:
        return "Service Technician"
    if days_since is None:
        return "Service Technician"
    if MAKE_READY_MIN_DAYS <= days_since <= MAKE_READY_MAX_DAYS:
        return "Make Ready"
    return "Service Technician"


def _extract_phase(location: str) -> str:
    parts = parse_unit_parts(normalize_unit_code(location))
    if parts["phase_code"]:
        return parts["phase_code"].upper()
    return normalize_unit_code(location)


def _extract_building(location: str) -> str | None:
    parts = parse_unit_parts(normalize_unit_code(location))
    return parts["building_code"]


def validate(property_id: int, sr_file_content: bytes) -> list[dict]:
    """Parse an Active Service Request file and classify each work order.

    Returns a list of enriched row dicts, each with added keys:
        "ph"                  – phase code (str)
        "bld"                 – building code (str | None)
        "wo_classification"   – classification string
        "days_since_move_in"  – int or None
    """
    try:
        df = pd.read_excel(io.BytesIO(sr_file_content))
    except Exception as exc:
        raise ValueError(f"Could not read Service Request file: {exc}") from exc

    df.columns = [str(c).strip() for c in df.columns]

    for _date_col in ("Created date", "Due date"):
        if _date_col in df.columns:
            df[_date_col] = coerce_datetime_series(df[_date_col])

    occupancy: dict[int, date | None] = occupancy_service.get_all_occupancy(property_id)

    unit_rows = unit_repository.get_by_property(property_id, active_only=False)
    unit_lookup: dict[str, int] = {
        row["unit_code_norm"]: row["unit_id"] for row in unit_rows
    }

    results: list[dict] = []
    for _, row in df.iterrows():
        rec = dict(row)
        location = str(rec.get("Location") or "").strip()

        phase = _extract_phase(location)
        building = _extract_building(location)
        rec["ph"] = phase
        rec["bld"] = building or ""

        unit_norm = normalize_unit_code(location)
        unit_id = unit_lookup.get(unit_norm)

        days_since: int | None = None
        move_in: date | None = None
        if unit_id is not None:
            move_in = occupancy.get(unit_id)
            created_raw = rec.get("Created date")
            if move_in is not None and pd.notna(created_raw):
                try:
                    created_dt = pd.Timestamp(created_raw).date()
                    days_since = (created_dt - move_in).days
                except Exception:
                    pass

        by_move_in_window = (
            unit_id is not None
            and move_in is not None
            and days_since is not None
            and MAKE_READY_MIN_DAYS <= days_since <= MAKE_READY_MAX_DAYS
        )
        by_service_text = _is_make_ready_by_service_category_or_issue(rec)

        if by_move_in_window or by_service_text:
            wo = "Make Ready"
        elif unit_id is None:
            wo = _classify(None, None, unit_found=False)
            if wo == "Service Technician":
                wo = _refine_service_technician_label(location)
        else:
            wo = _classify(days_since, move_in, unit_found=True)
            if wo == "Service Technician":
                wo = _refine_service_technician_label(location)

        rec["wo_classification"] = wo
        rec["days_since_move_in"] = days_since
        results.append(rec)

    logger.info(
        "work_order_validator_service.validate: property=%d total=%d "
        "make_ready=%d service_tech=%d",
        property_id,
        len(results),
        sum(1 for r in results if r["wo_classification"] == "Make Ready"),
        sum(1 for r in results if r["wo_classification"] != "Make Ready"),
    )
    return results


def build_report(property_id: int, sr_file_content: bytes) -> bytes:
    """Classify work orders and produce a formatted Excel report as bytes."""
    rows = validate(property_id, sr_file_content)
    return work_order_excel.build_work_order_report(rows)


def get_summary(rows: list[dict]) -> dict:
    """Return classification counts for the UI summary display."""
    total = len(rows)
    make_ready = sum(1 for r in rows if r.get("wo_classification") == "Make Ready")
    return {
        "total": total,
        "make_ready": make_ready,
        "service_tech": total - make_ready,
    }


# (source_key, dataframe_column_label) — aligns with work_order_excel row keys where possible.
_PREVIEW_COLUMNS: tuple[tuple[str, str], ...] = (
    ("Number", "Number"),
    ("Location", "Location"),
    ("Created date", "Created date"),
    ("Due date", "Due date"),
    ("Days open", "Days open"),
    ("Service Category", "Service Category"),
    ("Issue", "Issue"),
    ("Assigned to", "Assigned to"),
    ("Priority", "Priority"),
    ("Status", "Status"),
    ("ph", "PH"),
    ("bld", "BLD"),
    ("days_since_move_in", "Days since move-in"),
    ("wo_classification", "WO Classification"),
)


def _preview_scalar(val: object) -> object:
    """Normalize a cell for JSON-like / Streamlit-safe display."""
    if val is None:
        return None
    if isinstance(val, float) and pd.isna(val):
        return None
    if isinstance(val, pd.Timestamp):
        if pd.isna(val):
            return None
        return format_us_date(val)
    if isinstance(val, date):
        return format_us_date(val)
    if isinstance(val, str):
        return val
    if isinstance(val, (int, bool)):
        return val
    if hasattr(val, "item"):
        try:
            return _preview_scalar(val.item())
        except (ValueError, AttributeError, TypeError):
            pass
    return val


def rows_for_preview(rows: list[dict]) -> list[dict]:
    """Flatten validate() output for ``st.dataframe`` (stable columns, safe types)."""
    result: list[dict] = []
    for rec in rows:
        out: dict[str, object] = {}
        for src_key, label in _PREVIEW_COLUMNS:
            out[label] = _preview_scalar(rec.get(src_key))
        result.append(out)
    return result
