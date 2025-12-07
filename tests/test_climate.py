import logging
from types import SimpleNamespace

import pytest
from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.components.climate.const import SERVICE_SET_TEMPERATURE
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE
from homeassistant.core import Context, State
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.powerclimate.climate import PowerClimateClimate
from custom_components.powerclimate.const import (
    CONF_CLIMATE_ENTITY,
    CONF_DEVICES,
    DEFAULT_LOWER_SETPOINT_OFFSET_ASSIST,
    DEFAULT_MIN_SETPOINT,
    DEFAULT_UPPER_SETPOINT_OFFSET_ASSIST,
    DOMAIN,
)


@pytest.mark.asyncio
async def test_clamp_setpoint_respects_offsets(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_DEVICES: [
                {
                    CONF_CLIMATE_ENTITY: "climate.hp1",
                }
            ]
        },
    )
    entry.add_to_hass(hass)

    coordinator = DataUpdateCoordinator(
        hass,
        logging.getLogger(__name__),
        name="pc_test",
        update_method=lambda: None,
        update_interval=None,
    )
    coordinator.data = {"devices": []}

    climate = PowerClimateClimate(hass, entry, coordinator)
    device = entry.data[CONF_DEVICES][0]

    clamped = climate._clamp_setpoint(  # pylint: disable=protected-access
        25.0,
        22.0,
        device,
        0,
    )

    # HP1 default upper offset is 1.5
    assert clamped == pytest.approx(23.5)


@pytest.mark.asyncio
async def test_minimal_mode_target_and_clamping(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_DEVICES: [
                {
                    CONF_CLIMATE_ENTITY: "climate.hp1",
                },
                {
                    CONF_CLIMATE_ENTITY: "climate.hp2",
                    # Explicit offsets to validate clamp paths
                    "lower_setpoint_offset": DEFAULT_LOWER_SETPOINT_OFFSET_ASSIST,
                    "upper_setpoint_offset": DEFAULT_UPPER_SETPOINT_OFFSET_ASSIST,
                },
            ]
        },
    )
    entry.add_to_hass(hass)

    coordinator = DataUpdateCoordinator(
        hass,
        logging.getLogger(__name__),
        name="pc_test",
        update_method=lambda: None,
        update_interval=None,
    )
    coordinator.data = {"devices": []}
    climate = PowerClimateClimate(hass, entry, coordinator)

    assist_device = entry.data[CONF_DEVICES][1]

    target = climate._minimal_mode_target(  # pylint: disable=protected-access
        20.0,
        assist_device,
        1,
    )
    assert target == pytest.approx(max(DEFAULT_MIN_SETPOINT, 16.0))

    # None current temp should fall back to absolute floor
    assert climate._minimal_mode_target(  # pylint: disable=protected-access
        None,
        assist_device,
        1,
    ) == DEFAULT_MIN_SETPOINT

    # Clamp should respect upper bound
    clamped = climate._clamp_setpoint(  # pylint: disable=protected-access
        30.0,
        20.0,
        assist_device,
        1,
    )
    assert clamped == DEFAULT_MIN_SETPOINT + DEFAULT_UPPER_SETPOINT_OFFSET_ASSIST


@pytest.mark.asyncio
async def test_manual_setpoint_copy_forwards_to_powerclimate(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_DEVICES: [
                {
                    CONF_CLIMATE_ENTITY: "climate.hp1",
                },
            ]
        },
    )
    entry.add_to_hass(hass)

    coordinator = DataUpdateCoordinator(
        hass,
        logging.getLogger(__name__),
        name="pc_test",
        update_method=lambda: None,
        update_interval=None,
    )
    coordinator.data = {"devices": []}
    climate = PowerClimateClimate(hass, entry, coordinator)
    climate.entity_id = "climate.powerclimate"
    climate._copy_enabled_entities = {"climate.hp1"}  # pylint: disable=protected-access

    calls = async_mock_service(
        hass,
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
    )

    old_state = State(
        "climate.hp1",
        "heat",
        {ATTR_TEMPERATURE: 20.0},
        context=Context(),
    )
    new_state = State(
        "climate.hp1",
        "heat",
        {ATTR_TEMPERATURE: 21.0},
        context=Context(),
    )
    event = SimpleNamespace(
        data={
            "entity_id": "climate.hp1",
            "old_state": old_state,
            "new_state": new_state,
        }
    )

    climate._handle_hp_state_change(event)  # pylint: disable=protected-access
    await hass.async_block_till_done()

    assert len(calls) == 1
    call = calls[0]
    assert call.data[ATTR_ENTITY_ID] == "climate.powerclimate"
    assert call.data[ATTR_TEMPERATURE] == 21.0


@pytest.mark.asyncio
async def test_manual_setpoint_copy_ignores_integration_origin(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_DEVICES: [
                {
                    CONF_CLIMATE_ENTITY: "climate.hp1",
                },
            ]
        },
    )
    entry.add_to_hass(hass)

    coordinator = DataUpdateCoordinator(
        hass,
        logging.getLogger(__name__),
        name="pc_test",
        update_method=lambda: None,
        update_interval=None,
    )
    coordinator.data = {"devices": []}
    climate = PowerClimateClimate(hass, entry, coordinator)
    climate.entity_id = "climate.powerclimate"
    climate._copy_enabled_entities = {"climate.hp1"}  # pylint: disable=protected-access

    calls = async_mock_service(
        hass,
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
    )

    integration_ctx = climate._integration_context  # pylint: disable=protected-access
    old_state = State(
        "climate.hp1",
        "heat",
        {ATTR_TEMPERATURE: 20.0},
        context=Context(),
    )
    new_state = State(
        "climate.hp1",
        "heat",
        {ATTR_TEMPERATURE: 22.0},
        context=integration_ctx,
    )
    event = SimpleNamespace(
        data={
            "entity_id": "climate.hp1",
            "old_state": old_state,
            "new_state": new_state,
        }
    )

    climate._handle_hp_state_change(event)  # pylint: disable=protected-access
    await hass.async_block_till_done()

    assert len(calls) == 0
