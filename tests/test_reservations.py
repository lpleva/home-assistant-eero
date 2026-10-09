"""DHCP reservations (port of upstream PR #173): input checks and the API calls.

The services add a write surface to the router, so these pin down that bad
input is refused before any request, that a create or delete hits exactly one
record with exactly the expected body, and that API failures propagate.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from helpers import FakeResponse, build_api, eero_api, fixture, ok

MODULE = Path(__file__).resolve().parents[1] / "custom_components" / "eero" / "reservations.py"
spec = importlib.util.spec_from_file_location("eero_reservations", MODULE)
rv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rv)

ACCOUNT = "/2.2/account"
NETWORK = "/2.2/networks/1234567"
DEVICES = f"{NETWORK}/devices"
THREAD = f"{NETWORK}/thread"
PROFILES = f"{NETWORK}/profiles"
BACKUP = f"{NETWORK}/backup_access_points"
RESERVATIONS = f"{NETWORK}/reservations"

IPAD = {"url": f"{RESERVATIONS}/r1", "mac": "aa:bb:cc:dd:ee:ff", "ip": "192.168.4.21", "description": "Chloe iPad"}
PRINTER = {"url": f"{RESERVATIONS}/r2", "mac": "11:22:33:44:55:66", "ip": "192.168.4.30", "description": ""}


def routes(reservations=None, network=None) -> dict:
    """Routes for the fixture network; reservations defaults to the two records."""
    return {
        ACCOUNT: ok(fixture("account")),
        NETWORK: ok(network if network is not None else fixture("network")),
        THREAD: ok(fixture("thread")),
        DEVICES: ok(fixture("devices")),
        PROFILES: ok([]),
        BACKUP: ok([]),
        RESERVATIONS: ok([IPAD, PRINTER] if reservations is None else reservations),
    }


# ----------------------------------------------------------------- input checks


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("AA:BB:CC:DD:EE:FF", "aa:bb:cc:dd:ee:ff"),
        ("aa-bb-cc-dd-ee-01", "aa:bb:cc:dd:ee:01"),
        ("  aa:bb:cc:dd:ee:ff ", "aa:bb:cc:dd:ee:ff"),
    ],
)
def test_mac_is_normalized(raw, expected) -> None:
    assert rv.normalize_mac(raw) == expected


@pytest.mark.parametrize(
    "bad",
    [
        "", None, "aabbccddeeff", "aa:bb:cc:dd:ee", "aa:bb:cc:dd:ee:ff:00",
        "aa:bb:cc:dd:ee:gg", "aa:bb-cc:dd:ee:ff", "ff:ff:ff:ff:ff:ff",
        "00:00:00:00:00:00", "01:00:5e:00:00:01", "192.168.4.21",
        "aa:bb:cc:dd:ee:ff; rm", "aa:bb:cc:dd:ee:ff\nx",
    ],
)
def test_bad_mac_is_refused(bad) -> None:
    with pytest.raises(ValueError):
        rv.normalize_mac(bad)


def test_ip_must_be_a_host_inside_the_subnet() -> None:
    subnet, gateway = "192.168.4.0/22", "192.168.4.1"
    assert rv.validate_reservation_ip("192.168.4.21", subnet, gateway) == "192.168.4.21"
    assert rv.validate_reservation_ip(" 192.168.7.254 ", subnet, gateway) == "192.168.7.254"
    for bad in [
        "192.168.8.1",      # outside
        "10.0.0.5",         # outside
        "192.168.4.0",      # network address
        "192.168.7.255",    # broadcast
        "192.168.4.1",      # the router
        "192.168.4",        # not an address
        "192.168.4.300",
        "::1",
        "2001:db8::1",
        "", None, "192.168.4.21/32", "192.168.4.21 ",
        "127.0.0.1", "224.0.0.1", "0.0.0.0", "169.254.1.1",
    ]:
        if bad == "192.168.4.21 ":
            continue  # whitespace is trimmed; not a failure case
        with pytest.raises(ValueError):
            rv.validate_reservation_ip(bad, subnet, gateway)


def test_custom_subnet_is_read_as_cidr_from_a_gateway_address() -> None:
    """A custom DHCP block gives the router's own address plus a mask."""
    assert rv.validate_reservation_ip("10.0.0.50", "10.0.0.1/255.255.255.0") == "10.0.0.50"
    with pytest.raises(ValueError):
        rv.validate_reservation_ip("10.0.1.50", "10.0.0.1/255.255.255.0")


def test_unknown_subnet_falls_back_to_private_addresses() -> None:
    assert rv.validate_reservation_ip("192.168.1.50", None) == "192.168.1.50"
    assert rv.validate_reservation_ip("10.1.2.3", None) == "10.1.2.3"
    for bad in ["8.8.8.8", "1.1.1.1", "127.0.0.1", "0.0.0.0"]:
        with pytest.raises(ValueError):
            rv.validate_reservation_ip(bad, None)


def test_name_is_trimmed_and_bounded() -> None:
    assert rv.clean_reservation_name("  Chloe iPad ") == "Chloe iPad"
    assert rv.clean_reservation_name(None) == ""
    assert rv.clean_reservation_name("x" * 64) == "x" * 64
    with pytest.raises(ValueError):
        rv.clean_reservation_name("x" * 65)
    with pytest.raises(ValueError):
        rv.clean_reservation_name("line\nbreak")
    with pytest.raises(ValueError):
        rv.clean_reservation_name("tab\tcontrol\x00")


def test_duplicate_mac_or_ip_is_refused_before_any_call() -> None:
    existing = [IPAD, PRINTER]
    rv.check_reservation_is_new(existing, "de:ad:be:ef:00:01", "192.168.4.40")
    with pytest.raises(ValueError, match="already has a reservation"):
        rv.check_reservation_is_new(existing, "aa:bb:cc:dd:ee:ff", "192.168.4.40")
    with pytest.raises(ValueError, match="already reserved"):
        rv.check_reservation_is_new(existing, "de:ad:be:ef:00:01", "192.168.4.30")
    rv.check_reservation_is_new(None, "aa:bb:cc:dd:ee:ff", "192.168.4.21")  # unknown: router decides


def test_find_reservation_targets_exactly_one() -> None:
    assert rv.find_reservation([IPAD, PRINTER], "aa:bb:cc:dd:ee:ff") is IPAD
    assert rv.find_reservation([{"mac": "AA-BB-CC-DD-EE-FF"}], "aa:bb:cc:dd:ee:ff") is not None
    assert rv.find_reservation([PRINTER], "aa:bb:cc:dd:ee:ff") is None
    with pytest.raises(ValueError, match="could not be read"):
        rv.find_reservation(None, "aa:bb:cc:dd:ee:ff")
    with pytest.raises(ValueError, match="2 reservations"):
        rv.find_reservation([IPAD, dict(IPAD)], "aa:bb:cc:dd:ee:ff")


def test_select_one_network() -> None:
    assert rv.select_one(["n1"], "network", "name it") == "n1"
    with pytest.raises(ValueError, match="no network matches"):
        rv.select_one([], "network", "name it")
    with pytest.raises(ValueError, match="2 networks match; name it"):
        rv.select_one(["n1", "n2"], "network", "name it")


# ------------------------------------------------------------------- the reads


def test_update_reads_reservations_and_clients_see_theirs() -> None:
    api = build_api(routes())
    network = api.update().networks[0]

    assert network.reservations == [IPAD, PRINTER]
    ipad = next(c for c in network.clients if c.mac == "aa:bb:cc:dd:ee:ff")
    assert ipad.is_reserved is True
    assert ipad.reserved_ip == "192.168.4.21"
    assert ("GET", RESERVATIONS) in api.session.calls
    assert [b for b in api.session.bodies if b[0] != "GET"] == []  # a poll never writes


def test_resource_map_url_wins_over_the_standard_path() -> None:
    network = dict(fixture("network"))
    network["resources"] = dict(network["resources"], reservations=f"{NETWORK}/custom_reservations")
    r = routes(network=network)
    r[f"{NETWORK}/custom_reservations"] = ok([IPAD])
    api = build_api(r)

    assert api.update().networks[0].reservations == [IPAD]
    assert ("GET", RESERVATIONS) not in api.session.calls


def test_failed_reservations_fetch_warns_once_and_leaves_the_rest_usable(caplog) -> None:
    """A 500 on reservations is logged once; devices and trackers carry on."""
    r = routes()
    r[RESERVATIONS] = FakeResponse(
        {"meta": {"code": 500, "error": "error.internal"}}, status_code=500, reason="Internal Server Error"
    )
    api = build_api(r)

    network = api.update().networks[0]
    assert network.reservations is None
    assert [c.name for c in network.clients]
    assert next(iter(network.clients)).is_reserved is None
    assert sum("Could not read DHCP reservations" in rec.message for rec in caplog.records) == 1

    api.update()
    assert sum("Could not read DHCP reservations" in rec.message for rec in caplog.records) == 1

    api.session.routes[RESERVATIONS] = [ok([IPAD])]
    assert api.update().networks[0].reservations == [IPAD]


def test_unexpected_reservations_shape_is_unknown_not_a_crash() -> None:
    r = routes()
    r[RESERVATIONS] = ok({"weird": True})
    assert build_api(r).update().networks[0].reservations is None
    r[RESERVATIONS] = ok(["not", "dicts"])
    assert build_api(r).update().networks[0].reservations is None
    r[RESERVATIONS] = ok(None)
    assert build_api(r).update().networks[0].reservations == []


def test_expired_session_on_reservations_is_not_swallowed() -> None:
    """A dead session must reach the reauth path (C3), not become a warning."""
    r = routes()
    r[RESERVATIONS] = FakeResponse(fixture("error_session_expired"), status_code=401, reason="Unauthorized")
    r["/2.2/login/refresh"] = FakeResponse(fixture("error_session_refresh"), status_code=401, reason="Unauthorized")
    with pytest.raises(eero_api.EeroSessionExpired):
        build_api(r).update()


def test_lan_subnet_from_dhcp_block() -> None:
    def net(dhcp):
        body = dict(fixture("network"))
        if dhcp is not None:
            body["dhcp"] = dhcp
        return build_api(routes(network=body)).update().networks[0]

    n = net({"mode": "automatic"})
    assert (n.lan_subnet, n.lan_gateway_ip) == ("192.168.4.0/22", "192.168.4.1")
    n = net({"mode": "custom", "custom": {"subnet_ip": "10.0.0.1", "subnet_mask": "255.255.255.0"}})
    assert (n.lan_subnet, n.lan_gateway_ip) == ("10.0.0.1/255.255.255.0", "10.0.0.1")
    n = net(None)
    assert (n.lan_subnet, n.lan_gateway_ip) == (None, None)
    n = net({"mode": "bridge", "custom": None})
    assert (n.lan_subnet, n.lan_gateway_ip) == (None, None)


# ------------------------------------------------------------------ the writes


def test_create_posts_one_record_to_the_network_collection() -> None:
    r = routes()
    r[RESERVATIONS] = [ok([IPAD, PRINTER]), ok({"url": f"{RESERVATIONS}/r3"})]
    api = build_api(r)
    network = api.update().networks[0]

    result = network.create_reservation("de:ad:be:ef:00:01", "192.168.4.40", "Lamp")

    assert result == {"url": f"{RESERVATIONS}/r3"}
    writes = [b for b in api.session.bodies if b[0] != "GET"]
    assert writes == [
        ("POST", RESERVATIONS, {"mac": "de:ad:be:ef:00:01", "ip": "192.168.4.40", "description": "Lamp"})
    ]


def test_delete_hits_the_record_url_and_nothing_else() -> None:
    r = routes()
    r[f"{RESERVATIONS}/r1"] = ok(None)
    api = build_api(r)
    network = api.update().networks[0]

    network.delete_reservation(IPAD)

    writes = [b for b in api.session.bodies if b[0] != "GET"]
    assert writes == [("DELETE", f"{RESERVATIONS}/r1", None)]


def test_delete_builds_the_url_from_an_id_but_never_from_nothing() -> None:
    r = routes()
    r[f"{RESERVATIONS}/77"] = ok(None)
    api = build_api(r)
    network = api.update().networks[0]

    network.delete_reservation({"id": 77, "mac": "aa:bb:cc:dd:ee:ff"})
    assert ("DELETE", f"{RESERVATIONS}/77") in api.session.calls

    before = list(api.session.calls)
    with pytest.raises(ValueError):
        network.delete_reservation({"mac": "aa:bb:cc:dd:ee:ff"})
    with pytest.raises(ValueError):
        network.delete_reservation({"url": RESERVATIONS, "mac": "aa:bb:cc:dd:ee:ff"})  # the collection
    with pytest.raises(ValueError):
        network.delete_reservation({"url": "/2.2/networks/9/reservations/1"})  # another network
    assert api.session.calls == before


def test_api_errors_on_writes_propagate() -> None:
    r = routes()
    r[RESERVATIONS] = [
        ok([IPAD]),
        FakeResponse({"meta": {"code": 400, "error": "error.invalid"}}, status_code=400, reason="Bad Request"),
    ]
    r[f"{RESERVATIONS}/r1"] = FakeResponse(
        {"meta": {"code": 500, "error": "error.internal"}}, status_code=500, reason="Internal Server Error"
    )
    api = build_api(r)
    network = api.update().networks[0]

    with pytest.raises(eero_api.EeroException):
        network.create_reservation("de:ad:be:ef:00:01", "192.168.4.40", "")
    with pytest.raises(eero_api.EeroException):
        network.delete_reservation(IPAD)
