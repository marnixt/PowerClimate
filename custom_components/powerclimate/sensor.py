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
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_change_event,
)
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import (
    CONF_CLIMATE_ENTITY,
    CONF_DEVICE_ROLE,
    CONF_DEVICES,
    CONF_ENERGY_SENSOR,
    COORDINATOR,
    DEVICE_ROLE_WATER,
    DOMAIN,
)
from .helpers import (
    async_get_strings,
    integration_device_info,
    merged_entry_data,
    summary_signal,
)
from .utils import power_to_watts


class _TranslationMixin:
    """Small helper to provide translated fragments with English fallback."""

    def __init__(self) -> None:
        self._strings: dict[str, str] = {}

    async def _load_strings(self, hass: HomeAssistant) -> None:
        self._strings = await async_get_strings(hass)

    def _t(self, key: str, default: str) -> str:
        return str(self._strings.get(key, default))

    def _format_temp_pair(self, label: str, current, target) -> str:
        none_text = self._t("value_none", "none")
        if isinstance(current, (int, float)):
            parts = [f"{label} {current:.1f}°C"]
            if isinstance(target, (int, float)):
                parts.append(f"→{target:.1f}°C")
            return "".join(parts)
        if isinstance(target, (int, float)):
            return f"{label} →{target:.1f}°C"
        return f"{label} {none_text}"

    def _format_eta_fragment(self, eta_hours) -> str:
        label = self._t("label_eta", "ETA")
        none_text = self._t("value_none", "none")
        if not isinstance(eta_hours, (int, float)) or eta_hours <= 0:
            return f"{label} {none_text}"
        if eta_hours >= 1:
            return f"{label} {eta_hours:.1f}h"
        minutes = eta_hours * 60.0
        return f"{label} {minutes:.0f}m" if minutes >= 1 else f"{label} {minutes * 60:.0f}s"

    def _format_derivative_fragment(self, label: str, value) -> str:
        return (
            f"{label} {value:.1f}°C/h"
            if isinstance(value, (int, float))
            else f"{label} {self._t('value_none', 'none')}"
        )

    def _format_power_w(self, value) -> str | None:
        if not isinstance(value, (int, float)):
            return None
        return f"{self._t('label_power', 'Power')} {round(value)} W"

    @staticmethod
    def _short_hp_label(raw_label: object, role: str) -> str:
        text = str(raw_label or "").strip()
        base = text.split()[0][:10] if text else role.upper()
        return f"{base} ({role})"


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


def _snapshot_summary(
    hass: HomeAssistant,
    entry_id: str,
) -> dict[str, Any] | None:
    """Retrieve the current summary payload for a config entry."""
    entry_data = hass.data.get(DOMAIN, {}).get(entry_id)
    if not entry_data:
        return None
    return entry_data.get("summary_payload")


class _SummaryPayloadTextSensor(_TranslationMixin, SensorEntity):
    """Base class for dispatcher-driven summary text sensors."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        *,
        translation_key: str,
        unique_id_prefix: str,
    ) -> None:
        super().__init__()
        _TranslationMixin.__init__(self)
        self.hass = hass
        self._entry = entry
        self._entry_id = entry.entry_id
        self._signal = summary_signal(self._entry_id)
        self._unsub = None
        self._attr_translation_key = translation_key
        self._attr_unique_id = f"{unique_id_prefix}_{self._entry_id}"
        self._attr_has_entity_name = True
        self._attr_device_info = integration_device_info(entry)
        self._value = self._format_payload(_snapshot_summary(hass, self._entry_id))

    @property
    def native_value(self) -> str:
        return self._value

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self._load_strings(self.hass)
        self._value = self._format_payload(
            _snapshot_summary(self.hass, self._entry_id),
        )
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
        self._value = self._format_payload(payload)
        self.schedule_update_ha_state()

    def _format_payload(self, payload: dict | None) -> str:
        raise NotImplementedError


class PowerClimatePowerBudgetSensor(_TranslationMixin, SensorEntity):
    """Diagnostic sensor exposing current Solar preset budgets."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = "W"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:flash"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__()
        _TranslationMixin.__init__(self)
        self.hass = hass
        self._entry = entry
        self._entry_id = entry.entry_id
        self._signal = summary_signal(self._entry_id)
        self._unsub = None
        self._attr_translation_key = "power_budget"
        self._attr_unique_id = f"powerclimate_power_budget_{self._entry_id}"
        self._attr_has_entity_name = True
        self._attr_device_info = integration_device_info(entry)
        self._payload: dict[str, Any] | None = _snapshot_summary(hass, self._entry_id)

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
        self._payload = _snapshot_summary(self.hass, self._entry_id)
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


class PowerClimateThermalSummarySensor(_SummaryPayloadTextSensor):
    """Sensor providing a human-readable thermal summary."""

    _attr_icon = "mdi:radiator"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the thermal summary sensor."""
        super().__init__(
            hass,
            entry,
            translation_key="thermal_summary",
            unique_id_prefix="powerclimate_text_thermal_summary",
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        payload = _snapshot_summary(self.hass, self._entry_id) or {}
        return {
            "hvac_mode": payload.get("hvac_mode"),
            "mode": payload.get("mode"),
            "preset_mode": payload.get("preset_mode"),
            "thermal_is_converged": payload.get("thermal_is_converged"),
            "thermal_ua_emitter": payload.get("thermal_ua_emitter"),
            "thermal_u_building": payload.get("thermal_u_building"),
            "thermal_recommended_temp": payload.get("thermal_recommended_temp"),
        }

    def _format_payload(self, payload: dict | None) -> str:
        return self._format_summary(payload)

    def _format_summary(self, payload: dict | None) -> str:
        if not payload:
            return self._t("unavailable", "unavailable")

        parts: list[str] = []

        # Add HVAC mode
        hvac_mode = str(payload.get("hvac_mode") or "").strip().lower()
        if hvac_mode == "heat":
            hvac_label = self._t("hvac_heat", "Heat")
        elif hvac_mode == "cool":
            hvac_label = self._t("hvac_cool", "Cool")
        elif hvac_mode == "off":
            hvac_label = self._t("hvac_off", "Off")
        else:
            hvac_label = hvac_mode or self._t("hvac_off", "Off")
        mode_key = self._t("label_mode", "Mode")
        parts.append(f"{mode_key}: {hvac_label}")

        # Add preset mode at the beginning
        preset_label = self._t("label_preset", "Preset")
        preset_mode = str(payload.get("preset_mode") or "none").strip().lower()
        if preset_mode == "boost":
            preset_value = self._t("preset_boost", "Boost")
        elif preset_mode == "away":
            preset_value = self._t("preset_away", "Away")
        elif preset_mode == "solar":
            preset_value = self._t("preset_solar", "Solar")
        elif preset_mode == "mpc":
            preset_value = self._t("preset_mpc", "MPC")
        elif preset_mode == "thermal":
            preset_value = self._t("preset_thermal", "Thermal")
        else:
            preset_value = self._t("preset_none", "None")
        parts.append(f"{preset_label}: {preset_value}")

        # Show thermal model state when in thermal preset
        if preset_mode == "thermal":
            thermal_fragment = self._format_thermal_model_info(payload)
            if thermal_fragment:
                parts.append(thermal_fragment)

        avg_fragment = self._format_room_average(
            payload.get("room_sensor_values"),
            payload.get("room_temperature"),
        )
        if avg_fragment:
            parts.append(avg_fragment)

        room_text = self._format_temp_pair(
            self._t("label_room", "Room"),
            payload.get("room_temperature"),
            payload.get("target_temperature"),
        )
        room_derivative = self._format_derivative_fragment(
            self._t("label_derivative", "ΔT"),
            payload.get("derivative"),
        )
        room_eta = self._format_eta_fragment(payload.get("room_eta_hours"))
        parts.append(room_text)
        parts.append(room_derivative)
        parts.append(room_eta)

        # Aggregate power from configured energy sensors
        power_text = self._aggregate_power(payload)
        if power_text:
            parts.append(power_text)

        return " | ".join(parts)

    def _format_thermal_model_info(self, payload: dict) -> str | None:
        """Format thermal model info as a compact fragment."""
        is_converged = payload.get("thermal_is_converged")
        updates = int(payload.get("thermal_ua_emitter_updates") or 0)
        recommended = payload.get("thermal_recommended_temp")
        hvac_mode = str(payload.get("hvac_mode") or "").strip().lower()

        info_parts: list[str] = []
        if is_converged:
            info_parts.append(self._t("thermal_converged", "Converged"))
        else:
            learning_label = self._t("thermal_learning", "Learning")
            info_parts.append(f"{learning_label} ({updates}/10)")

        if isinstance(recommended, (int, float)):
            suggested_label = self._t("label_suggested", "Suggested")
            if hvac_mode == "cool":
                info_parts.append(f"{suggested_label} AC {recommended:.1f}\u00b0C")
            else:
                info_parts.append(f"{suggested_label} supply {recommended:.1f}\u00b0C")

        return " ".join(info_parts) if info_parts else None

    def _aggregate_power(self, payload: dict | None) -> str | None:
        """Aggregate total power from all configured heat pumps."""
        if not payload:
            return None

        config = merged_entry_data(self._entry)
        devices = config.get(CONF_DEVICES, [])
        hp_status = payload.get("hp_status") or []
        energy_by_entity = {
            hp.get("entity_id"): hp.get("energy")
            for hp in hp_status
            if hp.get("entity_id")
        }

        configured_sources = sum(1 for d in devices if d.get(CONF_ENERGY_SENSOR))
        if configured_sources == 0:
            return None

        total = sum(
            float(energy_by_entity[d.get(CONF_CLIMATE_ENTITY)])
            for d in devices
            if d.get(CONF_ENERGY_SENSOR)
            and d.get(CONF_CLIMATE_ENTITY)
            and isinstance(energy_by_entity.get(d.get(CONF_CLIMATE_ENTITY)), (int, float))
        )

        power_label = self._t("label_power", "Power")
        return f"{power_label} {round(total)} W"

    def _format_room_average(
        self,
        readings,
        average,
    ) -> str | None:
        if not readings and not isinstance(average, (int, float)):
            return None

        avg_label = self._t("label_avg_room", "Avg room")
        avg_func = self._t("label_avg_func", "avg")
        none_text = self._t("value_none", "none")

        samples = [
            f"{value:.1f}°C"
            for value in (readings or [])
            if isinstance(value, (int, float))
        ]

        if samples and isinstance(average, (int, float)):
            return f"{avg_label} = {avg_func}({' '.join(samples)}) = {average:.1f}°C"
        if samples:
            return f"{avg_label} = {avg_func}({' '.join(samples)}) = {none_text}"
        if isinstance(average, (int, float)):
            return f"{avg_label} = {average:.1f}°C"
        return f"{avg_label} = {none_text}"


class PowerClimateThermalModelTextSensor(_SummaryPayloadTextSensor):
    """Sensor providing a human-readable description of the internal thermal model state."""

    _attr_icon = "mdi:thermometer-auto"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the thermal model text sensor."""
        super().__init__(
            hass,
            entry,
            translation_key="thermal_model_status",
            unique_id_prefix="powerclimate_text_thermal_model",
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        payload = _snapshot_summary(self.hass, self._entry_id) or {}
        return {
            "ua_emitter": payload.get("thermal_ua_emitter"),
            "u_building": payload.get("thermal_u_building"),
            "ua_emitter_updates": payload.get("thermal_ua_emitter_updates"),
            "u_building_updates": payload.get("thermal_u_building_updates"),
            "is_converged": payload.get("thermal_is_converged"),
            "recommended_temp": payload.get("thermal_recommended_temp"),
            "preset_mode": payload.get("preset_mode"),
            "hvac_mode": payload.get("hvac_mode"),
        }

    def _format_payload(self, payload: dict | None) -> str:
        if not payload:
            return self._t("unavailable", "unavailable")

        parts: list[str] = []

        # Convergence status
        is_converged = payload.get("thermal_is_converged")
        updates = int(payload.get("thermal_ua_emitter_updates") or 0)
        if is_converged:
            parts.append(self._t("thermal_converged", "Converged"))
        else:
            learning_label = self._t("thermal_learning", "Learning")
            parts.append(f"{learning_label} ({updates}/10)")

        # Learned parameters
        ua_emitter = payload.get("thermal_ua_emitter")
        u_building = payload.get("thermal_u_building")
        if isinstance(ua_emitter, (int, float)):
            emitter_label = self._t("label_ua_emitter", "Emitter")
            parts.append(f"{emitter_label} {ua_emitter:.1f} W/K")
        if isinstance(u_building, (int, float)):
            building_label = self._t("label_u_building", "Building")
            parts.append(f"{building_label} {u_building:.1f} W/K")

        # Recommended temperature
        recommended = payload.get("thermal_recommended_temp")
        if isinstance(recommended, (int, float)):
            suggested_label = self._t("label_suggested", "Suggested")
            hvac_mode = str(payload.get("hvac_mode") or "").strip().lower()
            if hvac_mode == "cool":
                parts.append(f"{suggested_label} AC {recommended:.1f}\u00b0C")
            else:
                parts.append(f"{suggested_label} supply {recommended:.1f}\u00b0C")

        return " | ".join(parts)


class PowerClimateThermalRecommendedSensor(_TranslationMixin, SensorEntity):
    """Numeric sensor exposing the thermal model's recommended setpoint."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:thermometer-chevron-up"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the thermal recommended temperature sensor."""
        super().__init__()
        _TranslationMixin.__init__(self)
        self.hass = hass
        self._entry = entry
        self._entry_id = entry.entry_id
        self._signal = summary_signal(self._entry_id)
        self._unsub = None
        self._attr_translation_key = "thermal_advised_temperature"
        self._attr_unique_id = f"powerclimate_thermal_recommended_{self._entry_id}"
        self._attr_has_entity_name = True
        self._attr_device_info = integration_device_info(entry)
        self._payload: dict[str, Any] | None = _snapshot_summary(hass, self._entry_id)

    @property
    def native_value(self) -> float | None:
        payload = self._payload
        if not payload:
            return None
        value = payload.get("thermal_recommended_temp")
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        payload = self._payload or {}
        return {
            "preset_mode": payload.get("preset_mode"),
            "hvac_mode": payload.get("hvac_mode"),
            "ua_emitter": payload.get("thermal_ua_emitter"),
            "u_building": payload.get("thermal_u_building"),
            "is_converged": payload.get("thermal_is_converged"),
            "ua_emitter_updates": payload.get("thermal_ua_emitter_updates"),
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._payload = _snapshot_summary(self.hass, self._entry_id)
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


class PowerClimateAssistSummarySensor(_SummaryPayloadTextSensor):
    """Sensor providing human-readable assist pump control logic summary."""

    _attr_icon = "mdi:timer-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the assist summary sensor."""
        super().__init__(
            hass,
            entry,
            translation_key="assist_summary",
            unique_id_prefix="powerclimate_text_assist_summary",
        )

    def _format_payload(self, payload: dict | None) -> str:
        return self._format_assist_summary(payload)

    def _format_room_state_overview(self, payload: dict) -> list[str]:
        """Format room temperature, derivative, and ETA information."""
        parts: list[str] = []
        room_temp = payload.get("room_temperature")
        target_temp = payload.get("target_temperature")
        derivative = payload.get("derivative")
        eta_hours = payload.get("room_eta_hours")

        if isinstance(room_temp, (int, float)) and isinstance(target_temp, (int, float)):
            delta = room_temp - target_temp
            room_label = self._t("label_room", "Room")
            target_label = self._t("label_target", "target")
            delta_label = self._t("label_delta", "Δ")
            parts.append(
                f"{room_label}: {room_temp:.1f}°C "
                f"({target_label} {target_temp:.1f}°C, {delta_label}{delta:+.1f}°C)"
            )

        if isinstance(derivative, (int, float)):
            trend_label = self._t("label_trend", "Trend")
            if derivative > 0:
                trend = self._t("trend_warming", "warming")
            elif derivative < 0:
                trend = self._t("trend_cooling", "cooling")
            else:
                trend = self._t("trend_stable", "stable")
            parts.append(f"{trend_label}: {trend} ({derivative:+.1f}°C/h)")

        if isinstance(eta_hours, (int, float)) and eta_hours > 0:
            eta_label = self._t("label_eta", "ETA")
            hours_unit = self._t("unit_hours_short", "h")
            minutes_unit = self._t("unit_minutes_short", "min")
            eta_text = (
                f"{eta_hours:.1f}{hours_unit}"
                if eta_hours >= 1
                else f"{int(eta_hours * 60)}{minutes_unit}"
            )
            parts.append(f"{eta_label}: {eta_text}")

        return parts

    def _format_assist_summary(self, payload: dict | None) -> str:
        """Format assist pump control logic into a human-readable summary."""
        if not payload:
            return self._t("unavailable", "unavailable")

        parts = self._format_room_state_overview(payload)

        assist_timer_seconds = payload.get("assist_timer_seconds")
        eta_on_minutes = payload.get("assist_on_eta_threshold_minutes")
        eta_off_minutes = payload.get("assist_off_eta_threshold_minutes")

        condition_labels = self._condition_labels(
            eta_on_minutes,
            eta_off_minutes,
        )
        timer_total_seconds = self._timer_total_seconds(assist_timer_seconds)

        # Assist pump status
        hp_status = payload.get("hp_status", [])
        assist_pumps = [hp for hp in hp_status if hp.get("assist_mode") is not None]

        if not assist_pumps:
            parts.append(self._t("assist_no_pumps", "No assist pumps configured"))
            return " | ".join(parts)

        for hp in assist_pumps:
            raw_label = hp.get("name") or hp.get("role") or "HP"
            role = hp.get("role") or "hp?"
            hp_name = self._short_hp_label(raw_label, role)

            hvac_mode = (hp.get("hvac_mode") or "").lower()
            is_on = hvac_mode != "off"
            allow_control = hp.get("allow_on_off_control", False)

            hp_parts: list[str] = [hp_name]

            # State
            if is_on:
                hp_parts.append(self._t("state_on", "ON"))
            else:
                hp_parts.append(self._t("state_off", "OFF"))

            # Timer information
            if allow_control:
                on_timer = hp.get("on_timer_seconds", 0.0)
                off_timer = hp.get("off_timer_seconds", 0.0)
                condition = hp.get("active_condition", "none")
                blocked_by = str(hp.get("blocked_by") or "").strip()
                target_hvac_mode = str(hp.get("target_hvac_mode") or "").strip().lower()
                target_reason = str(hp.get("target_reason") or "").strip()

                if condition != "none":
                    condition_text = condition_labels.get(condition, condition)

                    if isinstance(on_timer, (int, float)) and on_timer > 0:
                        hp_parts.append(
                            f"{condition_text} "
                            f"ON:{self._format_timer(int(on_timer), int(timer_total_seconds))}"
                        )
                    elif isinstance(off_timer, (int, float)) and off_timer > 0:
                        hp_parts.append(
                            f"{condition_text} "
                            f"OFF:{self._format_timer(int(off_timer), int(timer_total_seconds))}"
                        )
                else:
                    hp_parts.append(self._t("assist_no_condition", "No condition"))

                # Explicitly show when PowerClimate is about to toggle HVAC mode.
                # This is separate from the timer direction above (which is a countdown).
                if target_hvac_mode in {"heat", "off"}:
                    reason_key = target_reason or condition
                    reason_text = (
                        condition_labels.get(reason_key, reason_key)
                        if reason_key
                        else ""
                    )
                    target_text = (
                        self._t("assist_target_on", "TargetON")
                        if target_hvac_mode == "heat"
                        else self._t("assist_target_off", "TargetOFF")
                    )
                    if reason_text:
                        hp_parts.append(f"{target_text}({reason_text})")
                    else:
                        hp_parts.append(target_text)

                if blocked_by:
                    blocked_label = self._t("assist_blocked", "Blocked")
                    hp_parts.append(f"{blocked_label}({blocked_by})")
            else:
                hp_parts.append(self._t("assist_manual_control", "Manual control"))

            parts.append(" ".join(hp_parts))

        return " | ".join(parts)

    @staticmethod
    def _timer_total_seconds(value) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        return 300.0

    def _condition_labels(self, eta_on_minutes, eta_off_minutes) -> dict[str, str]:
        return {
            "eta_high": (
                f"ETA>{int(eta_on_minutes)}m"
                if isinstance(eta_on_minutes, (int, float))
                else self._t("assist_condition_eta_high", "ETA high")
            ),
            "water_hot": self._t(
                "assist_condition_water_hot",
                "Water≥40°C",
            ),
            "stalled_below_target": self._t(
                "assist_condition_stalled_below_target",
                "Stalled",
            ),
            "eta_low": (
                f"ETA<{int(eta_off_minutes)}m"
                if isinstance(eta_off_minutes, (int, float))
                else self._t("assist_condition_eta_low", "ETA low")
            ),
            "stalled_at_target": self._t(
                "assist_condition_stalled_at_target",
                "At target",
            ),
            "overshoot": self._t(
                "assist_condition_overshoot",
                "Overshoot",
            ),
        }

    @staticmethod
    def _format_timer(elapsed_seconds: int, total_seconds: int) -> str:
        elapsed_seconds = max(0, int(elapsed_seconds))
        total_seconds = max(0, int(total_seconds))

        timer_min = int(elapsed_seconds // 60)
        timer_sec = int(elapsed_seconds % 60)
        total_min = int(total_seconds // 60)
        total_sec = int(total_seconds % 60)
        return f"{timer_min}:{timer_sec:02d}/{total_min}:{total_sec:02d}"


class _AssistBehaviorFormatter(_TranslationMixin):
    def __init__(self) -> None:
        super().__init__()

    def _format_hp_snapshot(self, label: str, entry: dict | None) -> list[str]:
        none_text = self._t("value_none", "none")
        if not entry:
            return [f"{label} {self._t('hp_not_configured', 'not configured')}"]
        parts: list[str] = []
        state_active = self._t("state_active", "active")
        state_idle = self._t("state_idle", "idle")
        parts.append(
            f"{label} {state_active if entry.get('active') else state_idle}"
        )
        hvac = (entry.get("hvac_mode") or self._t("value_unknown", "unknown")).upper()
        parts.append(f"{self._t('label_hvac', 'HVAC')} {hvac}")

        # Format temperature with optional (Boost) indicator
        temp_text = self._format_temp_pair(
            self._t("label_temps", "Temps"),
            entry.get("current_temperature"),
            entry.get("target_temperature"),
        )
        # Add (Boost) indicator if boost preset is active in payload
        payload = getattr(self, "_payload", None)
        if payload and payload.get("preset_mode") == "boost":
            temp_text = f"{temp_text} ({self._t('preset_boost', 'Boost')})"
        parts.append(temp_text)
        parts.append(
            self._format_derivative_fragment(
                self._t("label_derivative", "ΔT"),
                entry.get("temperature_derivative"),
            )
        )
        parts.append(self._format_eta_fragment(entry.get("eta_hours")))
        water_temp = entry.get("water_temperature")
        if isinstance(water_temp, (int, float)):
            water_label = self._t("label_water", "Water")
            parts.append(f"{water_label} {water_temp:.1f}°C")
        power_text = self._format_power_w(entry.get("energy"))
        if power_text:
            parts.append(power_text)
        if not parts:
            parts.append(none_text)
        return parts


class _AssistBehaviorSensor(_AssistBehaviorFormatter, SensorEntity):
    """Base class for heat pump behavior sensors."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:engine-outline"
    _is_water_device = False

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        role: str,
        prefix: str,
        label: str,
    ) -> None:
        """Initialize the assist behavior sensor."""
        super().__init__()
        self.hass = hass
        self._entry = entry
        self._entry_id = entry.entry_id
        self._role = role
        self._label = label
        self._prefix = prefix
        self._signal = summary_signal(self._entry_id)
        self._unsub = None
        self._payload: dict | None = None
        self._hp_entry: dict | None = None
        self._value = self._format_payload(
            _snapshot_summary(hass, self._entry_id),
        )
        self._attr_unique_id = (
            f"powerclimate_text_{prefix}_behavior_{self._entry_id}"
        )
        self._attr_translation_key = "hp_behavior"
        self._attr_translation_placeholders = {"label": label}
        self._attr_has_entity_name = True
        self._attr_device_info = integration_device_info(entry)

    @property
    def native_value(self) -> str:
        return self._value

    @property
    def extra_state_attributes(self) -> dict:
        entry = self._hp_entry or {}
        attrs: dict[str, Any] = {
            f"{self._prefix}_assist_mode": entry.get("assist_mode"),
            f"{self._prefix}_hvac_mode": entry.get("hvac_mode"),
            f"{self._prefix}_powerclimate_mode": entry.get("powerclimate_mode"),
            f"{self._prefix}_active": entry.get("active"),
            f"{self._prefix}_current_temperature": entry.get(
                "current_temperature",
            ),
            f"{self._prefix}_target_temperature": entry.get(
                "target_temperature",
            ),
            f"{self._prefix}_temperature_derivative": entry.get(
                "temperature_derivative",
            ),
            f"{self._prefix}_water_temperature": entry.get(
                "water_temperature",
            ),
            f"{self._prefix}_water_derivative": entry.get(
                "water_derivative",
            ),
        }
        energy = entry.get("energy")
        attrs[f"{self._prefix}_power_w"] = (
            round(energy)
            if isinstance(energy, (int, float))
            else None
        )
        return attrs

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self._load_strings(self.hass)
        self._value = self._format_payload(
            _snapshot_summary(self.hass, self._entry_id),
        )
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
        self._value = self._format_payload(payload)
        self.schedule_update_ha_state()

    def _format_payload(self, payload: dict | None) -> str:
        if not payload:
            self._payload = None
            self._hp_entry = None
            return self._t("unavailable", "unavailable")

        self._payload = payload
        hp_entry = self._find_hp_entry(payload, self._role)
        self._hp_entry = hp_entry
        if not hp_entry:
            return "{label} {status}".format(
                label=self._label,
                status=self._t("hp_not_configured", "not configured"),
            )

        parts: list[str] = []
        label = self._label_from_hp(hp_entry, self._label, self._role)
        parts.extend(self._format_hp_snapshot(label, hp_entry))
        # For HP1 we want to show water ΔT before power. Remove any existing
        # power fragment produced by the generic snapshot and then append
        # sensor-specific parts which will include water ΔT and power (if any).
        if self._is_water_device:
            power_prefix = f"{self._t('label_power', 'Power')} "
            parts = [p for p in parts if not p.startswith(power_prefix)]

        parts.extend(self._sensor_specific_parts(hp_entry))
        return " | ".join(parts)

    @staticmethod
    def _find_hp_entry(payload: dict, role: str) -> dict | None:
        for entry in payload.get("hp_status") or []:
            if entry.get("role") == role:
                return entry
        return None

    @staticmethod
    def _label_from_hp(entry: dict, fallback: str, role: str) -> str:
        raw_label = entry.get("name") or fallback or role.upper()
        return _TranslationMixin._short_hp_label(raw_label, role)

    def _sensor_specific_parts(self, entry: dict) -> list[str]:
        parts: list[str] = []
        # Add PowerClimate mode if present
        mode = entry.get("powerclimate_mode")
        if mode:
            mode_label = self._t("label_mode", "Mode")
            parts.append(f"{mode_label}: {mode}")
        # Show thermal recommended temp when in thermal MPC mode
        if mode == "thermal_mpc":
            payload = self._payload or {}
            recommended = payload.get("thermal_recommended_temp")
            if isinstance(recommended, (int, float)):
                suggested_label = self._t("label_suggested", "Suggested")
                parts.append(f"{suggested_label} {recommended:.1f}\u00b0C")
        return parts


class PowerClimateHPBehaviorSensor(_AssistBehaviorSensor):
    """Sensor showing HP2+ assist behavior status (parameterized)."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        role: str,
        prefix: str,
        label: str,
    ) -> None:
        super().__init__(
            hass,
            entry,
            role=role,
            prefix=prefix,
            label=label,
        )


class PowerClimateHP1BehaviorSensor(_AssistBehaviorSensor):
    """Sensor showing water heat pump behavior with water temperature."""

    _is_water_device = True

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        role: str = "hp1",
        prefix: str = "hp1",
        label: str = "HP1",
    ) -> None:
        """Initialize the water heat pump behavior sensor."""
        super().__init__(
            hass,
            entry,
            role=role,
            prefix=prefix,
            label=label,
        )

    def _sensor_specific_parts(self, entry: dict) -> list[str]:
        parts: list[str] = []
        # Add PowerClimate mode if present
        mode = entry.get("powerclimate_mode")
        if mode:
            mode_label = self._t("label_mode", "Mode")
            parts.append(f"{mode_label}: {mode}")

        # Show thermal recommended temp when in thermal MPC mode
        if mode == "thermal_mpc":
            payload = self._payload or {}
            recommended = payload.get("thermal_recommended_temp")
            if isinstance(recommended, (int, float)):
                suggested_label = self._t("label_suggested", "Suggested")
                parts.append(f"{suggested_label} {recommended:.1f}°C")

        water_label = self._t("label_water", "Water")
        d_label = self._t("label_derivative", "ΔT")
        parts.append(
            self._format_derivative_fragment(
                f"{water_label} {d_label}",
                entry.get("water_derivative"),
            )
        )

        power_text = self._format_power_w(entry.get("energy"))
        if power_text:
            parts.append(power_text)

        return parts


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
