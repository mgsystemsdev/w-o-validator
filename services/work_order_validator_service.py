"""Work Order Validator service.

Classifies active service request work orders as "Make Ready" or
"Service Technician" based on move-in timing, SR text fields, assignee, and Location.

Classification rules — a row is **Make Ready** if **any** of the following holds
(evaluation order):

1. **Service Category / Issue:** either column (case-insensitive) contains
   ``inspection and make ready`` or ``make ready``.

2. **Move-in window (strict):** unit is known, move-in and created date exist, and
   ``days_since_move_in`` is between ``-7`` and ``15`` (inclusive).

3. **Move-in window (extended):** the unit appears in ``anchor_units`` — at least
   one **other** row for the same normalized unit qualified under the **strict**
   window only (not via text or assignee) — and ``days_since_move_in`` is between
   ``-7`` and ``30`` (inclusive).

4. **Assignee allowlist (last resort):** ``Assigned to`` matches a configured
   make-ready technician name (trim + case-insensitive). Does not apply to
   ``Unassigned`` / ``Any technician``.

Otherwise → base **Service Technician**, refined by Location:

    Location matches unit pattern (phase-building-unit)  →  "Service Technician"
    Else if Location contains Pool, Grounds, or Exterior
        →  "Service Tech – Common Area" + optional `` – {venue}``
    Else if Location contains Fitness, Clubhouse, Game Room, or Dining
        →  "Service Tech – Amenities" + optional `` – {venue}`` (keyword stripped)
    Else  →  "Service Tech – Amenities" + `` – {location}`` (non-unit default fallback)
"""

from __future__ import annotations

import io
import logging
import re
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
MAKE_READY_MAX_DAYS = 15   # post-move-in grace window (strict)
MAKE_READY_EXTENDED_MAX_DAYS = 30  # extended upper bound when unit is anchored

# ---------------------------------------------------------------------------
# Phase → manager group mapping
# ---------------------------------------------------------------------------
MABI_PHASES: frozenset[str] = frozenset({"3", "4", "4C", "4S"})
ROBERT_PHASES: frozenset[str] = frozenset({"5", "7", "8"})

_AMENITY_LOCATION_SUBSTRINGS: tuple[str, ...] = (
    "Game Room",
    "Fitness",
    "Clubhouse",
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

# Assigned-to names that force Make Ready when nothing above matched (case-insensitive).
_MAKE_READY_ASSIGNEE_NAMES: frozenset[str] = frozenset(
    {
        "miguel gonzalez",
        "michael huang",
        "miguel gil",
        "chuck griffis",
        "chuck griffi",
        "rafael anez",
    }
)

_LABEL_AMENITIES = "Service Tech – Amenities"
_LABEL_COMMON = "Service Tech – Common Area"


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


def _is_make_ready_by_assignee(rec: dict) -> bool:
    """True when Assigned to is on the make-ready technician allowlist."""
    name = _excel_cell_str(rec.get("Assigned to")).casefold()
    if not name or name in ("unassigned", "any technician"):
        return False
    return name in _MAKE_READY_ASSIGNEE_NAMES


def _matches_unit_pattern(location: str) -> bool:
    parts = parse_unit_parts(normalize_unit_code(location))
    return parts["phase_code"] is not None and parts["building_code"] is not None


def _first_matching_substring(loc_lower: str, substrings: tuple[str, ...]) -> str | None:
    """Return the first substring from ``substrings`` that appears in ``loc_lower`` (longest first)."""
    for sub in sorted(substrings, key=len, reverse=True):
        if sub.casefold() in loc_lower:
            return sub
    return None


def _venue_remainder_after_keyword(location: str, keyword: str) -> str:
    """Strip the matched keyword from location; return a concise venue label."""
    raw = location.strip()
    if not keyword:
        return raw
    pattern = re.compile(re.escape(keyword), re.IGNORECASE)
    m = pattern.search(raw)
    if not m:
        return raw
    before = raw[: m.start()].strip(" \t-–—")
    after = raw[m.end() :].strip(" \t-–—")
    part = after if after else before
    part = " ".join(part.split())
    return part if part else keyword


def _with_venue_suffix(location: str, base_label: str) -> str:
    """Append `` – {venue}`` for amenities/common area when we can derive a venue."""
    if base_label == _LABEL_AMENITIES:
        kw = _first_matching_substring(location.casefold(), _AMENITY_LOCATION_SUBSTRINGS)
    elif base_label == _LABEL_COMMON:
        kw = _first_matching_substring(location.casefold(), _COMMON_AREA_LOCATION_SUBSTRINGS)
    else:
        return base_label
    if not kw:
        return base_label
    venue = _venue_remainder_after_keyword(location, kw)
    if not venue:
        return base_label
    return f"{base_label} – {venue}"


def _amenities_label_for_non_unit_location(location: str) -> str:
    """Amenities label: use keyword-based venue when possible, else full cleaned location."""
    loc_lower = location.casefold()
    if _first_matching_substring(loc_lower, _AMENITY_LOCATION_SUBSTRINGS):
        return _with_venue_suffix(location, _LABEL_AMENITIES)
    venue = " ".join(location.strip().split())
    if venue:
        return f"{_LABEL_AMENITIES} – {venue}"
    return _LABEL_AMENITIES


def _refine_service_technician_label(location: str) -> str:
    if _matches_unit_pattern(location):
        return "Service Technician"
    loc_lower = location.casefold()
    if _first_matching_substring(loc_lower, _COMMON_AREA_LOCATION_SUBSTRINGS):
        return _with_venue_suffix(location, _LABEL_COMMON)
    return _amenities_label_for_non_unit_location(location)


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

    # Pass A: build per-row timing + anchor units (strict move-in only).
    row_context: list[dict] = []
    anchor_units: set[str] = set()

    for _, row in df.iterrows():
        rec = dict(row)
        location = str(rec.get("Location") or "").strip()
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

        by_move_in_strict = (
            unit_id is not None
            and move_in is not None
            and days_since is not None
            and MAKE_READY_MIN_DAYS <= days_since <= MAKE_READY_MAX_DAYS
        )
        if by_move_in_strict:
            anchor_units.add(unit_norm)

        row_context.append(
            {
                "rec": rec,
                "location": location,
                "unit_norm": unit_norm,
                "unit_id": unit_id,
                "move_in": move_in,
                "days_since": days_since,
                "by_move_in_strict": by_move_in_strict,
            }
        )

    results: list[dict] = []
    for ctx in row_context:
        rec = ctx["rec"]
        location = ctx["location"]
        unit_norm = ctx["unit_norm"]
        unit_id = ctx["unit_id"]
        move_in = ctx["move_in"]
        days_since = ctx["days_since"]
        by_move_in_strict = ctx["by_move_in_strict"]

        phase = _extract_phase(location)
        building = _extract_building(location)
        rec["ph"] = phase
        rec["bld"] = building or ""

        by_service_text = _is_make_ready_by_service_category_or_issue(rec)
        by_move_in_extended = (
            unit_id is not None
            and move_in is not None
            and days_since is not None
            and unit_norm in anchor_units
            and MAKE_READY_MIN_DAYS <= days_since <= MAKE_READY_EXTENDED_MAX_DAYS
        )

        if by_service_text:
            wo = "Make Ready"
        elif by_move_in_strict or by_move_in_extended:
            wo = "Make Ready"
        elif _is_make_ready_by_assignee(rec):
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

    def _norm_wo(r: dict) -> str:
        s = str(r.get("wo_classification") or "").lower()
        for ch in ("–", "—"):
            s = s.replace(ch, "-")
        return s

    amenities = sum(
        1
        for r in rows
        if r.get("wo_classification") != "Make Ready"
        and _norm_wo(r).startswith("service tech - amenities")
    )
    common_area = sum(
        1
        for r in rows
        if r.get("wo_classification") != "Make Ready"
        and _norm_wo(r).startswith("service tech - common area")
    )
    service_tech_other = total - make_ready - amenities - common_area

    return {
        "total": total,
        "make_ready": make_ready,
        "service_tech": total - make_ready,
        "amenities": amenities,
        "common_area": common_area,
        "service_tech_unit": service_tech_other,
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
