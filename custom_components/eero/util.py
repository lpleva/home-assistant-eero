"""The Eero integration."""

from __future__ import annotations

import logging

from .api.client import EeroClient
from .const import (
    CONF_FILTER_EXCLUDE,
    CONF_FILTER_INCLUDE,
    CONF_WIRED_CLIENTS,
    CONF_WIRED_CLIENTS_FILTER,
    CONF_WIRELESS_CLIENTS,
    CONF_WIRELESS_CLIENTS_FILTER,
)

_LOGGER = logging.getLogger(__name__)


def resource_supports(resource, key: str) -> bool:
    """Return True if this resource reports the feature named by key.

    A resource type that simply does not have the property is not supported.
    A property that raises anything else is a defect in that property: log it
    and skip the entity. A bare hasattr() swallowed only AttributeError, so a
    property raising TypeError aborted the whole platform setup and no entity
    of that platform was created.
    """
    try:
        getattr(resource, key)
    except AttributeError:
        return False
    except Exception:  # noqa: BLE001
        _LOGGER.exception(
            "Error reading %s from %s, skipping entity",
            key,
            type(resource).__name__,
        )
        return False
    return True


def client_allowed(client: EeroClient, resources: dict) -> bool:
    """Validate client against configuration."""
    return any(
        [
            all(
                [
                    not client.wireless,
                    client.id in resources[CONF_WIRED_CLIENTS],
                    resources[CONF_WIRED_CLIENTS_FILTER] == CONF_FILTER_INCLUDE,
                ]
            ),
            all(
                [
                    not client.wireless,
                    client.id not in resources[CONF_WIRED_CLIENTS],
                    resources[CONF_WIRED_CLIENTS_FILTER] == CONF_FILTER_EXCLUDE,
                ]
            ),
            all(
                [
                    client.wireless,
                    client.id in resources[CONF_WIRELESS_CLIENTS],
                    resources[CONF_WIRELESS_CLIENTS_FILTER] == CONF_FILTER_INCLUDE,
                ]
            ),
            all(
                [
                    client.wireless,
                    client.id not in resources[CONF_WIRELESS_CLIENTS],
                    resources[CONF_WIRELESS_CLIENTS_FILTER] == CONF_FILTER_EXCLUDE,
                ]
            ),
        ]
    )
