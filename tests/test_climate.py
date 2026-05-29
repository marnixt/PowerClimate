"""Tests for PowerClimate climate orchestration helpers."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.climate.const import HVACMode

from custom_components.powerclimate.climate import PowerClimateClimate
from custom_components.powerclimate.const import (
    CONF_ALLOW_ON_OFF_CONTROL,
    CONF_CLIMATE_ENTITY,
    MODE_MPC,
)


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
    entity._config = SimpleNamespace(solar_enabled=True, mpc_enabled=True)
    entity._enter_boost_mode = AsyncMock()
    entity._enter_away_mode = AsyncMock()
    entity._enter_solar_mode = AsyncMock()
    entity._enter_mpc_mode = AsyncMock()
    entity._exit_preset_mode = AsyncMock()

    asyncio.run(entity.async_set_preset_mode("Solar"))
    asyncio.run(entity.async_set_preset_mode("Away"))
    asyncio.run(entity.async_set_preset_mode("MPC"))

    entity._enter_solar_mode.assert_awaited_once()
    entity._enter_away_mode.assert_awaited_once()
    entity._enter_mpc_mode.assert_awaited_once()


def test_preset_modes_include_mpc_when_sensor_configured() -> None:
    """MPC preset should be exposed when an MPC sensor is configured."""
    entity = make_entity()
    entity._config = SimpleNamespace(solar_enabled=False, mpc_enabled=True)

    assert entity.preset_modes == ["none", "boost", "away", "mpc"]


def test_determine_hp1_mode_returns_mpc_for_mpc_preset() -> None:
    """HP1 should use dedicated MPC mode when the MPC preset is active."""
    entity = make_entity()
    entity._attr_preset_mode = "mpc"
    entity._power_manager = SimpleNamespace(get_budget=lambda _entity_id: 0.0)

    assert entity._determine_hp1_mode(False, "climate.hp1") == MODE_MPC


def test_calculate_mode_target_uses_mpc_sensor_value() -> None:
    """MPC mode should use the external advised temperature when available."""
    entity = make_entity()
    entity._config = SimpleNamespace(
        min_setpoint=16.0,
        max_setpoint=35.0,
        get_device_lower_offset=lambda _device, _index: 0.0,
        get_device_upper_offset=lambda _device, _index: 0.0,
    )
    entity._read_mpc_temperature_state = MagicMock(return_value=32.5)

    target = entity._calculate_mode_target(
        MODE_MPC,
        current_temp=28.0,
        device={CONF_CLIMATE_ENTITY: "climate.hp1"},
        index=0,
    )

    assert target == 32.5


def test_calculate_mode_target_falls_back_when_mpc_sensor_unavailable() -> None:
    """MPC mode should fall back to setpoint clamping when the sensor is unavailable."""
    entity = make_entity()
    entity._config = SimpleNamespace(
        min_setpoint=16.0,
        max_setpoint=35.0,
        get_device_lower_offset=lambda _device, _index: 0.0,
        get_device_upper_offset=lambda _device, _index: 5.0,
    )
    entity._target_temperature = 21.0
    entity._read_mpc_temperature_state = MagicMock(return_value=None)

    target = entity._calculate_mode_target(
        MODE_MPC,
        current_temp=20.0,
        device={CONF_CLIMATE_ENTITY: "climate.hp1"},
        index=0,
    )

    assert target == 21.0


def test_is_water_overshoot_condition_true_uses_maximum_overshoot() -> None:
    """Water overshoot should only trigger above target plus configured margin."""
    entity = make_entity()
    entity._config = SimpleNamespace(maximum_overshoot=0.5)
    entity._target_temperature = 21.0
    entity.coordinator = SimpleNamespace(data={"room_temperature": 21.6})

    assert entity._is_water_overshoot_condition_true() is True


def test_handle_water_overshoot_control_turns_off_after_timer() -> None:
    """Auto-controllable water device should turn off after sustained overshoot."""
    entity = make_entity()
    entity._config = SimpleNamespace(assist_timer_seconds=300.0)
    entity._water_overshoot_since = None
    entity._is_water_overshoot_condition_true = MagicMock(side_effect=[True, True])
    entity._ensure_device_mode = AsyncMock()

    with patch("custom_components.powerclimate.climate.datetime") as mock_datetime:
        start = MagicMock()
        later = MagicMock()
        later.__sub__.return_value.total_seconds.return_value = 301.0
        mock_datetime.now.side_effect = [start, later]

        first = asyncio.run(
            entity._handle_water_overshoot_control(
                {CONF_ALLOW_ON_OFF_CONTROL: True},
                "climate.hp1",
                True,
            )
        )
        second = asyncio.run(
            entity._handle_water_overshoot_control(
                {CONF_ALLOW_ON_OFF_CONTROL: True},
                "climate.hp1",
                True,
            )
        )

    assert first is False
    assert second is True
    entity._ensure_device_mode.assert_awaited_once_with("climate.hp1", HVACMode.OFF)


def test_is_water_turn_on_condition_true_on_any_demand() -> None:
    """Water re-enable should trigger as soon as room is below target."""
    entity = make_entity()
    entity._target_temperature = 21.0
    entity._room_eta_hours = None  # ETA unknown – should not block
    entity.coordinator = SimpleNamespace(data={"room_temperature": 20.5})

    assert entity._is_water_turn_on_condition_true() is True


def test_is_water_turn_on_condition_false_when_at_or_above_target() -> None:
    """Water re-enable should not trigger when room is at or above target."""
    entity = make_entity()
    entity._target_temperature = 21.0
    entity._room_eta_hours = None
    entity.coordinator = SimpleNamespace(data={"room_temperature": 21.0})

    assert entity._is_water_turn_on_condition_true() is False


def test_process_water_device_keeps_off_when_room_at_or_above_target() -> None:
    """Water device should stay off when room is at or above target (no demand)."""
    entity = make_entity()
    entity._config = SimpleNamespace(
        get_water_device=lambda: (
            {
                CONF_CLIMATE_ENTITY: "climate.hp1",
                CONF_ALLOW_ON_OFF_CONTROL: True,
            },
            0,
        ),
    )
    entity._target_temperature = 21.0
    entity._room_eta_hours = None
    entity.coordinator = SimpleNamespace(data={"room_temperature": 21.0})  # at target
    entity._handle_water_overshoot_control = AsyncMock(return_value=False)
    entity._ensure_device_mode = AsyncMock()
    entity._determine_hp1_mode = MagicMock(return_value="setpoint")
    entity._calculate_mode_target = MagicMock(return_value=21.0)
    entity._hp_modes = {}

    desired_devices: set[str] = set()
    desired_targets: dict[str, float] = {}
    result = asyncio.run(
        entity._process_water_device(
            False,
            {
                "climate.hp1": {
                    "hvac_mode": HVACMode.OFF.value,
                    "current_temperature": 20.0,
                    "target_temperature": 20.0,
                    "energy": 0.0,
                    "water_temperature": 35.0,
                }
            },
            desired_devices,
            desired_targets,
        )
    )

    assert result == (35.0, "off")
    assert desired_devices == set()
    assert desired_targets == {}
    entity._ensure_device_mode.assert_not_awaited()


def test_process_water_device_turns_on_on_any_demand() -> None:
    """Water device should re-enable as soon as room is below target."""
    entity = make_entity()
    entity._config = SimpleNamespace(
        get_water_device=lambda: (
            {
                CONF_CLIMATE_ENTITY: "climate.hp1",
                CONF_ALLOW_ON_OFF_CONTROL: True,
            },
            0,
        ),
    )
    entity._target_temperature = 21.0
    entity._room_eta_hours = None  # ETA unknown – should not block
    entity.coordinator = SimpleNamespace(data={"room_temperature": 20.0})
    entity._handle_water_overshoot_control = AsyncMock(return_value=False)
    entity._ensure_device_mode = AsyncMock()
    entity._determine_hp1_mode = MagicMock(return_value="setpoint")
    entity._calculate_mode_target = MagicMock(return_value=21.0)
    entity._hp_modes = {}
    entity._get_device_payloads = MagicMock(
        return_value={
            "climate.hp1": {
                "hvac_mode": HVACMode.HEAT.value,
                "current_temperature": 20.0,
                "target_temperature": 20.0,
                "energy": 0.0,
                "water_temperature": 35.0,
            }
        }
    )

    desired_devices: set[str] = set()
    desired_targets: dict[str, float] = {}
    result = asyncio.run(
        entity._process_water_device(
            False,
            {
                "climate.hp1": {
                    "hvac_mode": HVACMode.OFF.value,
                    "current_temperature": 20.0,
                    "target_temperature": 20.0,
                    "energy": 0.0,
                    "water_temperature": 35.0,
                }
            },
            desired_devices,
            desired_targets,
        )
    )

    assert result == (35.0, "water_hp_only")
    assert desired_devices == {"climate.hp1"}
    assert desired_targets == {"climate.hp1": 21.0}
    entity._ensure_device_mode.assert_awaited_once_with("climate.hp1", HVACMode.HEAT)


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
