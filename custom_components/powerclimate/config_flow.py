"""Config flow and options flow for PowerClimate.

This module handles both the initial configuration flow and the options flow
for reconfiguring an existing integration instance.
"""

from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.core import callback

from .config_flow_handlers import (
    FIELD_AIR_CLIMATES,
    FIELD_WATER_CLIMATE,
    advanced_form_defaults,
    air_device_defaults,
    build_advanced_schema,
    build_air_device_schema,
    build_experimental_schema,
    build_global_schema,
    build_select_devices_schema,
    build_water_device_schema,
    experimental_form_defaults,
    generate_device_name,
    global_form_defaults,
    process_advanced_input,
    process_air_device_input,
    process_experimental_input,
    process_global_input,
    process_select_devices_input,
    process_water_device_input,
    select_devices_defaults,
    slugify,
    split_devices_by_role,
    water_device_defaults,
)
from .const import (
    CONF_CLIMATE_ENTITY,
    CONF_DEVICE_ID,
    CONF_DEVICE_ROLE,
    CONF_DEVICES,
    CONF_ENTRY_NAME,
    CONF_MIRROR_CLIMATE_ENTITIES,
    DEFAULT_ENTRY_NAME,
    DEVICE_ROLE_AIR,
    DEVICE_ROLE_WATER,
    DOMAIN,
)


class PowerClimateConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for PowerClimate."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
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

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step: name and room sensors."""
        errors: dict[str, str] = {}
        if user_input is not None:
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

    async def async_step_select_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle device selection: optional water HP + multi-select air HPs."""
        errors: dict[str, str] = {}

        if user_input is not None:
            water_entity, air_entities, errors = process_select_devices_input(
                user_input
            )
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

        mirror_entities = self._entry_data.get(CONF_MIRROR_CLIMATE_ENTITIES) or []
        defaults = select_devices_defaults(
            None,
            [],
            user_input,
            mirror_entities=mirror_entities,
        )
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

        if user_input is not None:
            device, errors = process_water_device_input(
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

        defaults = water_device_defaults(None, user_input)
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

        # Get current air entity
        if self._air_device_index >= len(self._air_entities):
            return await self._create_entry()

        current_entity = self._air_entities[self._air_device_index]

        if user_input is not None:
            device, errors = process_air_device_input(
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

        defaults = air_device_defaults(None, user_input)
        schema = build_air_device_schema(defaults)

        # Generate a friendly name for the air HP
        hp_number = self._air_device_index + 1
        if self._water_device:
            hp_number += 1  # Water device is HP1, so air devices start at HP2

        device_name = generate_device_name(current_entity)

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

        # Device selection state
        self._water_entity: str | None = None
        self._air_entities: list[str] = []

        # Configured devices
        self._water_device: dict[str, Any] | None = None
        self._air_devices: list[dict[str, Any]] = []

        # Track current air device index during configuration
        self._air_device_index: int = 0

        self._used_ids: set[str] = set()

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

    async def async_step_select_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle device selection: optional water HP + multi-select air HPs."""
        errors: dict[str, str] = {}

        if user_input is not None:
            water_entity, air_entities, errors = process_select_devices_input(
                user_input
            )
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

        mirror_entities = (
            self._entry_data.get(CONF_MIRROR_CLIMATE_ENTITIES)
            or self._base.get(CONF_MIRROR_CLIMATE_ENTITIES)
            or []
        )
        defaults = select_devices_defaults(
            self._base_water,
            self._base_air,
            user_input,
            mirror_entities=mirror_entities,
        )
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

        # Find existing water device config if entity matches
        existing = None
        if (
            self._base_water
            and self._base_water.get(CONF_CLIMATE_ENTITY) == self._water_entity
        ):
            existing = self._base_water

        if user_input is not None:
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
                return await self._create_options_entry()

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
            return await self._create_options_entry()

        current_entity = self._air_entities[self._air_device_index]

        # Find existing air device config if entity matches
        existing = None
        for air_dev in self._base_air:
            if air_dev.get(CONF_CLIMATE_ENTITY) == current_entity:
                existing = air_dev
                break

        if user_input is not None:
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
                return await self._create_options_entry()

        defaults = air_device_defaults(existing, user_input)
        schema = build_air_device_schema(defaults)

        hp_number = self._air_device_index + 1
        if self._water_device:
            hp_number += 1

        device_name = generate_device_name(current_entity)

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

    async def async_step_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle advanced/expert configuration options."""
        errors: dict[str, str] = {}
        if user_input is not None:
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
