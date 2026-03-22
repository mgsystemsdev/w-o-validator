"""Unit identity normalization and parsing.

Pure functions — no database access, no Streamlit imports.
"""

from __future__ import annotations

import re


def normalize_unit_code(raw: str) -> str:
    """Normalize a raw unit code.

    Strips whitespace, removes a leading ``"Unit "`` prefix (case-insensitive),
    uppercases, and collapses internal whitespace.
    """
    text = raw.strip()
    text = re.sub(r"(?i)^unit\s+", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.upper()


def parse_unit_parts(unit_code: str) -> dict:
    """Split a normalized unit code into its component parts.

    Expected format: ``<phase_code>-<building_code>-<unit_number>``
    (e.g. ``"4-26-0417"``).  If the code does not match the pattern the
    full string is returned as *unit_number* with the other parts set to
    ``None``.

    Returns:
        dict with keys ``phase_code``, ``building_code``, ``unit_number``.
    """
    match = re.match(r"^([A-Z0-9]+)-([A-Z0-9]+)-(.+)$", unit_code)
    if match:
        return {
            "phase_code": match.group(1),
            "building_code": match.group(2),
            "unit_number": match.group(3),
        }
    return {
        "phase_code": None,
        "building_code": None,
        "unit_number": unit_code,
    }


def compose_identity_key(property_id: int, unit_norm: str) -> str:
    """Create a unique identity key for a unit within a property."""
    return f"{property_id}:{unit_norm}"
