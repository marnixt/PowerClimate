"""Config flow and options flow for PowerClimate.

This module handles both the initial configuration flow and the options flow
for reconfiguring an existing integration instance.
"""

from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.core import callback

from .config_flow_handlers import (
    advanced_form_defaults,
    air_device_defaults,
    build_advanced_schema,
    build_air_device_schema,
    build_experimental_schema,
    build_global_schema,
    build_select_devices_schema,
    build_water_device_schema,
    experimental_form_defaults,
    flatten_section_data,
    global_form_defaults,
    process_advanced_input,
    process_air_device_input,
    process_experimental_input,
    process_global_input,
    process_select_devices_input,
    process_water_device_input,
    select_devices_defaults,
    split_devices_by_role,
    validate_advanced_input,
    water_device_defaults,
)
from .const import (
    CONF_CLIMATE_ENTITY,
    CONF_DEVICE_ID,
    CONF_DEVICES,
    CONF_ENTRY_NAME,
    CONF_MIRROR_CLIMATE_ENTITIES,
    DEFAULT_ENTRY_NAME,
    DOMAIN,
)
from .utils import generate_device_name, slugify


def _initialize_device_state(flow: Any) -> None:
    """Initialize state shared by the config and options flows."""
    flow._water_entity = None
    flow._air_entities = []
    flow._water_device = None
    flow._air_devices = []
    flow._air_device_index = 0
    flow._used_ids = set()


class _DeviceFlowMixin:
    """Share device configuration steps between config and options flows."""

    def _select_devices_defaults(
        self, user_input: dict[str, Any] | None
    ) -> dict[str, Any]:
        raise NotImplementedError

    def _existing_water_device(self) -> dict[str, Any] | None:
        raise NotImplementedError

    def _existing_air_device(self, climate_entity: str) -> dict[str, Any] | None:
        raise NotImplementedError

    async def _finish_device_flow(self) -> config_entries.ConfigFlowResult:
        raise NotImplementedError

    async def async_step_select_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle device selection: optional water HP + multi-select air HPs."""
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input = flatten_section_data(user_input)
            water_entity, air_entities, errors = process_select_devices_input(
                user_input
            )
            if not errors:
                self._water_entity = water_entity
                self._air_entities = air_entities
                self._air_device_index = 0

                if self._water_entity:
                    return await self.async_step_water_device()
                if self._air_entities:
                    return await self.async_step_air_device()
                return await self._finish_device_flow()

        defaults = self._select_devices_defaults(user_input)
        schema = build_select_devices_schema(defaults)
        return self.async_show_form(
            step_id="select_devices",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_water_device(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Configure the water-based heat pump."""
        errors: dict[str, str] = {}
        existing = self._existing_water_device()

        if user_input is not None:
            user_input = flatten_section_data(user_input)
            device, errors = process_water_device_input(
                user_input,
                self._water_entity,
                self._used_ids,
            )
            if not errors and device:
                self._water_device = device
                self._used_ids.add(device[CONF_DEVICE_ID])

                if self._air_entities:
                    return await self.async_step_air_device()
                return await self._finish_device_flow()

        defaults = water_device_defaults(existing, user_input)
        schema = build_water_device_schema(defaults)
        return self.async_show_form(
            step_id="water_device",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_air_device(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Configure an air heat pump."""
        errors: dict[str, str] = {}

        if self._air_device_index >= len(self._air_entities):
            return await self._finish_device_flow()

        current_entity = self._air_entities[self._air_device_index]
        existing = self._existing_air_device(current_entity)

        if user_input is not None:
            user_input = flatten_section_data(user_input)
            device, errors = process_air_device_input(
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
                return await self._finish_device_flow()

        defaults = air_device_defaults(existing, user_input)
        schema = build_air_device_schema(defaults)
        hp_number = self._air_device_index + 1
        if self._water_device:
            hp_number += 1

        return self.async_show_form(
            step_id="air_device",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "hp_label": f"Air HP{hp_number}",
                "device_name": generate_device_name(current_entity),
                "device_index": str(self._air_device_index + 1),
                "total_air_devices": str(len(self._air_entities)),
            },
        )


class PowerClimateConfigFlow(_DeviceFlowMixin, config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for PowerClimate."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._base: dict[str, Any] = {}
        self._entry_name: str = DEFAULT_ENTRY_NAME
        self._entry_data: dict[str, Any] = {}
        _initialize_device_state(self)

    def _select_devices_defaults(
        self, user_input: dict[str, Any] | None
    ) -> dict[str, Any]:
        mirror_entities = self._entry_data.get(CONF_MIRROR_CLIMATE_ENTITIES) or []
        return select_devices_defaults(
            None,
            [],
            user_input,
            mirror_entities=mirror_entities,
        )

    def _existing_water_device(self) -> dict[str, Any] | None:
        return None

    def _existing_air_device(self, climate_entity: str) -> dict[str, Any] | None:
        return None

    async def _finish_device_flow(self) -> config_entries.ConfigFlowResult:
        return await self._create_entry()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step: name and room sensors."""
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input = flatten_section_data(user_input)
            entry_name, data, errors = process_global_input(user_input, self._base)
            if not errors:
                self._entry_name = entry_name or DEFAULT_ENTRY_NAME
                self._entry_data = data
                return await self.async_step_select_devices()

        defaults = global_form_defaults(self._base, user_input)
        schema = build_global_schema(defaults)
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def _create_entry(self) -> config_entries.ConfigFlowResult:
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

        unique_id = slugify(self._entry_name)
        if unique_id:
            await self.async_set_unique_id(unique_id, raise_on_progress=False)
            self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=self._entry_name,
            data=entry_payload,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> PowerClimateOptionsFlowHandler:
        """Get the options flow handler."""
        return PowerClimateOptionsFlowHandler(config_entry)


class PowerClimateOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options for PowerClimate."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize the options flow handler."""
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
        self._base_water, self._base_air = split_devices_by_role(self._base)
        _initialize_device_state(self)

    def _select_devices_defaults(
        self, user_input: dict[str, Any] | None
    ) -> dict[str, Any]:
        mirror_entities = (
            self._entry_data.get(CONF_MIRROR_CLIMATE_ENTITIES)
            or self._base.get(CONF_MIRROR_CLIMATE_ENTITIES)
            or []
        )
        return select_devices_defaults(
            self._base_water,
            self._base_air,
            user_input,
            mirror_entities=mirror_entities,
        )

    def _existing_water_device(self) -> dict[str, Any] | None:
        if (
            self._base_water
            and self._base_water.get(CONF_CLIMATE_ENTITY) == self._water_entity
        ):
            return self._base_water
        return None

    def _existing_air_device(self, climate_entity: str) -> dict[str, Any] | None:
        return next(
            (
                device
                for device in self._base_air
                if device.get(CONF_CLIMATE_ENTITY) == climate_entity
            ),
            None,
        )

    async def _finish_device_flow(self) -> config_entries.ConfigFlowResult:
        return await self._create_options_entry()

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Show the options menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "edit_setup",
                "advanced",
                "experimental",
            ],
        )

    async def async_step_edit_setup(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Edit the general setup (name + room sensors), then devices."""
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input = flatten_section_data(user_input)
            entry_name, data, errors = process_global_input(user_input, self._base)
            if not errors:
                self._entry_name = entry_name or self._entry_name
                self._entry_data.update(data)
                return await self.async_step_select_devices()

        defaults = global_form_defaults(self._base, user_input)
        schema = build_global_schema(defaults)
        return self.async_show_form(
            step_id="edit_setup",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle advanced/expert configuration options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input = flatten_section_data(user_input)
            validation_data = dict(self._base)
            validation_data.update(user_input)
            errors = validate_advanced_input(validation_data)
            if not errors:
                advanced_data = process_advanced_input(user_input)
                self._entry_data.update(advanced_data)
                return await self._create_options_entry()

        defaults = advanced_form_defaults(self._base, user_input)
        schema = build_advanced_schema(defaults)
        return self.async_show_form(
            step_id="advanced",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_experimental(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle experimental configuration options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input = flatten_section_data(user_input)
            experimental_data = process_experimental_input(user_input)
            self._entry_data.update(experimental_data)
            return await self._create_options_entry()

        defaults = experimental_form_defaults(self._base, user_input)
        schema = build_experimental_schema(defaults)
        return self.async_show_form(
            step_id="experimental",
            data_schema=schema,
            errors=errors,
        )

    async def _create_options_entry(self) -> config_entries.ConfigFlowResult:
        """Create the options entry with all configured devices."""
        # If user only edited Advanced/Experimental, keep existing devices
        devices: list[dict[str, Any]] = []
        if self._water_device or self._air_devices:
            # Build device list from newly configured devices
            if self._water_device:
                devices.append(self._water_device)
            devices.extend(self._air_devices)
        else:
            if self._base_water:
                devices.append(dict(self._base_water))
            devices.extend(dict(air) for air in self._base_air)

        if devices:
            self._entry_data[CONF_DEVICES] = devices

        # Update the title together with the options so the update listener
        # (and thus the reload) only fires once.
        if self._entry_name != (
            self._entry.title or self._entry.data.get(CONF_ENTRY_NAME)
        ):
            new_data = dict(self._entry.data)
            new_data[CONF_ENTRY_NAME] = self._entry_name
            self.hass.config_entries.async_update_entry(
                self._entry,
                data=new_data,
                title=self._entry_name,
                options=self._entry_data,
            )

        return self.async_create_entry(data=self._entry_data)
