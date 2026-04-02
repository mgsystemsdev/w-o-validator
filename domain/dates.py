"""US-style date formatting (mm/dd/yyyy) used across the app."""

from __future__ import annotations

from datetime import date, datetime

US_DATE_DISPLAY_FMT = "%m/%d/%Y"
# openpyxl / Excel built-in number format (4-digit year)
EXCEL_DATE_NUMBER_FORMAT = "MM/DD/YYYY"


def format_us_date(value: date | datetime | None) -> str:
    """Format a date or datetime for UI and filenames; empty string if None."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime(US_DATE_DISPLAY_FMT)
    return value.strftime(US_DATE_DISPLAY_FMT)
