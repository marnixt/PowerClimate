"""Decision rules of the staging logic.

Pure functions: the climate entity passes its state in explicitly, so the
rules can be tested without Home Assistant.
"""

from __future__ import annotations

from homeassistant.components.climate.const import HVACAction, HVACMode

from .const import (
    MODE_BOOST,
    MODE_MINIMAL,
    MODE_SETPOINT,
    MODE_SUPPLY_ADVICE,
    PRESET_AWAY,
    PRESET_BOOST,
    PRESET_SUPPLY_ADVICE,
)
from .utils import compute_eta_hours


def room_at_target(room: float | None, target: float | None, cooling: bool) -> bool:
    """Return True when the room has reached the target.

    Heating: at or above the target. Cooling: at or below it.
    """
    if room is None or target is None:
        return False
    return room <= target if cooling else room >= target


def room_eta_hours(
    room: float | None,
    target: float | None,
    derivative: float | None,
    cooling: bool,
) -> float | None:
    """Return the hours until the room reaches the target at the current rate."""
    if room is None or target is None:
        return None
    if cooling:
        # The room cools when the derivative is negative.
        rate = -derivative if derivative is not None else None
        return compute_eta_hours(room - target, rate)
    return compute_eta_hours(target - room, derivative)


def water_overshoot(
    room: float | None,
    target: float | None,
    maximum_overshoot: float,
    cooling: bool,
) -> bool:
    """Return True when the room is above target plus the maximum overshoot (heating)."""
    if cooling or room is None or target is None:
        return False
    return room > target + maximum_overshoot


def water_demand(room: float | None, target: float | None, cooling: bool) -> bool:
    """Return True when the water heat pump should turn on: the room is below target.

    The water heat pump is the primary device and turns on at any demand, well
    before the assist pumps (which wait for their ETA threshold). It cannot
    cool, so there is no demand in cooling mode.
    """
    if cooling or room is None or target is None:
        return False
    return room < target


def water_mode(preset: str) -> str:
    """Return the mode of the water heat pump while heating."""
    if preset == PRESET_BOOST:
        return MODE_BOOST
    if preset == PRESET_AWAY:
        return MODE_MINIMAL
    if preset == PRESET_SUPPLY_ADVICE:
        return MODE_SUPPLY_ADVICE
    return MODE_SETPOINT


def assist_mode(
    preset: str,
    at_target: bool,
    off_timer_seconds: float,
    automatic: bool,
) -> str:
    """Return the mode of a running assist pump.

    The supply advice is for the water heat pump; assists keep following
    room demand in that preset. An automatic pump (with on/off control) whose
    off timer runs stays minimal until it turns off.
    """
    if preset == PRESET_BOOST:
        return MODE_BOOST
    if (automatic and off_timer_seconds > 0) or at_target:
        return MODE_MINIMAL
    return MODE_SETPOINT


def hvac_action(hvac_mode: HVACMode, any_active: bool) -> HVACAction:
    """Return what the UI shows: off, idle, heating or cooling."""
    if hvac_mode == HVACMode.OFF:
        return HVACAction.OFF
    if not any_active:
        return HVACAction.IDLE
    return HVACAction.COOLING if hvac_mode == HVACMode.COOL else HVACAction.HEATING
