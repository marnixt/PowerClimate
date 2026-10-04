"""Thermal summary, thermal model and advised temperature sensors."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory

from ..const import (
    CONF_CLIMATE_ENTITY,
    CONF_DEVICES,
    CONF_ENERGY_SENSOR,
)
from ..helpers import (
    integration_device_info,
    merged_entry_data,
    summary_signal,
)
from .common import SummaryPayloadTextSensor, TranslationMixin, snapshot_summary


class PowerClimateThermalSummarySensor(SummaryPayloadTextSensor):
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
        payload = snapshot_summary(self.hass, self._entry_id) or {}
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


class PowerClimateThermalModelTextSensor(SummaryPayloadTextSensor):
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
        payload = snapshot_summary(self.hass, self._entry_id) or {}
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


class PowerClimateThermalRecommendedSensor(TranslationMixin, SensorEntity):
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
        TranslationMixin.__init__(self)
        self.hass = hass
        self._entry = entry
        self._entry_id = entry.entry_id
        self._signal = summary_signal(self._entry_id)
        self._unsub = None
        self._attr_translation_key = "thermal_advised_temperature"
        self._attr_unique_id = f"powerclimate_thermal_recommended_{self._entry_id}"
        self._attr_has_entity_name = True
        self._attr_device_info = integration_device_info(entry)
        self._payload: dict[str, Any] | None = snapshot_summary(hass, self._entry_id)

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
