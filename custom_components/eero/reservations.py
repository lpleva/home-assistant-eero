"""Input checks for the DHCP reservation services.

Kept free of Home Assistant and package imports so it can be tested on its
own (the fork's tests run without Home Assistant installed). Every function
raises ValueError with a message fit to show the user; the service handler
turns that into ServiceValidationError. Nothing here talks to the network:
bad input is rejected before any API call.

Port of upstream PR #173, which validated nothing beyond "is a string".
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

MAC_RE = re.compile(r"^([0-9a-f]{2})([:-])([0-9a-f]{2})(\2[0-9a-f]{2}){4}$")
MAX_NAME_LENGTH = 64


def normalize_mac(value: Any) -> str:
    """Return the MAC as lowercase colon-separated, or raise ValueError.

    Six hex pairs joined by ":" or "-". The broadcast and all-zero addresses
    and multicast addresses (low bit of the first octet set) are refused: no
    client has them, and a reservation on one is a typo at best.
    """
    mac = str(value or "").strip().lower()
    if not MAC_RE.match(mac):
        raise ValueError(f"'{value}' is not a MAC address (expected aa:bb:cc:dd:ee:ff)")
    mac = mac.replace("-", ":")
    if mac in ("ff:ff:ff:ff:ff:ff", "00:00:00:00:00:00"):
        raise ValueError(f"{mac} is not a client MAC address")
    if int(mac[:2], 16) & 1:
        raise ValueError(f"{mac} is a multicast address, not a client")
    return mac


def validate_reservation_ip(
    value: Any, subnet: str | None, gateway: str | None = None
) -> str:
    """Return the IPv4 address as a string, or raise ValueError.

    With the network's LAN subnet known, the address must be a host address
    inside it (not the network or broadcast address, not the gateway).
    Without it, the address must at least be a private (RFC 1918) host
    address; the router still has the final say.
    """
    text = str(value or "").strip()
    try:
        address = ipaddress.IPv4Address(text)
    except (ipaddress.AddressValueError, ValueError) as err:
        raise ValueError(f"'{value}' is not an IPv4 address") from err
    if (
        address.is_multicast
        or address.is_loopback
        or address.is_unspecified
        or address.is_link_local
        or address.is_reserved
    ):
        raise ValueError(f"{address} cannot be reserved for a client")
    if gateway and text == str(gateway).strip():
        raise ValueError(f"{address} is the router's own address")
    if subnet:
        try:
            network = ipaddress.IPv4Network(subnet, strict=False)
        except ValueError as err:
            raise ValueError(f"the network's subnet '{subnet}' is unreadable") from err
        if address not in network:
            raise ValueError(f"{address} is outside the network's subnet {network}")
        if address in (network.network_address, network.broadcast_address):
            raise ValueError(f"{address} is not a host address in {network}")
    elif not address.is_private:
        raise ValueError(f"{address} is not a private address")
    return str(address)


def clean_reservation_name(value: Any) -> str:
    """Return the trimmed description, or raise ValueError.

    At most MAX_NAME_LENGTH characters, no control characters. Empty is fine.
    """
    name = str(value if value is not None else "").strip()
    if len(name) > MAX_NAME_LENGTH:
        raise ValueError(f"name is longer than {MAX_NAME_LENGTH} characters")
    if any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise ValueError("name contains control characters")
    return name


def reservation_mac(reservation: dict) -> str | None:
    """The MAC a reservation record is for, normalized, or None if it has none."""
    try:
        return normalize_mac(reservation.get("mac"))
    except ValueError:
        return None


def find_reservation(reservations: list[dict] | None, mac: str) -> dict | None:
    """Return the one reservation for mac, None if there is none.

    Raises ValueError if the reservation list could not be read, or if more
    than one record claims the MAC: a delete must target exactly one.
    """
    if reservations is None:
        raise ValueError("the network's reservations could not be read")
    matches = [r for r in reservations if reservation_mac(r) == mac]
    if len(matches) > 1:
        raise ValueError(f"{len(matches)} reservations claim {mac}; fix this in the eero app")
    return matches[0] if matches else None


def check_reservation_is_new(
    reservations: list[dict] | None, mac: str, ip: str
) -> None:
    """Raise ValueError if mac or ip is already reserved.

    One reservation per MAC and one MAC per address. Changing a device's
    address is delete then set, so every write creates exactly one record.
    An unreadable list is let through: the router enforces the same rule.
    """
    if reservations is None:
        return
    if existing := find_reservation(reservations, mac):
        raise ValueError(
            f"{mac} already has a reservation at {existing.get('ip')}; delete it first"
        )
    for reservation in reservations:
        if str(reservation.get("ip") or "").strip() == ip:
            raise ValueError(
                f"{ip} is already reserved for {reservation_mac(reservation) or 'another client'}"
            )


def select_one(items: list, what: str, hint: str) -> Any:
    """Return the single item, or raise ValueError naming what to narrow."""
    if not items:
        raise ValueError(f"no {what} matches")
    if len(items) > 1:
        raise ValueError(f"{len(items)} {what}s match; {hint}")
    return items[0]
