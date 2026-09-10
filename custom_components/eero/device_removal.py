"""Which devices Home Assistant may delete from the device page.

Kept free of Home Assistant and package imports so it can be tested on its own
(the fork's tests run without Home Assistant installed); the caller passes the
model names in.

The rule: a wired or wireless client that the eero does not currently report as
connected may go (the phone that left, the box whose wifi was turned off). If it
reconnects, the next update recreates the device, which is the right outcome.
The network, the eeros, backup networks and profiles are never removable this
way: they are recreated on every setup, so deleting them only causes confusion.
"""

from __future__ import annotations

from collections.abc import Iterable


def can_remove_device(
    model: str | None,
    identifiers: Iterable[tuple[str, str]],
    domain: str,
    client_models: Iterable[str],
    connected_client_ids: Iterable[str],
) -> bool:
    """True if the device is a client the eero does not currently see as connected."""
    if model not in set(client_models):
        return False
    ids = {ident for dom, ident in identifiers if dom == domain}
    if not ids:
        return False
    return ids.isdisjoint(set(connected_client_ids))
