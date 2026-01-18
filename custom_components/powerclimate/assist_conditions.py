"""Assist pump condition checking for PowerClimate."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config_accessor import ConfigAccessor


@dataclass
class ConditionResult:
    """Result of a condition check."""
    met: bool
    name: str = ""

    @classmethod
    def not_met(cls) -> ConditionResult:
        return cls(met=False, name="")


class AssistConditionChecker:
    """Checks conditions for assist pump ON/OFF control."""

    def __init__(self, config: ConfigAccessor) -> None:
        self._config = config

    def check_on_conditions(
        self, room_temp: float | None, target_temp: float | None,
        room_eta_minutes: float | None, water_temp: float | None,
        room_derivative: float | None,
    ) -> ConditionResult:
        """Check if any assist ON condition is met (eta_high, water_hot, stalled_below)."""
        result = self._check_eta_high(room_temp, target_temp, room_eta_minutes)
        if result.met:
            return result
        result = self._check_water_hot(room_temp, target_temp, water_temp)
        if result.met:
            return result
        result = self._check_stalled_below_target(room_temp, target_temp, room_derivative)
        if result.met:
            return result
        return ConditionResult.not_met()

    def check_off_conditions(
        self, room_temp: float | None, target_temp: float | None,
        room_eta_minutes: float | None, room_derivative: float | None,
    ) -> ConditionResult:
        """Check if any assist OFF condition is met (eta_low, overshoot, stalled_at_target)."""
        result = self._check_eta_low(room_eta_minutes)
        if result.met:
            return result
        result = self._check_overshoot(room_temp, target_temp)
        if result.met:
            return result
        result = self._check_stalled_at_target(room_temp, target_temp, room_derivative)
        if result.met:
            return result
        return ConditionResult.not_met()

    def _check_eta_high(self, room_temp: float | None, target_temp: float | None,
                        room_eta_minutes: float | None) -> ConditionResult:
        eta_threshold = self._config.assist_on_eta_threshold_minutes
        if (room_eta_minutes is not None and room_eta_minutes > eta_threshold
            and room_temp is not None and target_temp is not None
            and room_temp < target_temp):
            return ConditionResult(met=True, name="eta_high")
        return ConditionResult.not_met()

    def _check_water_hot(self, room_temp: float | None, target_temp: float | None,
                         water_temp: float | None) -> ConditionResult:
        water_threshold = self._config.assist_water_temp_threshold
        if (water_temp is not None and water_temp >= water_threshold
            and room_temp is not None and target_temp is not None
            and room_temp < target_temp):
            return ConditionResult(met=True, name="water_hot")
        return ConditionResult.not_met()

    def _check_stalled_below_target(self, room_temp: float | None, target_temp: float | None,
                                    room_derivative: float | None) -> ConditionResult:
        stall_delta = self._config.assist_stall_temp_delta
        if (room_derivative is not None and room_derivative <= 0.0
            and room_temp is not None and target_temp is not None
            and room_temp < (target_temp - stall_delta)):
            return ConditionResult(met=True, name="stalled_below_target")
        return ConditionResult.not_met()

    def _check_eta_low(self, room_eta_minutes: float | None) -> ConditionResult:
        eta_threshold = self._config.assist_off_eta_threshold_minutes
        if room_eta_minutes is not None and room_eta_minutes < eta_threshold:
            return ConditionResult(met=True, name="eta_low")
        return ConditionResult.not_met()

    def _check_overshoot(self, room_temp: float | None, target_temp: float | None) -> ConditionResult:
        if room_temp is not None and target_temp is not None and room_temp >= target_temp:
            return ConditionResult(met=True, name="overshoot")
        return ConditionResult.not_met()

    def _check_stalled_at_target(self, room_temp: float | None, target_temp: float | None,
                                 room_derivative: float | None) -> ConditionResult:
        stall_delta = self._config.assist_stall_temp_delta
        if (room_derivative is not None and room_derivative <= 0.0
            and room_temp is not None and target_temp is not None
            and (target_temp - room_temp) <= stall_delta):
            return ConditionResult(met=True, name="stalled_at_target")
        return ConditionResult.not_met()
