"""Tests for the staging decision rules."""

from homeassistant.components.climate.const import HVACAction, HVACMode

from custom_components.powerclimate import staging
from custom_components.powerclimate.const import (
    MODE_BOOST,
    MODE_MINIMAL,
    MODE_SETPOINT,
    MODE_SUPPLY_ADVICE,
)


def test_room_at_target_heating() -> None:
    assert staging.room_at_target(21.0, 21.0, cooling=False) is True
    assert staging.room_at_target(20.9, 21.0, cooling=False) is False


def test_room_at_target_cooling_is_at_or_below() -> None:
    assert staging.room_at_target(22.0, 22.0, cooling=True) is True
    assert staging.room_at_target(21.5, 22.0, cooling=True) is True
    assert staging.room_at_target(22.1, 22.0, cooling=True) is False


def test_room_at_target_without_readings() -> None:
    assert staging.room_at_target(None, 21.0, cooling=False) is False
    assert staging.room_at_target(21.0, None, cooling=False) is False


def test_room_eta_heating() -> None:
    assert staging.room_eta_hours(20.0, 21.0, 0.5, cooling=False) == 2.0


def test_room_eta_cooling_inverts_the_derivative() -> None:
    """While cooling the room approaches the target when the derivative is negative."""
    assert staging.room_eta_hours(23.0, 22.0, -0.5, cooling=True) == 2.0


def test_room_eta_unknown_without_readings() -> None:
    assert staging.room_eta_hours(None, 21.0, 0.5, cooling=False) is None


def test_water_overshoot_uses_maximum_overshoot() -> None:
    assert staging.water_overshoot(21.6, 21.0, 0.5, cooling=False) is True
    assert staging.water_overshoot(21.5, 21.0, 0.5, cooling=False) is False


def test_water_overshoot_false_in_cool_mode() -> None:
    assert staging.water_overshoot(25.0, 21.0, 0.5, cooling=True) is False


def test_water_demand_on_any_demand() -> None:
    """The water heat pump turns on as soon as the room is below target."""
    assert staging.water_demand(20.9, 21.0, cooling=False) is True
    assert staging.water_demand(21.0, 21.0, cooling=False) is False


def test_water_demand_false_in_cool_mode() -> None:
    assert staging.water_demand(18.0, 21.0, cooling=True) is False


def test_water_mode_per_preset() -> None:
    assert staging.water_mode("none") == MODE_SETPOINT
    assert staging.water_mode("main_only") == MODE_SETPOINT
    assert staging.water_mode("boost") == MODE_BOOST
    assert staging.water_mode("away") == MODE_MINIMAL
    assert staging.water_mode("supply_advice") == MODE_SUPPLY_ADVICE


def test_assist_follows_room_demand_in_supply_advice_preset() -> None:
    """The advice is a supply temperature; assists keep normal logic."""
    assert staging.assist_mode("supply_advice", False, 0.0, False) == MODE_SETPOINT
    assert staging.assist_mode("supply_advice", True, 0.0, False) == MODE_MINIMAL


def test_assist_mode_boost() -> None:
    assert staging.assist_mode("boost", True, 10.0, True) == MODE_BOOST


def test_automatic_assist_stays_minimal_while_off_timer_runs() -> None:
    assert staging.assist_mode("none", False, 30.0, True) == MODE_MINIMAL
    assert staging.assist_mode("none", False, 30.0, False) == MODE_SETPOINT


def test_hvac_action() -> None:
    assert staging.hvac_action(HVACMode.OFF, True) == HVACAction.OFF
    assert staging.hvac_action(HVACMode.HEAT, False) == HVACAction.IDLE
    assert staging.hvac_action(HVACMode.HEAT, True) == HVACAction.HEATING
    assert staging.hvac_action(HVACMode.COOL, True) == HVACAction.COOLING
