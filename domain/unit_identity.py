"""Unit identity normalization and parsing.

Pure functions — no database access, no Streamlit imports.
"""

from __future__ import annotations

import re


def normalize_unit_code(raw: str) -> str:
    """Normalize a raw unit code.

    Strips whitespace, removes leading ``"Unit "`` or ``"Building "`` prefixes (case-insensitive),
    uppercases, and collapses internal whitespace.
    """
    text = raw.strip()
    text = re.sub(r"(?i)^(unit|building)\s+", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.upper()


def parse_unit_parts(unit_code: str) -> dict:
    """Split a normalized unit code into its component parts.

    Expected format: ``<phase_code>-<building_code>-<unit_number>`` (e.g. ``"4-26-0417"``)
    or ``<phase_code>-<building_code>`` (e.g. ``"8-01"``).

    Returns:
        dict with keys ``phase_code``, ``building_code``, ``unit_number``.
    """
    # Try 3-part match first (PHASE-BLDG-UNIT)
    match3 = re.match(r"^([A-Z0-9]+)-([A-Z0-9]+)-(.+)$", unit_code)
    if match3:
        return {
            "phase_code": match3.group(1),
            "building_code": match3.group(2),
            "unit_number": match3.group(3),
        }

    # Try 2-part match (PHASE-BLDG)
    match2 = re.match(r"^([A-Z0-9]+)-([A-Z0-9]+)$", unit_code)
    if match2:
        return {
            "phase_code": match2.group(1),
            "building_code": match2.group(2),
            "unit_number": None,
        }

    # Fallback: whole string as unit number
    return {
        "phase_code": None,
        "building_code": None,
        "unit_number": unit_code,
    }


def compose_identity_key(property_id: int, unit_norm: str) -> str:
    """Create a unique identity key for a unit within a property."""
    return f"{property_id}:{unit_norm}"
