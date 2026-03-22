"""Property service — wraps property repository for UI consumption."""

from __future__ import annotations

from db.repository import property_repository, unit_repository


def get_all_properties() -> list[dict]:
    return property_repository.get_all()


def create_property(name: str) -> dict:
    return property_repository.insert(name)


def create_phase(property_id: int, phase_code: str, name: str | None = None) -> dict:
    return property_repository.insert_phase(property_id, phase_code, name)


def create_building(
    property_id: int,
    phase_id: int,
    building_code: str,
    name: str | None = None,
) -> dict:
    return property_repository.insert_building(property_id, phase_id, building_code, name)


def create_unit(
    property_id: int,
    unit_code_raw: str,
    unit_code_norm: str,
    unit_identity_key: str,
    *,
    phase_id: int | None = None,
    building_id: int | None = None,
    floor_plan: str | None = None,
    gross_sq_ft: int | None = None,
    has_carpet: bool = False,
    has_wd_expected: bool = False,
) -> dict:
    return unit_repository.insert(
        property_id, unit_code_raw, unit_code_norm, unit_identity_key,
        phase_id=phase_id, building_id=building_id,
        floor_plan=floor_plan, gross_sq_ft=gross_sq_ft,
        has_carpet=has_carpet, has_wd_expected=has_wd_expected,
    )


def get_phase_by_code(property_id: int, phase_code: str) -> dict | None:
    for p in property_repository.get_phases(property_id):
        if p["phase_code"] == phase_code:
            return p
    return None


def get_building_by_code(phase_id: int, building_code: str) -> dict | None:
    for b in property_repository.get_buildings(phase_id):
        if b["building_code"] == building_code:
            return b
    return None
