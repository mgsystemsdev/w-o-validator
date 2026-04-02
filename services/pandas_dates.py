"""Pandas date coercion: prefer mm/dd/yyyy, then infer (Excel-native cells, ISO, etc.)."""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd


def coerce_datetime_series(series: pd.Series) -> pd.Series:
    """Parse a column to datetime64, trying US ``mm/dd/yyyy`` first for string cells."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series, errors="coerce")
    parsed = pd.to_datetime(series, format="%m/%d/%Y", errors="coerce")
    mask = parsed.isna() & series.notna()
    nonempty = series.notna() & series.astype(str).str.strip().ne("")
    mask = mask & nonempty
    if mask.any():
        parsed = parsed.copy()
        parsed.loc[mask] = pd.to_datetime(series.loc[mask], errors="coerce")
    return parsed


def _excel_serial_to_date(value: float | int) -> date | None:
    """``.xls`` / Excel often stores dates as day serials (origin 1899-12-30)."""
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(x):
        return None
    # Ignore tiny integers (years, counts) and implausible serials.
    if x < 29500 or x > 120000:  # ~1980–2228
        return None
    whole = int(x)
    ts = pd.to_datetime(whole, unit="D", origin="1899-12-30", errors="coerce")
    if pd.isna(ts):
        return None
    return ts.date()


def parse_one_date_cell(value) -> date | None:
    """Parse a single Excel/CSV cell to a date, US format first for strings."""
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date() if pd.notna(value) else None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        d = _excel_serial_to_date(value)
        if d is not None:
            return d
    dt = coerce_datetime_series(pd.Series([value])).iloc[0]
    if pd.isna(dt):
        return None
    return pd.Timestamp(dt).date()
