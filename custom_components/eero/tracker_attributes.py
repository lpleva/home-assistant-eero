"""The state attributes a client's device tracker publishes.

Kept free of Home Assistant and package imports so it can be tested on its
own (the fork's tests run without Home Assistant installed); the entity
passes in the client resource, its own connected verdict and the network name.

Two groups of attributes:

- `connected_to` and `connected_to_model`: the eero the client is, or was
  last, connected to. The API keeps reporting `source` after a client
  disconnects, so these stay set while the tracker reads not_home and say
  where the client was last seen (upstream PR #179).
- `ip_reserved` and `reserved_ip`: whether the client's address is a DHCP
  reservation, and which address. Published whenever the reservations could
  be read, connected or not (upstream PR #173).
- Everything else describes the live connection (type, addresses, band,
  channel) and is published only while the client is connected.
"""

from __future__ import annotations

from typing import Any

ATTR_MANUFACTURER = "manufacturer"


def client_tracker_attributes(
    client: Any, connected: bool, network_name: str | None
) -> dict[str, Any]:
    """Return the extra state attributes for a client device tracker."""
    attrs: dict[str, Any] = {}
    if client is None:
        return attrs
    if location := client.source_location:
        attrs["connected_to"] = location
        if model := client.source_model:
            attrs["connected_to_model"] = model
    if (reserved := client.is_reserved) is not None:
        attrs["ip_reserved"] = reserved
        if reserved_ip := client.reserved_ip:
            attrs["reserved_ip"] = reserved_ip
    if not connected:
        return attrs
    attrs["connection_type"] = client.connection_type
    if ip_address := client.ip:
        attrs["ip"] = ip_address
    if mac_address := client.mac:
        attrs["mac"] = mac_address
    if hostname := client.hostname:
        attrs["host_name"] = hostname
    if manufacturer := client.manufacturer:
        attrs[ATTR_MANUFACTURER] = manufacturer
    attrs["network_name"] = network_name
    if client.wireless:
        frequency, frequency_unit = client.interface_frequency
        if frequency:
            attrs["band"] = (
                f"{frequency} {frequency_unit}" if frequency_unit else str(frequency)
            )
        if client.channel is not None:
            attrs["channel"] = client.channel
        if channel_width_rx := client.channel_width_rx:
            attrs["channel_width_rx"] = channel_width_rx
    return attrs
