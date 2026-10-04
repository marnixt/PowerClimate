"""Shared building blocks for the PowerClimate sensors."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory

from ..const import (
    DOMAIN,
)
from ..helpers import (
    async_get_strings,
    integration_device_info,
    summary_signal,
)


class TranslationMixin:
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


def snapshot_summary(
    hass: HomeAssistant,
    entry_id: str,
) -> dict[str, Any] | None:
    """Retrieve the current summary payload for a config entry."""
    entry_data = hass.data.get(DOMAIN, {}).get(entry_id)
    if not entry_data:
        return None
    return entry_data.get("summary_payload")


class SummaryPayloadTextSensor(TranslationMixin, SensorEntity):
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
        TranslationMixin.__init__(self)
        self.hass = hass
        self._entry = entry
        self._entry_id = entry.entry_id
        self._signal = summary_signal(self._entry_id)
        self._unsub = None
        self._attr_translation_key = translation_key
        self._attr_unique_id = f"{unique_id_prefix}_{self._entry_id}"
        self._attr_has_entity_name = True
        self._attr_device_info = integration_device_info(entry)
        self._value = self._format_payload(snapshot_summary(hass, self._entry_id))

    @property
    def native_value(self) -> str:
        return self._value

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self._load_strings(self.hass)
        self._value = self._format_payload(
            snapshot_summary(self.hass, self._entry_id),
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
