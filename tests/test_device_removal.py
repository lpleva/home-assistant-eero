"""Which eero devices HA may delete: clients the eero no longer sees connected."""

from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "custom_components" / "eero" / "device_removal.py"
spec = importlib.util.spec_from_file_location("eero_device_removal", MODULE)
dr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dr)

DOMAIN = "eero"
CLIENTS = ("Client (Wired)", "Client (Wireless)")


def test_disconnected_client_can_go():
    assert dr.can_remove_device("Client (Wireless)", {(DOMAIN, "client-1")}, DOMAIN, CLIENTS, {"client-2"}) is True


def test_connected_client_stays():
    assert dr.can_remove_device("Client (Wireless)", {(DOMAIN, "client-1")}, DOMAIN, CLIENTS, {"client-1", "client-2"}) is False


def test_eero_network_and_profile_devices_are_never_removable():
    for model in ("eero Pro 6E", "Network", "Profile", "Backup Network", None):
        assert dr.can_remove_device(model, {(DOMAIN, "x")}, DOMAIN, CLIENTS, set()) is False


def test_foreign_identifiers_do_not_count():
    assert dr.can_remove_device("Client (Wired)", {("other", "client-1")}, DOMAIN, CLIENTS, set()) is False
    assert dr.can_remove_device("Client (Wired)", set(), DOMAIN, CLIENTS, set()) is False
