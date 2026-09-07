"""Tests for saved responses and the release-notes fetch (audit C1, M2, M5)."""

from __future__ import annotations

import json

from helpers import FakeResponse, build_api, eero_api, fixture, ok

ACCOUNT = "/2.2/account"
NETWORK = "/2.2/networks/1234567"
REFRESH = "/2.2/login/refresh"
MANIFEST = "https://api-user.e2ro.com/2.2/updates/manifest-7.1.0"


def test_saved_responses_are_redacted(tmp_path) -> None:
    """Secrets never reach the saved file (C1)."""
    api = build_api({NETWORK: ok(fixture("network"))}, save_location=str(tmp_path))
    api.session.routes[f"{NETWORK}/thread"] = [ok(fixture("thread"))]

    api.call(method="GET", url=NETWORK)
    api.call(method="GET", url=f"{NETWORK}/thread")

    saved = json.loads((tmp_path / "_2_2_networks_1234567.json").read_text())
    assert saved["password"] == "**REDACTED**"
    assert saved["name"] == "TestNetwork"

    thread = json.loads((tmp_path / "_2_2_networks_1234567_thread.json").read_text())
    assert thread["master_key"] == "**REDACTED**"
    assert thread["active_operational_dataset"] == "**REDACTED**"
    assert thread["channel"] == 15


def test_nested_and_listed_secrets_are_redacted(tmp_path) -> None:
    """Redaction walks lists and nested dicts (C1)."""
    api = build_api({}, save_location=str(tmp_path))

    api.save_response(
        response={
            "devices": [{"nickname": "iPad", "psk": "hunter2"}],
            "guest_network": {"password": "guest-pass"},
        },
        name="update_data",
    )

    saved = json.loads((tmp_path / "update_data.json").read_text())
    assert saved["devices"][0]["psk"] == "**REDACTED**"
    assert saved["devices"][0]["nickname"] == "iPad"
    assert saved["guest_network"]["password"] == "**REDACTED**"


def test_auth_responses_are_never_written(tmp_path) -> None:
    """The login exchange is the token itself, so it is never saved (C1)."""
    api = build_api(
        {
            ACCOUNT: [
                FakeResponse(
                    fixture("error_session_expired"),
                    status_code=401,
                    reason="Unauthorized",
                ),
                ok(fixture("account")),
            ],
            REFRESH: ok(fixture("login_refresh")["data"]),
        },
        save_location=str(tmp_path),
    )

    api.call(method="GET", url=ACCOUNT)

    written = sorted(path.name for path in tmp_path.iterdir())
    assert written == ["_2_2_account.json"]
    assert "NEW-TOKEN" not in (tmp_path / "_2_2_account.json").read_text()


def test_nothing_is_written_without_a_save_location(tmp_path) -> None:
    """Saving is off by default."""
    api = build_api({ACCOUNT: ok(fixture("account"))})

    api.call(method="GET", url=ACCOUNT)

    assert list(tmp_path.iterdir()) == []


def test_release_notes_rejects_an_unexpected_host() -> None:
    """A manifest URL pointing off eero's domains is not fetched (M5)."""
    api = build_api({})

    assert api.get_release_notes("https://evil.example.com/manifest") is None
    assert api.get_release_notes("http://api-user.e2ro.com/manifest") is None
    assert api.get_release_notes(None) is None


def test_release_notes_are_fetched_once_per_url(monkeypatch) -> None:
    """The manifest is cached rather than refetched every poll (M2)."""
    api = build_api({})
    calls: list[str] = []

    def fake_get(url, **kwargs):
        calls.append(url)
        assert "timeout" in kwargs
        return FakeResponse({"target": {"os_version": "7.1.0"}})

    monkeypatch.setattr(eero_api.requests, "get", fake_get)

    first = api.get_release_notes(MANIFEST)
    second = api.get_release_notes(MANIFEST)

    assert first == second == {"target": {"os_version": "7.1.0"}}
    assert calls == [MANIFEST]


def test_a_failed_release_notes_fetch_does_not_fail_the_poll(
    monkeypatch, caplog
) -> None:
    """A 404 on the firmware manifest is a warning, not a dead network (N2)."""
    from eero_api import EeroUpdateConfig

    network = "/2.2/networks/1234567"
    api = build_api(
        {
            ACCOUNT: ok(fixture("account")),
            network: ok(fixture("network")),
            f"{network}/thread": ok(fixture("thread")),
            f"{network}/devices": ok(fixture("devices")),
            f"{network}/profiles": ok([]),
            f"{network}/backup_access_points": ok([]),
        }
    )

    def not_found(url, **kwargs):
        return FakeResponse({}, status_code=404, reason="Not Found", url=url)

    monkeypatch.setattr(eero_api.requests, "get", not_found)

    account = api.update({"1234567": EeroUpdateConfig(get_release_notes=True)})

    assert account.networks[0].name == "TestNetwork"
    assert account.networks[0].firmware_history == []
    assert "Could not fetch release notes" in caplog.text


def test_a_rejected_host_warns_once(caplog) -> None:
    """The refusal is cached, so it does not warn on every poll (N3)."""
    api = build_api({})

    assert api.get_release_notes("https://evil.example.com/manifest") is None
    assert api.get_release_notes("https://evil.example.com/manifest") is None

    assert caplog.text.count("Refusing to fetch release notes") == 1
