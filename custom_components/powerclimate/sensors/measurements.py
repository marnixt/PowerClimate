"""Numeric sensors: derivatives, supply control, target and total power."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.event import (
    async_track_state_change_event,
)
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from ..const import (
    CONF_DEVICES,
    CONF_ENERGY_SENSOR,
)
from ..helpers import (
    integration_device_info,
    merged_entry_data,
)
from ..utils import power_to_watts
from .common import SummaryPayloadValueSensor

SUPPLY_PI_ATTRIBUTES = (
    "supply_pi_active",
    "supply_pi_source",
    "supply_pi_advised_temp",
    "supply_pi_supply_temp",
    "supply_pi_supply_filtered",
    "supply_pi_spike",
    "supply_pi_error",
    "supply_pi_p",
    "supply_pi_i",
    "supply_pi_integrating",
    "supply_pi_saturated",
)


class PowerClimateTargetTemperatureSensor(SummaryPayloadValueSensor):
    """PowerClimate's room target temperature as a sensor.

    Other integrations that only accept a sensor (for example an external MPC
    source that needs the comfort target) can read the target from here
    instead of from a thermostat whose setpoint PowerClimate itself moves.
    """

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:home-thermometer-outline"
    _payload_key = "target_temperature"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the target temperature sensor."""
        super().__init__(
            hass,
            entry,
            translation_key="target_temperature",
            unique_id_prefix="powerclimate_target_temperature",
        )


class PowerClimateSupplyCorrectionSensor(SummaryPayloadValueSensor):
    """Correction the supply-temperature controller applies (MPC preset)."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:thermometer-plus"
    _payload_key = "supply_pi_correction"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the supply correction sensor."""
        super().__init__(
            hass,
            entry,
            translation_key="supply_correction",
            unique_id_prefix="powerclimate_supply_correction",
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        payload = self._payload or {}
        return {key: payload.get(key) for key in SUPPLY_PI_ATTRIBUTES}


class PowerClimateDerivativeSensor(CoordinatorEntity, SensorEntity):
    """Sensor tracking room temperature change rate."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = "°C/h"
    _attr_icon = "mdi:chart-line"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the derivative sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"powerclimate_derivative_{entry.entry_id}"
        self._attr_translation_key = "temperature_derivative"
        self._attr_has_entity_name = True
        self._attr_device_info = integration_device_info(entry)

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.get("room_derivative")


class PowerClimateWaterDerivativeSensor(CoordinatorEntity, SensorEntity):
    """Sensor tracking water temperature change rate."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = "°C/h"
    _attr_icon = "mdi:chart-line"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the water derivative sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = (
            f"powerclimate_water_derivative_{entry.entry_id}"
        )
        self._attr_translation_key = "water_derivative"
        self._attr_has_entity_name = True
        self._attr_device_info = integration_device_info(entry)

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.get("water_derivative")


class PowerClimateTotalPowerSensor(CoordinatorEntity, SensorEntity):
    """Sensor aggregating power consumption from all configured heat pumps."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:flash"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: DataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the total power sensor."""
        super().__init__(coordinator)
        self.hass = hass
        self._entry = entry
        self._attr_translation_key = "total_power"
        self._attr_unique_id = f"powerclimate_total_power_{entry.entry_id}"
        self._attr_extra_state_attributes = {}
        self._energy_sensors = self._configured_energy_sensors()
        self._sensor_unsubs: list[Callable[[], None]] = []
        self._attr_has_entity_name = True
        self._attr_device_info = integration_device_info(entry)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._recalculate()
        if self._energy_sensors:
            self._sensor_unsubs.append(
                async_track_state_change_event(
                    self.hass,
                    self._energy_sensors,
                    self._handle_energy_change,
                )
            )

    async def async_will_remove_from_hass(self) -> None:
        for unsub in self._sensor_unsubs:
            unsub()
        self._sensor_unsubs.clear()
        await super().async_will_remove_from_hass()

    @callback
    def _handle_energy_change(self, event) -> None:
        self._recalculate()
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._recalculate()
        super()._handle_coordinator_update()

    def _recalculate(self) -> None:
        """Recompute the total and attributes from the source sensors."""
        total = 0.0
        active_sources = 0
        missing_sources: list[str] = []
        contributions: list[dict[str, object]] = []

        for sensor_id in self._energy_sensors:
            value = self._read_sensor_watts(sensor_id)
            if value is None:
                missing_sources.append(sensor_id)
                continue
            power = round(value)
            total += power
            active_sources += 1
            contributions.append({"sensor": sensor_id, "value": power})

        attributes: dict[str, object] = {
            "source_count": len(self._energy_sensors),
            "active_sources": active_sources,
        }
        if missing_sources:
            attributes["missing_sources"] = missing_sources
        if contributions:
            attributes["sources"] = contributions
        self._attr_extra_state_attributes = attributes

        if not self._energy_sensors:
            self._attr_native_value = None
        else:
            self._attr_native_value = round(total) if active_sources else 0.0

    def _configured_energy_sensors(self) -> list[str]:
        config = merged_entry_data(self._entry)
        return [
            device[CONF_ENERGY_SENSOR]
            for device in config.get(CONF_DEVICES, [])
            if device.get(CONF_ENERGY_SENSOR)
        ]

    def _read_sensor_watts(self, sensor_id: str) -> float | None:
        """Read a power sensor in watts, converting kW sources."""
        state = self.hass.states.get(sensor_id)
        if not state or state.state in (None, "unknown", "unavailable"):
            return None
        return power_to_watts(state.state, state.attributes.get("unit_of_measurement"))
