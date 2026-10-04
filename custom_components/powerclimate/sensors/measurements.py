"""Numeric sensors: derivatives, internal MPC, power budget and total power."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
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
    DOMAIN,
)
from ..helpers import (
    integration_device_info,
    merged_entry_data,
    summary_signal,
)
from ..utils import power_to_watts
from .common import TranslationMixin, snapshot_summary


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


class PowerClimateInternalMPCSensor(CoordinatorEntity, SensorEntity):
    """Diagnostic sensor exposing the internal thermal model state."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = "W/K"
    _attr_icon = "mdi:thermometer-auto"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the internal MPC sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._entry_id = entry.entry_id
        self._attr_unique_id = f"powerclimate_internal_mpc_{entry.entry_id}"
        self._attr_translation_key = "internal_mpc"
        self._attr_has_entity_name = True
        self._attr_device_info = integration_device_info(entry)

    @property
    def native_value(self) -> float | None:
        state = (self.coordinator.data or {}).get("thermal_model_state") or {}
        value = state.get("ua_emitter")
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        state = (self.coordinator.data or {}).get("thermal_model_state") or {}
        outdoor_temp = (self.coordinator.data or {}).get("outdoor_temperature")
        summary = (
            (self.hass.data.get(DOMAIN, {}).get(self._entry_id) or {})
            .get("summary_payload") or {}
        )
        return {
            "ua_emitter": state.get("ua_emitter"),
            "u_building": state.get("u_building"),
            "ua_emitter_updates": state.get("ua_emitter_updates"),
            "u_building_updates": state.get("u_building_updates"),
            "is_converged": state.get("is_converged"),
            "outdoor_temperature": outdoor_temp,
            "thermal_recommended_temp": summary.get("thermal_recommended_temp"),
            "preset_mode": summary.get("preset_mode"),
        }


class PowerClimatePowerBudgetSensor(TranslationMixin, SensorEntity):
    """Diagnostic sensor exposing current Solar preset budgets."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = "W"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:flash"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__()
        TranslationMixin.__init__(self)
        self.hass = hass
        self._entry = entry
        self._entry_id = entry.entry_id
        self._signal = summary_signal(self._entry_id)
        self._unsub = None
        self._attr_translation_key = "power_budget"
        self._attr_unique_id = f"powerclimate_power_budget_{self._entry_id}"
        self._attr_has_entity_name = True
        self._attr_device_info = integration_device_info(entry)
        self._payload: dict[str, Any] | None = snapshot_summary(hass, self._entry_id)

    @property
    def native_value(self) -> float | None:
        payload = self._payload
        if not payload:
            return None
        value = payload.get("power_budget_total_w")
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        payload = self._payload or {}
        return {
            "preset_mode": payload.get("preset_mode"),
            "house_net_power_w": payload.get("house_net_power_w"),
            "power_available_w": payload.get("power_available_w"),
            "power_budget_remaining_w": payload.get("power_budget_remaining_w"),
            "power_budget_by_entity_w": payload.get("power_budget_by_entity_w") or {},
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self._load_strings(self.hass)
        self._payload = snapshot_summary(self.hass, self._entry_id)
        self._unsub = async_dispatcher_connect(
            self.hass,
            self._signal,
            self._handle_summary,
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None
        await super().async_will_remove_from_hass()

    def _handle_summary(self, payload: dict | None) -> None:
        self._payload = payload
        self.schedule_update_ha_state()


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
