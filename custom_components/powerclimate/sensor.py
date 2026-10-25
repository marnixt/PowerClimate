"""Diagnostic sensors for PowerClimate.

This module provides diagnostic sensor entities that expose internal state
and calculations from the PowerClimate integration:

- **Temperature Derivative**: Rate of room temperature change (°C/hour)
- **Water Derivative**: Rate of water temperature change (°C/hour)
- **Heat pump mode**: Mode PowerClimate runs each heat pump in, with its
  status as attributes
- **Total Power**: Aggregated power consumption from all configured heat pumps
- **Target Temperature**: PowerClimate's room target, for integrations that
  only accept a sensor
- **Supply Correction**: Setpoint correction of the supply-temperature
  controller in the supply advice preset

All sensors except Target Temperature are diagnostic entities. They are
grouped under the integration's virtual device in the Home Assistant device
registry.
"""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_CLIMATE_ENTITY,
    CONF_DEVICES,
    COORDINATOR,
    DOMAIN,
)
from .helpers import (
    merged_entry_data,
)
from .sensors.heat_pump import PowerClimateHeatPumpModeSensor
from .sensors.measurements import (
    PowerClimateDerivativeSensor,
    PowerClimateRoomCorrectionSensor,
    PowerClimateSupplyCorrectionSensor,
    PowerClimateTargetTemperatureSensor,
    PowerClimateTotalPowerSensor,
    PowerClimateWaterDerivativeSensor,
)

__all__ = [
    "PowerClimateDerivativeSensor",
    "PowerClimateHeatPumpModeSensor",
    "PowerClimateRoomCorrectionSensor",
    "PowerClimateSupplyCorrectionSensor",
    "PowerClimateTargetTemperatureSensor",
    "PowerClimateTotalPowerSensor",
    "PowerClimateWaterDerivativeSensor",
    "async_setup_entry",
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities for the config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data[COORDINATOR]

    derivative_sensor = PowerClimateDerivativeSensor(coordinator, entry)
    water_derivative_sensor = PowerClimateWaterDerivativeSensor(
        coordinator,
        entry,
    )
    total_power_sensor = PowerClimateTotalPowerSensor(
        hass,
        coordinator,
        entry,
    )

    sensors: list[SensorEntity] = [
        derivative_sensor,
        water_derivative_sensor,
        total_power_sensor,
        PowerClimateTargetTemperatureSensor(hass, entry),
        PowerClimateSupplyCorrectionSensor(hass, entry),
        PowerClimateRoomCorrectionSensor(hass, entry),
    ]

    sensors.extend(_build_heat_pump_sensors(hass, entry))

    async_add_entities(sensors)


def _build_heat_pump_sensors(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> list[SensorEntity]:
    devices = merged_entry_data(entry).get(CONF_DEVICES, []) or []
    return [
        PowerClimateHeatPumpModeSensor(
            hass, entry, role=f"hp{index + 1}", label=f"HP{index + 1}"
        )
        for index, device in enumerate(devices)
        if device and device.get(CONF_CLIMATE_ENTITY)
    ]
