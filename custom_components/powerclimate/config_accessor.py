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
    CONF_DEVICES,
    CONF_HOUSE_POWER_SENSOR,
    CONF_LOWER_SETPOINT_OFFSET,
    CONF_MAX_SETPOINT_OVERRIDE,
    CONF_MIN_SETPOINT_OVERRIDE,
    CONF_MIRROR_CLIMATE_ENTITIES,
    CONF_ROOM_SENSORS,
    CONF_UPPER_SETPOINT_OFFSET,
    DEFAULT_ASSIST_MIN_OFF_MINUTES,
    DEFAULT_ASSIST_MIN_ON_MINUTES,
    DEFAULT_ASSIST_OFF_ETA_THRESHOLD_MINUTES,
    DEFAULT_ASSIST_ON_ETA_THRESHOLD_MINUTES,
    DEFAULT_ASSIST_STALL_TEMP_DELTA,
    DEFAULT_ASSIST_TIMER_SECONDS,
    DEFAULT_ASSIST_WATER_TEMP_THRESHOLD,
    DEFAULT_LOWER_SETPOINT_OFFSET_ASSIST,
    DEFAULT_LOWER_SETPOINT_OFFSET_HP1,
    DEFAULT_MAX_SETPOINT,
    DEFAULT_MIN_SETPOINT,
    DEFAULT_UPPER_SETPOINT_OFFSET_ASSIST,
    DEFAULT_UPPER_SETPOINT_OFFSET_HP1,
    DEVICE_ROLE_AIR,
    DEVICE_ROLE_WATER,
)
from .helpers import merged_entry_data
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

    def invalidate_cache(self) -> None:
        """Invalidate the config cache to force a reload."""
        self._cache = None

    # --- Global Settings ---

    @property
    def min_setpoint(self) -> float:
        """Get the minimum setpoint override."""
        return float(
            self._get_config().get(CONF_MIN_SETPOINT_OVERRIDE, DEFAULT_MIN_SETPOINT)
        )

    @property
    def max_setpoint(self) -> float:
        """Get the maximum setpoint override."""
        return float(
            self._get_config().get(CONF_MAX_SETPOINT_OVERRIDE, DEFAULT_MAX_SETPOINT)
        )

    @property
    def room_sensors(self) -> list[str]:
        """Get list of room sensor entity IDs."""
        return self._get_config().get(CONF_ROOM_SENSORS) or []

    @property
    def house_power_sensor(self) -> str | None:
        """Get the house power sensor entity ID."""
        sensor = str(self._get_config().get(CONF_HOUSE_POWER_SENSOR) or "").strip()
        return sensor if sensor else None

    @property
    def solar_enabled(self) -> bool:
        """Check if Solar preset is available."""
        return bool(self.house_power_sensor)

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
        return float(
            self._get_config().get(CONF_ASSIST_TIMER_SECONDS, DEFAULT_ASSIST_TIMER_SECONDS)
        )

    @property
    def assist_on_eta_threshold_minutes(self) -> float:
        """Get the ETA threshold for turning assist pumps ON."""
        return float(
            self._get_config().get(
                CONF_ASSIST_ON_ETA_THRESHOLD_MINUTES,
                DEFAULT_ASSIST_ON_ETA_THRESHOLD_MINUTES,
            )
        )

    @property
    def assist_off_eta_threshold_minutes(self) -> float:
        """Get the ETA threshold for turning assist pumps OFF."""
        return float(
            self._get_config().get(
                CONF_ASSIST_OFF_ETA_THRESHOLD_MINUTES,
                DEFAULT_ASSIST_OFF_ETA_THRESHOLD_MINUTES,
            )
        )

    @property
    def assist_min_on_minutes(self) -> float:
        """Get minimum ON time for assist pumps (anti-short-cycle)."""
        return float(
            self._get_config().get(CONF_ASSIST_MIN_ON_MINUTES, DEFAULT_ASSIST_MIN_ON_MINUTES)
        )

    @property
    def assist_min_off_minutes(self) -> float:
        """Get minimum OFF time for assist pumps (anti-short-cycle)."""
        return float(
            self._get_config().get(CONF_ASSIST_MIN_OFF_MINUTES, DEFAULT_ASSIST_MIN_OFF_MINUTES)
        )

    @property
    def assist_water_temp_threshold(self) -> float:
        """Get water temperature threshold for assist pump activation."""
        return float(
            self._get_config().get(
                CONF_ASSIST_WATER_TEMP_THRESHOLD,
                DEFAULT_ASSIST_WATER_TEMP_THRESHOLD,
            )
        )

    @property
    def assist_stall_temp_delta(self) -> float:
        """Get the stall detection temperature delta."""
        return float(
            self._get_config().get(CONF_ASSIST_STALL_TEMP_DELTA, DEFAULT_ASSIST_STALL_TEMP_DELTA)
        )

    # --- Device Configuration ---

    @property
    def devices(self) -> list[dict[str, Any]]:
        """Get list of device configurations."""
        return self._get_config().get(CONF_DEVICES) or []

    def get_device_role(self, device: dict[str, Any], index: int) -> str:
        """Get device role with backward compatibility.

        If device_role is explicitly set, use it. Otherwise, treat first device
        as water (primary) and rest as air (assist).

        Args:
            device: Device configuration dictionary.
            index: Device index in the list.

        Returns:
            Device role: "water" or "air".
        """
        from .const import CONF_DEVICE_ROLE

        role = device.get(CONF_DEVICE_ROLE)
        if role in (DEVICE_ROLE_WATER, DEVICE_ROLE_AIR):
            return role
        # Backward compatibility: index 0 = water, rest = air
        return DEVICE_ROLE_WATER if index == 0 else DEVICE_ROLE_AIR

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
        """Get lower setpoint offset for a device."""
        return self._get_device_offset(device, index, "lower")

    def get_device_upper_offset(self, device: dict[str, Any], index: int) -> float:
        """Get upper setpoint offset for a device."""
        return self._get_device_offset(device, index, "upper")

    def _get_device_offset(
        self,
        device: dict[str, Any],
        index: int,
        offset_type: str,
    ) -> float:
        """Calculate device offset with defaults based on role."""
        if offset_type == "lower":
            value = device.get(CONF_LOWER_SETPOINT_OFFSET)
            default_water = DEFAULT_LOWER_SETPOINT_OFFSET_HP1
            default_air = DEFAULT_LOWER_SETPOINT_OFFSET_ASSIST
        else:  # upper
            value = device.get(CONF_UPPER_SETPOINT_OFFSET)
            default_water = DEFAULT_UPPER_SETPOINT_OFFSET_HP1
            default_air = DEFAULT_UPPER_SETPOINT_OFFSET_ASSIST

        parsed = parse_device_offset(value)
        if parsed is not None:
            return parsed

        # Use device role to determine default
        is_water = self.is_water_device(device, index)
        return default_water if is_water else default_air

    def to_dict(self) -> dict[str, Any]:
        """Export all configuration as a dictionary."""
        return {
            "min_setpoint": self.min_setpoint,
            "max_setpoint": self.max_setpoint,
            "assist_timer_seconds": self.assist_timer_seconds,
            "assist_on_eta_threshold_minutes": self.assist_on_eta_threshold_minutes,
            "assist_off_eta_threshold_minutes": self.assist_off_eta_threshold_minutes,
            "assist_min_on_minutes": self.assist_min_on_minutes,
            "assist_min_off_minutes": self.assist_min_off_minutes,
            "assist_water_temp_threshold": self.assist_water_temp_threshold,
            "assist_stall_temp_delta": self.assist_stall_temp_delta,
            "solar_enabled": self.solar_enabled,
            "house_power_sensor": self.house_power_sensor,
            "mirror_thermostats": self.mirror_thermostats,
            "device_count": len(self.devices),
        }
