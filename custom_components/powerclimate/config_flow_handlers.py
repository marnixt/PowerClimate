"""Shared step handlers for PowerClimate config and options flows.

This module provides shared logic between ConfigFlow and OptionsFlow,
reducing code duplication and ensuring consistent behavior.
"""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol
from homeassistant import data_entry_flow
from homeassistant.helpers.selector import selector

from .const import (
    CONF_ALLOW_ON_OFF_CONTROL,
    CONF_ASSIST_MIN_OFF_MINUTES,
    CONF_ASSIST_MIN_ON_MINUTES,
    CONF_ASSIST_OFF_ETA_THRESHOLD_MINUTES,
    CONF_ASSIST_ON_ETA_THRESHOLD_MINUTES,
    CONF_ASSIST_STALL_TEMP_DELTA,
    CONF_ASSIST_TIMER_SECONDS,
    CONF_ASSIST_WATER_TEMP_THRESHOLD,
    CONF_CLIMATE_ENTITY,
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    CONF_DEVICE_ROLE,
    CONF_DEVICES,
    CONF_ENERGY_SENSOR,
    CONF_ENTRY_NAME,
    CONF_HOUSE_POWER_SENSOR,
    CONF_LOWER_SETPOINT_OFFSET_HEATING,
    CONF_LOWER_SETPOINT_OFFSET_COOLING,
    CONF_MAX_SETPOINT_OVERRIDE,
    CONF_MAXIMUM_OVERSHOOT,
    CONF_MIN_SETPOINT_OVERRIDE,
    CONF_MPC_TEMPERATURE_SENSOR,
    CONF_MIRROR_CLIMATE_ENTITIES,
    CONF_OUTDOOR_TEMP_SENSOR,
    CONF_ROOM_SENSORS,
    CONF_UPPER_SETPOINT_OFFSET_HEATING,
    CONF_UPPER_SETPOINT_OFFSET_COOLING,
    CONF_WATER_SENSOR,
    DEFAULT_ASSIST_MIN_OFF_MINUTES,
    DEFAULT_ASSIST_MIN_ON_MINUTES,
    DEFAULT_ASSIST_STALL_TEMP_DELTA,
    DEFAULT_ASSIST_TIMER_SECONDS,
    DEFAULT_ASSIST_WATER_TEMP_THRESHOLD,
    DEFAULT_MAXIMUM_OVERSHOOT,
    DEFAULT_ENTRY_NAME,
    DEFAULT_LOWER_SETPOINT_OFFSET_ASSIST,
    DEFAULT_LOWER_SETPOINT_OFFSET_COOLING,
    DEFAULT_LOWER_SETPOINT_OFFSET_HP1,
    DEFAULT_MAX_SETPOINT,
    DEFAULT_MIN_SETPOINT,
    DEFAULT_UPPER_SETPOINT_OFFSET_ASSIST,
    DEFAULT_UPPER_SETPOINT_OFFSET_COOLING,
    DEFAULT_UPPER_SETPOINT_OFFSET_HP1,
    DEVICE_ROLE_AIR,
    DEVICE_ROLE_WATER,
)

# Field names for UI toggles (not stored in data)
FIELD_WATER_CLIMATE = "water_climate_entity_id"
FIELD_AIR_CLIMATES = "air_climate_entity_ids"


# --- Utility Functions ---


def entity_selector(domain: str, multiple: bool = False) -> Any:
    """Create an entity selector for the given domain."""
    return selector({"entity": {"domain": [domain], "multiple": multiple}})


def text_selector() -> Any:
    """Create a text input selector."""
    return selector({"text": {}})


def lower_offset_selector() -> Any:
    """Create a selector for lower offset values (-5 to 0)."""
    return selector({"number": {"min": -10, "max": 0, "step": 0.1}})


def upper_offset_selector() -> Any:
    """Create a selector for upper offset values (0 to 5)."""
    return selector({"number": {"min": 0, "max": 10, "step": 0.1}})


def sectioned_schema(
    sections: tuple[tuple[str, dict[Any, Any], bool], ...],
) -> vol.Schema:
    """Build a schema from named collapsible sections."""
    return vol.Schema(
        {
            vol.Required(name): data_entry_flow.section(
                vol.Schema(fields), {"collapsed": collapsed}
            )
            for name, fields, collapsed in sections
        }
    )


def flatten_section_data(user_input: dict[str, Any]) -> dict[str, Any]:
    """Flatten nested section values returned by Home Assistant forms."""
    flattened: dict[str, Any] = {}
    for key, value in user_input.items():
        if isinstance(value, dict):
            flattened.update(value)
        else:
            flattened[key] = value
    return flattened


def build_fields(
    defaults: dict[str, Any],
    fields: tuple[tuple[str, Any], ...],
    *,
    required: bool = False,
) -> dict[Any, Any]:
    """Build schema fields with defaults from the current configuration."""
    field_type = vol.Required if required else vol.Optional
    return {
        (
            field_type(key, default=defaults[key])
            if defaults.get(key) is not None
            else field_type(key)
        ): schema_value
        for key, schema_value in fields
    }


def parse_offset(raw: Any, default: float) -> tuple[float, bool]:
    """Parse an offset while preserving a leading -0.

    Returns:
        Tuple of (value, is_valid).
    """
    raw_str = None
    if isinstance(raw, str):
        raw_str = raw.strip()
    elif raw is not None:
        raw_str = str(raw).strip()

    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default, False

    if raw_str and re.match(r"^-0(\.0+)?$", raw_str):
        return -0.0, True

    return value, True


def parse_offset_pair(
    user_input: dict[str, Any],
    lower_key: str,
    lower_default: float,
    upper_key: str,
    upper_default: float,
    errors: dict[str, str],
    *,
    compare_invalid: bool = False,
) -> tuple[float, float]:
    """Parse and validate a lower/upper offset pair."""
    lower, lower_valid = parse_offset(
        user_input.get(lower_key, lower_default),
        lower_default,
    )
    if not lower_valid:
        errors[lower_key] = "invalid"

    upper, upper_valid = parse_offset(
        user_input.get(upper_key, upper_default),
        upper_default,
    )
    if not upper_valid:
        errors[upper_key] = "invalid"

    if (compare_invalid or lower_valid and upper_valid) and lower > upper:
        errors["base"] = "invalid_offsets"
        errors.setdefault(lower_key, "invalid")
        errors.setdefault(upper_key, "invalid")

    return lower, upper


def slugify(value: str) -> str:
    """Convert string to lowercase slug with underscores."""
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9_]+", "_", value)
    value = re.sub(r"_+", "_", value)
    return value.strip("_")


def generate_device_id(climate_entity: str, used_ids: set[str]) -> str:
    """Generate unique device ID from climate entity."""
    base = slugify(climate_entity.split(".")[-1]) or "hp"
    candidate = base
    counter = 2
    while candidate in used_ids:
        candidate = f"{base}_{counter}"
        counter += 1
    return candidate


def generate_device_name(climate_entity: str) -> str:
    """Generate human-readable device name from entity ID."""
    raw = climate_entity.split(".")[-1].replace("_", " ")
    return raw.title() if raw else climate_entity


def entry_name_from_input(
    user_input: dict[str, Any] | None,
    base: dict[str, Any] | None = None,
) -> str:
    """Extract entry name from user input or base config."""
    raw = None
    if user_input:
        raw = user_input.get(CONF_ENTRY_NAME)
    if raw is None and base:
        raw = base.get(CONF_ENTRY_NAME)
    if raw is None:
        return DEFAULT_ENTRY_NAME
    text = str(raw).strip()
    return text or DEFAULT_ENTRY_NAME


def split_devices_by_role(
    base: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Split devices into water device and air devices based on role.

    For backward compatibility, if no role is set:
    - First device is assumed to be water
    - Remaining devices are assumed to be air
    """
    devices = [
        dict(device)
        for device in (base or {}).get(CONF_DEVICES, [])
        if isinstance(device, dict)
    ]
    if not devices:
        return None, []

    water_device = None
    air_devices = []

    for i, device in enumerate(devices):
        role = device.get(CONF_DEVICE_ROLE)
        if role == DEVICE_ROLE_WATER:
            water_device = device
        elif role == DEVICE_ROLE_AIR:
            air_devices.append(device)
        else:
            # Backward compatibility: first device without role is water
            if i == 0 and water_device is None:
                water_device = device
            else:
                air_devices.append(device)

    return water_device, air_devices


# --- Global Setup Step ---


def global_form_defaults(
    base: dict[str, Any] | None,
    user_input: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build defaults for the global setup form."""
    defaults: dict[str, Any] = {}
    base = base or {}
    defaults[CONF_ENTRY_NAME] = base.get(CONF_ENTRY_NAME, DEFAULT_ENTRY_NAME)
    if base.get(CONF_ROOM_SENSORS) is not None:
        defaults[CONF_ROOM_SENSORS] = base.get(CONF_ROOM_SENSORS)
    if base.get(CONF_MIRROR_CLIMATE_ENTITIES) is not None:
        defaults[CONF_MIRROR_CLIMATE_ENTITIES] = base.get(CONF_MIRROR_CLIMATE_ENTITIES)
    if user_input:
        defaults.update(user_input)
    return defaults


def build_global_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Build schema for the global setup form."""
    general_fields = build_fields(
        defaults,
        (
            (CONF_ENTRY_NAME, text_selector()),
            (CONF_ROOM_SENSORS, entity_selector("sensor", multiple=True)),
        ),
        required=True,
    )
    mirror_fields = build_fields(
        defaults,
        ((CONF_MIRROR_CLIMATE_ENTITIES, entity_selector("climate", multiple=True)),),
    )
    return sectioned_schema(
        (("general", general_fields, False), ("mirrors", mirror_fields, True))
    )


def process_global_input(
    user_input: dict[str, Any],
    base: dict[str, Any] | None,
) -> tuple[str, dict[str, Any], dict[str, str]]:
    """Process global setup form input.

    Returns:
        Tuple of (entry_name, data, errors).
    """
    errors: dict[str, str] = {}
    room_sensors = user_input.get(CONF_ROOM_SENSORS)
    if not isinstance(room_sensors, list) or len(room_sensors) == 0:
        errors["base"] = "room_sensor_required"
        room_sensors = []
    else:
        seen: set[str] = set()
        deduped: list[str] = []
        for entity_id in room_sensors:
            if entity_id in seen:
                continue
            seen.add(entity_id)
            deduped.append(entity_id)
        room_sensors = deduped

    mirror_raw = user_input.get(CONF_MIRROR_CLIMATE_ENTITIES)
    if mirror_raw is None and base:
        mirror_raw = base.get(CONF_MIRROR_CLIMATE_ENTITIES)
    mirror_entities: list[str] = []
    if isinstance(mirror_raw, list):
        seen_mirror: set[str] = set()
        for entity_id in mirror_raw:
            entity_id = str(entity_id).strip()
            if not entity_id or entity_id in seen_mirror:
                continue
            seen_mirror.add(entity_id)
            mirror_entities.append(entity_id)

    entry_name = entry_name_from_input(user_input, base)
    data = {
        CONF_ROOM_SENSORS: room_sensors,
        CONF_MIRROR_CLIMATE_ENTITIES: mirror_entities,
    }
    return entry_name, data, errors


# --- Device Selection Step ---


def select_devices_defaults(
    water_device: dict[str, Any] | None,
    air_devices: list[dict[str, Any]],
    user_input: dict[str, Any] | None,
    mirror_entities: list[str] | None = None,
) -> dict[str, Any]:
    """Build defaults for the device selection step."""
    defaults: dict[str, Any] = {}

    if water_device:
        defaults[FIELD_WATER_CLIMATE] = water_device.get(CONF_CLIMATE_ENTITY)
    elif mirror_entities:
        defaults[FIELD_WATER_CLIMATE] = mirror_entities[0]

    if air_devices:
        defaults[FIELD_AIR_CLIMATES] = [
            d.get(CONF_CLIMATE_ENTITY) for d in air_devices if d.get(CONF_CLIMATE_ENTITY)
        ]

    if user_input:
        defaults.update(user_input)

    return defaults


def build_select_devices_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Build schema for selecting which devices to configure."""
    water_fields = build_fields(
        defaults,
        ((FIELD_WATER_CLIMATE, entity_selector("climate")),),
    )
    air_fields = build_fields(
        defaults,
        ((FIELD_AIR_CLIMATES, entity_selector("climate", multiple=True)),),
    )

    return sectioned_schema(
        (
            ("water_device", water_fields, False),
            ("air_devices", air_fields, False),
        )
    )


def process_select_devices_input(
    user_input: dict[str, Any],
) -> tuple[str | None, list[str], dict[str, str]]:
    """Process device selection input.

    Returns:
        Tuple of (water_entity, air_entities, errors).
    """
    errors: dict[str, str] = {}

    water_entity = user_input.get(FIELD_WATER_CLIMATE)
    if water_entity:
        water_entity = str(water_entity).strip() or None

    air_entities_raw = user_input.get(FIELD_AIR_CLIMATES) or []
    air_entities: list[str] = []
    seen: set[str] = set()

    # Deduplicate air entities
    for entity_id in air_entities_raw:
        entity_id = str(entity_id).strip()
        if not entity_id or entity_id in seen:
            continue
        seen.add(entity_id)
        air_entities.append(entity_id)

    # Validate: at least one device must be selected
    if not water_entity and not air_entities:
        errors["base"] = "no_devices"

    # Validate: water entity cannot also be an air entity
    if water_entity and water_entity in air_entities:
        errors["base"] = "duplicate"

    return water_entity, air_entities, errors


# --- Water Device Configuration Step ---


def water_device_defaults(
    existing_device: dict[str, Any] | None,
    user_input: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build defaults for water device configuration."""
    defaults: dict[str, Any] = {}

    if existing_device:
        defaults[CONF_ENERGY_SENSOR] = existing_device.get(CONF_ENERGY_SENSOR)
        defaults[CONF_WATER_SENSOR] = existing_device.get(CONF_WATER_SENSOR)
        defaults[CONF_ALLOW_ON_OFF_CONTROL] = existing_device.get(
            CONF_ALLOW_ON_OFF_CONTROL, False
        )
        # Read new heating key, fall back to legacy key for existing configs
        lower_h = existing_device.get(CONF_LOWER_SETPOINT_OFFSET_HEATING)
        if lower_h is None:
            lower_h = existing_device.get("lower_setpoint_offset", DEFAULT_LOWER_SETPOINT_OFFSET_HP1)
        defaults[CONF_LOWER_SETPOINT_OFFSET_HEATING] = lower_h

        upper_h = existing_device.get(CONF_UPPER_SETPOINT_OFFSET_HEATING)
        if upper_h is None:
            upper_h = existing_device.get("upper_setpoint_offset", DEFAULT_UPPER_SETPOINT_OFFSET_HP1)
        defaults[CONF_UPPER_SETPOINT_OFFSET_HEATING] = upper_h

    defaults.setdefault(CONF_LOWER_SETPOINT_OFFSET_HEATING, DEFAULT_LOWER_SETPOINT_OFFSET_HP1)
    defaults.setdefault(CONF_UPPER_SETPOINT_OFFSET_HEATING, DEFAULT_UPPER_SETPOINT_OFFSET_HP1)
    defaults.setdefault(CONF_ALLOW_ON_OFF_CONTROL, False)

    if user_input:
        defaults.update(user_input)

    return defaults


def build_water_device_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Build schema for water device configuration."""
    sensor_fields = build_fields(
        defaults,
        (
            (CONF_ENERGY_SENSOR, entity_selector("sensor")),
            (CONF_WATER_SENSOR, entity_selector("sensor")),
        ),
        required=True,
    )
    control_defaults = {**defaults, CONF_ALLOW_ON_OFF_CONTROL: defaults.get(
        CONF_ALLOW_ON_OFF_CONTROL, False
    )}
    control_fields = build_fields(
        control_defaults,
        (
            (CONF_LOWER_SETPOINT_OFFSET_HEATING, lower_offset_selector()),
            (CONF_UPPER_SETPOINT_OFFSET_HEATING, upper_offset_selector()),
            (CONF_ALLOW_ON_OFF_CONTROL, bool),
        ),
    )

    return sectioned_schema(
        (("sensors", sensor_fields, False), ("control", control_fields, True))
    )


def process_water_device_input(
    user_input: dict[str, Any],
    climate_entity: str,
    used_ids: set[str],
) -> tuple[dict[str, Any] | None, dict[str, str]]:
    """Process water device configuration input.

    Returns:
        Tuple of (device_config, errors).
    """
    errors: dict[str, str] = {}

    energy_sensor = user_input.get(CONF_ENERGY_SENSOR)
    if not energy_sensor:
        errors[CONF_ENERGY_SENSOR] = "required"

    water_sensor = user_input.get(CONF_WATER_SENSOR)
    if not water_sensor:
        errors[CONF_WATER_SENSOR] = "required"

    lower_offset, upper_offset = parse_offset_pair(
        user_input,
        CONF_LOWER_SETPOINT_OFFSET_HEATING,
        DEFAULT_LOWER_SETPOINT_OFFSET_HP1,
        CONF_UPPER_SETPOINT_OFFSET_HEATING,
        DEFAULT_UPPER_SETPOINT_OFFSET_HP1,
        errors,
        compare_invalid=True,
    )

    if errors:
        return None, errors

    device_id = generate_device_id(climate_entity, used_ids)
    device = {
        CONF_DEVICE_ID: device_id,
        CONF_DEVICE_NAME: generate_device_name(climate_entity),
        CONF_DEVICE_ROLE: DEVICE_ROLE_WATER,
        CONF_CLIMATE_ENTITY: climate_entity,
        CONF_ENERGY_SENSOR: energy_sensor,
        CONF_WATER_SENSOR: water_sensor,
        CONF_ALLOW_ON_OFF_CONTROL: bool(
            user_input.get(CONF_ALLOW_ON_OFF_CONTROL, False)
        ),
        CONF_LOWER_SETPOINT_OFFSET_HEATING: lower_offset,
        CONF_UPPER_SETPOINT_OFFSET_HEATING: upper_offset,
    }

    return device, {}


# --- Air Device Configuration Step ---


def air_device_defaults(
    existing_device: dict[str, Any] | None,
    user_input: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build defaults for air device configuration."""
    defaults: dict[str, Any] = {}

    if existing_device:
        defaults[CONF_ENERGY_SENSOR] = existing_device.get(CONF_ENERGY_SENSOR)
        defaults[CONF_ALLOW_ON_OFF_CONTROL] = existing_device.get(
            CONF_ALLOW_ON_OFF_CONTROL, False
        )
        # Heating offsets: new key first, fall back to legacy for existing configs
        lower_h = existing_device.get(CONF_LOWER_SETPOINT_OFFSET_HEATING)
        if lower_h is None:
            lower_h = existing_device.get("lower_setpoint_offset", DEFAULT_LOWER_SETPOINT_OFFSET_ASSIST)
        defaults[CONF_LOWER_SETPOINT_OFFSET_HEATING] = lower_h

        upper_h = existing_device.get(CONF_UPPER_SETPOINT_OFFSET_HEATING)
        if upper_h is None:
            upper_h = existing_device.get("upper_setpoint_offset", DEFAULT_UPPER_SETPOINT_OFFSET_ASSIST)
        defaults[CONF_UPPER_SETPOINT_OFFSET_HEATING] = upper_h

        # Cooling offsets
        defaults[CONF_LOWER_SETPOINT_OFFSET_COOLING] = existing_device.get(
            CONF_LOWER_SETPOINT_OFFSET_COOLING, DEFAULT_LOWER_SETPOINT_OFFSET_COOLING
        )
        defaults[CONF_UPPER_SETPOINT_OFFSET_COOLING] = existing_device.get(
            CONF_UPPER_SETPOINT_OFFSET_COOLING, DEFAULT_UPPER_SETPOINT_OFFSET_COOLING
        )

    defaults.setdefault(CONF_LOWER_SETPOINT_OFFSET_HEATING, DEFAULT_LOWER_SETPOINT_OFFSET_ASSIST)
    defaults.setdefault(CONF_UPPER_SETPOINT_OFFSET_HEATING, DEFAULT_UPPER_SETPOINT_OFFSET_ASSIST)
    defaults.setdefault(CONF_LOWER_SETPOINT_OFFSET_COOLING, DEFAULT_LOWER_SETPOINT_OFFSET_COOLING)
    defaults.setdefault(CONF_UPPER_SETPOINT_OFFSET_COOLING, DEFAULT_UPPER_SETPOINT_OFFSET_COOLING)
    defaults.setdefault(CONF_ALLOW_ON_OFF_CONTROL, False)

    if user_input:
        defaults.update(user_input)

    return defaults


def build_air_device_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Build schema for air device configuration."""
    energy_fields = build_fields(
        defaults,
        ((CONF_ENERGY_SENSOR, entity_selector("sensor")),),
        required=True,
    )
    heating_fields = build_fields(
        defaults,
        (
            (CONF_LOWER_SETPOINT_OFFSET_HEATING, lower_offset_selector()),
            (CONF_UPPER_SETPOINT_OFFSET_HEATING, upper_offset_selector()),
        ),
    )
    cooling_fields = build_fields(
        defaults,
        (
            (CONF_LOWER_SETPOINT_OFFSET_COOLING, lower_offset_selector()),
            (CONF_UPPER_SETPOINT_OFFSET_COOLING, upper_offset_selector()),
        ),
    )
    control_defaults = {**defaults, CONF_ALLOW_ON_OFF_CONTROL: defaults.get(
        CONF_ALLOW_ON_OFF_CONTROL, False
    )}
    control_fields = build_fields(
        control_defaults,
        ((CONF_ALLOW_ON_OFF_CONTROL, bool),),
    )

    return sectioned_schema(
        (
            ("energy", energy_fields, False),
            ("heating", heating_fields, True),
            ("cooling", cooling_fields, True),
            ("control", control_fields, True),
        )
    )


def process_air_device_input(
    user_input: dict[str, Any],
    climate_entity: str,
    used_ids: set[str],
) -> tuple[dict[str, Any] | None, dict[str, str]]:
    """Process air device configuration input.

    Returns:
        Tuple of (device_config, errors).
    """
    errors: dict[str, str] = {}

    energy_sensor = user_input.get(CONF_ENERGY_SENSOR)
    if not energy_sensor:
        errors[CONF_ENERGY_SENSOR] = "required"

    lower_h, upper_h = parse_offset_pair(
        user_input,
        CONF_LOWER_SETPOINT_OFFSET_HEATING,
        DEFAULT_LOWER_SETPOINT_OFFSET_ASSIST,
        CONF_UPPER_SETPOINT_OFFSET_HEATING,
        DEFAULT_UPPER_SETPOINT_OFFSET_ASSIST,
        errors,
    )
    lower_c, upper_c = parse_offset_pair(
        user_input,
        CONF_LOWER_SETPOINT_OFFSET_COOLING,
        DEFAULT_LOWER_SETPOINT_OFFSET_COOLING,
        CONF_UPPER_SETPOINT_OFFSET_COOLING,
        DEFAULT_UPPER_SETPOINT_OFFSET_COOLING,
        errors,
    )

    if errors:
        return None, errors

    device_id = generate_device_id(climate_entity, used_ids)
    device = {
        CONF_DEVICE_ID: device_id,
        CONF_DEVICE_NAME: generate_device_name(climate_entity),
        CONF_DEVICE_ROLE: DEVICE_ROLE_AIR,
        CONF_CLIMATE_ENTITY: climate_entity,
        CONF_ENERGY_SENSOR: energy_sensor,
        CONF_ALLOW_ON_OFF_CONTROL: bool(
            user_input.get(CONF_ALLOW_ON_OFF_CONTROL, False)
        ),
        CONF_LOWER_SETPOINT_OFFSET_HEATING: lower_h,
        CONF_UPPER_SETPOINT_OFFSET_HEATING: upper_h,
        CONF_LOWER_SETPOINT_OFFSET_COOLING: lower_c,
        CONF_UPPER_SETPOINT_OFFSET_COOLING: upper_c,
    }

    return device, {}


# --- Advanced Options Step ---


def build_advanced_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Build the schema for advanced/expert options."""
    setpoint_fields: dict[Any, Any] = {}

    setpoint_options = [
        (
            CONF_MIN_SETPOINT_OVERRIDE,
            {"min": 10, "max": 25, "step": 0.5, "unit_of_measurement": "°C"},
        ),
        (
            CONF_MAX_SETPOINT_OVERRIDE,
            {"min": 20, "max": 35, "step": 0.5, "unit_of_measurement": "°C"},
        ),
        (
            CONF_MAXIMUM_OVERSHOOT,
            {"min": 0, "max": 5, "step": 0.1, "unit_of_measurement": "°C"},
        ),
    ]

    assist_options = [
        (
            CONF_ASSIST_TIMER_SECONDS,
            {"min": 60, "max": 900, "step": 30, "unit_of_measurement": "s"},
        ),
        (
            CONF_ASSIST_ON_ETA_THRESHOLD_MINUTES,
            {"min": 5, "max": 600, "step": 1, "unit_of_measurement": "min"},
        ),
        (
            CONF_ASSIST_OFF_ETA_THRESHOLD_MINUTES,
            {"min": 1, "max": 120, "step": 1, "unit_of_measurement": "min"},
        ),
        (
            CONF_ASSIST_MIN_ON_MINUTES,
            {"min": 0, "max": 180, "step": 1, "unit_of_measurement": "min"},
        ),
        (
            CONF_ASSIST_MIN_OFF_MINUTES,
            {"min": 0, "max": 180, "step": 1, "unit_of_measurement": "min"},
        ),
        (
            CONF_ASSIST_WATER_TEMP_THRESHOLD,
            {"min": 30, "max": 55, "step": 1, "unit_of_measurement": "°C"},
        ),
        (
            CONF_ASSIST_STALL_TEMP_DELTA,
            {"min": 0.1, "max": 2, "step": 0.1, "unit_of_measurement": "°C"},
        ),
    ]

    setpoint_fields = build_fields(
        defaults,
        tuple(
            (field_name, selector({"number": selector_config}))
            for field_name, selector_config in setpoint_options
        ),
    )
    assist_fields = build_fields(
        defaults,
        tuple(
            (field_name, selector({"number": selector_config}))
            for field_name, selector_config in assist_options
        ),
    )

    return sectioned_schema(
        (("setpoints", setpoint_fields, False), ("assist", assist_fields, True))
    )


def advanced_form_defaults(
    base: dict[str, Any],
    user_input: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build defaults for advanced form."""
    if user_input:
        return dict(user_input)

    default_map = {
        CONF_MIN_SETPOINT_OVERRIDE: DEFAULT_MIN_SETPOINT,
        CONF_MAX_SETPOINT_OVERRIDE: DEFAULT_MAX_SETPOINT,
        CONF_ASSIST_TIMER_SECONDS: DEFAULT_ASSIST_TIMER_SECONDS,
        CONF_ASSIST_ON_ETA_THRESHOLD_MINUTES: None,
        CONF_ASSIST_OFF_ETA_THRESHOLD_MINUTES: None,
        CONF_ASSIST_MIN_ON_MINUTES: DEFAULT_ASSIST_MIN_ON_MINUTES,
        CONF_ASSIST_MIN_OFF_MINUTES: DEFAULT_ASSIST_MIN_OFF_MINUTES,
        CONF_ASSIST_WATER_TEMP_THRESHOLD: DEFAULT_ASSIST_WATER_TEMP_THRESHOLD,
        CONF_ASSIST_STALL_TEMP_DELTA: DEFAULT_ASSIST_STALL_TEMP_DELTA,
        CONF_MAXIMUM_OVERSHOOT: DEFAULT_MAXIMUM_OVERSHOOT,
    }

    return {key: base.get(key, default_val) for key, default_val in default_map.items()}


def process_advanced_input(user_input: dict[str, Any]) -> dict[str, Any]:
    """Process and validate advanced options input."""
    advanced_keys = {
        CONF_MIN_SETPOINT_OVERRIDE,
        CONF_MAX_SETPOINT_OVERRIDE,
        CONF_ASSIST_TIMER_SECONDS,
        CONF_ASSIST_ON_ETA_THRESHOLD_MINUTES,
        CONF_ASSIST_OFF_ETA_THRESHOLD_MINUTES,
        CONF_ASSIST_MIN_ON_MINUTES,
        CONF_ASSIST_MIN_OFF_MINUTES,
        CONF_ASSIST_WATER_TEMP_THRESHOLD,
        CONF_ASSIST_STALL_TEMP_DELTA,
        CONF_MAXIMUM_OVERSHOOT,
    }

    return {key: user_input[key] for key in advanced_keys if key in user_input}


# --- Experimental Options Step ---


def build_experimental_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Build the schema for experimental options."""
    sensor_fields = build_fields(
        defaults,
        (
            (CONF_HOUSE_POWER_SENSOR, entity_selector("sensor")),
            (CONF_MPC_TEMPERATURE_SENSOR, entity_selector("sensor")),
            (CONF_OUTDOOR_TEMP_SENSOR, entity_selector("sensor")),
        ),
    )

    return sectioned_schema(
        (("sensors", sensor_fields, False),),
    )


def experimental_form_defaults(
    base: dict[str, Any],
    user_input: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build defaults for experimental form."""
    if user_input:
        return dict(user_input)

    return {
        CONF_HOUSE_POWER_SENSOR: base.get(CONF_HOUSE_POWER_SENSOR),
        CONF_MPC_TEMPERATURE_SENSOR: base.get(CONF_MPC_TEMPERATURE_SENSOR),
        CONF_OUTDOOR_TEMP_SENSOR: base.get(CONF_OUTDOOR_TEMP_SENSOR),
    }


def process_experimental_input(user_input: dict[str, Any]) -> dict[str, Any]:
    """Process and validate experimental options input."""
    data: dict[str, Any] = {}
    if CONF_HOUSE_POWER_SENSOR in user_input:
        sensor_entity_id = str(user_input.get(CONF_HOUSE_POWER_SENSOR) or "").strip()
        data[CONF_HOUSE_POWER_SENSOR] = sensor_entity_id or None
    if CONF_MPC_TEMPERATURE_SENSOR in user_input:
        sensor_entity_id = str(user_input.get(CONF_MPC_TEMPERATURE_SENSOR) or "").strip()
        data[CONF_MPC_TEMPERATURE_SENSOR] = sensor_entity_id or None
    if CONF_OUTDOOR_TEMP_SENSOR in user_input:
        sensor_entity_id = str(user_input.get(CONF_OUTDOOR_TEMP_SENSOR) or "").strip()
        data[CONF_OUTDOOR_TEMP_SENSOR] = sensor_entity_id or None
    return data
