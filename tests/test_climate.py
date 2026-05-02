"""Tests for PowerClimate climate orchestration helpers."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.climate.const import HVACMode

from custom_components.powerclimate.climate import PowerClimateClimate
from custom_components.powerclimate.const import CONF_ALLOW_ON_OFF_CONTROL, CONF_CLIMATE_ENTITY


def make_entity() -> PowerClimateClimate:
    """Create a bare PowerClimateClimate instance for method-level unit tests."""
    return PowerClimateClimate.__new__(PowerClimateClimate)


def test_apply_away_mode_uses_air_device_roles() -> None:
    """Away mode should only force off configured air devices."""
    entity = make_entity()
    entity._config = SimpleNamespace(
        get_air_devices=lambda: [
            (
                1,
                {
                    CONF_CLIMATE_ENTITY: "climate.air1",
                    CONF_ALLOW_ON_OFF_CONTROL: True,
                },
            ),
            (
                2,
                {
                    CONF_CLIMATE_ENTITY: "climate.air2",
                    CONF_ALLOW_ON_OFF_CONTROL: False,
                },
            ),
        ]
    )
    entity._assist_controller = MagicMock()
    entity._ensure_device_mode = AsyncMock()
    entity._apply_staging = AsyncMock()

    asyncio.run(entity._apply_away_mode())

    entity._ensure_device_mode.assert_awaited_once_with("climate.air1", HVACMode.OFF)
    entity._assist_controller.force_off.assert_called_once_with("climate.air1")
    entity._apply_staging.assert_awaited_once()


def test_turn_off_water_device_forces_off_when_powerclimate_is_off() -> None:
    """Turning PowerClimate off should explicitly switch HP1 off."""
    entity = make_entity()
    entity._config = SimpleNamespace(
        get_water_device=lambda: (
            {CONF_CLIMATE_ENTITY: "climate.hp1"},
            0,
        )
    )
    entity._ensure_device_mode = AsyncMock()
    entity._hp_modes = {}
    payloads = {"climate.hp1": {"hvac_mode": "heat"}}

    asyncio.run(entity._turn_off_water_device(payloads))

    entity._ensure_device_mode.assert_awaited_once_with(
        "climate.hp1",
        HVACMode.OFF,
        allow_when_off=True,
        force=True,
    )
    assert payloads["climate.hp1"]["hvac_mode"] == HVACMode.OFF.value


def test_async_set_preset_mode_accepts_legacy_case() -> None:
    """Preset setters should normalize legacy title-cased preset values."""
    entity = make_entity()
    entity._config = SimpleNamespace(solar_enabled=True)
    entity._enter_boost_mode = AsyncMock()
    entity._enter_away_mode = AsyncMock()
    entity._enter_solar_mode = AsyncMock()
    entity._exit_preset_mode = AsyncMock()

    asyncio.run(entity.async_set_preset_mode("Solar"))
    asyncio.run(entity.async_set_preset_mode("Away"))

    entity._enter_solar_mode.assert_awaited_once()
    entity._enter_away_mode.assert_awaited_once()


def test_async_process_update_replays_pending_refresh() -> None:
    """Queued coordinator updates should be coalesced into a second processing pass."""
    entity = make_entity()
    entity._coordinator_update_pending = False
    entity._coordinator_update_task = MagicMock()
    apply_calls: list[str] = []
    dispatch_calls: list[str] = []

    async def fake_apply_staging() -> None:
        apply_calls.append("apply")
        if len(apply_calls) == 1:
            entity._coordinator_update_pending = True

    entity._apply_staging = fake_apply_staging

    with patch(
        "custom_components.powerclimate.climate.CoordinatorEntity._handle_coordinator_update",
        autospec=True,
        side_effect=lambda _self: dispatch_calls.append("dispatch"),
    ):
        asyncio.run(entity._async_process_update())

    assert len(apply_calls) == 2
    assert len(dispatch_calls) == 2
    assert entity._coordinator_update_task is None


def test_handle_hp_state_change_forwards_mirror_updates() -> None:
    """Mirror thermostat updates should be forwarded before refreshing the coordinator."""
    entity = make_entity()
    entity._pending_state_refresh = False
    entity._mirror_entities = {"climate.mirror"}
    entity._maybe_forward_setpoint = MagicMock()
    entity.coordinator = SimpleNamespace(async_request_refresh=AsyncMock())
    entity.hass = SimpleNamespace(async_create_task=MagicMock(side_effect=lambda coro: coro.close()))

    event = SimpleNamespace(
        data={
            "entity_id": "climate.mirror",
            "old_state": SimpleNamespace(attributes={"temperature": 20.0}),
            "new_state": SimpleNamespace(attributes={"temperature": 21.0}),
        }
    )

    entity._handle_hp_state_change(event)

    entity._maybe_forward_setpoint.assert_called_once_with(
        "climate.mirror",
        event.data["old_state"],
        event.data["new_state"],
    )
    entity.hass.async_create_task.assert_called_once()
