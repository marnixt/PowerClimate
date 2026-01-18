"""Power budget management for PowerClimate.

This module handles power budget allocation and setpoint calculation
for the Solar preset mode, distributing available solar power across
configured heat pumps.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

from .const import (
    DEFAULT_POWER_BUDGET_UPDATE_INTERVAL_SECONDS,
    DEFAULT_POWER_MAX_BUDGET_PER_DEVICE_W,
    DEFAULT_POWER_MIN_BUDGET_W,
    DEFAULT_POWER_MODE_ADJUSTMENT_INTERVAL_SECONDS,
    DEFAULT_POWER_MODE_DEADBAND_PERCENT,
    DEFAULT_POWER_MODE_STEP_SIZE,
    DEFAULT_POWER_SURPLUS_RESERVE_W,
)
from .utils import safe_float

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .config_accessor import ConfigAccessor

_LOGGER = logging.getLogger(__name__)


class PowerBudgetManager:
    """Manages power budget allocation for Solar preset.

    This class handles:
    - Reading house net power from configured sensor
    - Allocating power budgets across heat pumps
    - Calculating setpoints to match power budgets
    """

    def __init__(
        self,
        hass: HomeAssistant,
        config: ConfigAccessor,
    ) -> None:
        """Initialize the power budget manager.

        Args:
            hass: Home Assistant instance.
            config: ConfigAccessor for reading configuration.
        """
        self._hass = hass
        self._config = config

        # Power budget state
        self._budgets: dict[str, float] = {}  # entity_id -> target watts
        self._current_setpoints: dict[str, float] = {}  # entity_id -> setpoint
        self._last_adjustments: dict[str, datetime] = {}  # entity_id -> timestamp
        self._last_update: datetime | None = None

        # Diagnostic values
        self._house_net_power_w: float | None = None
        self._power_available_w: float | None = None
        self._power_budget_remaining_w: float | None = None

    @property
    def house_net_power_w(self) -> float | None:
        """Get the last read house net power in watts."""
        return self._house_net_power_w

    @property
    def power_available_w(self) -> float | None:
        """Get the available power for heat pumps in watts."""
        return self._power_available_w

    @property
    def power_budget_remaining_w(self) -> float | None:
        """Get the remaining unallocated power in watts."""
        return self._power_budget_remaining_w

    @property
    def budgets(self) -> dict[str, float]:
        """Get current power budgets by entity ID."""
        return dict(self._budgets)

    @property
    def total_budget_w(self) -> float:
        """Get total allocated power budget in watts."""
        return sum(float(v) for v in self._budgets.values()) if self._budgets else 0.0

    def get_budget(self, entity_id: str) -> float:
        """Get power budget for a specific entity.

        Args:
            entity_id: Climate entity ID.

        Returns:
            Power budget in watts, or 0.0 if not set.
        """
        return self._budgets.get(entity_id, 0.0)

    def set_budget(self, entity_id: str, power_watts: float) -> None:
        """Set power budget for a device.

        Args:
            entity_id: Climate entity ID.
            power_watts: Target power in watts.
        """
        self._budgets[entity_id] = power_watts
        _LOGGER.info("Power budget set for %s: %d W", entity_id, power_watts)

    def clear_budget(self, entity_id: str) -> None:
        """Clear power budget for a device.

        Args:
            entity_id: Climate entity ID.
        """
        self._budgets.pop(entity_id, None)
        self._current_setpoints.pop(entity_id, None)
        self._last_adjustments.pop(entity_id, None)
        _LOGGER.info("Power budget cleared for %s", entity_id)

    def clear_all(self) -> None:
        """Clear all power budgets and reset state."""
        self._budgets.clear()
        self._current_setpoints.clear()
        self._last_adjustments.clear()
        self._last_update = None
        self._house_net_power_w = None
        self._power_available_w = None
        self._power_budget_remaining_w = None

    def update_budgets(self, devices: list[dict[str, Any]]) -> None:
        """Update per-device power budgets from house net power.

        Budgets are allocated in device order (HP1 -> HP2 -> ...) until
        available power is exhausted.

        Args:
            devices: List of device configurations.
        """
        from .const import CONF_CLIMATE_ENTITY

        now = dt_util.utcnow()

        # Rate limit updates
        if self._last_update is not None:
            elapsed = (now - self._last_update).total_seconds()
            if elapsed < DEFAULT_POWER_BUDGET_UPDATE_INTERVAL_SECONDS:
                return

        self._last_update = now

        # Read house net power
        net_power_w = self._read_house_net_power()
        if net_power_w is None:
            self.clear_all()
            return

        self._house_net_power_w = float(net_power_w)

        # Calculate available power (negative = exporting = surplus)
        available_w = max(0.0, -net_power_w - DEFAULT_POWER_SURPLUS_RESERVE_W)
        self._power_available_w = float(available_w)

        remaining_w = available_w
        new_budgets: dict[str, float] = {}

        # Allocate budgets in device order
        for device in devices:
            entity_id = str(device.get(CONF_CLIMATE_ENTITY) or "").strip()
            if not entity_id:
                continue

            budget = min(DEFAULT_POWER_MAX_BUDGET_PER_DEVICE_W, remaining_w)
            if budget >= DEFAULT_POWER_MIN_BUDGET_W:
                new_budgets[entity_id] = float(budget)
                remaining_w -= budget
            else:
                # Stop allocating (priority order)
                break

        # Clear budgets for devices no longer allocated
        for entity_id in list(self._budgets.keys()):
            if entity_id not in new_budgets:
                self.clear_budget(entity_id)

        # Apply new budgets
        for entity_id, budget in new_budgets.items():
            self.set_budget(entity_id, budget)

        self._power_budget_remaining_w = float(max(0.0, remaining_w))

    def calculate_setpoint(
        self,
        entity_id: str,
        current_power: float | None,
        min_setpoint: float,
        max_setpoint: float,
    ) -> float:
        """Calculate setpoint to match power budget.

        Uses a simple step algorithm:
        1. Only adjust every ADJUSTMENT_INTERVAL seconds
        2. Use deadband - no adjustment if within tolerance
        3. Small fixed step size per adjustment
        4. Direction: power too low → raise setpoint, too high → lower

        Args:
            entity_id: Climate entity ID.
            current_power: Current power consumption in watts.
            min_setpoint: Minimum allowed setpoint.
            max_setpoint: Maximum allowed setpoint.

        Returns:
            Calculated setpoint temperature.
        """
        target_power = self._budgets.get(entity_id, 0.0)
        now = dt_util.utcnow()

        # Get or initialize current setpoint
        current_setpoint = self._current_setpoints.get(entity_id)
        if current_setpoint is None:
            current_setpoint = (min_setpoint + max_setpoint) / 2.0
            self._current_setpoints[entity_id] = current_setpoint

        # No budget or no power reading - return current
        if target_power <= 0 or current_power is None:
            return current_setpoint

        # Rate limit adjustments
        last_adjustment = self._last_adjustments.get(entity_id)
        if last_adjustment is not None:
            elapsed = (now - last_adjustment).total_seconds()
            if elapsed < DEFAULT_POWER_MODE_ADJUSTMENT_INTERVAL_SECONDS:
                return current_setpoint

        # Calculate error
        power_error = target_power - current_power
        power_error_percent = abs(power_error) / target_power

        # Within deadband - no adjustment
        if power_error_percent < DEFAULT_POWER_MODE_DEADBAND_PERCENT:
            return current_setpoint

        # Apply step adjustment
        if power_error > 0:
            # Need more power - raise setpoint
            new_setpoint = current_setpoint + DEFAULT_POWER_MODE_STEP_SIZE
        else:
            # Need less power - lower setpoint
            new_setpoint = current_setpoint - DEFAULT_POWER_MODE_STEP_SIZE

        # Clamp to bounds
        new_setpoint = max(min_setpoint, min(new_setpoint, max_setpoint))

        # Store state
        self._current_setpoints[entity_id] = new_setpoint
        self._last_adjustments[entity_id] = now

        _LOGGER.debug(
            "Power mode %s: target=%dW current=%dW error=%.0f%% setpoint %.1f→%.1f",
            entity_id,
            target_power,
            current_power,
            power_error_percent * 100,
            current_setpoint,
            new_setpoint,
        )

        return new_setpoint

    def _read_house_net_power(self) -> float | None:
        """Read signed house net active power in watts.

        Convention: negative means exporting (solar surplus).

        Returns:
            Power in watts, or None if unavailable.
        """
        sensor_id = self._config.house_power_sensor
        if not sensor_id:
            return None

        state = self._hass.states.get(sensor_id)
        if state is None:
            return None

        value = safe_float(state.state)
        if value is None:
            return None

        # Handle kW units
        unit = str(state.attributes.get("unit_of_measurement") or "").strip()
        if unit.lower() == "kw":
            return value * 1000.0

        return value

    def get_diagnostics(self) -> dict[str, Any]:
        """Get diagnostic information for summary payload.

        Returns:
            Dictionary with power budget diagnostic data.
        """
        return {
            "house_net_power_w": self._house_net_power_w,
            "power_available_w": self._power_available_w,
            "power_budget_remaining_w": self._power_budget_remaining_w,
            "power_budget_total_w": self.total_budget_w,
            "power_budget_by_entity_w": dict(self._budgets),
        }
