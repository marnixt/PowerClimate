"""Device configuration builder for PowerClimate.

This module provides reusable components for building device
configuration schemas and processing user input in the config flow.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.helpers.selector import selector

from .const import (
    CONF_ALLOW_ON_OFF_CONTROL,
    CONF_CLIMATE_ENTITY,
    CONF_COPY_SETPOINT_TO_POWERCLIMATE,
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    CONF_DEVICE_ROLE,
    CONF_ENERGY_SENSOR,
    CONF_LOWER_SETPOINT_OFFSET,
    CONF_UPPER_SETPOINT_OFFSET,
    CONF_WATER_SENSOR,
    DEFAULT_LOWER_SETPOINT_OFFSET_ASSIST,
    DEFAULT_LOWER_SETPOINT_OFFSET_HP1,
    DEFAULT_UPPER_SETPOINT_OFFSET_ASSIST,
    DEFAULT_UPPER_SETPOINT_OFFSET_HP1,
    DEVICE_ROLE_AIR,
    DEVICE_ROLE_WATER,
)
from .utils import generate_device_id, generate_device_name, parse_offset_with_default


# --- Selector Factories ---


def entity_selector(domain: str, multiple: bool = False) -> Any:
    """Create an entity selector.

    Args:
        domain: Entity domain to filter by.
        multiple: Whether to allow multiple selection.

    Returns:
        Selector configuration.
    """
    return selector({"entity": {"domain": [domain], "multiple": multiple}})


def text_selector() -> Any:
    """Create a text input selector."""
    return selector({"text": {}})


def number_selector(
    min_val: float,
    max_val: float,
    step: float = 0.1,
    unit: str | None = None,
) -> Any:
    """Create a number input selector.

    Args:
        min_val: Minimum value.
        max_val: Maximum value.
        step: Step increment.
        unit: Unit of measurement.

    Returns:
        Selector configuration.
    """
    config: dict[str, Any] = {"min": min_val, "max": max_val, "step": step}
    if unit:
        config["unit_of_measurement"] = unit
    return selector({"number": config})


def lower_offset_selector() -> Any:
    """Create a lower offset selector (-5 to 0)."""
    return number_selector(-5, 0, 0.1)


def upper_offset_selector() -> Any:
    """Create an upper offset selector (0 to 5)."""
    return number_selector(0, 5, 0.1)


# --- Schema Field Helpers ---


def required_field(
    key: str,
    defaults: dict[str, Any],
    schema_fields: dict[Any, Any],
    schema_value: Any,
) -> None:
    """Add a required field to schema with optional default.

    Args:
        key: Field key.
        defaults: Dictionary of default values.
        schema_fields: Schema fields dictionary to modify.
        schema_value: Selector for the field.
    """
    default_value = defaults.get(key)
    if default_value is None:
        schema_fields[vol.Required(key)] = schema_value
    else:
        schema_fields[vol.Required(key, default=default_value)] = schema_value


def optional_field(
    key: str,
    defaults: dict[str, Any],
    schema_fields: dict[Any, Any],
    schema_value: Any,
) -> None:
    """Add an optional field to schema with optional default.

    Args:
        key: Field key.
        defaults: Dictionary of default values.
        schema_fields: Schema fields dictionary to modify.
        schema_value: Selector for the field.
    """
    default_value = defaults.get(key)
    if default_value is None:
        schema_fields[vol.Optional(key)] = schema_value
    else:
        schema_fields[vol.Optional(key, default=default_value)] = schema_value


# --- Device Configuration Builder ---


class DeviceConfigBuilder:
    """Builder for device configuration with schema and validation."""

    def __init__(
        self,
        device_role: str,
        climate_entity: str,
        used_ids: set[str],
    ) -> None:
        """Initialize the device config builder.

        Args:
            device_role: Device role ("water" or "air").
            climate_entity: Climate entity ID for this device.
            used_ids: Set of already-used device IDs.
        """
        self._role = device_role
        self._climate_entity = climate_entity
        self._used_ids = used_ids
        self._is_water = device_role == DEVICE_ROLE_WATER

    @property
    def default_lower_offset(self) -> float:
        """Get default lower offset for device role."""
        return (
            DEFAULT_LOWER_SETPOINT_OFFSET_HP1
            if self._is_water
            else DEFAULT_LOWER_SETPOINT_OFFSET_ASSIST
        )

    @property
    def default_upper_offset(self) -> float:
        """Get default upper offset for device role."""
        return (
            DEFAULT_UPPER_SETPOINT_OFFSET_HP1
            if self._is_water
            else DEFAULT_UPPER_SETPOINT_OFFSET_ASSIST
        )

    def build_defaults(
        self,
        existing_device: dict[str, Any] | None,
        user_input: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Build defaults dictionary from existing config and user input.

        Args:
            existing_device: Existing device configuration.
            user_input: Current user input (overrides existing).

        Returns:
            Dictionary of default values.
        """
        defaults: dict[str, Any] = {}

        if existing_device:
            defaults[CONF_ENERGY_SENSOR] = existing_device.get(CONF_ENERGY_SENSOR)
            defaults[CONF_COPY_SETPOINT_TO_POWERCLIMATE] = existing_device.get(
                CONF_COPY_SETPOINT_TO_POWERCLIMATE, False
            )
            defaults[CONF_LOWER_SETPOINT_OFFSET] = existing_device.get(
                CONF_LOWER_SETPOINT_OFFSET, self.default_lower_offset
            )
            defaults[CONF_UPPER_SETPOINT_OFFSET] = existing_device.get(
                CONF_UPPER_SETPOINT_OFFSET, self.default_upper_offset
            )

            # Water-specific
            if self._is_water:
                defaults[CONF_WATER_SENSOR] = existing_device.get(CONF_WATER_SENSOR)

            # Air-specific
            if not self._is_water:
                defaults[CONF_ALLOW_ON_OFF_CONTROL] = existing_device.get(
                    CONF_ALLOW_ON_OFF_CONTROL, False
                )

        # Set role-specific defaults
        defaults.setdefault(CONF_LOWER_SETPOINT_OFFSET, self.default_lower_offset)
        defaults.setdefault(CONF_UPPER_SETPOINT_OFFSET, self.default_upper_offset)
        defaults.setdefault(CONF_COPY_SETPOINT_TO_POWERCLIMATE, False)

        if not self._is_water:
            defaults.setdefault(CONF_ALLOW_ON_OFF_CONTROL, False)

        # User input takes priority
        if user_input:
            defaults.update(user_input)

        return defaults

    def build_schema(self, defaults: dict[str, Any]) -> vol.Schema:
        """Build voluptuous schema for device configuration.

        Args:
            defaults: Default values dictionary.

        Returns:
            Voluptuous schema.
        """
        schema_fields: dict[Any, Any] = {}

        # Common fields
        required_field(
            CONF_ENERGY_SENSOR,
            defaults,
            schema_fields,
            entity_selector("sensor"),
        )

        # Water-specific fields
        if self._is_water:
            required_field(
                CONF_WATER_SENSOR,
                defaults,
                schema_fields,
                entity_selector("sensor"),
            )

        # Offset fields
        optional_field(
            CONF_LOWER_SETPOINT_OFFSET,
            defaults,
            schema_fields,
            lower_offset_selector(),
        )
        optional_field(
            CONF_UPPER_SETPOINT_OFFSET,
            defaults,
            schema_fields,
            upper_offset_selector(),
        )

        # Boolean flags
        schema_fields[vol.Optional(
            CONF_COPY_SETPOINT_TO_POWERCLIMATE,
            default=defaults.get(CONF_COPY_SETPOINT_TO_POWERCLIMATE, False),
        )] = bool

        # Air-specific fields
        if not self._is_water:
            schema_fields[vol.Optional(
                CONF_ALLOW_ON_OFF_CONTROL,
                default=defaults.get(CONF_ALLOW_ON_OFF_CONTROL, False),
            )] = bool

        return vol.Schema(schema_fields)

    def process_input(
        self,
        user_input: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, dict[str, str]]:
        """Process and validate user input.

        Args:
            user_input: User-provided configuration values.

        Returns:
            Tuple of (device_config, errors) where device_config is None
            if validation failed.
        """
        errors: dict[str, str] = {}

        # Validate required fields
        energy_sensor = user_input.get(CONF_ENERGY_SENSOR)
        if not energy_sensor:
            errors[CONF_ENERGY_SENSOR] = "required"

        # Water-specific validation
        if self._is_water:
            water_sensor = user_input.get(CONF_WATER_SENSOR)
            if not water_sensor:
                errors[CONF_WATER_SENSOR] = "required"

        # Parse and validate offsets
        lower_offset, lower_valid = parse_offset_with_default(
            user_input.get(CONF_LOWER_SETPOINT_OFFSET, self.default_lower_offset),
            self.default_lower_offset,
        )
        if not lower_valid:
            errors[CONF_LOWER_SETPOINT_OFFSET] = "invalid"

        upper_offset, upper_valid = parse_offset_with_default(
            user_input.get(CONF_UPPER_SETPOINT_OFFSET, self.default_upper_offset),
            self.default_upper_offset,
        )
        if not upper_valid:
            errors[CONF_UPPER_SETPOINT_OFFSET] = "invalid"

        # Validate offset relationship
        if lower_offset > upper_offset:
            errors["base"] = "invalid_offsets"
            errors.setdefault(CONF_LOWER_SETPOINT_OFFSET, "invalid")
            errors.setdefault(CONF_UPPER_SETPOINT_OFFSET, "invalid")

        if errors:
            return None, errors

        # Build device configuration
        device_id = generate_device_id(self._climate_entity, self._used_ids)
        device: dict[str, Any] = {
            CONF_DEVICE_ID: device_id,
            CONF_DEVICE_NAME: generate_device_name(self._climate_entity),
            CONF_DEVICE_ROLE: self._role,
            CONF_CLIMATE_ENTITY: self._climate_entity,
            CONF_ENERGY_SENSOR: energy_sensor,
            CONF_COPY_SETPOINT_TO_POWERCLIMATE: bool(
                user_input.get(CONF_COPY_SETPOINT_TO_POWERCLIMATE, False)
            ),
            CONF_LOWER_SETPOINT_OFFSET: lower_offset,
            CONF_UPPER_SETPOINT_OFFSET: upper_offset,
        }

        # Role-specific fields
        if self._is_water:
            device[CONF_WATER_SENSOR] = user_input.get(CONF_WATER_SENSOR)
        else:
            device[CONF_ALLOW_ON_OFF_CONTROL] = bool(
                user_input.get(CONF_ALLOW_ON_OFF_CONTROL, False)
            )

        return device, {}


def create_water_device_builder(
    climate_entity: str,
    used_ids: set[str],
) -> DeviceConfigBuilder:
    """Create a builder for water device configuration.

    Args:
        climate_entity: Climate entity ID.
        used_ids: Set of already-used device IDs.

    Returns:
        DeviceConfigBuilder configured for water device.
    """
    return DeviceConfigBuilder(DEVICE_ROLE_WATER, climate_entity, used_ids)


def create_air_device_builder(
    climate_entity: str,
    used_ids: set[str],
) -> DeviceConfigBuilder:
    """Create a builder for air device configuration.

    Args:
        climate_entity: Climate entity ID.
        used_ids: Set of already-used device IDs.

    Returns:
        DeviceConfigBuilder configured for air device.
    """
    return DeviceConfigBuilder(DEVICE_ROLE_AIR, climate_entity, used_ids)
