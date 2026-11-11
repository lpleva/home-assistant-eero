"""The eero tracker's registry defaults do not depend on Home Assistant's base class.

Home Assistant 2026.11 (core PR #188883) made ScannerEntity always disabled by
default (`_attr_entity_registry_enabled_default = False`,
homeassistant/components/device_tracker/entity.py:554 at tag 2026.11.0) and let
it build a device of its own when the integration supplies none (entity.py:598-613).
The eero tracker subclasses BaseScannerEntity, which that PR left alone, so it
keeps Home Assistant's general default (enabled). These tests pin what the house
relies on, so a later move of that default into the base class cannot silently
disable every newly seen client:

- a tracker for a new client is enabled by default, whatever the base says;
- its device is the one EeroEntity describes, never one the base makes up;
- its unique ID is EeroEntity's, so existing entities keep their ids.

The real device_tracker.py is loaded against stand-ins for Home Assistant,
because these tests run without Home Assistant installed. The stand-in Entity
resolves `entity_registry_enabled_default` and `device_info` the way core does
(homeassistant/helpers/entity.py:941-950 and :873-878 at tag 2026.11.0; the same
code at :905-914 and :837-842 at 2026.10.4).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
import importlib
from pathlib import Path
import sys
import types
from typing import Any
from unittest import mock

import pytest

EERO_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "eero"
TRACKER_SOURCE = EERO_DIR / "device_tracker.py"
EERO_DEVICE_INFO = {"identifiers": {("eero", "client-1")}, "name": "Chloe iPad"}


class FakeEntity:
    """Home Assistant's Entity, reduced to the two defaults under test."""

    _attr_device_info: Any = None

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Mirror helpers/entity.py: _attr_ first, then the description, then True."""
        if hasattr(self, "_attr_entity_registry_enabled_default"):
            return self._attr_entity_registry_enabled_default
        if hasattr(self, "entity_description"):
            return self.entity_description.entity_registry_enabled_default
        return True

    @property
    def device_info(self) -> Any:
        """Mirror helpers/entity.py: the _attr_ value."""
        return self._attr_device_info

    @property
    def unique_id(self) -> str | None:
        """Mirror helpers/entity.py: no unique ID unless a subclass gives one."""
        return None


class BaseScannerToday(FakeEntity):
    """BaseScannerEntity as it is in 2026.10.4 and 2026.11.0: no opinion on enabling."""


class BaseScannerDisabledByDefault(FakeEntity):
    """A base that carries the defaults 2026.11 gave ScannerEntity."""

    _attr_entity_registry_enabled_default = False
    _attr_device_info = {"connections": {("mac", "aa:bb:cc:dd:ee:ff")}}

    @property
    def unique_id(self) -> str | None:
        """ScannerEntity's unique ID is the MAC address."""
        return "aa:bb:cc:dd:ee:ff"


@dataclass
class FakeEeroEntityDescription:
    """EeroEntityDescription, reduced to what the tracker's description needs."""

    key: str = ""
    entity_registry_enabled_default: bool = True
    premium_type: bool = False


class FakeEeroEntity:
    """EeroEntity, reduced to its constructor and the properties under test."""

    def __init__(self, coordinator, network_id, resource_id, description, miscellaneous):
        self.coordinator = coordinator
        self.network_id = network_id
        self.resource_id = resource_id
        self.entity_description = description

    @property
    def device_info(self) -> dict[str, Any]:
        """Stand in for EeroEntity.device_info."""
        return EERO_DEVICE_INFO

    @property
    def unique_id(self) -> str:
        """Stand in for EeroEntity.unique_id."""
        return f"{self.network_id}-{self.resource_id}-{self.entity_description.key}"


def _module(name: str, **attrs: Any) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    return module


def load_tracker(base_scanner: type):
    """Load the real device_tracker.py with `base_scanner` as BaseScannerEntity."""
    # The package's real __init__ imports Home Assistant, so a stand-in package
    # takes its place; its __path__ is the real folder, so const, util,
    # tracker_attributes and the api package are the real ones.
    package = _module(
        "eero_tracker_pkg",
        EeroEntity=FakeEeroEntity,
        EeroEntityDescription=FakeEeroEntityDescription,
    )
    package.__path__ = [str(EERO_DIR)]
    source_type = types.SimpleNamespace(ROUTER="router")
    fakes = {
        "eero_tracker_pkg": package,
        "homeassistant": _module("homeassistant"),
        "homeassistant.components": _module("homeassistant.components"),
        "homeassistant.components.device_tracker": _module(
            "homeassistant.components.device_tracker",
            BaseScannerEntity=base_scanner,
            SourceType=source_type,
        ),
        "homeassistant.config_entries": _module(
            "homeassistant.config_entries", ConfigEntry=object
        ),
        "homeassistant.core": _module("homeassistant.core", HomeAssistant=object),
        "homeassistant.helpers": _module("homeassistant.helpers"),
        "homeassistant.helpers.entity": _module(
            "homeassistant.helpers.entity",
            EntityCategory=types.SimpleNamespace(DIAGNOSTIC="diagnostic"),
        ),
        "homeassistant.helpers.entity_platform": _module(
            "homeassistant.helpers.entity_platform", AddEntitiesCallback=object
        ),
        "homeassistant.helpers.update_coordinator": _module(
            "homeassistant.helpers.update_coordinator", DataUpdateCoordinator=object
        ),
        "homeassistant.util": _module("homeassistant.util", dt=_module("dt")),
    }
    # patch.dict restores sys.modules afterwards, so nothing here (the stand-in
    # package and its real submodules included) leaks into other tests.
    with mock.patch.dict(sys.modules, fakes):
        return importlib.import_module("eero_tracker_pkg.device_tracker")


def new_client_tracker(base_scanner: type):
    """Build the tracker the platform builds for a newly seen client."""
    module = load_tracker(base_scanner)
    (description,) = module.DEVICE_TRACKER_DESCRIPTIONS
    return module.EeroDeviceTrackerEntity(
        None, "1234567", "client-1", description, {module.CONF_CONSIDER_HOME: 0}
    )


BASES = pytest.mark.parametrize(
    "base_scanner", [BaseScannerToday, BaseScannerDisabledByDefault]
)


def test_new_client_tracker_is_enabled_on_todays_base() -> None:
    """On 2026.10.4 and 2026.11.0 a new client's tracker is added enabled."""
    tracker = new_client_tracker(BaseScannerToday)

    assert tracker.entity_registry_enabled_default is True


def test_new_client_tracker_is_enabled_even_if_the_base_disables() -> None:
    """A base class that defaults to disabled must not disable eero's trackers."""
    tracker = new_client_tracker(BaseScannerDisabledByDefault)

    assert tracker.entity_registry_enabled_default is True


def test_the_enabled_default_is_stated_on_the_tracker_class() -> None:
    """The default is set by the fork itself, not inherited from Home Assistant."""
    module = load_tracker(BaseScannerToday)

    assert (
        module.EeroDeviceTrackerEntity.__dict__["_attr_entity_registry_enabled_default"]
        is True
    )


@BASES
def test_device_info_is_eero_entitys(base_scanner: type) -> None:
    """The tracker attaches to the device EeroEntity describes, on either base."""
    tracker = new_client_tracker(base_scanner)

    assert tracker.device_info is EERO_DEVICE_INFO
    assert "device_info" not in type(tracker).__dict__
    assert "_attr_device_info" not in type(tracker).__dict__


@BASES
def test_unique_id_is_eero_entitys(base_scanner: type) -> None:
    """The unique ID stays network-resource-key, so existing entities keep their ids."""
    tracker = new_client_tracker(base_scanner)

    assert tracker.unique_id == "1234567-client-1-device_tracker"
    assert "unique_id" not in type(tracker).__dict__


def test_tracker_subclasses_base_scanner_entity_after_eero_entity() -> None:
    """EeroEntity comes first so its device_info and unique_id win.

    And the base is BaseScannerEntity, not ScannerEntity: ScannerEntity is the
    class 2026.11 changed (MAC as unique ID, a device of its own, disabled).
    """
    tree = ast.parse(TRACKER_SOURCE.read_text())
    (tracker,) = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "EeroDeviceTrackerEntity"
    ]

    assert [base.id for base in tracker.bases] == ["EeroEntity", "BaseScannerEntity"]
