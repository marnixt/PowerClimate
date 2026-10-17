"""Human-readable summary sensor."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from ..const import (
    CONF_CLIMATE_ENTITY,
    CONF_DEVICES,
    CONF_ENERGY_SENSOR,
)
from ..helpers import (
    merged_entry_data,
)
from .common import SummaryPayloadTextSensor, snapshot_summary


class PowerClimateSummarySensor(SummaryPayloadTextSensor):
    """Sensor providing a human-readable summary of the system state."""

    _attr_icon = "mdi:radiator"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the summary sensor."""
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
        elif preset_mode == "main_only":
            preset_value = self._t("preset_main_only", "Main only")
        elif preset_mode == "mpc":
            preset_value = self._t("preset_mpc", "MPC")
        else:
            preset_value = self._t("preset_none", "None")
        parts.append(f"{preset_label}: {preset_value}")

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

