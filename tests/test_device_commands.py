"""Tests for the device commander (mode and setpoint sync with real device state)."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from homeassistant.components.climate.const import HVACMode
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError

from custom_components.powerclimate.device_commands import DeviceCommander


def _make_commander(states: dict, *, is_off: bool = False) -> DeviceCommander:
    hass = SimpleNamespace(states=SimpleNamespace(get=states.get))
    commander = DeviceCommander(hass, lambda: is_off)
    commander.call_service = AsyncMock(return_value=True)
    return commander


def test_ensure_mode_reapplies_after_external_change() -> None:
    """A cached mode must not hide a device that was switched off externally."""
    commander = _make_commander({"climate.hp1": SimpleNamespace(state="off", attributes={})})
    commander.device_modes["climate.hp1"] = HVACMode.HEAT

    asyncio.run(commander.ensure_mode("climate.hp1", HVACMode.HEAT))

    commander.call_service.assert_awaited_once()


def test_ensure_mode_skips_when_device_already_in_mode() -> None:
    commander = _make_commander({"climate.hp1": SimpleNamespace(state="heat", attributes={})})

    asyncio.run(commander.ensure_mode("climate.hp1", HVACMode.HEAT))

    commander.call_service.assert_not_awaited()


def test_ensure_mode_does_not_cache_failed_call() -> None:
    commander = _make_commander({})
    commander.call_service = AsyncMock(return_value=False)

    asyncio.run(commander.ensure_mode("climate.hp1", HVACMode.HEAT))

    assert "climate.hp1" not in commander.device_modes


def test_ensure_mode_respects_cooldown_unless_forced() -> None:
    commander = _make_commander({"climate.hp1": SimpleNamespace(state="off", attributes={})})

    asyncio.run(commander.ensure_mode("climate.hp1", HVACMode.HEAT))
    asyncio.run(commander.ensure_mode("climate.hp1", HVACMode.HEAT))
    assert commander.call_service.await_count == 1

    asyncio.run(commander.ensure_mode("climate.hp1", HVACMode.HEAT, force=True))
    assert commander.call_service.await_count == 2


def test_ensure_temperature_reapplies_after_external_change() -> None:
    """A setpoint changed on the device itself must be corrected."""
    state = SimpleNamespace(state="heat", attributes={"temperature": 21.5})
    commander = _make_commander({"climate.hp1": state})
    commander.device_targets["climate.hp1"] = 21.3
    commander.device_reported_targets["climate.hp1"] = 21.5

    # Device rounded our 21.3 to 21.5: nothing to do.
    asyncio.run(commander.ensure_temperature("climate.hp1", 21.3))
    commander.call_service.assert_not_awaited()

    # Someone changed it to 19 on the device: re-apply.
    state.attributes = {"temperature": 19.0}
    asyncio.run(commander.ensure_temperature("climate.hp1", 21.3))
    commander.call_service.assert_awaited_once()


def test_call_service_skipped_while_off() -> None:
    hass = SimpleNamespace(services=SimpleNamespace(async_call=AsyncMock()))
    commander = DeviceCommander(hass, lambda: True)

    result = asyncio.run(commander.call_service("climate.hp1", "set_temperature", {}, "test"))

    assert result is False
    hass.services.async_call.assert_not_awaited()


def test_call_service_uses_own_context_and_reports_failures() -> None:
    hass = SimpleNamespace(services=SimpleNamespace(async_call=AsyncMock()))
    commander = DeviceCommander(hass, lambda: False)

    assert asyncio.run(commander.call_service("climate.hp1", "set_temperature", {}, "test"))
    assert hass.services.async_call.await_args.kwargs["context"] is commander.context

    hass.services.async_call.side_effect = HomeAssistantError("boom")
    assert not asyncio.run(commander.call_service("climate.hp1", "set_temperature", {}, "test"))


def test_is_own_state() -> None:
    commander = DeviceCommander(SimpleNamespace(), lambda: False)

    assert commander.is_own_state(SimpleNamespace(context=commander.context))
    assert not commander.is_own_state(SimpleNamespace(context=Context()))
    assert not commander.is_own_state(None)
