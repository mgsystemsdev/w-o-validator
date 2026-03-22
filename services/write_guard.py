"""Write guard — no-op stub for wo_standalone.

The system_settings write-toggle is not used in this app. Writes are
always enabled. This stub exists so vendored modules that call
check_writes_enabled() continue to work without modification.
"""

from __future__ import annotations


class WritesDisabledError(Exception):
    pass


class ConcurrencyError(Exception):
    pass


def check_writes_enabled() -> None:
    """No-op — writes are always enabled in wo_standalone."""


def check_concurrency(entity: dict, table_name: str = "") -> None:
    """No-op."""
