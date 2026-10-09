"""Smoothing and spike detection for the measured supply temperature.

Pure logic, like the PI controller it feeds. The raw supply temperature is
noisy (a few tenths of a degree per reading) and can jump when something else
heats the same pipe, such as a boiler making domestic hot water. Feeding that
straight into the controller makes the setpoint jitter, and a short jump
drives the controller to its lower limit for no reason.

The filter keeps a time-weighted moving average. A reading far above that
average is treated as a spike: the average is left alone and the caller is
told to hold its output. A "spike" that lasts longer than the maximum spike
duration is accepted as a real change of the supply temperature.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SupplyReading:
    """Filtered supply temperature and whether the raw reading is a spike."""

    filtered: float
    spike: bool


class SupplyFilter:
    """Exponential moving average with upward spike rejection."""

    def __init__(
        self,
        tau_seconds: float,
        spike_kelvin: float,
        max_spike_seconds: float,
    ) -> None:
        """Initialize the filter.

        Args:
            tau_seconds: Time constant of the moving average.
            spike_kelvin: A reading this far above the average is a spike.
            max_spike_seconds: After this long a spike counts as a real change.
        """
        self._tau = tau_seconds
        self._spike_kelvin = spike_kelvin
        self._max_spike_seconds = max_spike_seconds
        self._filtered: float | None = None
        self._last_update: datetime | None = None
        self._spike_since: datetime | None = None

    def reset(self) -> None:
        """Forget the average and any running spike."""
        self._filtered = None
        self._last_update = None
        self._spike_since = None

    def update(self, raw: float, now: datetime) -> SupplyReading:
        """Add a reading and return the filtered value."""
        if self._filtered is None or self._last_update is None:
            self._filtered = raw
            self._last_update = now
            self._spike_since = None
            return SupplyReading(raw, spike=False)

        if raw - self._filtered > self._spike_kelvin:
            if self._spike_since is None:
                self._spike_since = now
            if (now - self._spike_since).total_seconds() < self._max_spike_seconds:
                return SupplyReading(self._filtered, spike=True)
            # Too long for a spike: the supply temperature really changed.
            self._filtered = raw
            self._last_update = now
            self._spike_since = None
            return SupplyReading(raw, spike=False)

        self._spike_since = None
        dt = max(0.0, (now - self._last_update).total_seconds())
        alpha = 1.0 - math.exp(-dt / self._tau) if self._tau > 0 else 1.0
        self._filtered += alpha * (raw - self._filtered)
        self._last_update = now
        return SupplyReading(self._filtered, spike=False)
