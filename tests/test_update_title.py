"""The update entity's title: no trailing copy of the latest version.

Covers the reimplementation of the one new idea in upstream PR #176. Home
Assistant prints the title followed by the latest version, so eero's
"eeroOS 7.17.2" showed as "eeroOS 7.17.2 v7.17.2".
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "eero"
    / "update_title.py"
)
spec = importlib.util.spec_from_file_location("eero_update_title", MODULE)
ut = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ut)


def test_drops_the_version_eero_puts_on_the_title() -> None:
    # The live values on the house network, 2026-10-09.
    assert ut.firmware_title("eeroOS 7.17.2", "v7.17.2") == "eeroOS"


def test_matches_with_or_without_a_leading_v() -> None:
    assert ut.firmware_title("eeroOS v7.17.2", "v7.17.2") == "eeroOS"
    assert ut.firmware_title("eeroOS 7.17.2", "7.17.2") == "eeroOS"
    assert ut.firmware_title("eeroOS v7.17.2", "7.17.2") == "eeroOS"


def test_title_without_a_version_is_left_alone() -> None:
    # Upstream's rsplit would have turned this into "eero".
    assert ut.firmware_title("eero OS", "v7.17.2") == "eero OS"
    assert ut.firmware_title("eeroOS", "v7.17.2") == "eeroOS"


def test_a_different_version_on_the_title_is_left_alone() -> None:
    # Not a copy of the latest version, so it carries information.
    assert ut.firmware_title("eeroOS 7.16.1", "v7.17.2") == "eeroOS 7.16.1"


def test_a_title_that_is_only_the_version_is_left_alone() -> None:
    assert ut.firmware_title("7.17.2", "v7.17.2") == "7.17.2"


def test_missing_values_pass_through() -> None:
    assert ut.firmware_title(None, "v7.17.2") is None
    assert ut.firmware_title("eeroOS 7.17.2", None) == "eeroOS 7.17.2"
    assert ut.firmware_title("", "v7.17.2") == ""
    assert ut.firmware_title("eeroOS 7.17.2", "v") == "eeroOS 7.17.2"
