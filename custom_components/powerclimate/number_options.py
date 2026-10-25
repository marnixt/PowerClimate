"""Numeric options of PowerClimate.

Each option is defined once here: the options forms, their defaults, the
config accessor and the diagnostics all read this table. Adding an option
means adding a row (plus its translations).
"""

from __future__ import annotations

from dataclasses import dataclass

from .const import (
    CONF_ASSIST_MIN_OFF_MINUTES,
    CONF_ASSIST_MIN_ON_MINUTES,
    CONF_ASSIST_OFF_ETA_THRESHOLD_MINUTES,
    CONF_ASSIST_ON_ETA_THRESHOLD_MINUTES,
    CONF_ASSIST_STALL_TEMP_DELTA,
    CONF_ASSIST_TIMER_SECONDS,
    CONF_ASSIST_WATER_TEMP_THRESHOLD,
    CONF_MAX_SETPOINT_OVERRIDE,
    CONF_MAXIMUM_OVERSHOOT,
    CONF_MIN_SETPOINT_OVERRIDE,
    CONF_ROOM_PI_TI_MINUTES,
    CONF_SUPPLY_PI_KP,
    CONF_SUPPLY_PI_MIN_POWER_W,
    CONF_SUPPLY_PI_TI_MINUTES,
)


@dataclass(frozen=True)
class NumberOption:
    """A numeric option with its default and the range the form allows."""

    key: str
    default: float
    min: float
    max: float
    step: float
    unit: str | None = None


# Advanced options: absolute setpoint limits and the room overshoot.
SETPOINT_OPTIONS = (
    NumberOption(CONF_MIN_SETPOINT_OVERRIDE, 16.0, 10, 25, 0.5, "°C"),
    NumberOption(CONF_MAX_SETPOINT_OVERRIDE, 30.0, 20, 35, 0.5, "°C"),
    NumberOption(CONF_MAXIMUM_OVERSHOOT, 0.5, 0, 5, 0.1, "°C"),
)

# Advanced options: when assist pumps turn on and off. The minimum on/off
# times are the anti-short-cycle protection (only with on/off control).
ASSIST_OPTIONS = (
    NumberOption(CONF_ASSIST_TIMER_SECONDS, 300.0, 60, 900, 30, "s"),
    NumberOption(CONF_ASSIST_ON_ETA_THRESHOLD_MINUTES, 60.0, 5, 600, 1, "min"),
    NumberOption(CONF_ASSIST_OFF_ETA_THRESHOLD_MINUTES, 15.0, 1, 120, 1, "min"),
    NumberOption(CONF_ASSIST_MIN_ON_MINUTES, 20.0, 0, 180, 1, "min"),
    NumberOption(CONF_ASSIST_MIN_OFF_MINUTES, 10.0, 0, 180, 1, "min"),
    NumberOption(CONF_ASSIST_WATER_TEMP_THRESHOLD, 40.0, 30, 55, 1, "°C"),
    NumberOption(CONF_ASSIST_STALL_TEMP_DELTA, 0.5, 0.1, 2, 0.1, "°C"),
)

# Experimental options: tuning of the supply-temperature controller.
SUPPLY_PI_OPTIONS = (
    NumberOption(CONF_SUPPLY_PI_KP, 0.15, 0.01, 1.0, 0.01),
    NumberOption(CONF_SUPPLY_PI_TI_MINUTES, 45.0, 5, 240, 1, "min"),
    NumberOption(CONF_SUPPLY_PI_MIN_POWER_W, 200.0, 0, 2000, 10, "W"),
)

# Experimental options: tuning of the water heat pump's room control.
ROOM_PI_OPTIONS = (
    NumberOption(CONF_ROOM_PI_TI_MINUTES, 30.0, 5, 240, 1, "min"),
)

ADVANCED_OPTIONS = (*SETPOINT_OPTIONS, *ASSIST_OPTIONS)

NUMBER_OPTIONS = {
    option.key: option
    for option in (*ADVANCED_OPTIONS, *SUPPLY_PI_OPTIONS, *ROOM_PI_OPTIONS)
}


def number_default(key: str) -> float:
    """Return the default of a numeric option."""
    return NUMBER_OPTIONS[key].default
