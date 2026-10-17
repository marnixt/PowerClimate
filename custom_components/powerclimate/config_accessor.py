"""Configuration accessor for PowerClimate.

This module provides a centralized way to access configuration values
with proper defaults and type conversion.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .const import (
    CONF_ASSIST_MIN_OFF_MINUTES,
    CONF_ASSIST_MIN_ON_MINUTES,
    CONF_ASSIST_OFF_ETA_THRESHOLD_MINUTES,
    CONF_ASSIST_ON_ETA_THRESHOLD_MINUTES,
    CONF_ASSIST_STALL_TEMP_DELTA,
    CONF_ASSIST_TIMER_SECONDS,
    CONF_ASSIST_WATER_TEMP_THRESHOLD,
    CONF_DEVICE_ROLE,
    CONF_DEVICES,
    CONF_LOWER_SETPOINT_OFFSET_COOLING,
    CONF_LOWER_SETPOINT_OFFSET_HEATING,
    CONF_MAX_SETPOINT_OVERRIDE,
    CONF_MAXIMUM_OVERSHOOT,
    CONF_MIN_SETPOINT_OVERRIDE,
    CONF_MIRROR_CLIMATE_ENTITIES,
    CONF_ROOM_SENSORS,
    CONF_SUPPLY_ADVICE_SENSOR,
    CONF_SUPPLY_PI_KP,
    CONF_SUPPLY_PI_MIN_POWER_W,
    CONF_SUPPLY_PI_TI_MINUTES,
    CONF_UPPER_SETPOINT_OFFSET_COOLING,
    CONF_UPPER_SETPOINT_OFFSET_HEATING,
    DEFAULT_LOWER_SETPOINT_OFFSET_ASSIST,
    DEFAULT_LOWER_SETPOINT_OFFSET_COOLING,
    DEFAULT_LOWER_SETPOINT_OFFSET_HP1,
    DEFAULT_UPPER_SETPOINT_OFFSET_ASSIST,
    DEFAULT_UPPER_SETPOINT_OFFSET_COOLING,
    DEFAULT_UPPER_SETPOINT_OFFSET_HP1,
    DEVICE_ROLE_AIR,
    DEVICE_ROLE_WATER,
)
from .helpers import merged_entry_data
from .number_options import NUMBER_OPTIONS
from .utils import parse_device_offset

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry


class ConfigAccessor:
    """Centralized access to PowerClimate configuration.

    This class provides type-safe access to configuration values with
    proper defaults, reducing code duplication across the integration.
    """

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the config accessor.

        Args:
            entry: The config entry to read configuration from.
        """
        self._entry = entry
        self._cache: dict[str, Any] | None = None

    def _get_config(self) -> dict[str, Any]:
        """Get merged config data with caching."""
        if self._cache is None:
            self._cache = merged_entry_data(self._entry)
        return self._cache

    def _number(self, key: str) -> float:
        """Return a numeric option, or its default when not set."""
        return float(self._get_config().get(key, NUMBER_OPTIONS[key].default))

    # --- Global Settings ---

    @property
    def min_setpoint(self) -> float:
        """Get the minimum setpoint override."""
        return self._number(CONF_MIN_SETPOINT_OVERRIDE)

    @property
    def max_setpoint(self) -> float:
        """Get the maximum setpoint override."""
        return self._number(CONF_MAX_SETPOINT_OVERRIDE)

    @property
    def room_sensors(self) -> list[str]:
        """Get list of room sensor entity IDs."""
        return self._get_config().get(CONF_ROOM_SENSORS) or []

    @property
    def supply_advice_sensor(self) -> str | None:
        """Get the advised supply temperature sensor entity ID."""
        sensor = str(self._get_config().get(CONF_SUPPLY_ADVICE_SENSOR) or "").strip()
        return sensor if sensor else None

    @property
    def supply_advice_enabled(self) -> bool:
        """Check if the supply advice preset is available."""
        return bool(self.supply_advice_sensor)

    @property
    def supply_pi_kp(self) -> float:
        """Get the supply-temperature controller's proportional gain."""
        return self._number(CONF_SUPPLY_PI_KP)

    @property
    def supply_pi_ti_minutes(self) -> float:
        """Get the supply-temperature controller's integral time in minutes."""
        return self._number(CONF_SUPPLY_PI_TI_MINUTES)

    @property
    def supply_pi_min_power_w(self) -> float:
        """Get the water heat pump power below which the integral is frozen."""
        return self._number(CONF_SUPPLY_PI_MIN_POWER_W)

    @property
    def mirror_thermostats(self) -> list[str]:
        """Get list of thermostats whose setpoints should be mirrored."""
        raw = self._get_config().get(CONF_MIRROR_CLIMATE_ENTITIES) or []
        if not isinstance(raw, list):
            return []
        seen: set[str] = set()
        result: list[str] = []
        for entity_id in raw:
            entity_id = str(entity_id).strip()
            if not entity_id or entity_id in seen:
                continue
            seen.add(entity_id)
            result.append(entity_id)
        return result

    # --- Assist Pump Settings ---

    @property
    def assist_timer_seconds(self) -> float:
        """Get the assist timer duration in seconds."""
        return self._number(CONF_ASSIST_TIMER_SECONDS)

    @property
    def assist_on_eta_threshold_minutes(self) -> float:
        """Get the ETA threshold for turning assist pumps ON."""
        return self._number(CONF_ASSIST_ON_ETA_THRESHOLD_MINUTES)

    @property
    def assist_off_eta_threshold_minutes(self) -> float:
        """Get the ETA threshold for turning assist pumps OFF."""
        return self._number(CONF_ASSIST_OFF_ETA_THRESHOLD_MINUTES)

    @property
    def assist_min_on_minutes(self) -> float:
        """Get minimum ON time for assist pumps (anti-short-cycle)."""
        return self._number(CONF_ASSIST_MIN_ON_MINUTES)

    @property
    def assist_min_off_minutes(self) -> float:
        """Get minimum OFF time for assist pumps (anti-short-cycle)."""
        return self._number(CONF_ASSIST_MIN_OFF_MINUTES)

    @property
    def assist_water_temp_threshold(self) -> float:
        """Get water temperature threshold for assist pump activation."""
        return self._number(CONF_ASSIST_WATER_TEMP_THRESHOLD)

    @property
    def assist_stall_temp_delta(self) -> float:
        """Get the stall detection temperature delta."""
        return self._number(CONF_ASSIST_STALL_TEMP_DELTA)

    @property
    def maximum_overshoot(self) -> float:
        """Get the maximum room overshoot before optional water shutoff."""
        return self._number(CONF_MAXIMUM_OVERSHOOT)

    # --- Device Configuration ---

    @property
    def devices(self) -> list[dict[str, Any]]:
        """Get list of device configurations."""
        return self._get_config().get(CONF_DEVICES) or []

    def get_device_role(self, device: dict[str, Any], index: int) -> str | None:
        """Get device role from explicit configuration.

        Returns the configured role ("water" or "air"), or None if the device
        has no valid role set. Devices without a role are ignored until
        reconfigured via the options flow.

        Args:
            device: Device configuration dictionary.
            index: Device index in the list.

        Returns:
            Device role: "water", "air", or None.
        """
        role = device.get(CONF_DEVICE_ROLE)
        if role in (DEVICE_ROLE_WATER, DEVICE_ROLE_AIR):
            return role
        return None

    def is_water_device(self, device: dict[str, Any], index: int) -> bool:
        """Check if device is a water-based heat pump."""
        return self.get_device_role(device, index) == DEVICE_ROLE_WATER

    def is_air_device(self, device: dict[str, Any], index: int) -> bool:
        """Check if device is an air-based heat pump."""
        return self.get_device_role(device, index) == DEVICE_ROLE_AIR

    def get_water_device(self) -> tuple[dict[str, Any], int] | None:
        """Get the water-based heat pump device and its index."""
        for index, device in enumerate(self.devices):
            if self.is_water_device(device, index):
                return device, index
        return None

    def get_air_devices(self) -> list[tuple[int, dict[str, Any]]]:
        """Get all air-based heat pump devices with their indices."""
        return [
            (index, device)
            for index, device in enumerate(self.devices)
            if self.is_air_device(device, index)
        ]

    def get_device_lower_offset(self, device: dict[str, Any], index: int) -> float:
        """Get lower setpoint offset for a device (heating mode)."""
        return self._get_device_heating_offset(device, index, "lower")

    def get_device_upper_offset(self, device: dict[str, Any], index: int) -> float:
        """Get upper setpoint offset for a device (heating mode)."""
        return self._get_device_heating_offset(device, index, "upper")

    def get_device_lower_offset_cooling(self, device: dict[str, Any], index: int) -> float:
        """Get lower setpoint offset for a device (cooling mode, air devices only)."""
        return self._get_device_cooling_offset(device, "lower")

    def get_device_upper_offset_cooling(self, device: dict[str, Any], index: int) -> float:
        """Get upper setpoint offset for a device (cooling mode, air devices only)."""
        return self._get_device_cooling_offset(device, "upper")

    def _get_device_heating_offset(
        self,
        device: dict[str, Any],
        index: int,
        offset_type: str,
    ) -> float:
        """Calculate device heating offset with role-based defaults."""
        if offset_type == "lower":
            value = device.get(CONF_LOWER_SETPOINT_OFFSET_HEATING)
            default_water = DEFAULT_LOWER_SETPOINT_OFFSET_HP1
            default_air = DEFAULT_LOWER_SETPOINT_OFFSET_ASSIST
        else:  # upper
            value = device.get(CONF_UPPER_SETPOINT_OFFSET_HEATING)
            default_water = DEFAULT_UPPER_SETPOINT_OFFSET_HP1
            default_air = DEFAULT_UPPER_SETPOINT_OFFSET_ASSIST

        parsed = parse_device_offset(value)
        if parsed is not None:
            return parsed

        is_water = self.is_water_device(device, index)
        return default_water if is_water else default_air

    def _get_device_cooling_offset(
        self,
        device: dict[str, Any],
        offset_type: str,
    ) -> float:
        """Calculate device cooling offset (air devices only)."""
        if offset_type == "lower":
            value = device.get(CONF_LOWER_SETPOINT_OFFSET_COOLING)
            default = DEFAULT_LOWER_SETPOINT_OFFSET_COOLING
        else:  # upper
            value = device.get(CONF_UPPER_SETPOINT_OFFSET_COOLING)
            default = DEFAULT_UPPER_SETPOINT_OFFSET_COOLING

        parsed = parse_device_offset(value)
        return parsed if parsed is not None else default

    def to_dict(self) -> dict[str, Any]:
        """Export all configuration as a dictionary."""
        return {
            **{key: self._number(key) for key in NUMBER_OPTIONS},
            "supply_advice_enabled": self.supply_advice_enabled,
            "supply_advice_sensor": self.supply_advice_sensor,
            "mirror_thermostats": self.mirror_thermostats,
            "device_count": len(self.devices),
        }
