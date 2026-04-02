"""Streamlit tables: show every date-like value as mm/dd/yyyy (never raw ISO)."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

from domain.dates import format_us_date

# Full-line ISO date only — avoids touching unit codes like "3-16-0302".
_ISO_DATE_ONLY = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})\s*$")


def _format_one_cell(val: Any) -> Any:
    if val is None:
        return ""
    if isinstance(val, float) and pd.isna(val):
        return ""
    if not isinstance(val, (str, bytes)) and pd.isna(val):
        return ""
    if isinstance(val, pd.Timestamp):
        return format_us_date(val) if pd.notna(val) else ""
    if isinstance(val, datetime):
        return format_us_date(val)
    if isinstance(val, date):
        return format_us_date(val)
    if isinstance(val, np.datetime64):
        ts = pd.Timestamp(val)
        return format_us_date(ts) if pd.notna(ts) else ""
    if isinstance(val, str):
        m = _ISO_DATE_ONLY.match(val)
        if m:
            return format_us_date(
                date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            )
        return val
    if hasattr(val, "item"):
        try:
            it = val.item()
        except (ValueError, AttributeError, TypeError):
            return val
        if it is None:
            return ""
        if isinstance(it, np.datetime64):
            ts = pd.Timestamp(it)
            return format_us_date(ts) if pd.notna(ts) else ""
        if isinstance(it, datetime):
            return format_us_date(it)
        if isinstance(it, date):
            return format_us_date(it)
    return val


def dataframe_for_streamlit(rows: list[dict] | pd.DataFrame | None) -> pd.DataFrame:
    """Copy of the table with datetime columns and date-like object cells as US date strings."""
    if rows is None:
        return pd.DataFrame()
    df = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    if df.empty:
        return df
    out = df.copy()
    for col in out.columns:
        s = out[col]
        if pd.api.types.is_datetime64_any_dtype(s):
            conv = pd.to_datetime(s, errors="coerce")
            out[col] = conv.map(lambda x: format_us_date(x) if pd.notna(x) else "")
            continue
        if pd.api.types.is_bool_dtype(s) or pd.api.types.is_numeric_dtype(s):
            continue
        out[col] = s.map(_format_one_cell)
    return out
