"""Supply-temperature control of the water heat pump (supply advice preset).

The water heat pump's setpoint is a room setpoint, so an advised supply
temperature cannot be sent as is. A PI controller on
``advice - measured supply`` moves the setpoint within the device's offsets
around the temperature the device measures.

Pure logic: the caller passes the readings and the current time, so the
control can be tested without Home Assistant.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from .const import (
    FLOAT_COMPARISON_EPSILON,
    SUPPLY_FILTER_TAU_SECONDS,
    SUPPLY_SETPOINT_DEADBAND,
    SUPPLY_SPIKE_KELVIN,
    SUPPLY_SPIKE_MAX_SECONDS,
)
from .mode_targets import SetpointLimits
from .pi_controller import PIConfig, PIController, PIResult
from .summary_payload import build_supply_pi_summary
from .supply_filter import SupplyFilter
from .utils import clamp_value


class SupplyTuning(Protocol):
    """The tuning options the controller reads (see ConfigAccessor)."""

    supply_pi_kp: float
    supply_pi_ti_minutes: float
    supply_pi_min_power_w: float


class SupplyController:
    """Turns an advised supply temperature into a setpoint correction."""

    def __init__(self, tuning: SupplyTuning) -> None:
        """Initialize the controller with the configured tuning."""
        self._tuning = tuning
        self._pi = PIController()
        self._filter = SupplyFilter(
            SUPPLY_FILTER_TAU_SECONDS, SUPPLY_SPIKE_KELVIN, SUPPLY_SPIKE_MAX_SECONDS
        )
        self._last_result: PIResult | None = None
        self._last_correction: float | None = None
        self._held_target: float | None = None
        # Diagnostics of the last update; inactive until the controller runs.
        self.summary: dict[str, Any] = build_supply_pi_summary(None)

    @property
    def initialized(self) -> bool:
        """Return True once the controller has started."""
        return self._pi.initialized

    def reset(self) -> None:
        """Start the control afresh."""
        self._pi.reset()
        self._filter.reset()
        self._last_result = None
        self._last_correction = None
        self._held_target = None

    def clear_summary(self) -> None:
        """Mark the controller inactive until it runs again."""
        self.summary = build_supply_pi_summary(None)

    def correction(
        self,
        *,
        source: str | None,
        advice: float | None,
        limits: SetpointLimits,
        current_temp: float | None,
        current_target: float | None,
        water_temp: float | None,
        power: float | None,
        overshoot: bool,
        now: datetime,
    ) -> float | None:
        """Return the correction (°C) on the device temperature.

        Args:
            source: The sensor the advice comes from.
            advice: Advised supply temperature.
            limits: The device's offsets bound the correction.
            current_temp: Temperature the device measures.
            current_target: The device's current setpoint.
            water_temp: Measured supply temperature.
            power: The water heat pump's power.
            overshoot: True when the room is above target plus the maximum
                overshoot.
            now: Current time.

        Returns None (normal setpoint logic) without an advice, a supply
        reading or a device temperature; the controller then keeps its state.
        """
        if advice is None or water_temp is None or current_temp is None:
            return None

        reading = self._filter.update(water_temp, now)
        if reading.spike and self._last_correction is not None:
            # Something else is heating the supply pipe (e.g. hot water from
            # a boiler): hold the last correction until the spike is over.
            self.summary = build_supply_pi_summary(
                source,
                advised_temp=advice,
                supply_temp=water_temp,
                supply_filtered=reading.filtered,
                spike=True,
                result=self._last_result,
                correction=self._last_correction,
            )
            return self._last_correction

        config = PIConfig(
            kp=self._tuning.supply_pi_kp,
            ti_seconds=self._tuning.supply_pi_ti_minutes * 60.0,
            output_min=limits.lower_offset,
            output_max=limits.upper_offset,
        )
        error = advice - reading.filtered
        if not self._pi.initialized:
            # Start from the device's current offset, so entering the preset
            # or restarting does not make the setpoint jump.
            start = current_target - current_temp if current_target is not None else 0.0
            self._pi.initialize(
                clamp_value(start, config.output_min, config.output_max), error, config
            )

        # Without compressor output the supply temperature says nothing about
        # the heat delivered, and above the overshoot limit the room has
        # enough: freeze the integral in both cases.
        compressor_running = power is not None and power >= self._tuning.supply_pi_min_power_w
        result = self._pi.update(
            error,
            now,
            config,
            integrate=compressor_running and not overshoot,
        )
        correction = config.output_min if overshoot else result.output

        # Keep the setpoint unless it moves by at least the deadband, so the
        # heat pump does not get a new setpoint for every bit of noise.
        target = current_temp + correction
        held = self._held_target
        if (
            not overshoot
            and held is not None
            and abs(target - held) < SUPPLY_SETPOINT_DEADBAND - FLOAT_COMPARISON_EPSILON
            and config.output_min <= held - current_temp <= config.output_max
        ):
            correction = held - current_temp
        else:
            self._held_target = target

        self._last_result = result
        self._last_correction = correction
        self.summary = build_supply_pi_summary(
            source,
            advised_temp=advice,
            supply_temp=water_temp,
            supply_filtered=reading.filtered,
            result=result,
            correction=correction,
        )
        return correction
