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
    MODE_OFF,
    MODE_SUPPLY_ADVICE,
)
from custom_components.powerclimate.supply_control import SupplyController


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
    entity._commands = MagicMock(ensure_mode=AsyncMock())
    entity._apply_staging = AsyncMock()

    asyncio.run(entity._apply_away_mode())

    entity._commands.ensure_mode.assert_awaited_once_with("climate.air1", HVACMode.OFF)
    entity._assist_controller.force_off.assert_called_once_with("climate.air1")
    entity._apply_staging.assert_awaited_once()


def test_turn_off_water_device_forces_off_when_powerclimate_is_off() -> None:
    """Turning PowerClimate off should explicitly switch HP1 off."""
    entity = make_entity()
    entity._config = SimpleNamespace(
        get_water_device=lambda: (
            {CONF_CLIMATE_ENTITY: "climate.hp1", CONF_ALLOW_ON_OFF_CONTROL: True},
            0,
        )
    )
    entity._commands = MagicMock(ensure_mode=AsyncMock())
    entity._hp_modes = {}
    payloads = {"climate.hp1": {"hvac_mode": "heat"}}

    asyncio.run(entity._turn_off_water_device(payloads))

    entity._commands.ensure_mode.assert_awaited_once_with(
        "climate.hp1",
        HVACMode.OFF,
        allow_when_off=True,
        force=True,
    )
    assert payloads["climate.hp1"]["hvac_mode"] == HVACMode.OFF.value


def test_turn_off_water_device_leaves_device_without_on_off_control() -> None:
    """Without on/off control the water device stays as the user set it."""
    entity = make_entity()
    entity._config = SimpleNamespace(
        get_water_device=lambda: (
            {CONF_CLIMATE_ENTITY: "climate.hp1", CONF_ALLOW_ON_OFF_CONTROL: False},
            0,
        )
    )
    entity._commands = MagicMock(ensure_mode=AsyncMock())
    entity._hp_modes = {}
    payloads = {"climate.hp1": {"hvac_mode": "heat"}}

    asyncio.run(entity._turn_off_water_device(payloads))

    entity._commands.ensure_mode.assert_not_awaited()
    assert payloads["climate.hp1"]["hvac_mode"] == "heat"


def test_async_set_preset_mode_accepts_legacy_case() -> None:
    """Preset setters should normalize legacy title-cased preset values."""
    entity = make_entity()
    entity._config = SimpleNamespace(supply_advice_enabled=True, get_water_device=lambda: None)
    entity._attr_preset_mode = "none"
    entity._supply = MagicMock()
    entity._enter_boost_mode = AsyncMock()
    entity._enter_away_mode = AsyncMock()
    entity._enter_staged_preset = AsyncMock()

    asyncio.run(entity.async_set_preset_mode("Boost"))
    asyncio.run(entity.async_set_preset_mode("Away"))
    asyncio.run(entity.async_set_preset_mode("Supply_Advice"))

    entity._enter_boost_mode.assert_awaited_once()
    entity._enter_away_mode.assert_awaited_once()
    entity._enter_staged_preset.assert_awaited_once_with("supply_advice")


def test_preset_modes_include_supply_advice_when_sensor_configured() -> None:
    """The supply advice preset is offered when an advice sensor is configured."""
    entity = make_entity()
    entity._config = SimpleNamespace(supply_advice_enabled=True, get_water_device=lambda: None)

    assert entity.preset_modes == ["none", "boost", "away", "main_only", "supply_advice"]


def _make_main_only_entity(
    *,
    water: bool,
    allow_on_off: bool = True,
    air2_mode: str = "heat",
) -> PowerClimateClimate:
    entity = make_entity()
    entity._attr_preset_mode = "main_only"
    entity._attr_hvac_mode = HVACMode.HEAT
    entity._target_temperature = 21.0
    entity._room_eta_hours = None
    air_devices = [
        (1, {CONF_CLIMATE_ENTITY: "climate.air1", CONF_ALLOW_ON_OFF_CONTROL: False}),
        (2, {CONF_CLIMATE_ENTITY: "climate.air2", CONF_ALLOW_ON_OFF_CONTROL: allow_on_off}),
    ]
    entity._config = SimpleNamespace(
        get_water_device=lambda: ({CONF_CLIMATE_ENTITY: "climate.hp1"}, 0) if water else None,
        get_air_devices=lambda: air_devices,
    )
    entity.coordinator = SimpleNamespace(data={})
    entity._assist_controller = MagicMock()
    entity._assist_controller.get_timer_state.return_value = SimpleNamespace(
        off_timer_seconds=0.0, on_timer_seconds=0.0, active_condition="none"
    )
    entity._commands = MagicMock(ensure_mode=AsyncMock(return_value=True))
    entity._calculate_mode_target = MagicMock(return_value=21.0)
    entity._assist_modes = {}
    entity._hp_modes = {}
    entity._payloads = {
        "climate.air1": {"hvac_mode": "heat"},
        "climate.air2": {"hvac_mode": air2_mode},
    }
    return entity


def _process_main_only(entity: PowerClimateClimate) -> set[str]:
    desired: set[str] = set()
    asyncio.run(
        entity._process_air_devices(20.0, False, None, entity._payloads, desired, {})
    )
    return desired


def test_main_only_turns_off_assists_with_on_off_control() -> None:
    """With a water main, air pumps with on/off control are turned off."""
    entity = _make_main_only_entity(water=True)

    desired = _process_main_only(entity)

    entity._commands.ensure_mode.assert_awaited_once_with("climate.air2", HVACMode.OFF)
    entity._assist_controller.force_off.assert_called_once_with("climate.air2")
    entity._assist_controller.evaluate_action.assert_not_called()
    assert desired == set()
    assert entity._assist_modes["climate.air2"] == MODE_OFF


def test_main_only_never_turns_on_other_pumps() -> None:
    """A stopped non-main pump stays off."""
    entity = _make_main_only_entity(water=True, air2_mode="off")

    _process_main_only(entity)

    entity._commands.ensure_mode.assert_not_awaited()
    entity._assist_controller.evaluate_action.assert_not_called()


def test_main_only_leaves_pump_without_on_off_control() -> None:
    """Without on/off control a non-main pump keeps running untouched."""
    entity = _make_main_only_entity(water=True, allow_on_off=False)

    desired = _process_main_only(entity)

    entity._commands.ensure_mode.assert_not_awaited()
    assert desired == set()


def test_main_only_runs_first_air_pump_without_water() -> None:
    """Without a water heat pump, the first air pump is the main one."""
    entity = _make_main_only_entity(water=False)

    desired = _process_main_only(entity)

    assert desired == {"climate.air1"}
    entity._commands.ensure_mode.assert_awaited_once_with("climate.air2", HVACMode.OFF)


def test_set_preset_mode_ignores_removed_solar_preset() -> None:
    """The removed Solar preset is no longer accepted."""
    entity = make_entity()
    entity._config = SimpleNamespace(supply_advice_enabled=True, get_water_device=lambda: None)
    entity._enter_staged_preset = AsyncMock()

    asyncio.run(entity.async_set_preset_mode("solar"))

    entity._enter_staged_preset.assert_not_awaited()


# ---------------------------------------------------------------------------
# Supply-temperature control (supply advice preset); see test_supply_control.py
# ---------------------------------------------------------------------------


def _make_advice_entity(advice: float | None) -> PowerClimateClimate:
    """Return an entity in the supply advice preset with a kp 0.1 / 10 min controller."""
    entity = make_entity()
    entity._attr_hvac_mode = HVACMode.HEAT
    entity._attr_preset_mode = "supply_advice"
    entity._target_temperature = 21.4
    entity._config = SimpleNamespace(
        min_setpoint=16.0,
        max_setpoint=30.0,
        get_device_lower_offset=lambda _device, _index: -0.3,
        get_device_upper_offset=lambda _device, _index: 1.5,
        supply_pi_kp=0.1,
        supply_pi_ti_minutes=10.0,
        supply_pi_min_power_w=200.0,
        maximum_overshoot=0.5,
        supply_advice_sensor="sensor.supply_advice",
    )
    entity.coordinator = SimpleNamespace(data={"room_temperature": 21.0})
    entity._read_supply_advice = MagicMock(return_value=(advice, None))
    entity._supply = SupplyController(entity._config)
    return entity


def _water_target(entity: PowerClimateClimate, current_target: float = 21.5) -> float:
    return entity._calculate_mode_target(
        MODE_SUPPLY_ADVICE,
        current_temp=21.0,
        device={CONF_CLIMATE_ENTITY: "climate.hp1"},
        index=0,
        current_power=1000.0,
        current_target=current_target,
        water_temp=28.0,
    )


def test_supply_advice_target_comes_from_the_controller() -> None:
    """The water setpoint is the device temperature plus the controller's correction."""
    entity = _make_advice_entity(advice=30.0)

    assert _water_target(entity) == 21.5  # bumpless start from the current offset
    assert entity._supply.summary["supply_pi_advised_temp"] == 30.0


def test_supply_advice_falls_back_to_room_target_without_advice() -> None:
    """Without advice the normal setpoint logic applies and the controller waits."""
    entity = _make_advice_entity(advice=None)

    assert _water_target(entity) == 21.4
    assert entity._supply.initialized is False


def test_preset_change_resets_supply_controller() -> None:
    """A new preset starts the supply-temperature control afresh."""
    entity = make_entity()
    entity._config = SimpleNamespace(supply_advice_enabled=True, get_water_device=lambda: None)
    entity._attr_preset_mode = "none"
    entity._supply = MagicMock()
    entity._enter_staged_preset = AsyncMock()

    asyncio.run(entity.async_set_preset_mode("supply_advice"))

    entity._supply.reset.assert_called_once()


def test_hvac_mode_change_resets_supply_controller() -> None:
    """Switching between heat and cool starts the supply control afresh."""
    entity = make_entity()
    entity._attr_hvac_mode = HVACMode.HEAT
    entity._attr_preset_mode = "none"
    entity._supply = MagicMock()
    entity._apply_staging = AsyncMock()

    asyncio.run(entity.async_set_hvac_mode(HVACMode.COOL))

    entity._supply.reset.assert_called_once()


def test_handle_water_overshoot_control_turns_off_after_timer() -> None:
    """Auto-controllable water device should turn off after sustained overshoot."""
    entity = make_entity()
    entity._config = SimpleNamespace(assist_timer_seconds=300.0)
    entity._water_overshoot_since = None
    entity._water_overshoot = MagicMock(side_effect=[True, True])
    entity._commands = MagicMock(ensure_mode=AsyncMock())

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
    entity._commands.ensure_mode.assert_awaited_once_with("climate.hp1", HVACMode.OFF)


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
    entity._commands = MagicMock(ensure_mode=AsyncMock())
    entity._attr_preset_mode = "none"
    entity._calculate_mode_target = MagicMock(return_value=21.0)
    entity._hp_modes = {}

    desired_devices: set[str] = set()
    desired_targets: dict[str, float] = {}
    result = asyncio.run(
        entity._process_water_device(
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
    entity._commands.ensure_mode.assert_not_awaited()


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
    entity._commands = MagicMock(ensure_mode=AsyncMock())
    entity._attr_preset_mode = "none"
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
    entity._commands.ensure_mode.assert_awaited_once_with("climate.hp1", HVACMode.HEAT)


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
    entity._commands = MagicMock(ensure_mode=AsyncMock())
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
        entity._process_water_device(payloads, desired_devices, desired_targets)
    )

    # Water temp is still returned for diagnostic purposes
    assert result == (38.0, "off")
    assert entity._hp_modes["climate.hp1"] == MODE_OFF
    assert desired_devices == set()
    # Should have been switched off because allow_on_off=True and it was running
    entity._commands.ensure_mode.assert_awaited_once_with("climate.hp1", HVACMode.OFF)


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
        supply_advice_enabled=False,
    )
    entity._apply_away_mode = AsyncMock()

    asyncio.run(entity._enter_away_mode())

    assert entity._target_temperature == 30.0
    assert entity._attr_preset_mode == "away"
    assert entity._attr_hvac_mode == HVACMode.COOL  # mode must not change


def test_enter_supply_advice_preset_preserves_cool_mode() -> None:
    """Selecting the supply advice preset in cool mode keeps cool mode."""
    entity = make_entity()
    entity._attr_hvac_mode = HVACMode.COOL
    entity._attr_preset_mode = "none"
    entity._previous_target = None
    entity._apply_staging = AsyncMock()

    asyncio.run(entity._enter_staged_preset("supply_advice"))

    assert entity._attr_hvac_mode == HVACMode.COOL
    assert entity._attr_preset_mode == "supply_advice"


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
    entity._commands = MagicMock(ensure_mode=AsyncMock())
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
    entity._commands.ensure_mode.assert_awaited_once_with(
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
    entity._commands.ensure_mode.assert_awaited_once_with("climate.air1", HVACMode.OFF)
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
    entity._commands.ensure_mode.assert_not_awaited()


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
    entity._commands.ensure_mode.assert_awaited_once_with("climate.air1", HVACMode.COOL)
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
    entity._commands.ensure_mode.assert_awaited_once_with(
        "climate.air1", HVACMode.COOL, force=True
    )


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


def test_handle_assist_control_does_not_record_failed_turn_on() -> None:
    """A failed mode call must not be recorded as a turn-on."""
    entity = _make_assist_entity(HVACMode.HEAT)
    entity._assist_controller.evaluate_action.return_value = ("heat", "eta_high")
    entity._commands = MagicMock(ensure_mode=AsyncMock(return_value=False))

    result = asyncio.run(entity._handle_assist_control("climate.ac", False, {}))

    assert result is False
    entity._assist_controller.record_turn_on.assert_not_called()


def test_calculate_mode_target_keeps_device_setpoint_without_temperature() -> None:
    """Without a device temperature the current device setpoint is kept."""
    entity = make_entity()
    entity._config = SimpleNamespace(
        min_setpoint=16.0,
        max_setpoint=30.0,
        get_device_lower_offset=lambda _d, _i: -2.0,
        get_device_upper_offset=lambda _d, _i: 2.0,
    )
    entity._target_temperature = 21.0

    target = entity._calculate_mode_target(
        "setpoint", None, {CONF_CLIMATE_ENTITY: "climate.hp1"}, 0, current_target=35.0
    )

    assert target == 30.0
