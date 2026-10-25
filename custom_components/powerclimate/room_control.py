"""Room control of the water heat pump (experimental, setpoint mode, heating).

The water heat pump's setpoint is a room setpoint, but the heat pump compares
it with its own thermostat. Sending PowerClimate's target as is hides the room
error PowerClimate measures (other sensors, an average of several) and gives
no extra push while a small shortage lasts. This controller moves the setpoint
relative to the temperature the device measures:

    setpoint = device temperature + (target - room) + integral

The proportional part (gain 1) passes the room error on as is; the integral
grows while a shortage lasts. The device's offsets bound the result.

The integral stops growing once the smoothed supply temperature reaches the
assist water threshold: the water heat pump then works hard and the assist
pumps take over. It does not shrink while an assist pump heats: a room above
target is then the assist's doing, not a sign that the water heat pump
pushes too hard.

Pure logic: the caller passes the readings and the current time, so the
control can be tested without Home Assistant.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from .const import (
    FLOAT_COMPARISON_EPSILON,
    WATER_SETPOINT_DEADBAND,
)
from .mode_targets import SetpointLimits
from .pi_controller import PIConfig, PIController
from .summary_payload import build_room_pi_summary
from .utils import clamp_value

# The proportional part passes the room error on one to one.
ROOM_PI_KP = 1.0


class RoomTuning(Protocol):
    """The options the controller reads (see ConfigAccessor)."""

    room_pi_ti_minutes: float
    assist_water_temp_threshold: float


class RoomController:
    """Turns the room error into a setpoint correction for the water heat pump."""

    def __init__(self, tuning: RoomTuning) -> None:
        """Initialize the controller with the configured tuning."""
        self._tuning = tuning
        self._pi = PIController()
        self._held_target: float | None = None
        # True when the water heat pump cannot push harder (setpoint at its
        # upper offset or supply at the threshold); None while not running.
        self.at_limit: bool | None = None
        # Diagnostics of the last update; inactive until the controller runs.
        self.summary: dict[str, Any] = build_room_pi_summary()

    @property
    def initialized(self) -> bool:
        """Return True once the controller has started."""
        return self._pi.initialized

    def reset(self) -> None:
        """Start the control afresh."""
        self._pi.reset()
        self._held_target = None
        self.at_limit = None

    def clear_summary(self) -> None:
        """Mark the controller inactive until it runs again."""
        self.at_limit = None
        self.summary = build_room_pi_summary()

    def correction(
        self,
        *,
        room: float | None,
        target: float | None,
        limits: SetpointLimits,
        current_temp: float | None,
        current_target: float | None,
        water_filtered: float | None,
        assist_running: bool,
        overshoot: bool,
        now: datetime,
    ) -> float | None:
        """Return the correction (°C) on the device temperature.

        Args:
            room: PowerClimate's room temperature.
            target: PowerClimate's room target.
            limits: The device's offsets bound the correction.
            current_temp: Temperature the device measures.
            current_target: The device's current setpoint.
            water_filtered: Smoothed supply temperature, if measured.
            assist_running: True while an assist pump heats.
            overshoot: True when the room is above target plus the maximum
                overshoot.
            now: Current time.

        Returns None (normal setpoint logic) without a room temperature, a
        target or a device temperature; the controller then keeps its state.
        """
        if room is None or target is None or current_temp is None:
            return None

        config = PIConfig(
            kp=ROOM_PI_KP,
            ti_seconds=self._tuning.room_pi_ti_minutes * 60.0,
            output_min=limits.lower_offset,
            output_max=limits.upper_offset,
        )
        error = target - room
        if not self._pi.initialized:
            # Start from the device's current offset, so enabling the control
            # or restarting does not make the setpoint jump.
            start = current_target - current_temp if current_target is not None else error
            self._pi.initialize(
                clamp_value(start, config.output_min, config.output_max), error, config
            )

        supply_hot = (
            water_filtered is not None
            and water_filtered >= self._tuning.assist_water_temp_threshold
        )
        result = self._pi.update(
            error,
            now,
            config,
            allow_increase=not supply_hot,
            allow_decrease=not assist_running,
        )
        correction = config.output_min if overshoot else result.output

        # Keep the setpoint unless it moves by at least the deadband, so the
        # heat pump does not get a new setpoint for every bit of noise.
        target_setpoint = current_temp + correction
        held = self._held_target
        if (
            not overshoot
            and held is not None
            and abs(target_setpoint - held) < WATER_SETPOINT_DEADBAND - FLOAT_COMPARISON_EPSILON
            and config.output_min <= held - current_temp <= config.output_max
        ):
            correction = held - current_temp
        else:
            self._held_target = target_setpoint

        self.at_limit = supply_hot or (
            result.output >= config.output_max - FLOAT_COMPARISON_EPSILON
        )
        self.summary = build_room_pi_summary(
            result=result,
            correction=correction,
            supply_hot=supply_hot,
            assist_running=assist_running,
            at_limit=self.at_limit,
        )
        return correction
