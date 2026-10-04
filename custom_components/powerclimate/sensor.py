"""Diagnostic sensors for PowerClimate.

This module provides diagnostic sensor entities that expose internal state
and calculations from the PowerClimate integration:

- **Temperature Derivative**: Rate of room temperature change (°C/hour)
- **Water Derivative**: Rate of water temperature change (°C/hour)
- **Thermal Summary**: Human-readable summary of system state
- **Assist Behavior**: Simple per-stage view showing HVAC state and assist mode
- **Total Power**: Aggregated power consumption from all configured heat pumps

All sensors are marked as diagnostic entities and grouped under the
integration's virtual device in the Home Assistant device registry.
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
    PowerClimateInternalMPCSensor,
    PowerClimatePowerBudgetSensor,
    PowerClimateTotalPowerSensor,
    PowerClimateWaterDerivativeSensor,
)
from .sensors.thermal import (
    PowerClimateThermalModelTextSensor,
    PowerClimateThermalRecommendedSensor,
    PowerClimateThermalSummarySensor,
)

__all__ = [
    "PowerClimateAssistSummarySensor",
    "PowerClimateDerivativeSensor",
    "PowerClimateHP1BehaviorSensor",
    "PowerClimateHPBehaviorSensor",
    "PowerClimateInternalMPCSensor",
    "PowerClimatePowerBudgetSensor",
    "PowerClimateThermalModelTextSensor",
    "PowerClimateThermalRecommendedSensor",
    "PowerClimateThermalSummarySensor",
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
    thermal_summary_sensor = PowerClimateThermalSummarySensor(hass, entry)
    assist_summary_sensor = PowerClimateAssistSummarySensor(hass, entry)
    total_power_sensor = PowerClimateTotalPowerSensor(
        hass,
        coordinator,
        entry,
    )
    power_budget_sensor = PowerClimatePowerBudgetSensor(hass, entry)
    internal_mpc_sensor = PowerClimateInternalMPCSensor(coordinator, entry)
    thermal_model_text_sensor = PowerClimateThermalModelTextSensor(hass, entry)
    thermal_recommended_sensor = PowerClimateThermalRecommendedSensor(hass, entry)

    sensors: list[SensorEntity] = [
        derivative_sensor,
        water_derivative_sensor,
        thermal_summary_sensor,
        assist_summary_sensor,
        total_power_sensor,
        power_budget_sensor,
        internal_mpc_sensor,
        thermal_model_text_sensor,
        thermal_recommended_sensor,
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
