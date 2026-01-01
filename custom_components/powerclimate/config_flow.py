from __future__ import annotations

import re
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
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
    CONF_COPY_SETPOINT_TO_POWERCLIMATE,
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    CONF_DEVICE_ROLE,
    CONF_DEVICES,
    CONF_ENERGY_SENSOR,
    CONF_ENTRY_NAME,
    CONF_HOUSE_POWER_SENSOR,
    CONF_LOWER_SETPOINT_OFFSET,
    CONF_MAX_SETPOINT_OVERRIDE,
    CONF_MIN_SETPOINT_OVERRIDE,
    CONF_ROOM_SENSORS,
    CONF_UPPER_SETPOINT_OFFSET,
    CONF_WATER_SENSOR,
    DEFAULT_ASSIST_MIN_OFF_MINUTES,
    DEFAULT_ASSIST_MIN_ON_MINUTES,
    DEFAULT_ASSIST_STALL_TEMP_DELTA,
    DEFAULT_ASSIST_TIMER_SECONDS,
    DEFAULT_ASSIST_WATER_TEMP_THRESHOLD,
    DEFAULT_ENTRY_NAME,
    DEFAULT_LOWER_SETPOINT_OFFSET_ASSIST,
    DEFAULT_LOWER_SETPOINT_OFFSET_HP1,
    DEFAULT_MAX_SETPOINT,
    DEFAULT_MIN_SETPOINT,
    DEFAULT_UPPER_SETPOINT_OFFSET_ASSIST,
    DEFAULT_UPPER_SETPOINT_OFFSET_HP1,
    DEVICE_ROLE_AIR,
    DEVICE_ROLE_WATER,
    DOMAIN,
)

# Field names for UI toggles (not stored in data)
FIELD_WATER_CLIMATE = "water_climate_entity_id"
FIELD_AIR_CLIMATES = "air_climate_entity_ids"


def _entity_selector(domain: str, multiple: bool = False) -> Any:
    return selector({"entity": {"domain": [domain], "multiple": multiple}})


def _text_selector() -> Any:
    return selector({"text": {}})


def _offset_number_selector(min_val: float = -10, max_val: float = 10) -> Any:
    return selector({"number": {"min": min_val, "max": max_val, "step": 0.1}})


def _lower_offset_selector() -> Any:
    return selector({"number": {"min": -5, "max": 0, "step": 0.1}})


def _upper_offset_selector() -> Any:
    return selector({"number": {"min": 0, "max": 5, "step": 0.1}})


def _required_field(
    key: str,
    defaults: dict[str, Any],
    schema_fields: dict[Any, Any],
    schema_value: Any,
) -> None:
    default_value = defaults.get(key)
    if default_value is None:
        schema_fields[vol.Required(key)] = schema_value
    else:
        schema_fields[vol.Required(key, default=default_value)] = schema_value


def _optional_field(
    key: str,
    defaults: dict[str, Any],
    schema_fields: dict[Any, Any],
    schema_value: Any,
) -> None:
    default_value = defaults.get(key)
    if default_value is None:
        schema_fields[vol.Optional(key)] = schema_value
    else:
        schema_fields[vol.Optional(key, default=default_value)] = schema_value


def _parse_offset(raw: Any, default: float) -> tuple[float, bool]:
    """Parse an offset while preserving a leading -0."""
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


def _split_devices_by_role(
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


def _global_form_defaults(
    base: dict[str, Any] | None,
    user_input: dict[str, Any] | None,
) -> dict[str, Any]:
    defaults: dict[str, Any] = {}
    base = base or {}
    defaults[CONF_ENTRY_NAME] = base.get(CONF_ENTRY_NAME, DEFAULT_ENTRY_NAME)
    if base.get(CONF_ROOM_SENSORS) is not None:
        defaults[CONF_ROOM_SENSORS] = base.get(CONF_ROOM_SENSORS)
    if user_input:
        defaults.update(user_input)
    return defaults


def _build_global_schema(defaults: dict[str, Any]) -> vol.Schema:
    schema_fields: dict[Any, Any] = {}
    _required_field(
        CONF_ENTRY_NAME,
        defaults,
        schema_fields,
        _text_selector(),
    )
    _required_field(
        CONF_ROOM_SENSORS,
        defaults,
        schema_fields,
        _entity_selector("sensor", multiple=True),
    )
    return vol.Schema(schema_fields)


def _process_global_input(
    user_input: dict[str, Any],
    base: dict[str, Any] | None,
) -> tuple[str, dict[str, Any], dict[str, str]]:
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
    entry_name = _entry_name_from_input(user_input, base)
    data = {
        CONF_ROOM_SENSORS: room_sensors,
    }
    return entry_name, data, errors


# --- Device Selection Step ---

def _select_devices_defaults(
    water_device: dict[str, Any] | None,
    air_devices: list[dict[str, Any]],
    user_input: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build defaults for the device selection step."""
    defaults: dict[str, Any] = {}
    
    if water_device:
        defaults[FIELD_WATER_CLIMATE] = water_device.get(CONF_CLIMATE_ENTITY)
    
    if air_devices:
        defaults[FIELD_AIR_CLIMATES] = [
            d.get(CONF_CLIMATE_ENTITY) for d in air_devices if d.get(CONF_CLIMATE_ENTITY)
        ]
    
    if user_input:
        defaults.update(user_input)
    
    return defaults


def _build_select_devices_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Build schema for selecting which devices to configure."""
    schema_fields: dict[Any, Any] = {}
    
    # Optional water-based heat pump (single select)
    _optional_field(
        FIELD_WATER_CLIMATE,
        defaults,
        schema_fields,
        _entity_selector("climate"),
    )
    
    # Optional air heat pumps (multi-select)
    _optional_field(
        FIELD_AIR_CLIMATES,
        defaults,
        schema_fields,
        _entity_selector("climate", multiple=True),
    )
    
    return vol.Schema(schema_fields)


def _process_select_devices_input(
    user_input: dict[str, Any],
) -> tuple[str | None, list[str], dict[str, str]]:
    """Process device selection input.
    
    Returns:
        - water_entity: climate entity ID for water HP or None
        - air_entities: list of climate entity IDs for air HPs
        - errors: validation errors
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

def _water_device_defaults(
    existing_device: dict[str, Any] | None,
    user_input: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build defaults for water device configuration."""
    defaults: dict[str, Any] = {}
    
    if existing_device:
        defaults[CONF_ENERGY_SENSOR] = existing_device.get(CONF_ENERGY_SENSOR)
        defaults[CONF_WATER_SENSOR] = existing_device.get(CONF_WATER_SENSOR)
        defaults[CONF_COPY_SETPOINT_TO_POWERCLIMATE] = existing_device.get(
            CONF_COPY_SETPOINT_TO_POWERCLIMATE, False
        )
        defaults[CONF_LOWER_SETPOINT_OFFSET] = existing_device.get(
            CONF_LOWER_SETPOINT_OFFSET, DEFAULT_LOWER_SETPOINT_OFFSET_HP1
        )
        defaults[CONF_UPPER_SETPOINT_OFFSET] = existing_device.get(
            CONF_UPPER_SETPOINT_OFFSET, DEFAULT_UPPER_SETPOINT_OFFSET_HP1
        )
    
    defaults.setdefault(CONF_LOWER_SETPOINT_OFFSET, DEFAULT_LOWER_SETPOINT_OFFSET_HP1)
    defaults.setdefault(CONF_UPPER_SETPOINT_OFFSET, DEFAULT_UPPER_SETPOINT_OFFSET_HP1)
    defaults.setdefault(CONF_COPY_SETPOINT_TO_POWERCLIMATE, False)
    
    if user_input:
        defaults.update(user_input)
    
    return defaults


def _build_water_device_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Build schema for water device configuration."""
    schema_fields: dict[Any, Any] = {}
    
    _required_field(
        CONF_ENERGY_SENSOR,
        defaults,
        schema_fields,
        _entity_selector("sensor"),
    )
    _required_field(
        CONF_WATER_SENSOR,
        defaults,
        schema_fields,
        _entity_selector("sensor"),
    )
    _optional_field(
        CONF_LOWER_SETPOINT_OFFSET,
        defaults,
        schema_fields,
        _lower_offset_selector(),
    )
    _optional_field(
        CONF_UPPER_SETPOINT_OFFSET,
        defaults,
        schema_fields,
        _upper_offset_selector(),
    )
    schema_fields[vol.Optional(
        CONF_COPY_SETPOINT_TO_POWERCLIMATE,
        default=defaults.get(CONF_COPY_SETPOINT_TO_POWERCLIMATE, False),
    )] = bool
    
    return vol.Schema(schema_fields)


def _process_water_device_input(
    user_input: dict[str, Any],
    climate_entity: str,
    used_ids: set[str],
) -> tuple[dict[str, Any] | None, dict[str, str]]:
    """Process water device configuration input."""
    errors: dict[str, str] = {}
    
    energy_sensor = user_input.get(CONF_ENERGY_SENSOR)
    if not energy_sensor:
        errors[CONF_ENERGY_SENSOR] = "required"
    
    water_sensor = user_input.get(CONF_WATER_SENSOR)
    if not water_sensor:
        errors[CONF_WATER_SENSOR] = "required"
    
    lower_offset, lower_valid = _parse_offset(
        user_input.get(CONF_LOWER_SETPOINT_OFFSET, DEFAULT_LOWER_SETPOINT_OFFSET_HP1),
        DEFAULT_LOWER_SETPOINT_OFFSET_HP1,
    )
    if not lower_valid:
        errors[CONF_LOWER_SETPOINT_OFFSET] = "invalid"
    
    upper_offset, upper_valid = _parse_offset(
        user_input.get(CONF_UPPER_SETPOINT_OFFSET, DEFAULT_UPPER_SETPOINT_OFFSET_HP1),
        DEFAULT_UPPER_SETPOINT_OFFSET_HP1,
    )
    if not upper_valid:
        errors[CONF_UPPER_SETPOINT_OFFSET] = "invalid"
    
    if lower_offset > upper_offset:
        errors["base"] = "invalid_offsets"
        errors.setdefault(CONF_LOWER_SETPOINT_OFFSET, "invalid")
        errors.setdefault(CONF_UPPER_SETPOINT_OFFSET, "invalid")
    
    if errors:
        return None, errors
    
    device_id = _generate_device_id(climate_entity, used_ids)
    device = {
        CONF_DEVICE_ID: device_id,
        CONF_DEVICE_NAME: _generate_device_name(climate_entity),
        CONF_DEVICE_ROLE: DEVICE_ROLE_WATER,
        CONF_CLIMATE_ENTITY: climate_entity,
        CONF_ENERGY_SENSOR: energy_sensor,
        CONF_WATER_SENSOR: water_sensor,
        CONF_COPY_SETPOINT_TO_POWERCLIMATE: bool(
            user_input.get(CONF_COPY_SETPOINT_TO_POWERCLIMATE, False)
        ),
        CONF_LOWER_SETPOINT_OFFSET: lower_offset,
        CONF_UPPER_SETPOINT_OFFSET: upper_offset,
    }
    
    return device, {}


# --- Air Device Configuration Step ---

def _air_device_defaults(
    existing_device: dict[str, Any] | None,
    user_input: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build defaults for air device configuration."""
    defaults: dict[str, Any] = {}
    
    if existing_device:
        defaults[CONF_ENERGY_SENSOR] = existing_device.get(CONF_ENERGY_SENSOR)
        defaults[CONF_COPY_SETPOINT_TO_POWERCLIMATE] = existing_device.get(
            CONF_COPY_SETPOINT_TO_POWERCLIMATE, False
        )
        defaults[CONF_ALLOW_ON_OFF_CONTROL] = existing_device.get(
            CONF_ALLOW_ON_OFF_CONTROL, False
        )
        defaults[CONF_LOWER_SETPOINT_OFFSET] = existing_device.get(
            CONF_LOWER_SETPOINT_OFFSET, DEFAULT_LOWER_SETPOINT_OFFSET_ASSIST
        )
        defaults[CONF_UPPER_SETPOINT_OFFSET] = existing_device.get(
            CONF_UPPER_SETPOINT_OFFSET, DEFAULT_UPPER_SETPOINT_OFFSET_ASSIST
        )
    
    defaults.setdefault(CONF_LOWER_SETPOINT_OFFSET, DEFAULT_LOWER_SETPOINT_OFFSET_ASSIST)
    defaults.setdefault(CONF_UPPER_SETPOINT_OFFSET, DEFAULT_UPPER_SETPOINT_OFFSET_ASSIST)
    defaults.setdefault(CONF_COPY_SETPOINT_TO_POWERCLIMATE, False)
    defaults.setdefault(CONF_ALLOW_ON_OFF_CONTROL, False)
    
    if user_input:
        defaults.update(user_input)
    
    return defaults


def _build_air_device_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Build schema for air device configuration."""
    schema_fields: dict[Any, Any] = {}
    
    _required_field(
        CONF_ENERGY_SENSOR,
        defaults,
        schema_fields,
        _entity_selector("sensor"),
    )
    _optional_field(
        CONF_LOWER_SETPOINT_OFFSET,
        defaults,
        schema_fields,
        _lower_offset_selector(),
    )
    _optional_field(
        CONF_UPPER_SETPOINT_OFFSET,
        defaults,
        schema_fields,
        _upper_offset_selector(),
    )
    schema_fields[vol.Optional(
        CONF_COPY_SETPOINT_TO_POWERCLIMATE,
        default=defaults.get(CONF_COPY_SETPOINT_TO_POWERCLIMATE, False),
    )] = bool
    schema_fields[vol.Optional(
        CONF_ALLOW_ON_OFF_CONTROL,
        default=defaults.get(CONF_ALLOW_ON_OFF_CONTROL, False),
    )] = bool
    
    return vol.Schema(schema_fields)


def _process_air_device_input(
    user_input: dict[str, Any],
    climate_entity: str,
    used_ids: set[str],
) -> tuple[dict[str, Any] | None, dict[str, str]]:
    """Process air device configuration input."""
    errors: dict[str, str] = {}
    
    energy_sensor = user_input.get(CONF_ENERGY_SENSOR)
    if not energy_sensor:
        errors[CONF_ENERGY_SENSOR] = "required"
    
    lower_offset, lower_valid = _parse_offset(
        user_input.get(CONF_LOWER_SETPOINT_OFFSET, DEFAULT_LOWER_SETPOINT_OFFSET_ASSIST),
        DEFAULT_LOWER_SETPOINT_OFFSET_ASSIST,
    )
    if not lower_valid:
        errors[CONF_LOWER_SETPOINT_OFFSET] = "invalid"
    
    upper_offset, upper_valid = _parse_offset(
        user_input.get(CONF_UPPER_SETPOINT_OFFSET, DEFAULT_UPPER_SETPOINT_OFFSET_ASSIST),
        DEFAULT_UPPER_SETPOINT_OFFSET_ASSIST,
    )
    if not upper_valid:
        errors[CONF_UPPER_SETPOINT_OFFSET] = "invalid"
    
    if lower_offset > upper_offset:
        errors["base"] = "invalid_offsets"
        errors.setdefault(CONF_LOWER_SETPOINT_OFFSET, "invalid")
        errors.setdefault(CONF_UPPER_SETPOINT_OFFSET, "invalid")
    
    if errors:
        return None, errors
    
    device_id = _generate_device_id(climate_entity, used_ids)
    device = {
        CONF_DEVICE_ID: device_id,
        CONF_DEVICE_NAME: _generate_device_name(climate_entity),
        CONF_DEVICE_ROLE: DEVICE_ROLE_AIR,
        CONF_CLIMATE_ENTITY: climate_entity,
        CONF_ENERGY_SENSOR: energy_sensor,
        CONF_COPY_SETPOINT_TO_POWERCLIMATE: bool(
            user_input.get(CONF_COPY_SETPOINT_TO_POWERCLIMATE, False)
        ),
        CONF_ALLOW_ON_OFF_CONTROL: bool(
            user_input.get(CONF_ALLOW_ON_OFF_CONTROL, False)
        ),
        CONF_LOWER_SETPOINT_OFFSET: lower_offset,
        CONF_UPPER_SETPOINT_OFFSET: upper_offset,
    }
    
    return device, {}


class PowerClimateConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for PowerClimate."""

    VERSION = 1

    def __init__(self):
        self._base: dict[str, Any] = {}
        self._entry_name: str = DEFAULT_ENTRY_NAME
        self._entry_data: dict[str, Any] = {}
        
        # Device selection state
        self._water_entity: str | None = None
        self._air_entities: list[str] = []
        
        # Configured devices
        self._water_device: dict[str, Any] | None = None
        self._air_devices: list[dict[str, Any]] = []
        
        # Track current air device index during configuration
        self._air_device_index: int = 0
        
        self._used_ids: set[str] = set()

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle the initial step: name and room sensors."""
        errors: dict[str, str] = {}
        if user_input is not None:
            entry_name, data, errors = _process_global_input(user_input, self._base)
            if not errors:
                self._entry_name = entry_name or DEFAULT_ENTRY_NAME
                self._entry_data = data
                return await self.async_step_select_devices()
        
        defaults = _global_form_defaults(self._base, user_input)
        schema = _build_global_schema(defaults)
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_select_devices(self, user_input: dict[str, Any] | None = None):
        """Handle device selection: optional water HP + multi-select air HPs."""
        errors: dict[str, str] = {}
        
        if user_input is not None:
            water_entity, air_entities, errors = _process_select_devices_input(user_input)
            if not errors:
                self._water_entity = water_entity
                self._air_entities = air_entities
                self._air_device_index = 0
                
                # Go to water device config if selected, otherwise start with air devices
                if self._water_entity:
                    return await self.async_step_water_device()
                elif self._air_entities:
                    return await self.async_step_air_device()
                else:
                    # Should not happen due to validation, but handle gracefully
                    return await self._create_entry()
        
        defaults = _select_devices_defaults(None, [], user_input)
        schema = _build_select_devices_schema(defaults)
        return self.async_show_form(
            step_id="select_devices",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_water_device(self, user_input: dict[str, Any] | None = None):
        """Configure the water-based heat pump."""
        errors: dict[str, str] = {}
        
        if user_input is not None:
            device, errors = _process_water_device_input(
                user_input,
                self._water_entity,
                self._used_ids,
            )
            if not errors and device:
                self._water_device = device
                self._used_ids.add(device[CONF_DEVICE_ID])
                
                # Continue to air devices if any
                if self._air_entities:
                    return await self.async_step_air_device()
                return await self._create_entry()
        
        defaults = _water_device_defaults(None, user_input)
        schema = _build_water_device_schema(defaults)
        return self.async_show_form(
            step_id="water_device",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_air_device(self, user_input: dict[str, Any] | None = None):
        """Configure an air heat pump."""
        errors: dict[str, str] = {}
        
        # Get current air entity
        if self._air_device_index >= len(self._air_entities):
            return await self._create_entry()
        
        current_entity = self._air_entities[self._air_device_index]
        
        if user_input is not None:
            device, errors = _process_air_device_input(
                user_input,
                current_entity,
                self._used_ids,
            )
            if not errors and device:
                self._air_devices.append(device)
                self._used_ids.add(device[CONF_DEVICE_ID])
                self._air_device_index += 1
                
                # Continue to next air device or finish
                if self._air_device_index < len(self._air_entities):
                    return await self.async_step_air_device()
                return await self._create_entry()
        
        defaults = _air_device_defaults(None, user_input)
        schema = _build_air_device_schema(defaults)
        
        # Generate a friendly name for the air HP
        hp_number = self._air_device_index + 1
        if self._water_device:
            hp_number += 1  # Water device is HP1, so air devices start at HP2
        
        device_name = _generate_device_name(current_entity)
        
        return self.async_show_form(
            step_id="air_device",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "hp_label": f"Air HP{hp_number}",
                "device_name": device_name,
                "device_index": str(self._air_device_index + 1),
                "total_air_devices": str(len(self._air_entities)),
            },
        )

    async def _create_entry(self):
        """Create the config entry with all configured devices."""
        # Build device list: water first (if present), then air devices
        devices: list[dict[str, Any]] = []
        
        if self._water_device:
            devices.append(self._water_device)
        
        devices.extend(self._air_devices)
        
        if not devices:
            # No devices configured - go back to selection
            return await self.async_step_select_devices()
        
        entry_payload = dict(self._entry_data)
        entry_payload[CONF_DEVICES] = devices
        entry_payload[CONF_ENTRY_NAME] = self._entry_name
        
        unique_id = _slugify(self._entry_name)
        if unique_id:
            await self.async_set_unique_id(unique_id, raise_on_progress=False)
            self._abort_if_unique_id_configured()
        
        return self.async_create_entry(
            title=self._entry_name,
            data=entry_payload,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return PowerClimateOptionsFlowHandler(config_entry)


class PowerClimateOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options for PowerClimate."""

    def __init__(self, config_entry):
        self._entry = config_entry
        self._base = dict(config_entry.data)
        self._base.update(config_entry.options)
        self._base.setdefault(
            CONF_ENTRY_NAME,
            config_entry.title or DEFAULT_ENTRY_NAME,
        )
        self._entry_name = self._base.get(CONF_ENTRY_NAME, DEFAULT_ENTRY_NAME)
        self._entry_data: dict[str, Any] = dict(config_entry.options)
        
        # Parse existing devices
        self._base_water, self._base_air = _split_devices_by_role(self._base)
        
        # Device selection state
        self._water_entity: str | None = None
        self._air_entities: list[str] = []
        
        # Configured devices
        self._water_device: dict[str, Any] | None = None
        self._air_devices: list[dict[str, Any]] = []
        
        # Track current air device index during configuration
        self._air_device_index: int = 0
        
        self._used_ids: set[str] = set()

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Show the options menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "edit_setup",
                "advanced",
                "experimental",
            ],
        )

    async def async_step_edit_setup(self, user_input: dict[str, Any] | None = None):
        """Edit the general setup (name + room sensors), then devices."""
        errors: dict[str, str] = {}
        if user_input is not None:
            entry_name, data, errors = _process_global_input(user_input, self._base)
            if not errors:
                self._entry_name = entry_name or self._entry_name
                self._entry_data.update(data)
                return await self.async_step_select_devices()
        
        defaults = _global_form_defaults(self._base, user_input)
        schema = _build_global_schema(defaults)
        return self.async_show_form(
            step_id="edit_setup",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_select_devices(self, user_input: dict[str, Any] | None = None):
        """Handle device selection: optional water HP + multi-select air HPs."""
        errors: dict[str, str] = {}
        
        if user_input is not None:
            water_entity, air_entities, errors = _process_select_devices_input(user_input)
            if not errors:
                self._water_entity = water_entity
                self._air_entities = air_entities
                self._air_device_index = 0
                
                if self._water_entity:
                    return await self.async_step_water_device()
                elif self._air_entities:
                    return await self.async_step_air_device()
                else:
                    return await self._create_options_entry()
        
        defaults = _select_devices_defaults(self._base_water, self._base_air, user_input)
        schema = _build_select_devices_schema(defaults)
        return self.async_show_form(
            step_id="select_devices",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_water_device(self, user_input: dict[str, Any] | None = None):
        """Configure the water-based heat pump."""
        errors: dict[str, str] = {}
        
        # Find existing water device config if entity matches
        existing = None
        if self._base_water and self._base_water.get(CONF_CLIMATE_ENTITY) == self._water_entity:
            existing = self._base_water
        
        if user_input is not None:
            device, errors = _process_water_device_input(
                user_input,
                self._water_entity,
                self._used_ids,
            )
            if not errors and device:
                self._water_device = device
                self._used_ids.add(device[CONF_DEVICE_ID])
                
                if self._air_entities:
                    return await self.async_step_air_device()
                return await self._create_options_entry()
        
        defaults = _water_device_defaults(existing, user_input)
        schema = _build_water_device_schema(defaults)
        return self.async_show_form(
            step_id="water_device",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_air_device(self, user_input: dict[str, Any] | None = None):
        """Configure an air heat pump."""
        errors: dict[str, str] = {}
        
        if self._air_device_index >= len(self._air_entities):
            return await self._create_options_entry()
        
        current_entity = self._air_entities[self._air_device_index]
        
        # Find existing air device config if entity matches
        existing = None
        for air_dev in self._base_air:
            if air_dev.get(CONF_CLIMATE_ENTITY) == current_entity:
                existing = air_dev
                break
        
        if user_input is not None:
            device, errors = _process_air_device_input(
                user_input,
                current_entity,
                self._used_ids,
            )
            if not errors and device:
                self._air_devices.append(device)
                self._used_ids.add(device[CONF_DEVICE_ID])
                self._air_device_index += 1
                
                if self._air_device_index < len(self._air_entities):
                    return await self.async_step_air_device()
                return await self._create_options_entry()
        
        defaults = _air_device_defaults(existing, user_input)
        schema = _build_air_device_schema(defaults)
        
        hp_number = self._air_device_index + 1
        if self._water_device:
            hp_number += 1
        
        device_name = _generate_device_name(current_entity)
        
        return self.async_show_form(
            step_id="air_device",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "hp_label": f"Air HP{hp_number}",
                "device_name": device_name,
                "device_index": str(self._air_device_index + 1),
                "total_air_devices": str(len(self._air_entities)),
            },
        )

    async def async_step_advanced(self, user_input: dict[str, Any] | None = None):
        """Handle advanced/expert configuration options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            advanced_data = _process_advanced_input(user_input)
            self._entry_data.update(advanced_data)
            return await self._create_options_entry()
        
        defaults = _advanced_form_defaults(self._base, user_input)
        schema = _build_advanced_schema(defaults)
        return self.async_show_form(
            step_id="advanced",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_experimental(self, user_input: dict[str, Any] | None = None):
        """Handle experimental configuration options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            experimental_data = _process_experimental_input(user_input)
            self._entry_data.update(experimental_data)
            return await self._create_options_entry()
        
        defaults = _experimental_form_defaults(self._base, user_input)
        schema = _build_experimental_schema(defaults)
        return self.async_show_form(
            step_id="experimental",
            data_schema=schema,
            errors=errors,
        )

    async def _create_options_entry(self):
        """Create the options entry with all configured devices."""
        # If user only edited Advanced/Experimental, keep existing devices
        if not self._water_device and not self._air_devices:
            if self._base_water or self._base_air:
                devices = []
                if self._base_water:
                    # Ensure role is set for backward compat
                    water = dict(self._base_water)
                    water.setdefault(CONF_DEVICE_ROLE, DEVICE_ROLE_WATER)
                    devices.append(water)
                for air in self._base_air:
                    air_copy = dict(air)
                    air_copy.setdefault(CONF_DEVICE_ROLE, DEVICE_ROLE_AIR)
                    devices.append(air_copy)
                self._entry_data[CONF_DEVICES] = devices
        else:
            # Build device list from newly configured devices
            devices: list[dict[str, Any]] = []
            if self._water_device:
                devices.append(self._water_device)
            devices.extend(self._air_devices)
            
            if devices:
                self._entry_data[CONF_DEVICES] = devices
        
        # Update entry title if name changed
        if self._entry_name != (
            self._entry.title or self._entry.data.get(CONF_ENTRY_NAME)
        ):
            new_data = dict(self._entry.data)
            new_data[CONF_ENTRY_NAME] = self._entry_name
            self.hass.config_entries.async_update_entry(
                self._entry,
                data=new_data,
                title=self._entry_name,
            )
        
        return self.async_create_entry(data=self._entry_data)


def _generate_device_id(climate_entity: str, used_ids: set[str]) -> str:
    base = _slugify(climate_entity.split(".")[-1]) or "hp"
    candidate = base
    counter = 2
    while candidate in used_ids:
        candidate = f"{base}_{counter}"
        counter += 1
    return candidate


def _generate_device_name(climate_entity: str) -> str:
    raw = climate_entity.split(".")[-1].replace("_", " ")
    pretty = raw.title() if raw else climate_entity
    return pretty


def _slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9_]+", "_", value)
    value = re.sub(r"_+", "_", value)
    return value.strip("_")


def _entry_name_from_input(
    user_input: dict[str, Any] | None,
    base: dict[str, Any] | None = None,
) -> str:
    raw = None
    if user_input:
        raw = user_input.get(CONF_ENTRY_NAME)
    if raw is None and base:
        raw = base.get(CONF_ENTRY_NAME)
    if raw is None:
        return DEFAULT_ENTRY_NAME
    text = str(raw).strip()
    return text or DEFAULT_ENTRY_NAME


def _build_advanced_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Build the schema for advanced/expert options."""
    schema_fields: dict[Any, Any] = {}

    advanced_fields = [
        (CONF_MIN_SETPOINT_OVERRIDE, {"min": 10, "max": 25, "step": 0.5, "unit_of_measurement": "°C"}),
        (CONF_MAX_SETPOINT_OVERRIDE, {"min": 20, "max": 35, "step": 0.5, "unit_of_measurement": "°C"}),
        (CONF_ASSIST_TIMER_SECONDS, {"min": 60, "max": 900, "step": 30, "unit_of_measurement": "s"}),
        (CONF_ASSIST_ON_ETA_THRESHOLD_MINUTES, {"min": 5, "max": 600, "step": 1, "unit_of_measurement": "min"}),
        (CONF_ASSIST_OFF_ETA_THRESHOLD_MINUTES, {"min": 1, "max": 120, "step": 1, "unit_of_measurement": "min"}),
        (CONF_ASSIST_MIN_ON_MINUTES, {"min": 0, "max": 180, "step": 1, "unit_of_measurement": "min"}),
        (CONF_ASSIST_MIN_OFF_MINUTES, {"min": 0, "max": 180, "step": 1, "unit_of_measurement": "min"}),
        (CONF_ASSIST_WATER_TEMP_THRESHOLD, {"min": 30, "max": 55, "step": 1, "unit_of_measurement": "°C"}),
        (CONF_ASSIST_STALL_TEMP_DELTA, {"min": 0.1, "max": 2, "step": 0.1, "unit_of_measurement": "°C"}),
    ]

    for field_name, selector_config in advanced_fields:
        _optional_field(
            field_name,
            defaults,
            schema_fields,
            selector({"number": selector_config}),
        )

    return vol.Schema(schema_fields)


def _advanced_form_defaults(
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
    }

    return {key: base.get(key, default_val) for key, default_val in default_map.items()}


def _process_advanced_input(user_input: dict[str, Any]) -> dict[str, Any]:
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
    }
    
    return {key: user_input[key] for key in advanced_keys if key in user_input}


def _build_experimental_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Build the schema for experimental options."""
    schema_fields: dict[Any, Any] = {}

    _optional_field(
        CONF_HOUSE_POWER_SENSOR,
        defaults,
        schema_fields,
        _entity_selector("sensor"),
    )

    return vol.Schema(schema_fields)


def _experimental_form_defaults(
    base: dict[str, Any],
    user_input: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build defaults for experimental form."""
    if user_input:
        return dict(user_input)

    return {
        CONF_HOUSE_POWER_SENSOR: base.get(CONF_HOUSE_POWER_SENSOR),
    }


def _process_experimental_input(user_input: dict[str, Any]) -> dict[str, Any]:
    """Process and validate experimental options input."""
    data: dict[str, Any] = {}
    if CONF_HOUSE_POWER_SENSOR in user_input:
        sensor_entity_id = str(user_input.get(CONF_HOUSE_POWER_SENSOR) or "").strip()
        data[CONF_HOUSE_POWER_SENSOR] = sensor_entity_id or None
    return data


