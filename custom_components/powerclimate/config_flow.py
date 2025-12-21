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
    CONF_DEVICES,
    CONF_ENERGY_SENSOR,
    CONF_ENTRY_NAME,
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
    DOMAIN,
)

ADD_ANOTHER_DEVICE_FIELD = "add_another_device"
ADD_MORE_DEVICES_FIELD = "add_more_devices"


def _entity_selector(domain: str, multiple: bool = False) -> Any:
    return selector({"entity": {"domain": [domain], "multiple": multiple}})


def _text_selector() -> Any:
    return selector({"text": {}})


def _offset_number_selector(min_val: float = -10, max_val: float = 10) -> Any:
    # Use a numeric selector so defaults can be passed as floats and the UI
    # provides a proper number input. Step and bounds are generous.
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


def _split_devices(
    base: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    devices = [
        dict(device)
        for device in (base or {}).get(CONF_DEVICES, [])
        if isinstance(device, dict)
    ]
    if not devices:
        return None, []
    first = devices[0]
    rest = devices[1:]
    return first, rest


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
        # Deduplicate while preserving order
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


def _hp1_form_defaults(
    base: dict[str, Any] | None,
    primary_device: dict[str, Any] | None,
    user_input: dict[str, Any] | None,
    has_additional_defaults: bool,
) -> dict[str, Any]:
    defaults: dict[str, Any] = {}
    base = base or {}
    if primary_device:
        defaults[CONF_CLIMATE_ENTITY] = primary_device.get(CONF_CLIMATE_ENTITY)
        defaults[CONF_ENERGY_SENSOR] = primary_device.get(CONF_ENERGY_SENSOR)
        defaults[CONF_WATER_SENSOR] = primary_device.get(CONF_WATER_SENSOR)
        defaults[CONF_COPY_SETPOINT_TO_POWERCLIMATE] = primary_device.get(
            CONF_COPY_SETPOINT_TO_POWERCLIMATE,
            False,
        )
        defaults[CONF_LOWER_SETPOINT_OFFSET] = primary_device.get(
            CONF_LOWER_SETPOINT_OFFSET,
            DEFAULT_LOWER_SETPOINT_OFFSET_HP1,
        )
        defaults[CONF_UPPER_SETPOINT_OFFSET] = primary_device.get(
            CONF_UPPER_SETPOINT_OFFSET,
            DEFAULT_UPPER_SETPOINT_OFFSET_HP1,
        )
    defaults.setdefault(
        CONF_LOWER_SETPOINT_OFFSET,
        DEFAULT_LOWER_SETPOINT_OFFSET_HP1,
    )
    defaults.setdefault(
        CONF_UPPER_SETPOINT_OFFSET,
        DEFAULT_UPPER_SETPOINT_OFFSET_HP1,
    )
    defaults.setdefault(ADD_MORE_DEVICES_FIELD, has_additional_defaults)
    if user_input:
        defaults.update(user_input)
    return defaults


def _build_hp1_schema(defaults: dict[str, Any]) -> vol.Schema:
    schema_fields: dict[Any, Any] = {}
    _required_field(
        CONF_CLIMATE_ENTITY,
        defaults,
        schema_fields,
        _entity_selector("climate"),
    )
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
    schema_fields[vol.Optional(
        ADD_MORE_DEVICES_FIELD,
        default=defaults.get(ADD_MORE_DEVICES_FIELD, False),
    )] = bool
    return vol.Schema(schema_fields)


def _process_hp1_input(
    user_input: dict[str, Any],
    used_ids: set[str],
) -> tuple[
    dict[str, Any] | None,
    bool,
    dict[str, str],
]:
    errors: dict[str, str] = {}
    climate_entity = user_input.get(CONF_CLIMATE_ENTITY)
    if not climate_entity:
        errors[CONF_CLIMATE_ENTITY] = "required"
    energy_sensor = user_input.get(CONF_ENERGY_SENSOR)
    if not energy_sensor:
        errors[CONF_ENERGY_SENSOR] = "required"
    water_sensor = user_input.get(CONF_WATER_SENSOR)
    if not water_sensor:
        errors[CONF_WATER_SENSOR] = "required"

    lower_offset, lower_valid = _parse_offset(
        user_input.get(
            CONF_LOWER_SETPOINT_OFFSET,
            DEFAULT_LOWER_SETPOINT_OFFSET_HP1,
        ),
        DEFAULT_LOWER_SETPOINT_OFFSET_HP1,
    )
    if not lower_valid:
        errors[CONF_LOWER_SETPOINT_OFFSET] = "invalid"

    upper_offset, upper_valid = _parse_offset(
        user_input.get(
            CONF_UPPER_SETPOINT_OFFSET,
            DEFAULT_UPPER_SETPOINT_OFFSET_HP1,
        ),
        DEFAULT_UPPER_SETPOINT_OFFSET_HP1,
    )
    if not upper_valid:
        errors[CONF_UPPER_SETPOINT_OFFSET] = "invalid"

    if lower_offset > upper_offset:
        errors["base"] = "invalid_offsets"
        errors.setdefault(CONF_LOWER_SETPOINT_OFFSET, "invalid")
        errors.setdefault(CONF_UPPER_SETPOINT_OFFSET, "invalid")

    add_more = bool(user_input.get(ADD_MORE_DEVICES_FIELD))

    if errors:
        return None, add_more, errors

    device_id = _generate_device_id(climate_entity, used_ids)
    device = {
        CONF_DEVICE_ID: device_id,
        CONF_DEVICE_NAME: _generate_device_name(climate_entity),
        CONF_CLIMATE_ENTITY: climate_entity,
        CONF_ENERGY_SENSOR: energy_sensor,
        CONF_WATER_SENSOR: water_sensor,
        CONF_COPY_SETPOINT_TO_POWERCLIMATE: bool(
            user_input.get(CONF_COPY_SETPOINT_TO_POWERCLIMATE, False)
        ),
        CONF_LOWER_SETPOINT_OFFSET: lower_offset,
        CONF_UPPER_SETPOINT_OFFSET: upper_offset,
    }

    return device, add_more, {}


def _additional_form_defaults(
    _device_index: int,
    base_defaults: dict[str, Any],
    user_input: dict[str, Any] | None,
    has_pending_defaults: bool,
) -> dict[str, Any]:
    defaults: dict[str, Any] = {}
    defaults.update(base_defaults)
    defaults.setdefault(
        CONF_LOWER_SETPOINT_OFFSET,
        DEFAULT_LOWER_SETPOINT_OFFSET_ASSIST,
    )
    defaults.setdefault(
        CONF_UPPER_SETPOINT_OFFSET,
        DEFAULT_UPPER_SETPOINT_OFFSET_ASSIST,
    )
    defaults.setdefault(CONF_COPY_SETPOINT_TO_POWERCLIMATE, False)
    defaults.setdefault(CONF_ALLOW_ON_OFF_CONTROL, False)
    defaults.setdefault(ADD_ANOTHER_DEVICE_FIELD, has_pending_defaults)
    if user_input:
        defaults.update(user_input)
    defaults.setdefault(ADD_ANOTHER_DEVICE_FIELD, False)
    return defaults


def _build_additional_schema(
    device_index: int,
    defaults: dict[str, Any],
) -> vol.Schema:
    schema_fields: dict[Any, Any] = {}
    _required_field(
        CONF_CLIMATE_ENTITY,
        defaults,
        schema_fields,
        _entity_selector("climate"),
    )
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
    schema_fields[vol.Optional(
        ADD_ANOTHER_DEVICE_FIELD,
        default=defaults.get(ADD_ANOTHER_DEVICE_FIELD, False),
    )] = bool
    return vol.Schema(schema_fields)


def _build_additional_device_data(
    user_input: dict[str, Any],
    _device_index: int,
    used_ids: set[str],
    inherited_water_sensor: Any,
) -> tuple[dict[str, Any] | None, dict[str, str]]:
    errors: dict[str, str] = {}
    climate_entity = user_input.get(CONF_CLIMATE_ENTITY)
    if not climate_entity:
        errors[CONF_CLIMATE_ENTITY] = "required"
    energy_sensor = user_input.get(CONF_ENERGY_SENSOR)
    if not energy_sensor:
        errors[CONF_ENERGY_SENSOR] = "required"

    lower_offset, lower_valid = _parse_offset(
        user_input.get(
            CONF_LOWER_SETPOINT_OFFSET,
            DEFAULT_LOWER_SETPOINT_OFFSET_ASSIST,
        ),
        DEFAULT_LOWER_SETPOINT_OFFSET_ASSIST,
    )
    if not lower_valid:
        errors[CONF_LOWER_SETPOINT_OFFSET] = "invalid"

    upper_offset, upper_valid = _parse_offset(
        user_input.get(
            CONF_UPPER_SETPOINT_OFFSET,
            DEFAULT_UPPER_SETPOINT_OFFSET_ASSIST,
        ),
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
    if inherited_water_sensor:
        device[CONF_WATER_SENSOR] = inherited_water_sensor
    return device, {}


class _DeviceWizardState:
    def __init__(self, base_devices: list[dict[str, Any]] | None = None):
        self.reset(base_devices)

    def reset(self, base_devices: list[dict[str, Any]] | None = None) -> None:
        self._devices: list[dict[str, Any]] = []
        self._defaults_queue: list[dict[str, Any]] = [
            dict(device) for device in (base_devices or [])
        ]
        self._current_defaults: dict[str, Any] | None = None

    @property
    def devices(self) -> list[dict[str, Any]]:
        return self._devices

    def next_index(self) -> int:
        return len(self._devices)

    def has_pending_prefills(self) -> bool:
        return bool(self._defaults_queue)

    def acquire_defaults(self) -> dict[str, Any]:
        if self._current_defaults is None:
            if self._defaults_queue:
                self._current_defaults = self._defaults_queue.pop(0)
            else:
                self._current_defaults = {}
        return self._current_defaults

    def current_defaults(self) -> dict[str, Any]:
        return self._current_defaults or {}

    def append_device(self, device: dict[str, Any]) -> None:
        self._devices.append(device)
        self._current_defaults = None

    def placeholders(self) -> dict[str, str]:
        names = [
            device.get(CONF_DEVICE_NAME)
            or device.get(CONF_CLIMATE_ENTITY)
            or f"HP{index}"
            for index, device in enumerate(self._devices, start=1)
        ]
        return {
            "device_list": ", ".join(names) if names else "None yet",
        }


class PowerClimateConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for PowerClimate."""

    VERSION = 1

    def __init__(self):
        self._base: dict[str, Any] = {}
        self._entry_name: str = DEFAULT_ENTRY_NAME
        self._entry_data: dict[str, Any] = {}
        self._primary_device: dict[str, Any] | None = None
        self._device_state = _DeviceWizardState()
        self._collect_additional = False
        self._used_ids: set[str] = set()

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            entry_name, data, errors = _process_global_input(
                user_input, self._base,
            )
            if not errors:
                self._entry_name = entry_name or DEFAULT_ENTRY_NAME
                self._entry_data = data
                return await self.async_step_primary()
        defaults = _global_form_defaults(self._base, user_input)
        schema = _build_global_schema(defaults)
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_primary(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        defaults = _hp1_form_defaults(
            self._entry_data,
            self._primary_device,
            user_input,
            False,
        )
        errors: dict[str, str] = {}
        if user_input is not None:
            device, add_more, errors = _process_hp1_input(
                user_input,
                self._used_ids,
            )
            if not errors and device:
                self._primary_device = device
                self._used_ids.add(device[CONF_DEVICE_ID])
                self._collect_additional = add_more
                self._device_state.reset(None if not add_more else [])
                if add_more:
                    return await self.async_step_devices()
                return await self._create_entry()
        schema = _build_hp1_schema(defaults)
        return self.async_show_form(
            step_id="primary",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_devices(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        if not self._collect_additional:
            return await self._create_entry()

        device_index = 1 + self._device_state.next_index()
        errors: dict[str, str] = {}

        defaults_source = (
            self._device_state.acquire_defaults()
            if user_input is None
            else self._device_state.current_defaults()
        )
        inherited_water = defaults_source.get(CONF_WATER_SENSOR)

        if user_input is not None:
            device, errors = _build_additional_device_data(
                user_input,
                device_index,
                self._used_ids,
                inherited_water,
            )
            add_another = bool(user_input.get(ADD_ANOTHER_DEVICE_FIELD))
            if not errors and device is not None:
                self._device_state.append_device(device)
                self._used_ids.add(device[CONF_DEVICE_ID])
                if add_another:
                    return await self.async_step_devices()
                return await self._create_entry()

        defaults = _additional_form_defaults(
            device_index,
            defaults_source,
            user_input,
            self._device_state.has_pending_prefills(),
        )
        schema = _build_additional_schema(device_index, defaults)
        placeholders = self._device_state.placeholders()
        hp_number = device_index + 1
        placeholders["next_index"] = str(hp_number)
        placeholders["hp_number"] = str(hp_number)
        placeholders["hp_label"] = f"HP{hp_number}"
        return self.async_show_form(
            step_id="devices",
            data_schema=schema,
            errors=errors,
            description_placeholders=placeholders,
        )

    async def _create_entry(self):
        if not self._primary_device:
            return await self.async_step_primary()
        devices = [self._primary_device] + [
            dict(device) for device in self._device_state.devices
        ]
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
        self._entry_data: dict[str, Any] = {}
        self._primary_device: dict[str, Any] | None = None
        self._base_primary, self._base_additional = _split_devices(self._base)
        if self._base_primary:
            self._primary_device = dict(self._base_primary)
        self._device_state = _DeviceWizardState()
        self._collect_additional = False
        self._used_ids: set[str] = set()

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        # Start with a simple menu so users can change advanced behavior
        # without having to reconfigure all devices.
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "edit_setup",
                "advanced",
            ],
        )

    async def async_step_edit_setup(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Edit the general setup (name + room sensors), then devices."""
        errors: dict[str, str] = {}
        if user_input is not None:
            entry_name, data, errors = _process_global_input(
                user_input,
                self._base,
            )
            if not errors:
                self._entry_name = entry_name or self._entry_name
                self._entry_data = data
                return await self.async_step_primary()

        defaults = _global_form_defaults(self._base, user_input)
        schema = _build_global_schema(defaults)
        return self.async_show_form(
            step_id="edit_setup",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_primary(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        defaults = _hp1_form_defaults(
            self._base,
            self._base_primary,
            user_input,
            bool(self._base_additional),
        )
        errors: dict[str, str] = {}
        if user_input is not None:
            device, add_more, errors = _process_hp1_input(
                user_input,
                self._used_ids,
            )
            if not errors and device:
                self._primary_device = device
                self._used_ids.add(device[CONF_DEVICE_ID])
                self._collect_additional = add_more
                if add_more:
                    self._device_state.reset(self._base_additional)
                    return await self.async_step_devices()
                self._device_state.reset(None)
                return await self._create_options_entry()
        schema = _build_hp1_schema(defaults)
        return self.async_show_form(
            step_id="primary",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_devices(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        if not self._collect_additional:
            return await self._create_options_entry()

        device_index = 1 + self._device_state.next_index()
        errors: dict[str, str] = {}

        defaults_source = (
            self._device_state.acquire_defaults()
            if user_input is None
            else self._device_state.current_defaults()
        )
        inherited_water = defaults_source.get(CONF_WATER_SENSOR)

        if user_input is not None:
            device, errors = _build_additional_device_data(
                user_input,
                device_index,
                self._used_ids,
                inherited_water,
            )
            add_another = bool(user_input.get(ADD_ANOTHER_DEVICE_FIELD))
            if not errors and device is not None:
                self._device_state.append_device(device)
                self._used_ids.add(device[CONF_DEVICE_ID])
                if add_another:
                    return await self.async_step_devices()
                return await self._create_options_entry()

        defaults = _additional_form_defaults(
            device_index,
            defaults_source,
            user_input,
            self._device_state.has_pending_prefills(),
        )
        schema = _build_additional_schema(device_index, defaults)
        placeholders = self._device_state.placeholders()
        hp_number = device_index + 1
        placeholders["next_index"] = str(hp_number)
        placeholders["hp_number"] = str(hp_number)
        placeholders["hp_label"] = f"HP{hp_number}"
        return self.async_show_form(
            step_id="devices",
            data_schema=schema,
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_advanced(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Handle advanced/expert configuration options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            # Validate and store advanced options
            advanced_data = _process_advanced_input(user_input)
            self._entry_data.update(advanced_data)
            return await self._create_options_entry()

        defaults = _advanced_form_defaults(self._base, user_input)
        schema = _build_advanced_schema(defaults)
        return self.async_show_form(
            step_id="advanced",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "timer_desc": (
                    "Duration in seconds that a condition must remain true "
                    "before action is taken"
                ),
                "eta_on_desc": "Turn assist pumps ON if ETA exceeds this many hours",
                "eta_off_desc": (
                    "Turn assist pumps OFF if ETA drops below this many hours "
                    "(15min = 0.25)"
                ),
                "water_temp_desc": (
                    "Turn assist pumps ON if water temperature reaches this threshold"
                ),
                "stall_delta_desc": "Temperature difference threshold for stall detection",
            },
        )

    async def _create_options_entry(self):
        # If the user only edited Advanced options, keep existing devices.
        if not self._primary_device and self._base_primary:
            self._primary_device = dict(self._base_primary)

        if not self._primary_device:
            return await self.async_step_primary()

        additional_devices = (
            self._device_state.devices if self._device_state.devices else self._base_additional
        )
        devices = [self._primary_device] + [dict(device) for device in additional_devices]
        data = dict(self._entry_data)
        data[CONF_DEVICES] = devices

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

        return self.async_create_entry(data=data)


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

    # Data-driven approach for advanced options
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

    # Data-driven defaults mapping
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
    # All advanced option keys
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


