"""End-to-end tests for the config and options flows.

The flows are driven step by step through their public ``async_step_*``
methods, so a missing or misrouted step fails here even though Home
Assistant's flow manager is not available on every test platform.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.powerclimate.config_flow import (
    PowerClimateConfigFlow,
    PowerClimateOptionsFlowHandler,
)
from custom_components.powerclimate.config_flow_handlers import (
    FIELD_AIR_CLIMATES,
    FIELD_WATER_CLIMATE,
)
from custom_components.powerclimate.const import (
    CONF_CLIMATE_ENTITY,
    CONF_DEVICE_ID,
    CONF_DEVICE_ROLE,
    CONF_DEVICES,
    CONF_ENERGY_SENSOR,
    CONF_ENTRY_NAME,
    CONF_MIRROR_CLIMATE_ENTITIES,
    CONF_ROOM_SENSORS,
    CONF_WATER_SENSOR,
    DEVICE_ROLE_AIR,
    DEVICE_ROLE_WATER,
)

GLOBAL_INPUT = {
    "general": {
        CONF_ENTRY_NAME: "Living",
        CONF_ROOM_SENSORS: ["sensor.room"],
    },
    "mirrors": {CONF_MIRROR_CLIMATE_ENTITIES: []},
}
WATER_INPUT = {
    CONF_ENERGY_SENSOR: "sensor.water_power",
    CONF_WATER_SENSOR: "sensor.water_temp",
}
AIR_INPUT = {CONF_ENERGY_SENSOR: "sensor.air_power"}


def _show_form(**kwargs):
    return {"type": "form", **kwargs}


def _create_entry(**kwargs):
    return {"type": "create_entry", **kwargs}


def _make_config_flow() -> PowerClimateConfigFlow:
    flow = PowerClimateConfigFlow()
    flow.async_show_form = MagicMock(side_effect=_show_form)
    flow.async_create_entry = MagicMock(side_effect=_create_entry)
    flow.async_set_unique_id = MagicMock(side_effect=lambda *a, **kw: asyncio.sleep(0))
    flow._abort_if_unique_id_configured = MagicMock()
    return flow


def _make_entry() -> SimpleNamespace:
    return SimpleNamespace(
        title="Living",
        data={
            CONF_ENTRY_NAME: "Living",
            CONF_ROOM_SENSORS: ["sensor.room"],
            CONF_DEVICES: [
                {
                    CONF_DEVICE_ID: "water_hp",
                    CONF_DEVICE_ROLE: DEVICE_ROLE_WATER,
                    CONF_CLIMATE_ENTITY: "climate.water_hp",
                    CONF_ENERGY_SENSOR: "sensor.water_power",
                    CONF_WATER_SENSOR: "sensor.water_temp",
                },
                {
                    CONF_DEVICE_ID: "air_hp",
                    CONF_DEVICE_ROLE: DEVICE_ROLE_AIR,
                    CONF_CLIMATE_ENTITY: "climate.air_hp",
                    CONF_ENERGY_SENSOR: "sensor.air_power",
                },
            ],
        },
        options={},
    )


def _make_options_flow(entry=None) -> PowerClimateOptionsFlowHandler:
    flow = PowerClimateOptionsFlowHandler(entry or _make_entry())
    flow.async_show_form = MagicMock(side_effect=_show_form)
    flow.async_show_menu = MagicMock(side_effect=lambda **kw: {"type": "menu", **kw})
    flow.async_create_entry = MagicMock(side_effect=_create_entry)
    flow.hass = MagicMock()
    return flow


class TestConfigFlow:
    """Initial setup: user -> select_devices -> water_device -> air_device."""

    def test_full_flow_creates_entry(self):
        flow = _make_config_flow()

        result = asyncio.run(flow.async_step_user())
        assert result["step_id"] == "user"

        result = asyncio.run(flow.async_step_user(GLOBAL_INPUT))
        assert result["step_id"] == "select_devices"

        result = asyncio.run(
            flow.async_step_select_devices(
                {
                    FIELD_WATER_CLIMATE: "climate.water_hp",
                    FIELD_AIR_CLIMATES: ["climate.air_hp"],
                }
            )
        )
        assert result["step_id"] == "water_device"

        result = asyncio.run(flow.async_step_water_device(WATER_INPUT))
        assert result["step_id"] == "air_device"

        result = asyncio.run(flow.async_step_air_device(AIR_INPUT))
        assert result["type"] == "create_entry"
        assert result["title"] == "Living"
        devices = result["data"][CONF_DEVICES]
        assert [d[CONF_DEVICE_ROLE] for d in devices] == [
            DEVICE_ROLE_WATER,
            DEVICE_ROLE_AIR,
        ]

    def test_air_only_flow_skips_water_step(self):
        flow = _make_config_flow()
        asyncio.run(flow.async_step_user(GLOBAL_INPUT))

        result = asyncio.run(
            flow.async_step_select_devices({FIELD_AIR_CLIMATES: ["climate.air_hp"]})
        )
        assert result["step_id"] == "air_device"

        result = asyncio.run(flow.async_step_air_device(AIR_INPUT))
        assert result["type"] == "create_entry"

    def test_select_devices_requires_a_device(self):
        flow = _make_config_flow()
        asyncio.run(flow.async_step_user(GLOBAL_INPUT))

        result = asyncio.run(flow.async_step_select_devices({}))
        assert result["step_id"] == "select_devices"
        assert result["errors"]["base"] == "no_devices"


class TestOptionsFlow:
    """Options: init menu -> edit_setup -> device steps, advanced, experimental."""

    def test_menu_lists_all_steps(self):
        flow = _make_options_flow()
        result = asyncio.run(flow.async_step_init())
        assert result["menu_options"] == ["edit_setup", "advanced", "experimental"]
        for step in result["menu_options"]:
            assert callable(getattr(flow, f"async_step_{step}", None)), step

    def test_edit_setup_continues_to_device_steps(self):
        """Regression: edit_setup used to crash on a missing select_devices step."""
        flow = _make_options_flow()

        result = asyncio.run(flow.async_step_edit_setup(GLOBAL_INPUT))
        assert result["step_id"] == "select_devices"

        result = asyncio.run(
            flow.async_step_select_devices(
                {
                    FIELD_WATER_CLIMATE: "climate.water_hp",
                    FIELD_AIR_CLIMATES: ["climate.air_hp"],
                }
            )
        )
        assert result["step_id"] == "water_device"

        result = asyncio.run(flow.async_step_water_device(WATER_INPUT))
        assert result["step_id"] == "air_device"

        result = asyncio.run(flow.async_step_air_device(AIR_INPUT))
        assert result["type"] == "create_entry"
        devices = result["data"][CONF_DEVICES]
        assert [d[CONF_CLIMATE_ENTITY] for d in devices] == [
            "climate.water_hp",
            "climate.air_hp",
        ]
        flow.hass.config_entries.async_update_entry.assert_not_called()

    def test_renaming_updates_entry_title(self):
        flow = _make_options_flow()
        renamed = {
            **GLOBAL_INPUT,
            "general": {**GLOBAL_INPUT["general"], CONF_ENTRY_NAME: "Upstairs"},
        }

        asyncio.run(flow.async_step_edit_setup(renamed))
        asyncio.run(
            flow.async_step_select_devices({FIELD_AIR_CLIMATES: ["climate.air_hp"]})
        )
        asyncio.run(flow.async_step_air_device(AIR_INPUT))

        kwargs = flow.hass.config_entries.async_update_entry.call_args.kwargs
        assert kwargs["title"] == "Upstairs"

    def test_experimental_keeps_existing_devices(self):
        flow = _make_options_flow()

        result = asyncio.run(flow.async_step_experimental({}))
        assert result["type"] == "create_entry"
        devices = result["data"][CONF_DEVICES]
        assert [d[CONF_DEVICE_ID] for d in devices] == ["water_hp", "air_hp"]
