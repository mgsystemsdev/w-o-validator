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
    dt = coerce_datetime_series(pd.Series([value])).iloc[0]
    if pd.isna(dt):
        return None
    return pd.Timestamp(dt).date()
