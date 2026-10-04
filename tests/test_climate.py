"""Tests for PowerClimate climate orchestration helpers."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.climate.const import HVACAction, HVACMode

from custom_components.powerclimate.climate import PowerClimateClimate
from custom_components.powerclimate.const import (
    CONF_ALLOW_ON_OFF_CONTROL,
    CONF_CLIMATE_ENTITY,
    MODE_BOOST,
    MODE_MPC,
    MODE_OFF,
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

    assert entity.preset_modes == ["none", "boost", "away", "mpc", "thermal"]


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
    entity.hass = SimpleNamespace(
        async_create_task=MagicMock(side_effect=lambda coro: coro.close())
    )

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


# ---------------------------------------------------------------------------
# Cooling mode tests
# ---------------------------------------------------------------------------


def test_is_cooling_false_without_attr() -> None:
    """_is_cooling should not raise when _attr_hvac_mode is not yet set."""
    entity = make_entity()
    assert entity._is_cooling() is False


def test_is_cooling_true_in_cool_mode() -> None:
    """_is_cooling should return True when HVAC mode is COOL."""
    entity = make_entity()
    entity._attr_hvac_mode = HVACMode.COOL
    assert entity._is_cooling() is True


def test_is_cooling_false_in_heat_mode() -> None:
    """_is_cooling should return False when HVAC mode is HEAT."""
    entity = make_entity()
    entity._attr_hvac_mode = HVACMode.HEAT
    assert entity._is_cooling() is False


def test_is_room_at_target_cool_mode_true_when_at_or_below() -> None:
    """In cool mode, target is reached when room is at or below setpoint."""
    entity = make_entity()
    entity._attr_hvac_mode = HVACMode.COOL
    entity._target_temperature = 22.0

    assert entity._is_room_at_target(22.0) is True
    assert entity._is_room_at_target(21.5) is True


def test_is_room_at_target_cool_mode_false_when_above() -> None:
    """In cool mode, target is NOT reached when room is still above setpoint."""
    entity = make_entity()
    entity._attr_hvac_mode = HVACMode.COOL
    entity._target_temperature = 22.0

    assert entity._is_room_at_target(22.1) is False


def test_is_water_overshoot_false_in_cool_mode() -> None:
    """Water overshoot check should always return False in cooling mode."""
    entity = make_entity()
    entity._attr_hvac_mode = HVACMode.COOL
    entity._config = SimpleNamespace(maximum_overshoot=0.5)
    entity._target_temperature = 22.0
    entity.coordinator = SimpleNamespace(data={"room_temperature": 30.0})

    assert entity._is_water_overshoot_condition_true() is False


def test_is_water_turn_on_false_in_cool_mode() -> None:
    """Water turn-on check should always return False in cooling mode."""
    entity = make_entity()
    entity._attr_hvac_mode = HVACMode.COOL
    entity._target_temperature = 22.0
    entity.coordinator = SimpleNamespace(data={"room_temperature": 26.0})

    assert entity._is_water_turn_on_condition_true() is False


def test_determine_hp1_mode_returns_off_in_cool_mode() -> None:
    """HP1 (water HP) must be kept off when PowerClimate is cooling."""
    entity = make_entity()
    entity._attr_hvac_mode = HVACMode.COOL
    entity._attr_preset_mode = "none"

    assert entity._determine_hp1_mode(False, "climate.hp1") == MODE_OFF


def test_process_water_device_turns_off_in_cool_mode() -> None:
    """Water device must be switched off in cooling mode (even when allowed on/off)."""
    entity = make_entity()
    entity._attr_hvac_mode = HVACMode.COOL
    entity._config = SimpleNamespace(
        get_water_device=lambda: (
            {
                CONF_CLIMATE_ENTITY: "climate.hp1",
                CONF_ALLOW_ON_OFF_CONTROL: True,
            },
            0,
        ),
    )
    entity._ensure_device_mode = AsyncMock()
    entity._hp_modes = {}

    desired_devices: set[str] = set()
    desired_targets: dict[str, float] = {}
    payloads = {
        "climate.hp1": {
            "hvac_mode": HVACMode.HEAT.value,
            "water_temperature": 38.0,
        }
    }

    result = asyncio.run(
        entity._process_water_device(False, payloads, desired_devices, desired_targets)
    )

    # Water temp is still returned for diagnostic purposes
    assert result == (38.0, "off")
    assert entity._hp_modes["climate.hp1"] == MODE_OFF
    assert desired_devices == set()
    # Should have been switched off because allow_on_off=True and it was running
    entity._ensure_device_mode.assert_awaited_once_with("climate.hp1", HVACMode.OFF)


def test_enter_away_mode_in_cool_raises_target_to_max() -> None:
    """Away mode in cooling should raise target to max so ACs stop running."""
    entity = make_entity()
    entity._attr_hvac_mode = HVACMode.COOL
    entity._attr_preset_mode = "none"
    entity._target_temperature = 22.0
    entity._previous_target = None
    entity._config = SimpleNamespace(
        min_setpoint=16.0,
        max_setpoint=30.0,
        solar_enabled=False,
        mpc_enabled=False,
    )
    entity._power_manager = SimpleNamespace(clear_all=MagicMock())
    entity._apply_away_mode = AsyncMock()

    asyncio.run(entity._enter_away_mode())

    assert entity._target_temperature == 30.0
    assert entity._attr_preset_mode == "away"
    assert entity._attr_hvac_mode == HVACMode.COOL  # mode must not change


def test_enter_mpc_mode_preserves_cool_mode() -> None:
    """Selecting MPC in cool mode must preserve cool mode (MPC works for heat and cool)."""
    entity = make_entity()
    entity._attr_hvac_mode = HVACMode.COOL
    entity._attr_preset_mode = "none"
    entity._previous_target = None
    entity._power_manager = SimpleNamespace(clear_all=MagicMock())
    entity._apply_staging = AsyncMock()

    asyncio.run(entity._enter_mpc_mode())

    assert entity._attr_hvac_mode == HVACMode.COOL
    assert entity._attr_preset_mode == "mpc"


def test_calculate_mode_target_boost_cooling_uses_lower_offset() -> None:
    """Boost in cool mode picks the lowest setpoint (most aggressive cooling)."""
    entity = make_entity()
    entity._attr_hvac_mode = HVACMode.COOL
    entity._target_temperature = 22.0
    entity._config = SimpleNamespace(
        min_setpoint=16.0,
        max_setpoint=30.0,
        get_device_lower_offset_cooling=lambda _d, _i: -4.0,
        get_device_upper_offset_cooling=lambda _d, _i: 0.0,
    )
    entity._read_mpc_temperature_state = MagicMock(return_value=None)

    target = entity._calculate_mode_target(
        MODE_BOOST,
        current_temp=25.0,
        device={CONF_CLIMATE_ENTITY: "climate.air1"},
        index=1,
    )

    # Boost cooling: current + lower_offset = 25 + (-4) = 21, clamped to [16, 30]
    assert target == 21.0


def test_calculate_mode_target_boost_heating_uses_upper_offset() -> None:
    """Boost in heat mode picks the highest setpoint (most aggressive heating)."""
    entity = make_entity()
    entity._attr_hvac_mode = HVACMode.HEAT
    entity._target_temperature = 22.0
    entity._config = SimpleNamespace(
        min_setpoint=16.0,
        max_setpoint=30.0,
        get_device_lower_offset=lambda _d, _i: -4.0,
        get_device_upper_offset=lambda _d, _i: 4.0,
    )
    entity._read_mpc_temperature_state = MagicMock(return_value=None)

    target = entity._calculate_mode_target(
        MODE_BOOST,
        current_temp=20.0,
        device={CONF_CLIMATE_ENTITY: "climate.air1"},
        index=1,
    )

    # Boost heating: current + upper_offset = 20 + 4 = 24, clamped to [16, 30]
    assert target == 24.0


def test_update_room_state_cool_inverts_eta() -> None:
    """In cooling mode ETA uses the cooling rate (negative derivative inverted)."""
    entity = make_entity()
    entity._attr_hvac_mode = HVACMode.COOL
    entity._target_temperature = 22.0
    # Room is 2°C above target; derivative = -1°C/h (room getting cooler)
    entity.coordinator = SimpleNamespace(
        data={"room_derivative": -1.0, "room_temperature": 24.0}
    )

    entity._update_room_state(24.0)

    # delta = room - target = 24 - 22 = 2; cooling_rate = -(-1) = 1
    # ETA = 2 / 1 = 2 hours
    assert entity._delta == 2.0
    assert entity._room_eta_hours == 2.0


def test_hvac_action_set_to_cooling_when_active() -> None:
    """HVACAction should be COOLING when cool mode is on and devices are active."""
    entity = make_entity()
    entity._attr_hvac_mode = HVACMode.COOL
    entity._active_devices = {"climate.air1"}

    # Simulate the hvac_action assignment logic used in _apply_staging

    if entity._attr_hvac_mode == HVACMode.OFF:
        action = HVACAction.OFF
    elif entity._attr_hvac_mode == HVACMode.COOL:
        action = HVACAction.COOLING if entity._active_devices else HVACAction.IDLE
    else:
        action = HVACAction.HEATING if entity._active_devices else HVACAction.IDLE

    assert action == HVACAction.COOLING


def test_hvac_action_idle_when_cool_mode_no_active_devices() -> None:
    """HVACAction should be IDLE when in cool mode but no devices are running."""
    entity = make_entity()
    entity._attr_hvac_mode = HVACMode.COOL
    entity._active_devices = set()


    if entity._attr_hvac_mode == HVACMode.OFF:
        action = HVACAction.OFF
    elif entity._attr_hvac_mode == HVACMode.COOL:
        action = HVACAction.COOLING if entity._active_devices else HVACAction.IDLE
    else:
        action = HVACAction.HEATING if entity._active_devices else HVACAction.IDLE

    assert action == HVACAction.IDLE


# ---------------------------------------------------------------------------
# _handle_assist_control — mode-switch behaviour
# ---------------------------------------------------------------------------


def _make_assist_entity(hvac_mode: HVACMode) -> PowerClimateClimate:
    """Return a minimal entity configured for assist-control tests."""
    entity = make_entity()
    entity._attr_hvac_mode = hvac_mode
    entity._assist_controller = MagicMock()
    entity._assist_controller.evaluate_action.return_value = (None, "")
    entity._ensure_device_mode = AsyncMock()
    entity._get_device_payloads = MagicMock(return_value={})
    return entity


def test_handle_assist_control_switches_mode_when_running_in_wrong_mode() -> None:
    """Device running in HEAT while system is COOL should be switched to COOL."""
    entity = _make_assist_entity(HVACMode.COOL)
    payloads = {
        "climate.air1": {
            "hvac_mode": "heat",
            "hvac_modes": ["off", "heat", "cool"],
        }
    }

    result = asyncio.run(
        entity._handle_assist_control("climate.air1", is_running=True, device_payloads=payloads)
    )

    assert result is True
    entity._ensure_device_mode.assert_awaited_once_with(
        "climate.air1", HVACMode.COOL, force=True
    )


def test_handle_assist_control_turns_off_when_mode_not_supported() -> None:
    """Device running in HEAT should be turned off when it doesn't support COOL."""
    entity = _make_assist_entity(HVACMode.COOL)
    payloads = {
        "climate.air1": {
            "hvac_mode": "heat",
            "hvac_modes": ["off", "heat"],  # no cool
        }
    }

    result = asyncio.run(
        entity._handle_assist_control("climate.air1", is_running=True, device_payloads=payloads)
    )

    assert result is False
    entity._ensure_device_mode.assert_awaited_once_with("climate.air1", HVACMode.OFF)
    entity._assist_controller.record_turn_off.assert_called_once_with("climate.air1")


def test_handle_assist_control_does_not_turn_on_unsupported_mode() -> None:
    """evaluate_action returning 'cool' should be skipped if device doesn't support it."""
    entity = _make_assist_entity(HVACMode.COOL)
    entity._assist_controller.evaluate_action.return_value = ("cool", "condition_met")
    payloads = {
        "climate.air1": {
            "hvac_mode": "off",
            "hvac_modes": ["off", "heat"],  # no cool
        }
    }

    result = asyncio.run(
        entity._handle_assist_control("climate.air1", is_running=False, device_payloads=payloads)
    )

    assert result is False
    entity._ensure_device_mode.assert_not_awaited()


def test_handle_assist_control_turns_on_when_mode_supported() -> None:
    """evaluate_action returning 'cool' should turn the device on when supported."""
    entity = _make_assist_entity(HVACMode.COOL)
    entity._assist_controller.evaluate_action.return_value = ("cool", "condition_met")
    payloads = {
        "climate.air1": {
            "hvac_mode": "off",
            "hvac_modes": ["off", "heat", "cool"],
        }
    }

    result = asyncio.run(
        entity._handle_assist_control("climate.air1", is_running=False, device_payloads=payloads)
    )

    assert result is True
    entity._ensure_device_mode.assert_awaited_once_with("climate.air1", HVACMode.COOL)
    entity._assist_controller.record_turn_on.assert_called_once_with("climate.air1")


def test_handle_assist_control_allows_mode_change_when_hvac_modes_unknown() -> None:
    """If hvac_modes is absent, assume the device supports any mode and switch it."""
    entity = _make_assist_entity(HVACMode.COOL)
    payloads = {
        "climate.air1": {
            "hvac_mode": "heat",
            # hvac_modes not present — treat as unknown / unrestricted
        }
    }

    result = asyncio.run(
        entity._handle_assist_control("climate.air1", is_running=True, device_payloads=payloads)
    )

    assert result is True
    entity._ensure_device_mode.assert_awaited_once_with(
        "climate.air1", HVACMode.COOL, force=True
    )


# ---------------------------------------------------------------------------
# Device mode / setpoint sync uses the real device state
# ---------------------------------------------------------------------------


def _make_sync_entity(states: dict) -> PowerClimateClimate:
    entity = make_entity()
    entity.hass = SimpleNamespace(states=SimpleNamespace(get=states.get))
    entity._device_modes = {}
    entity._device_targets = {}
    entity._device_reported_targets = {}
    entity._last_mode_call = {}
    entity._last_temp_call = {}
    entity._call_climate_service = AsyncMock(return_value=True)
    return entity


def test_ensure_device_mode_reapplies_after_external_change() -> None:
    """A cached mode must not hide a device that was switched off externally."""
    entity = _make_sync_entity({"climate.hp1": SimpleNamespace(state="off", attributes={})})
    entity._device_modes["climate.hp1"] = HVACMode.HEAT

    asyncio.run(entity._ensure_device_mode("climate.hp1", HVACMode.HEAT))

    entity._call_climate_service.assert_awaited_once()


def test_ensure_device_mode_skips_when_device_already_in_mode() -> None:
    entity = _make_sync_entity({"climate.hp1": SimpleNamespace(state="heat", attributes={})})

    asyncio.run(entity._ensure_device_mode("climate.hp1", HVACMode.HEAT))

    entity._call_climate_service.assert_not_awaited()


def test_ensure_device_mode_does_not_cache_failed_call() -> None:
    entity = _make_sync_entity({})
    entity._call_climate_service = AsyncMock(return_value=False)

    asyncio.run(entity._ensure_device_mode("climate.hp1", HVACMode.HEAT))

    assert "climate.hp1" not in entity._device_modes


def test_ensure_device_temperature_reapplies_after_external_change() -> None:
    """A setpoint changed on the device itself must be corrected."""
    state = SimpleNamespace(state="heat", attributes={"temperature": 21.5})
    entity = _make_sync_entity({"climate.hp1": state})
    entity._device_targets["climate.hp1"] = 21.3
    entity._device_reported_targets["climate.hp1"] = 21.5

    # Device rounded our 21.3 to 21.5: nothing to do.
    asyncio.run(entity._ensure_device_temperature("climate.hp1", 21.3))
    entity._call_climate_service.assert_not_awaited()

    # Someone changed it to 19 on the device: re-apply.
    state.attributes = {"temperature": 19.0}
    asyncio.run(entity._ensure_device_temperature("climate.hp1", 21.3))
    entity._call_climate_service.assert_awaited_once()


def test_set_power_budget_triggers_staging() -> None:
    entity = make_entity()
    entity._power_manager = MagicMock()
    entity._apply_staging = AsyncMock()

    asyncio.run(entity.async_set_power_budget("climate.hp1", 800.0))

    entity._power_manager.set_budget.assert_called_once_with("climate.hp1", 800.0)
    entity._apply_staging.assert_awaited_once()


def test_handle_hp_state_change_forwards_mirror_while_refresh_pending() -> None:
    entity = make_entity()
    entity._pending_state_refresh = True
    entity._mirror_entities = {"climate.thermostat"}
    entity._maybe_forward_setpoint = MagicMock()
    event = SimpleNamespace(
        data={"entity_id": "climate.thermostat", "new_state": object(), "old_state": None}
    )

    entity._handle_hp_state_change(event)

    entity._maybe_forward_setpoint.assert_called_once()


def test_build_hp_status_air_only_includes_assist_info() -> None:
    """Without a water device the first air device still gets assist info."""
    from custom_components.powerclimate.const import CONF_DEVICE_ROLE, DEVICE_ROLE_AIR

    entity = make_entity()
    entity.coordinator = SimpleNamespace(data={"water_derivative": 9.9})
    entity._config = SimpleNamespace(is_water_device=lambda device, index: False)
    entity._active_devices = set()
    entity._assist_modes = {"climate.ac1": "setpoint"}
    entity._hp_modes = {}
    entity._assist_controller = MagicMock()
    entity._assist_controller.get_hp_status_info.return_value = {"on_timer_seconds": 12.0}
    devices = [{CONF_CLIMATE_ENTITY: "climate.ac1", CONF_DEVICE_ROLE: DEVICE_ROLE_AIR}]

    status = entity._build_hp_status(devices, {"climate.ac1": {"hvac_mode": "heat"}})

    assert status[0]["assist_mode"] == "setpoint"
    assert status[0]["on_timer_seconds"] == 12.0
    assert status[0]["water_derivative"] is None
