"""Shared building blocks for the PowerClimate sensors."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from ..const import (
    DOMAIN,
)
from ..helpers import (
    integration_device_info,
    summary_signal,
)


def snapshot_summary(
    hass: HomeAssistant,
    entry_id: str,
) -> dict[str, Any] | None:
    """Retrieve the current summary payload for a config entry."""
    entry_data = hass.data.get(DOMAIN, {}).get(entry_id)
    if not entry_data:
        return None
    return entry_data.get("summary_payload")


class SummaryPayloadSensor(SensorEntity):
    """Base class for sensors fed by the climate entity's summary payload."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        *,
        translation_key: str,
        unique_id_prefix: str,
    ) -> None:
        super().__init__()
        self.hass = hass
        self._entry = entry
        self._entry_id = entry.entry_id
        self._signal = summary_signal(self._entry_id)
        self._unsub = None
        self._attr_translation_key = translation_key
        self._attr_unique_id = f"{unique_id_prefix}_{self._entry_id}"
        self._attr_device_info = integration_device_info(entry)
        self._payload: dict[str, Any] | None = snapshot_summary(hass, self._entry_id)

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


class SummaryPayloadValueSensor(SummaryPayloadSensor):
    """Sensor showing one numeric value of the summary payload."""

    _payload_key: str

    @property
    def native_value(self) -> float | None:
        value = (self._payload or {}).get(self._payload_key)
        return float(value) if isinstance(value, (int, float)) else None
