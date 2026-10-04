"""Diagnostics support for PowerClimate.

Collects the configuration, the latest coordinator data and the internal
control state of an entry for the "Download diagnostics" button. The
configuration only holds entity IDs and numbers, so nothing is redacted.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import COORDINATOR, DOMAIN


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    coordinator = data.get(COORDINATOR)
    climate_entity = data.get("climate_entity")

    diagnostics: dict[str, Any] = {
        "entry": {
            "title": entry.title,
            "version": entry.version,
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "coordinator": None,
        "climate": None,
        "thermal_model": None,
    }

    if coordinator is not None:
        diagnostics["coordinator"] = {
            "last_update_success": coordinator.last_update_success,
            "data": coordinator.data,
        }
        diagnostics["thermal_model"] = coordinator.thermal_model.to_dict()

    if climate_entity is not None:
        state = (
            hass.states.get(climate_entity.entity_id)
            if climate_entity.entity_id
            else None
        )
        diagnostics["climate"] = {
            "entity_id": climate_entity.entity_id,
            "state": state.state if state else None,
            "attributes": dict(state.attributes) if state else None,
            **climate_entity.diagnostics(),
        }

    return diagnostics
