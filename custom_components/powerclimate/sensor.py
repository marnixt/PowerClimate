"""Diagnostic sensors for PowerClimate.

This module provides diagnostic sensor entities that expose internal state
and calculations from the PowerClimate integration:

- **Temperature Derivative**: Rate of room temperature change (°C/hour)
- **Water Derivative**: Rate of water temperature change (°C/hour)
- **Summary**: Human-readable summary of system state
- **Assist Behavior**: Simple per-stage view showing HVAC state and assist mode
- **Total Power**: Aggregated power consumption from all configured heat pumps
- **Target Temperature**: PowerClimate's room target, for integrations that
  only accept a sensor
- **Supply Correction**: Setpoint correction of the supply-temperature
  controller in the MPC preset

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
    CONF_DEVICE_ROLE,
    CONF_DEVICES,
    COORDINATOR,
    DEVICE_ROLE_WATER,
    DOMAIN,
)
from .helpers import (
    merged_entry_data,
)
from .sensors.assist import (
    PowerClimateAssistSummarySensor,
    PowerClimateHP1BehaviorSensor,
    PowerClimateHPBehaviorSensor,
)
from .sensors.measurements import (
    PowerClimateDerivativeSensor,
    PowerClimateSupplyCorrectionSensor,
    PowerClimateTargetTemperatureSensor,
    PowerClimateTotalPowerSensor,
    PowerClimateWaterDerivativeSensor,
)
from .sensors.summary import PowerClimateSummarySensor

__all__ = [
    "PowerClimateAssistSummarySensor",
    "PowerClimateDerivativeSensor",
    "PowerClimateHP1BehaviorSensor",
    "PowerClimateHPBehaviorSensor",
    "PowerClimateSupplyCorrectionSensor",
    "PowerClimateSummarySensor",
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
    summary_sensor = PowerClimateSummarySensor(hass, entry)
    assist_summary_sensor = PowerClimateAssistSummarySensor(hass, entry)
    total_power_sensor = PowerClimateTotalPowerSensor(
        hass,
        coordinator,
        entry,
    )

    sensors: list[SensorEntity] = [
        derivative_sensor,
        water_derivative_sensor,
        summary_sensor,
        assist_summary_sensor,
        total_power_sensor,
        PowerClimateTargetTemperatureSensor(hass, entry),
        PowerClimateSupplyCorrectionSensor(hass, entry),
    ]

    sensors.extend(_build_behavior_sensors(hass, entry))

    async_add_entities(sensors)


def _build_behavior_sensors(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> list[SensorEntity]:
    sensors: list[SensorEntity] = []
    config = merged_entry_data(entry)
    devices = config.get(CONF_DEVICES, []) or []
    for index, device in enumerate(devices):
        if not device or not device.get(CONF_CLIMATE_ENTITY):
            continue

        role = f"hp{index + 1}"
        prefix = role
        label = f"HP{index + 1}"
        if device.get(CONF_DEVICE_ROLE) == DEVICE_ROLE_WATER:
            sensors.append(
                PowerClimateHP1BehaviorSensor(
                    hass, entry, role=role, prefix=prefix, label=label
                )
            )
        else:
            sensors.append(
                PowerClimateHPBehaviorSensor(
                    hass,
                    entry,
                    role=role,
                    prefix=prefix,
                    label=label,
                )
            )

    return sensors
