"""Eero API."""

from __future__ import annotations

from .const import STATE_ACTIVE, STATE_TRIALING


def sum_data_usage(resource, key: str) -> int | None:
    """Return total bytes for a (download, upload) pair.

    Returns None when neither direction is reported: a period that has just
    rolled over has no series yet, and None + None is not a sum.
    """
    down, up = getattr(resource, key)
    if down is None and up is None:
        return None
    return (down or 0) + (up or 0)


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
