"""Tests for PowerClimate integration setup and services."""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.powerclimate.__init__ import (
    SERVICE_CLEAR_POWER_BUDGET,
    SERVICE_SET_POWER_BUDGET,
    _async_register_services,
)
from custom_components.powerclimate.const import CONF_CLIMATE_ENTITY, CONF_DEVICES, DOMAIN


class FakeServices:
    """Minimal service registry for unit tests."""

    def __init__(self) -> None:
        self._handlers: dict[tuple[str, str], object] = {}

    def has_service(self, domain: str, service: str) -> bool:
        return (domain, service) in self._handlers

    def async_register(self, domain: str, service: str, handler, schema=None) -> None:
        self._handlers[(domain, service)] = handler

    def get_handler(self, domain: str, service: str):
        return self._handlers[(domain, service)]


def make_entry(*entity_ids: str) -> SimpleNamespace:
    """Create a minimal config entry test double."""
    devices = [{CONF_CLIMATE_ENTITY: entity_id} for entity_id in entity_ids]
    return SimpleNamespace(data={CONF_DEVICES: devices}, options={})


def test_set_power_budget_routes_to_matching_entry() -> None:
    """Service should target the entry that owns the requested device."""
    services = FakeServices()
    climate_one = MagicMock()
    climate_two = MagicMock()
    hass = SimpleNamespace(
        services=services,
        data={
            DOMAIN: {
                "entry-1": {"entry": make_entry("climate.hp1"), "climate_entity": climate_one},
                "entry-2": {"entry": make_entry("climate.hp2"), "climate_entity": climate_two},
            }
        },
    )

    asyncio.run(_async_register_services(hass))

    handler = services.get_handler(DOMAIN, SERVICE_SET_POWER_BUDGET)
    asyncio.run(handler(SimpleNamespace(data={"entity_id": "climate.hp2", "power_watts": 850.0})))

    climate_one.set_power_budget.assert_not_called()
    climate_two.set_power_budget.assert_called_once_with("climate.hp2", 850.0)


def test_clear_power_budget_ignores_unknown_entity_with_multiple_entries() -> None:
    """Service should not mutate an arbitrary entry when ownership is ambiguous."""
    services = FakeServices()
    climate_one = MagicMock()
    climate_two = MagicMock()
    hass = SimpleNamespace(
        services=services,
        data={
            DOMAIN: {
                "entry-1": {"entry": make_entry("climate.hp1"), "climate_entity": climate_one},
                "entry-2": {"entry": make_entry("climate.hp2"), "climate_entity": climate_two},
            }
        },
    )

    asyncio.run(_async_register_services(hass))

    handler = services.get_handler(DOMAIN, SERVICE_CLEAR_POWER_BUDGET)
    asyncio.run(handler(SimpleNamespace(data={"entity_id": "climate.unknown"})))

    climate_one.clear_power_budget.assert_not_called()
    climate_two.clear_power_budget.assert_not_called()


def test_set_power_budget_ignores_ambiguous_duplicate_ownership() -> None:
    """Service should not pick an arbitrary entry when ownership is duplicated."""
    services = FakeServices()
    climate_one = MagicMock()
    climate_two = MagicMock()
    hass = SimpleNamespace(
        services=services,
        data={
            DOMAIN: {
                "entry-1": {"entry": make_entry("climate.hp1"), "climate_entity": climate_one},
                "entry-2": {"entry": make_entry("climate.hp1"), "climate_entity": climate_two},
            }
        },
    )

    asyncio.run(_async_register_services(hass))

    handler = services.get_handler(DOMAIN, SERVICE_SET_POWER_BUDGET)
    asyncio.run(handler(SimpleNamespace(data={"entity_id": "climate.hp1", "power_watts": 900.0})))

    climate_one.set_power_budget.assert_not_called()
    climate_two.set_power_budget.assert_not_called()


def test_set_power_budget_falls_back_when_single_entry_exists() -> None:
    """Service should still work for existing single-entry installations."""
    services = FakeServices()
    climate_entity = MagicMock()
    hass = SimpleNamespace(
        services=services,
        data={
            DOMAIN: {
                "entry-1": {"climate_entity": climate_entity},
            }
        },
    )

    asyncio.run(_async_register_services(hass))

    handler = services.get_handler(DOMAIN, SERVICE_SET_POWER_BUDGET)
    asyncio.run(
        handler(SimpleNamespace(data={"entity_id": "climate.hp1", "power_watts": 500.0}))
    )

    climate_entity.set_power_budget.assert_called_once_with("climate.hp1", 500.0)