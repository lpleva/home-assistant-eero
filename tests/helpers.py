"""Test helpers: load the api package and fake the network.

The api package is loaded under its own name because its real parent,
custom_components.eero, imports homeassistant, and these tests run without
Home Assistant installed.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "custom_components" / "eero" / "api"
FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_api():
    """Load custom_components/eero/api as a standalone package."""
    if (module := sys.modules.get("eero_api")) is not None:
        return module
    spec = importlib.util.spec_from_file_location(
        "eero_api",
        API_DIR / "__init__.py",
        submodule_search_locations=[str(API_DIR)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["eero_api"] = module
    spec.loader.exec_module(module)
    return module


eero_api = load_api()


def fixture(name: str) -> Any:
    """Return a recorded response body."""
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text())


class FakeResponse:
    """Stand-in for requests.Response."""

    def __init__(
        self,
        body: Any = None,
        status_code: int = 200,
        reason: str = "OK",
        url: str = "https://api-user.e2ro.com/2.2/account?secret=abc",
        headers: dict[str, str] | None = None,
        text: str | None = None,
    ) -> None:
        """Initialize."""
        self.status_code = status_code
        self.reason = reason
        self.url = url
        self.headers = headers or {}
        self.text = json.dumps(body) if text is None else text

    @property
    def ok(self) -> bool:
        """Match requests.Response.ok."""
        return self.status_code < 400


class FakeSession:
    """Stand-in for requests.Session.

    routes maps a URL path to either a response or a list of responses served
    in order; the last one repeats once the list is exhausted.
    """

    def __init__(self, routes: dict[str, Any]) -> None:
        """Initialize."""
        self.routes = {
            path: value if isinstance(value, list) else [value]
            for path, value in routes.items()
        }
        self.calls: list[tuple[str, str]] = []
        self.closed = False

    def _serve(self, method: str, url: str, **kwargs) -> FakeResponse:
        path = url.replace("https://api-user.e2ro.com", "")
        self.calls.append((method, path))
        assert "timeout" in kwargs, f"{method} {path} was sent with no timeout"
        if path not in self.routes:
            raise AssertionError(f"unexpected request: {method} {path}")
        responses = self.routes[path]
        return responses.pop(0) if len(responses) > 1 else responses[0]

    def get(self, url: str, **kwargs) -> FakeResponse:
        """GET."""
        return self._serve("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> FakeResponse:
        """POST."""
        return self._serve("POST", url, **kwargs)

    def put(self, url: str, **kwargs) -> FakeResponse:
        """PUT."""
        return self._serve("PUT", url, **kwargs)

    def delete(self, url: str, **kwargs) -> FakeResponse:
        """DELETE."""
        return self._serve("DELETE", url, **kwargs)

    def close(self) -> None:
        """Close."""
        self.closed = True


def build_api(routes: dict[str, Any], **kwargs) -> Any:
    """Return an EeroAPI wired to a fake session."""
    api = eero_api.EeroAPI(user_token="OLD-TOKEN", **kwargs)
    api.session = FakeSession(routes)
    return api


def ok(body: Any, **kwargs) -> FakeResponse:
    """Return a successful response carrying body as data."""
    return FakeResponse({"meta": {"code": 200}, "data": body}, **kwargs)
