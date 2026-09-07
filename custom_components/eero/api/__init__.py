"""Eero API."""

from __future__ import annotations

from collections.abc import Callable
import datetime
import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests

from .account import EeroAccount
from .const import (
    ACTIVITY_MAP,
    API_ENDPOINT,
    CADENCE_DAILY,
    CADENCE_HOURLY,
    DEFAULT_REQUEST_TIMEOUT,
    METHOD_DELETE,
    METHOD_GET,
    METHOD_POST,
    METHOD_PUT,
    PERIOD_DAY,
    PERIOD_MONTH,
    PERIOD_WEEK,
    REDACT_KEYS,
    RESOURCE_MAP,
    URL_ACCOUNT,
)
from .util import backup_access_point_ok, premium_ok

_LOGGER = logging.getLogger(__name__)


class EeroException(Exception):
    """Error returned by the Eero API."""

    def __init__(
        self,
        code: int | None = None,
        error: str | None = None,
        message: str | None = None,
        server_time: str | None = None,
    ) -> None:
        """Initialize."""
        self.code = code
        self.error = error
        self.message = message
        self.server_time = server_time
        super().__init__(f"{message or 'Eero API error'} (code={code}, error={error})")


class EeroSessionExpired(EeroException):
    """The session is dead and cannot be refreshed."""


class EeroRateLimited(EeroException):
    """The Eero API is rate limiting this account."""

    def __init__(self, retry_after: float | None = None, **kwargs) -> None:
        """Initialize."""
        super().__init__(**kwargs)
        self.retry_after = retry_after


class EeroAPI:
    """EeroAPI."""

    ALLOWED_RELEASE_NOTE_HOSTS = frozenset({"eero.com", "e2ro.com"})

    def __init__(
        self,
        save_location: str | None = None,
        user_token: str | None = None,
        request_timeout: float | tuple[float, float] | None = None,
        token_callback: Callable[[str], None] | None = None,
    ) -> None:
        """Initialize."""
        self.data = EeroAccount(self, {})
        self.release_notes_cache: dict[str, dict[str, Any]] = {}
        self.save_location = save_location
        self.session = requests.Session()
        self.user_token = user_token
        self.request_timeout = request_timeout or DEFAULT_REQUEST_TIMEOUT
        self.token_callback = token_callback

    @property
    def cookie(self) -> dict:
        """Cookie."""
        if self.user_token:
            return {"s": self.user_token}
        return {}

    def call(
        self, method: str, url: str, allow_refresh: bool = True, **kwargs
    ) -> dict[str, Any] | None:
        """Call."""
        if method not in [METHOD_DELETE, METHOD_GET, METHOD_POST, METHOD_PUT]:
            return None
        _LOGGER.debug("Calling API with method: %s and URL: %s", method, url)
        kwargs.setdefault("timeout", self.request_timeout)
        if method == METHOD_DELETE:
            response = self.parse_response(
                lambda: self.session.delete(
                    url=f"{API_ENDPOINT}{url}", cookies=self.cookie, **kwargs
                ),
                allow_refresh=allow_refresh,
            )
        elif method == METHOD_GET:
            response = self.parse_response(
                lambda: self.session.get(
                    url=f"{API_ENDPOINT}{url}", cookies=self.cookie, **kwargs
                ),
                allow_refresh=allow_refresh,
            )
        elif method == METHOD_POST:
            response = self.parse_response(
                lambda: self.session.post(
                    url=f"{API_ENDPOINT}{url}", cookies=self.cookie, **kwargs
                ),
                allow_refresh=allow_refresh,
            )
        elif method == METHOD_PUT:
            response = self.parse_response(
                lambda: self.session.put(
                    url=f"{API_ENDPOINT}{url}", cookies=self.cookie, **kwargs
                ),
                allow_refresh=allow_refresh,
            )
        self.save_response(response=response, name=url)
        return response

    def define_period(self, period: str, timezone: str) -> tuple:
        """Define period."""
        # Imported here so this package can be imported, and unit tested,
        # without python-dateutil, which arrives with Home Assistant rather
        # than through this integration's requirements.
        from dateutil import relativedelta  # noqa: PLC0415

        start, end, cadence = None, None, None
        now = datetime.datetime.now(tz=ZoneInfo(timezone))
        if period == PERIOD_DAY:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = (
                start
                + relativedelta.relativedelta(days=1)
                - datetime.timedelta(seconds=1)
            )
            cadence = CADENCE_HOURLY
        elif period == PERIOD_WEEK:
            start = now - relativedelta.relativedelta(days=now.weekday() + 1)
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
            end = (
                start
                + relativedelta.relativedelta(weeks=1)
                - datetime.timedelta(seconds=1)
            )
            cadence = CADENCE_DAILY
        elif period == PERIOD_MONTH:
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            end = (
                start
                + relativedelta.relativedelta(months=1)
                - datetime.timedelta(seconds=1)
            )
            cadence = CADENCE_DAILY
        else:
            return (start, end, cadence)
        start = f"{start.astimezone(datetime.UTC).replace(tzinfo=None).isoformat()}Z"
        end = f"{end.astimezone(datetime.UTC).replace(tzinfo=None).isoformat()}Z"
        return (start, end, cadence)

    def get_release_notes(self, url: str | None) -> dict[str, Any] | None:
        """Get release notes.

        Cached by manifest URL: the manifest changes only when the firmware
        does, and refetching it every poll is a large share of this
        integration's request volume.
        """
        if not url:
            return None
        if url in self.release_notes_cache:
            return self.release_notes_cache[url]
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if parsed.scheme != "https" or not any(
            host == domain or host.endswith(f".{domain}")
            for domain in self.ALLOWED_RELEASE_NOTE_HOSTS
        ):
            _LOGGER.warning(
                "Refusing to fetch release notes from unexpected host: %s", host
            )
            return None
        # A bare request rather than self.session: the manifest URL comes from
        # the API response, and the session carries the account's cookie jar.
        response = self.raise_on_transport_error(
            lambda: requests.get(url=url, timeout=self.request_timeout)
        )
        if not response.ok:
            raise EeroException(
                code=response.status_code,
                error=response.reason,
                message="Unable to get release notes",
            )
        text = self.decode_json(response)
        self.save_response(response=text, name="release_notes")
        self.release_notes_cache[url] = text
        return text

    def login(self, login: str | int) -> dict[str, Any]:
        """Login."""
        _LOGGER.debug("Requesting login code")
        response = self.call(
            method=METHOD_POST,
            url="/2.2/login",
            json={"login": login},
        )
        if not response or not response.get("user_token"):
            raise EeroException(message="Login did not return a session token")
        self.user_token = response["user_token"]
        return response

    def login_refresh(self) -> dict[str, Any]:
        """Login refresh."""
        _LOGGER.debug("Refreshing session")
        response = self.call(
            method=METHOD_POST,
            url="/2.2/login/refresh",
            allow_refresh=False,
        )
        if not response or not response.get("user_token"):
            raise EeroSessionExpired(
                message="Session refresh did not return a session token"
            )
        self.user_token = response["user_token"]
        if self.token_callback:
            self.token_callback(self.user_token)
        return response

    def login_verify(self, code: str) -> dict[str, Any]:
        """Login verify."""
        _LOGGER.debug("Verifying login code")
        return self.call(
            method=METHOD_POST,
            url="/2.2/login/verify",
            json={"code": code},
        )

    def decode_json(self, response: requests.Response) -> dict[str, Any]:
        """Decode JSON."""
        try:
            decoded = json.loads(response.text)
        except json.decoder.JSONDecodeError as exception:
            raise EeroException(
                code=response.status_code,
                error=response.reason,
                message="Unable to decode JSON",
            ) from exception
        if not isinstance(decoded, dict):
            raise EeroException(
                code=response.status_code,
                error=response.reason,
                message=f"Expected a JSON object, got {type(decoded).__name__}",
            )
        return decoded

    def parse_response(
        self, function: Callable, allow_refresh: bool = True
    ) -> dict[str, Any] | None:
        """Parse response.

        Refreshes the session at most once. A session that cannot be refreshed
        raises EeroSessionExpired, which the integration turns into a reauth
        request rather than retrying forever.
        """
        response = self.raise_on_transport_error(function)
        if not response.ok:
            if response.status_code == 429:
                raise EeroRateLimited(
                    code=429,
                    error=response.reason,
                    message="Rate limited by the Eero API",
                    retry_after=self.retry_after(response),
                )
            meta = self.decode_json(response).get("meta", {})
            code, error = meta.get("code"), meta.get("error")
            session_dead = bool(
                code == 401
                and error in ("error.session.invalid", "error.session.refresh")
            )
            if session_dead and allow_refresh:
                _LOGGER.debug("Session has expired, refreshing once")
                self.login_refresh()
                response = self.raise_on_transport_error(function)
                if not response.ok:
                    raise EeroSessionExpired(
                        code=response.status_code,
                        error=response.reason,
                        message="Session refresh did not restore access",
                    )
            elif session_dead:
                raise EeroSessionExpired(
                    code=code,
                    error=error,
                    message="Session refresh was rejected",
                )
            else:
                raise EeroException(
                    code=response.status_code,
                    error=response.reason,
                    message=f"Bad response from {urlparse(response.url).path}",
                )
        return self.decode_json(response).get("data")

    @staticmethod
    def retry_after(response: requests.Response) -> float | None:
        """Return the Retry-After header in seconds, if the server sent a usable one."""
        try:
            return float(response.headers.get("Retry-After", ""))
        except (TypeError, ValueError):
            return None

    def raise_on_transport_error(self, function: Callable) -> requests.Response:
        """Run the request, converting a transport failure into an EeroException."""
        try:
            return function()
        except requests.exceptions.Timeout as exception:
            raise EeroException(
                message="Request timed out",
            ) from exception
        except requests.exceptions.RequestException as exception:
            raise EeroException(
                message=f"Request failed: {type(exception).__name__}",
            ) from exception

    def redact(self, obj: Any) -> Any:
        """Return a copy of obj with every secret value replaced."""
        if isinstance(obj, dict):
            return {
                key: ("**REDACTED**" if key in REDACT_KEYS else self.redact(value))
                for key, value in obj.items()
            }
        if isinstance(obj, list):
            return [self.redact(item) for item in obj]
        return obj

    def save_response(self, response: dict[str, Any] | None, name="response") -> None:
        """Save a redacted response for debugging.

        Auth exchanges are never written to disk: their bodies are the session
        token itself.
        """
        if not self.save_location or not response:
            return
        if name.startswith("/2.2/login"):
            _LOGGER.debug("Not saving response for auth endpoint: %s", name)
            return
        Path(self.save_location).mkdir(parents=True, exist_ok=True)
        name = name.replace("/", "_").replace(".", "_")
        file_path_name = f"{self.save_location}/{name}.json"
        _LOGGER.debug("Saving response: %s", file_path_name)
        with Path(file_path_name).open(mode="w", encoding="utf-8") as file:
            json.dump(
                obj=self.redact(response),
                fp=file,
                indent=4,
                default=lambda o: "not-serializable",
                sort_keys=True,
            )

    def update(
        self,
        config: dict[str, EeroUpdateConfig] | None = None,
    ) -> EeroAccount:
        """Update.

        Raises EeroException on failure; the caller decides what that means.
        """
        if config is None:
            config = {}
        account = self.call(method=METHOD_GET, url=URL_ACCOUNT) or {}
        networks = []
        for network in account.get("networks", {}).get("data", []):
            network_url = network.get("url")
            if not network_url:
                _LOGGER.debug("Skipping a network entry that reports no url")
                continue
            network_id = network_url.replace("/2.2/networks/", "")
            if any(
                [
                    not config,
                    network_id in config,
                ]
            ):
                network_data = self.call(method=METHOD_GET, url=network_url) or {}
                resources = network_data.get("resources", {})
                if thread_url := resources.get("thread"):
                    network_data["thread"] = self.call(
                        method=METHOD_GET,
                        url=thread_url,
                    )

                capabilities = network_data.get("capabilities", {})
                backup_access_point = capabilities.get("backup_access_point", {})
                if all(
                    [
                        any(
                            [
                                not config,
                                config.get(
                                    network_id, EeroUpdateConfig()
                                ).get_backup_access_points,
                            ]
                        ),
                        backup_access_point_ok(
                            capable=backup_access_point.get("capable"),
                            requirements=backup_access_point.get("requirements"),
                        ),
                        premium_ok(
                            capable=capabilities.get("premium", {}).get("capable"),
                            status=network_data.get("premium_status"),
                        ),
                    ]
                ):
                    backup_access_points = (
                        self.call(
                            method=METHOD_GET,
                            url=f"{network_url}/backup_access_points",
                        )
                        or []
                    )
                    network_data["backup_access_points"] = {
                        "count": len(backup_access_points),
                        "data": backup_access_points,
                    }

                if any(
                    [
                        not config,
                        config.get(network_id, EeroUpdateConfig()).get_devices,
                    ]
                ):
                    network_data["devices"] = self.get_resource_data(
                        network_data, "devices"
                    )

                if any(
                    [
                        not config,
                        config.get(network_id, EeroUpdateConfig()).get_profiles,
                    ]
                ):
                    network_data["profiles"] = self.get_resource_data(
                        network_data, "profiles"
                    )

                update_data = network_data.get("updates") or {}
                if config.get(network_id, EeroUpdateConfig()).get_release_notes:
                    try:
                        update_data["release_notes"] = self.get_release_notes(
                            url=update_data.get("manifest_resource"),
                        )
                    except EeroException as error:
                        # Release notes only decorate the update entities.
                        # Losing them must not take the rest of the network,
                        # including the device trackers, unavailable.
                        _LOGGER.warning("Could not fetch release notes: %s", error)
                network_data["updates"] = update_data

                timezone = network_data.get("timezone", {}).get("value") or "UTC"
                activity_data = {}
                for resource, activities in config.get(
                    network_id, EeroUpdateConfig()
                ).activity.items():
                    resource = RESOURCE_MAP.get(resource, resource)
                    activity_data[resource] = {}
                    for activity in activities:
                        if resource == "profiles":
                            activity_data[resource][activity] = {}
                            for profile_id in config.get(
                                network_id, EeroUpdateConfig()
                            ).profiles:
                                activity_data[resource][activity][profile_id] = (
                                    self.update_activity(
                                        activity=activity,
                                        network_url=network_url,
                                        profile_id=profile_id,
                                        resource=resource,
                                        timezone=timezone,
                                    )
                                )
                        else:
                            activity_data[resource][activity] = (
                                self.update_activity(
                                    activity=activity,
                                    network_url=network_url,
                                    profile_id=None,
                                    resource=resource,
                                    timezone=timezone,
                                )
                            )
                network_data["activity"] = activity_data
                networks.append(network_data)
        account.setdefault("networks", {})["data"] = networks
        self.save_response(response=account, name="update_data")
        self.data = EeroAccount(self, account)
        return self.data

    def get_resource_data(
        self,
        network_data: dict,
        resource: str,
    ) -> dict:
        """Get resource data."""
        url = network_data.get("resources", {}).get(resource)
        if not url:
            _LOGGER.debug("Network reports no %s resource", resource)
            return {"count": 0, "data": []}
        resource_data = self.call(method=METHOD_GET, url=url) or []
        return {
            "count": len(resource_data),
            "data": resource_data,
        }

    def update_activity(
        self,
        activity: str,
        network_url: str,
        profile_id: int,
        resource: str,
        timezone: str,
    ) -> list[dict]:
        """Update activity."""
        activity_url = ACTIVITY_MAP[activity][0].format(network_url)
        if resource != "network":
            activity_url = f"{activity_url}/{resource}"
        if resource == "profiles":
            activity_url = f"{activity_url}/{profile_id}"
        start, end, cadence = self.define_period(
            period=ACTIVITY_MAP[activity][2],
            timezone=timezone,
        )
        json_data = {
            "start": start,
            "end": end,
            "cadence": cadence,
            "timezone": timezone,
        }
        if ACTIVITY_MAP[activity][1]:
            json_data["insight_type"] = ACTIVITY_MAP[activity][1]
        data = (
            self.call(
                method=METHOD_GET,
                url=activity_url,
                json=json_data,
            )
            or {}
        )
        return data.get("insights", data.get("series", data.get("values")))


class EeroUpdateConfig:
    """A class that describes an Eero update config."""

    def __init__(
        self,
        activity: dict | None = None,
        profiles: list | None = None,
        get_backup_access_points: bool = False,
        get_devices: bool = False,
        get_release_notes: bool = False,
    ) -> None:
        """Initialize."""
        self.activity = activity
        self.profiles = profiles
        self.get_backup_access_points = get_backup_access_points
        self.get_devices = get_devices
        self.get_profiles = bool(profiles)
        self.get_release_notes = get_release_notes
        if self.activity is None:
            self.activity = {}
        if self.profiles is None:
            self.profiles = []
