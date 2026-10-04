"""Setpoint calculation for a heat pump in a given control mode.

Pure logic: every input is passed in explicitly, so the rules can be tested
without a climate entity. Inputs that are expensive or only meaningful for
one mode (MPC sensor, thermal model, power budget) are passed as callables
and only evaluated when that mode needs them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .const import (
    MODE_BOOST,
    MODE_MINIMAL,
    MODE_MPC,
    MODE_POWER,
    MODE_SETPOINT,
    MODE_THERMAL_MPC,
)
from .utils import clamp_setpoint, safe_float


@dataclass(frozen=True)
class SetpointLimits:
    """Setpoint range and the device's offsets around the current temperature."""

    min_setpoint: float
    max_setpoint: float
    lower_offset: float
    upper_offset: float


def calculate_mode_target(
    mode: str,
    current_temp: float | None,
    limits: SetpointLimits,
    *,
    target_temperature: float | None,
    is_cooling: bool,
    current_target: float | None = None,
    mpc_target: Callable[[], float | None] | None = None,
    thermal_target: Callable[[], float | None] | None = None,
    power_target: Callable[[], float] | None = None,
) -> float:
    """Calculate the setpoint for a device in the given mode.

    Args:
        mode: One of the MODE_* constants.
        current_temp: Temperature the device reports, if any.
        limits: Setpoint range and the device's offsets for the active
            HVAC mode (heating or cooling offsets).
        target_temperature: PowerClimate's room target.
        is_cooling: True when PowerClimate is in cooling mode.
        current_target: The device's current setpoint.
        mpc_target: Returns the external MPC sensor's advised temperature.
        thermal_target: Returns the internal thermal model's setpoint.
        power_target: Returns the setpoint that fits the power budget.
    """
    min_sp = limits.min_setpoint
    max_sp = limits.max_setpoint

    if current_temp is None:
        # Without a device temperature keep the current setpoint.
        fallback = safe_float(current_target)
        if fallback is None:
            fallback = safe_float(target_temperature)
        if fallback is None:
            return min_sp
        return max(min_sp, min(fallback, max_sp))

    if mode == MODE_MPC and mpc_target is not None:
        value = mpc_target()
        if value is not None:
            return max(min_sp, min(value, max_sp))

    if mode == MODE_THERMAL_MPC and thermal_target is not None:
        value = thermal_target()
        if value is not None:
            return value

    lower_offset = limits.lower_offset
    upper_offset = limits.upper_offset

    if mode == MODE_BOOST:
        # Boost: lowest setpoint when cooling, highest when heating.
        target = current_temp + (lower_offset if is_cooling else upper_offset)
        return max(min_sp, min(target, max_sp))

    if mode == MODE_MINIMAL:
        # Minimal: least cooling (highest setpoint) or least heating.
        target = current_temp + (upper_offset if is_cooling else lower_offset)
        return clamp_setpoint(target, current_temp, lower_offset, upper_offset, min_sp, max_sp)

    if mode == MODE_POWER and power_target is not None:
        return power_target()

    if mode in (MODE_SETPOINT, MODE_MPC, MODE_THERMAL_MPC):
        # MPC modes fall back to the room target when no advice is available.
        return clamp_setpoint(
            target_temperature, current_temp, lower_offset, upper_offset, min_sp, max_sp
        )

    return min_sp
