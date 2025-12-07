import logging

import pytest
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powerclimate.climate import PowerClimateClimate
from custom_components.powerclimate.const import (
    CONF_CLIMATE_ENTITY,
    CONF_DEVICES,
    DEFAULT_LOWER_SETPOINT_OFFSET_ASSIST,
    DEFAULT_MAX_SETPOINT,
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
*** End File