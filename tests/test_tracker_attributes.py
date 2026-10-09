"""Client device tracker attributes: where a client is, or was last, connected.

Covers the port of upstream PR #179 (`connected_to_model`, and `connected_to`
kept after a disconnect) and the null guards on `source`, `connectivity` and
`interface`, which the API sends as explicit null for a client that is offline.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from helpers import eero_api

MODULE = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "eero"
    / "tracker_attributes.py"
)
spec = importlib.util.spec_from_file_location("eero_tracker_attributes", MODULE)
ta = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ta)

NETWORK = "/2.2/networks/1234567"


def client(**overrides) -> eero_api.client.EeroClient:
    """Return a wireless client connected to the office eero."""
    data = {
        "url": f"{NETWORK}/devices/aa:bb:cc:dd:ee:ff",
        "mac": "aa:bb:cc:dd:ee:ff",
        "nickname": "Chloe iPad",
        "hostname": "chloe-ipad",
        "ip": "192.168.4.21",
        "manufacturer": "Apple",
        "connected": True,
        "connection_type": "wireless",
        "wireless": True,
        "source": {"location": "Office", "model": "eero Pro 6E"},
        "interface": {"frequency": "5", "frequency_unit": "GHz"},
        "channel": 36,
        "connectivity": {
            "signal": "-42 dBm",
            "rx_rate_info": {"channel_width": "80 MHz"},
            "tx_rate_info": {"channel_width": "40 MHz"},
        },
    }
    data.update(overrides)
    return eero_api.client.EeroClient(api=None, network=None, data=data)


def test_source_model_is_read_from_source() -> None:
    """The new property reads source.model next to source.location."""
    c = client()
    assert c.source_location == "Office"
    assert c.source_model == "eero Pro 6E"


def test_connected_client_reports_where_and_what_it_is_connected_to() -> None:
    """A connected client publishes connected_to_model alongside connected_to."""
    attrs = ta.client_tracker_attributes(client(), True, "TestNetwork")

    assert attrs["connected_to"] == "Office"
    assert attrs["connected_to_model"] == "eero Pro 6E"
    assert attrs["connection_type"] == "wireless"
    assert attrs["ip"] == "192.168.4.21"
    assert attrs["mac"] == "aa:bb:cc:dd:ee:ff"
    assert attrs["host_name"] == "chloe-ipad"
    assert attrs["manufacturer"] == "Apple"
    assert attrs["network_name"] == "TestNetwork"
    assert attrs["band"] == "5 GHz"
    assert attrs["channel"] == 36
    assert attrs["channel_width_rx"] == "80 MHz"


def test_disconnected_client_keeps_its_last_eero_only() -> None:
    """After a disconnect, connected_to says where the client was last seen.

    The live-connection attributes (type, addresses, band) are dropped, as
    before; only the last source survives (upstream PR #179).
    """
    c = client(connected=False, connectivity=None, interface=None, ip=None)
    attrs = ta.client_tracker_attributes(c, False, "TestNetwork")

    assert attrs == {"connected_to": "Office", "connected_to_model": "eero Pro 6E"}


def test_consider_home_grace_keeps_the_live_attributes() -> None:
    """While consider_home still counts the client as home, nothing changes."""
    c = client(connected=False)
    attrs = ta.client_tracker_attributes(c, True, "TestNetwork")

    assert attrs["connected_to"] == "Office"
    assert attrs["connection_type"] == "wireless"
    assert attrs["network_name"] == "TestNetwork"


def test_client_with_no_source_has_no_connected_to() -> None:
    """A client the API has never placed carries neither attribute."""
    attrs = ta.client_tracker_attributes(client(source=None, connected=False), False, "N")
    assert "connected_to" not in attrs
    assert "connected_to_model" not in attrs

    attrs = ta.client_tracker_attributes(client(source={"location": "Office"}), True, "N")
    assert attrs["connected_to"] == "Office"
    assert "connected_to_model" not in attrs


def test_explicit_nulls_do_not_raise() -> None:
    """`source`, `connectivity`, `interface` and the rate blocks may be null."""
    c = client(
        source=None,
        connectivity=None,
        interface=None,
    )
    assert c.source_location is None
    assert c.source_model is None
    assert c.channel_width_rx is None
    assert c.channel_width_tx is None
    assert c.signal == (None, None)
    assert c.interface_frequency == (None, None)

    c = client(connectivity={"signal": "-60 dBm", "rx_rate_info": None, "tx_rate_info": None})
    assert c.channel_width_rx is None
    assert c.channel_width_tx is None
    assert c.signal == (-60, "dBm")

    missing = client()
    for key in ("source", "connectivity", "interface"):
        del missing.data[key]
    assert missing.source_location is None
    assert missing.channel_width_rx is None
    assert missing.interface_frequency == (None, None)


def test_a_vanished_resource_yields_no_attributes() -> None:
    """A client the API no longer reports (H3) must not raise AttributeError."""
    assert ta.client_tracker_attributes(None, False, "TestNetwork") == {}
