"""Proportional-integral controller for the supply-temperature correction.

Pure logic: the caller passes the error, the current time and the tuning on
every update, so the controller can be tested without Home Assistant.

The output is a correction in °C that the caller adds to a base temperature.
It is limited to ``[output_min, output_max]``. Anti-windup uses conditional
integration: the integral does not grow while the output is saturated in the
direction of the error, and it is itself kept within the output limits.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .utils import clamp_value

DEFAULT_MAX_DT_SECONDS = 300.0


@dataclass(frozen=True)
class PIConfig:
    """Tuning and output limits of the controller.

    Attributes:
        kp: Proportional gain (output °C per °C of error).
        ti_seconds: Integral time; the integral adds ``kp * error`` every
            ``ti_seconds``.
        output_min: Lowest correction.
        output_max: Highest correction.
        max_dt_seconds: Longest time step counted in one update, so a long gap
            between updates (restart, missing data) does not cause a jump.
    """

    kp: float
    ti_seconds: float
    output_min: float
    output_max: float
    max_dt_seconds: float = DEFAULT_MAX_DT_SECONDS


@dataclass(frozen=True)
class PIResult:
    """Outcome of one controller update."""

    output: float
    error: float
    p_term: float
    i_term: float
    integrating: bool
    saturated: bool


class PIController:
    """PI controller with conditional-integration anti-windup."""

    def __init__(self) -> None:
        """Initialize an empty controller."""
        self._integral: float | None = None
        self._last_update: datetime | None = None

    @property
    def initialized(self) -> bool:
        """Return True once the integral has a starting value."""
        return self._integral is not None

    def reset(self) -> None:
        """Forget the integral and the time of the last update."""
        self._integral = None
        self._last_update = None

    def initialize(self, output: float, error: float, config: PIConfig) -> None:
        """Start so that the first output equals ``output`` (bumpless start)."""
        self._integral = clamp_value(
            output - config.kp * error, config.output_min, config.output_max
        )
        self._last_update = None

    def update(
        self,
        error: float,
        now: datetime,
        config: PIConfig,
        *,
        integrate: bool = True,
    ) -> PIResult:
        """Advance the controller and return the new output.

        Args:
            error: Setpoint minus measurement.
            now: Time of this update.
            config: Tuning and output limits.
            integrate: False freezes the integral; the proportional term
                still responds.
        """
        integral = self._integral if self._integral is not None else 0.0
        integral = clamp_value(integral, config.output_min, config.output_max)

        dt = 0.0
        if self._last_update is not None:
            elapsed = (now - self._last_update).total_seconds()
            dt = clamp_value(elapsed, 0.0, config.max_dt_seconds)
        self._last_update = now

        p_term = config.kp * error
        unclamped = p_term + integral
        pushing_up = error > 0 and unclamped >= config.output_max
        pushing_down = error < 0 and unclamped <= config.output_min
        integrating = (
            integrate
            and config.ti_seconds > 0
            and dt > 0
            and not pushing_up
            and not pushing_down
        )
        if integrating:
            integral += config.kp / config.ti_seconds * error * dt
            integral = clamp_value(integral, config.output_min, config.output_max)
        self._integral = integral

        unclamped = p_term + integral
        output = clamp_value(unclamped, config.output_min, config.output_max)
        return PIResult(
            output=output,
            error=error,
            p_term=p_term,
            i_term=integral,
            integrating=integrating,
            saturated=output != unclamped,
        )
