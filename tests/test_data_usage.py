"""Tests for data usage totals and other partial payloads (audit H5, H7, L7, L8)."""

from __future__ import annotations

from helpers import eero_api

sum_data_usage = eero_api.util.sum_data_usage


class Usage:
    """Minimal stand-in exposing a (download, upload) pair."""

    def __init__(self, value) -> None:
        """Initialize."""
        self.data_usage_day = value


def network_with_activity(activity: dict):
    """Return an EeroNetwork carrying the given network activity block."""
    api = eero_api.EeroAPI()
    account = eero_api.EeroAccount(
        api,
        {
            "networks": {
                "data": [
                    {
                        "url": "/2.2/networks/1234567",
                        "name": "TestNetwork",
                        "activity": {"network": activity},
                    }
                ]
            }
        },
    )
    return account.networks[0]


def test_no_series_sums_to_none() -> None:
    """A period that has just rolled over has no series yet (H5)."""
    assert sum_data_usage(Usage((None, None)), "data_usage_day") is None


def test_one_direction_only() -> None:
    """A half-populated pair still sums (H5)."""
    assert sum_data_usage(Usage((1234, None)), "data_usage_day") == 1234
    assert sum_data_usage(Usage((None, 99)), "data_usage_day") == 99


def test_both_directions() -> None:
    """The ordinary case."""
    assert sum_data_usage(Usage((1000, 200)), "data_usage_day") == 1200


def test_zero_is_not_treated_as_missing() -> None:
    """Zero bytes is a real reading."""
    assert sum_data_usage(Usage((0, 0)), "data_usage_day") == 0


def test_network_reports_none_when_the_series_is_absent() -> None:
    """The API layer reports the pair as (None, None), not zero."""
    network = network_with_activity({})

    assert network.data_usage_day == (None, None)
    assert sum_data_usage(network, "data_usage_day") is None


def test_network_with_only_a_download_series() -> None:
    """Eero backfills the two directions separately."""
    network = network_with_activity(
        {"data_usage_day": [{"type": "download", "sum": 500}]}
    )

    assert network.data_usage_day == (500, None)
    assert sum_data_usage(network, "data_usage_day") == 500


def test_network_with_both_series() -> None:
    """Both directions present."""
    network = network_with_activity(
        {
            "data_usage_day": [
                {"type": "download", "sum": 500},
                {"type": "upload", "sum": 100},
            ]
        }
    )

    assert sum_data_usage(network, "data_usage_day") == 600


def test_release_notes_key_present_but_null() -> None:
    """get_release_notes returns None for a network with no manifest (H7)."""
    api = eero_api.EeroAPI()
    account = eero_api.EeroAccount(
        api,
        {
            "networks": {
                "data": [
                    {
                        "url": "/2.2/networks/1234567",
                        "updates": {"release_notes": None},
                    }
                ]
            }
        },
    )
    network = account.networks[0]

    assert network.firmware_history == []
    assert network.target_firmware.os_version is None


def test_preferred_update_hour_outside_the_map() -> None:
    """An unexpected hour returns None rather than raising ValueError (L7)."""
    api = eero_api.EeroAPI()
    account = eero_api.EeroAccount(
        api,
        {
            "networks": {
                "data": [
                    {
                        "url": "/2.2/networks/1234567",
                        "updates": {"preferred_update_hour": 99},
                    }
                ]
            }
        },
    )

    assert account.networks[0].preferred_update_hour is None


def test_client_signal_formats() -> None:
    """An unexpected signal string is (None, None), not an IndexError (L8)."""
    api = eero_api.EeroAPI()
    network = eero_api.EeroAccount(api, {}).networks

    def client(signal):
        return eero_api.client.EeroClient(
            api, network, {"connectivity": {"signal": signal}}
        )

    assert client("-42 dBm").signal == (-42, "dBm")
    assert client("-42").signal == (None, None)
    assert client("strong signal").signal == (None, None)
    assert client(None).signal == (None, None)


def test_name_unique_without_geo_ip() -> None:
    """A network with no geo_ip must not render None into the label (L6)."""
    api = eero_api.EeroAPI()
    account = eero_api.EeroAccount(
        api,
        {
            "networks": {
                "data": [
                    {"url": "/2.2/networks/1234567", "name": "TestNetwork"},
                    {
                        "url": "/2.2/networks/7654321",
                        "name": "Other",
                        "geo_ip": {"city": "Elgin", "regionName": "Illinois"},
                    },
                ]
            }
        },
    )

    assert account.networks[0].name_unique == "TestNetwork"
    assert account.networks[1].name_unique == "Other (Elgin, Illinois)"
