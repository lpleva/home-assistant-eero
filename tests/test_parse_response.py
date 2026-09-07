"""Tests for EeroAPI response parsing (audit C2, C3, H1, M1, M2)."""

from __future__ import annotations

import pytest
import requests

from helpers import FakeResponse, build_api, eero_api, fixture, ok

ACCOUNT = "/2.2/account"
REFRESH = "/2.2/login/refresh"


def expired(name: str = "error_session_expired") -> FakeResponse:
    """Return a 401 whose body says the session is no longer valid."""
    return FakeResponse(fixture(name), status_code=401, reason="Unauthorized")


def test_successful_call_returns_data() -> None:
    """A 200 returns the data member and sends a timeout."""
    api = build_api({ACCOUNT: ok(fixture("account"))})

    account = api.call(method="GET", url=ACCOUNT)

    assert account["name"] == "Test Account"
    assert api.session.calls == [("GET", ACCOUNT)]


def test_expired_session_is_refreshed_once_then_retried() -> None:
    """A 401 refreshes the session once and retries the original request."""
    api = build_api(
        {
            ACCOUNT: [expired(), ok(fixture("account"))],
            REFRESH: ok(fixture("login_refresh")["data"]),
        }
    )

    account = api.call(method="GET", url=ACCOUNT)

    assert account["name"] == "Test Account"
    assert api.user_token == "NEW-TOKEN"
    assert api.session.calls == [
        ("GET", ACCOUNT),
        ("POST", REFRESH),
        ("GET", ACCOUNT),
    ]


def test_refresh_that_does_not_restore_access_raises_and_stops() -> None:
    """A retry that fails again raises instead of recursing (C3)."""
    api = build_api(
        {
            ACCOUNT: expired(),
            REFRESH: ok(fixture("login_refresh")["data"]),
        }
    )

    with pytest.raises(eero_api.EeroSessionExpired):
        api.call(method="GET", url=ACCOUNT)

    assert api.session.calls == [
        ("GET", ACCOUNT),
        ("POST", REFRESH),
        ("GET", ACCOUNT),
    ]


def test_rejected_refresh_does_not_refresh_again() -> None:
    """A 401 from the refresh endpoint itself terminates immediately (C3)."""
    api = build_api({ACCOUNT: expired(), REFRESH: expired("error_session_refresh")})

    with pytest.raises(eero_api.EeroSessionExpired):
        api.call(method="GET", url=ACCOUNT)

    assert api.session.calls == [("GET", ACCOUNT), ("POST", REFRESH)]


def test_refresh_without_a_token_raises_session_expired() -> None:
    """A refresh that returns no user_token is a dead session, not a KeyError."""
    api = build_api({ACCOUNT: expired(), REFRESH: ok({})})

    with pytest.raises(eero_api.EeroSessionExpired):
        api.call(method="GET", url=ACCOUNT)


def test_refreshed_token_is_handed_to_the_callback() -> None:
    """The rotated token is published so it can be persisted (H2)."""
    tokens: list[str] = []
    api = build_api(
        {
            ACCOUNT: [expired(), ok(fixture("account"))],
            REFRESH: ok(fixture("login_refresh")["data"]),
        },
        token_callback=tokens.append,
    )

    api.call(method="GET", url=ACCOUNT)

    assert tokens == ["NEW-TOKEN"]


def test_rate_limited_carries_retry_after() -> None:
    """429 raises EeroRateLimited with the Retry-After value (M2)."""
    api = build_api(
        {
            ACCOUNT: FakeResponse(
                fixture("error_rate_limited"),
                status_code=429,
                reason="Too Many Requests",
                headers={"Retry-After": "42"},
            )
        }
    )

    with pytest.raises(eero_api.EeroRateLimited) as caught:
        api.call(method="GET", url=ACCOUNT)

    assert caught.value.retry_after == 42.0
    assert api.session.calls == [("GET", ACCOUNT)]


def test_rate_limited_without_a_usable_header() -> None:
    """A missing or unparseable Retry-After is None, not a crash."""
    api = build_api(
        {
            ACCOUNT: FakeResponse(
                fixture("error_rate_limited"),
                status_code=429,
                reason="Too Many Requests",
                headers={"Retry-After": "soon"},
            )
        }
    )

    with pytest.raises(eero_api.EeroRateLimited) as caught:
        api.call(method="GET", url=ACCOUNT)

    assert caught.value.retry_after is None


def test_server_error_never_carries_the_response_body() -> None:
    """The exception must not repeat secrets from the body or the query (C2)."""
    body = fixture("error_server")
    api = build_api(
        {
            ACCOUNT: FakeResponse(
                body,
                status_code=500,
                reason="Internal Server Error",
                url="https://api-user.e2ro.com/2.2/account?token=SECRET",
            )
        }
    )

    with pytest.raises(eero_api.EeroException) as caught:
        api.call(method="GET", url=ACCOUNT)

    message = str(caught.value)
    assert "the-wifi-password" not in message
    assert body["data"]["thread"]["master_key"] not in message
    assert "SECRET" not in message
    assert "/2.2/account" in message


def test_transport_failure_becomes_an_eero_exception() -> None:
    """A ConnectionError is an EeroException, not an escaping crash (H1)."""
    api = build_api({ACCOUNT: ok(fixture("account"))})

    def explode(*args, **kwargs):
        raise requests.exceptions.ConnectionError("no route to host")

    api.session.get = explode

    with pytest.raises(eero_api.EeroException) as caught:
        api.call(method="GET", url=ACCOUNT)

    assert "ConnectionError" in str(caught.value)


def test_timeouts_become_an_eero_exception() -> None:
    """A socket timeout is an EeroException (H1)."""
    api = build_api({ACCOUNT: ok(fixture("account"))})

    def explode(*args, **kwargs):
        raise requests.exceptions.Timeout

    api.session.get = explode

    with pytest.raises(eero_api.EeroException) as caught:
        api.call(method="GET", url=ACCOUNT)

    assert "timed out" in str(caught.value)


def test_non_json_body_raises_rather_than_returning_none() -> None:
    """An HTML error page is an EeroException."""
    api = build_api({ACCOUNT: FakeResponse(text="<html>gateway error</html>")})

    with pytest.raises(eero_api.EeroException) as caught:
        api.call(method="GET", url=ACCOUNT)

    assert "decode" in str(caught.value)


def test_json_that_is_not_an_object_raises() -> None:
    """A JSON list would break .get(); it raises instead."""
    api = build_api({ACCOUNT: FakeResponse(["nope"])})

    with pytest.raises(eero_api.EeroException):
        api.call(method="GET", url=ACCOUNT)


def test_unknown_method_makes_no_request() -> None:
    """An unsupported method returns None without touching the network."""
    api = build_api({ACCOUNT: ok(fixture("account"))})

    assert api.call(method="PATCH", url=ACCOUNT) is None
    assert api.session.calls == []
