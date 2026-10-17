"""Per-heat-pump mode sensor."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory

from ..const import (
    MODE_BOOST,
    MODE_MINIMAL,
    MODE_OFF,
    MODE_SETPOINT,
    MODE_SUPPLY_ADVICE,
)
from .common import SummaryPayloadSensor


class PowerClimateHeatPumpModeSensor(SummaryPayloadSensor):
    """The mode PowerClimate runs a heat pump in, with its status as attributes."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [MODE_OFF, MODE_MINIMAL, MODE_SETPOINT, MODE_BOOST, MODE_SUPPLY_ADVICE]
    _attr_icon = "mdi:engine-outline"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        *,
        role: str,
        label: str,
    ) -> None:
        """Initialize the heat pump mode sensor."""
        super().__init__(
            hass,
            entry,
            translation_key="hp_mode",
            unique_id_prefix=f"powerclimate_text_{role}_behavior",
        )
        self._role = role
        self._attr_translation_placeholders = {"label": label}

    @property
    def native_value(self) -> str | None:
        return self._hp_entry().get("powerclimate_mode")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {key: value for key, value in self._hp_entry().items() if key != "role"}

    def _hp_entry(self) -> dict[str, Any]:
        for entry in (self._payload or {}).get("hp_status") or []:
            if entry.get("role") == self._role:
                return entry
        return {}
