"""Tests for the update loop's tolerance of partial responses (audit H4, H3)."""

from __future__ import annotations

import pytest

from helpers import FakeResponse, build_api, eero_api, fixture, ok

ACCOUNT = "/2.2/account"
NETWORK = "/2.2/networks/1234567"
DEVICES = f"{NETWORK}/devices"
PROFILES = f"{NETWORK}/profiles"
THREAD = f"{NETWORK}/thread"
BACKUP = f"{NETWORK}/backup_access_points"


def full_routes(devices=None, network=None) -> dict:
    """Return routes for a network that reports everything."""
    return {
        ACCOUNT: ok(fixture("account")),
        NETWORK: ok(network if network is not None else fixture("network")),
        THREAD: ok(fixture("thread")),
        DEVICES: ok(fixture("devices") if devices is None else devices),
        PROFILES: ok([]),
        BACKUP: ok([]),
    }


def test_update_reads_a_complete_network() -> None:
    """The happy path still assembles the account tree."""
    api = build_api(full_routes())

    account = api.update()
    network = account.networks[0]

    assert network.id == "1234567"
    assert network.name == "TestNetwork"
    assert network.thread_name == "eero-thread"
    assert sorted(client.name for client in network.clients) == [
        "Chloe iPad",
        "Office Printer",
    ]


def test_network_without_a_thread_resource(caplog) -> None:
    """A network with no Thread border router must not raise KeyError (H4)."""
    routes = {
        ACCOUNT: ok(fixture("account")),
        NETWORK: ok(fixture("network_no_thread")),
        DEVICES: ok(fixture("devices")),
    }
    api = build_api(routes)

    account = api.update()

    assert account.networks[0].name == "TestNetwork"
    assert account.networks[0].thread_enabled is None
    assert (THREAD not in [path for _, path in api.session.calls])


def test_network_missing_capabilities_updates_and_timezone() -> None:
    """Absent capability, updates and timezone blocks are all optional (H4)."""
    network = {
        "url": NETWORK,
        "name": "TestNetwork",
        "resources": {"devices": DEVICES},
    }
    api = build_api(
        {
            ACCOUNT: ok(fixture("account")),
            NETWORK: ok(network),
            DEVICES: ok([]),
        }
    )

    account = api.update()

    assert account.networks[0].target_firmware.os_version is None
    assert account.networks[0].firmware_history == []
    assert account.networks[0].preferred_update_hour is None


def test_network_entry_without_a_url_is_skipped() -> None:
    """A malformed networks entry is skipped, not fatal (H4)."""
    account_body = {"name": "Test Account", "networks": {"data": [{"name": "broken"}]}}
    api = build_api({ACCOUNT: ok(account_body)})

    account = api.update()

    assert account.networks == []
    assert api.session.calls == [("GET", ACCOUNT)]


def test_empty_account_response_raises() -> None:
    """A body with no networks member is a failed poll, not zero entities (N6)."""
    api = build_api({ACCOUNT: ok({})})

    with pytest.raises(eero_api.EeroException):
        api.update()


def test_null_account_response_raises() -> None:
    """Same for a 200 carrying no data at all (N6)."""
    api = build_api({ACCOUNT: ok(None)})

    with pytest.raises(eero_api.EeroException):
        api.update()


def test_update_raises_rather_than_returning_stale_data() -> None:
    """A failed poll must not quietly return the last good tree (C4)."""
    api = build_api(full_routes())
    api.update()
    assert api.data.networks

    api.session.routes[ACCOUNT] = [
        FakeResponse(
            {"meta": {"code": 500, "error": "error.internal"}},
            status_code=500,
            reason="Internal Server Error",
        )
    ]

    with pytest.raises(eero_api.EeroException):
        api.update()


def test_resource_that_disappears_between_polls() -> None:
    """A client removed from the Eero app is simply gone from resources (H3)."""
    api = build_api(full_routes())
    before = api.update().networks[0]
    client_id = "aa:bb:cc:dd:ee:ff"
    assert client_id in [resource.id for resource in before.resources]

    remaining = [
        device
        for device in fixture("devices")
        if device["mac"] != client_id
    ]
    api.session.routes[DEVICES] = [ok(remaining)]
    after = api.update().networks[0]

    ids = [resource.id for resource in after.resources]
    assert client_id not in ids
    assert "11:22:33:44:55:66" in ids
