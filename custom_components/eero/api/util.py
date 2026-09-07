"""Eero API."""

from __future__ import annotations

from .const import STATE_ACTIVE, STATE_TRIALING


def backup_access_point_ok(capable: bool | None, requirements: dict | None) -> bool:
    """Backup access point OK."""
    return bool(capable) and all(bool(value) for value in (requirements or {}).values())


def premium_ok(capable: bool | None, status: str | None) -> bool:
    """Premium OK."""
    return all(
        [
            capable,
            status in [STATE_ACTIVE, STATE_TRIALING],
        ]
    )
