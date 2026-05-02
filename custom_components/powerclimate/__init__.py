"""PowerClimate - Multi-heat-pump orchestration for Home Assistant.

This integration provides intelligent coordination of multiple heat pumps
(air-to-water or similar) around a shared hydronic system. It exposes:

- A central climate entity representing the combined system
- Diagnostic sensors for temperature derivatives and system state
- Automatic assist logic for HP2, HP3, etc. based on room demand

Key features:
- HP1 (primary water-based heat pump) HVAC mode is controlled by PowerClimate
- Assist pumps (HP2+) remain under user HVAC control; only setpoints adjust
- Per-device temperature offsets for minimal and setpoint modes
- Room demand-based mode switching (minimal vs setpoint mode)
- Absolute setpoint guardrails between 16-30°C
- Power mode: steer heat pump to match a power budget

See README.md for detailed documentation of the control algorithm.
"""

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_CLIMATE_ENTITY,
    CONF_DEVICES,
    COORDINATOR,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import OSDataUpdateCoordinator
from .helpers import merged_entry_data

LOGGER = logging.getLogger(__name__)

# Service names
SERVICE_SET_POWER_BUDGET = "set_power_budget"
SERVICE_CLEAR_POWER_BUDGET = "clear_power_budget"

# Service schema
SERVICE_SET_POWER_BUDGET_SCHEMA = vol.Schema({
    vol.Required("entity_id"): cv.entity_id,
    vol.Required("power_watts"): vol.Coerce(float),
})

SERVICE_CLEAR_POWER_BUDGET_SCHEMA = vol.Schema({
    vol.Required("entity_id"): cv.entity_id,
})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the integration from a config entry.

    Creates the data coordinator and forwards setup to platform modules
    (climate, sensor).

    Args:
        hass: Home Assistant instance.
        entry: Config entry being set up.

    Returns:
        True if setup succeeded.
    """
    hass.data.setdefault(DOMAIN, {})

    coordinator = OSDataUpdateCoordinator(hass, entry, LOGGER)

    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        COORDINATOR: coordinator,
        "entry": entry,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services (only once, on first entry)
    if not hass.services.has_service(DOMAIN, SERVICE_SET_POWER_BUDGET):
        await _async_register_services(hass)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def _async_register_services(hass: HomeAssistant) -> None:
    """Register PowerClimate services."""

    def resolve_climate_entity(target_entity_id: str):
        """Resolve the climate entity that owns a controlled device."""
        matches = []
        all_entities = []

        for data in hass.data.get(DOMAIN, {}).values():
            climate_entity = data.get("climate_entity")
            if climate_entity is None:
                continue

            all_entities.append(climate_entity)

            entry = data.get("entry")
            if entry is None:
                continue

            devices = merged_entry_data(entry).get(CONF_DEVICES) or []
            if any(
                str(device.get(CONF_CLIMATE_ENTITY) or "").strip() == target_entity_id
                for device in devices
            ):
                matches.append(climate_entity)

        if len(matches) == 1:
            return matches[0]

        if len(matches) > 1:
            LOGGER.warning(
                "Multiple PowerClimate entries manage %s; service call is ambiguous",
                target_entity_id,
            )
            return None

        if len(all_entities) == 1:
            return all_entities[0]

        return None

    async def handle_set_power_budget(call: ServiceCall) -> None:
        """Handle set_power_budget service call."""
        entity_id = str(call.data["entity_id"]).strip()
        power_watts = call.data["power_watts"]

        climate_entity = resolve_climate_entity(entity_id)
        if climate_entity is None:
            LOGGER.warning(
                "No PowerClimate climate entity found for power budget target %s",
                entity_id,
            )
            return

        climate_entity.set_power_budget(entity_id, power_watts)
        LOGGER.info(
            "Power budget set for %s: %.0f W via service",
            entity_id,
            power_watts,
        )

    async def handle_clear_power_budget(call: ServiceCall) -> None:
        """Handle clear_power_budget service call."""
        entity_id = str(call.data["entity_id"]).strip()

        climate_entity = resolve_climate_entity(entity_id)
        if climate_entity is None:
            LOGGER.warning(
                "No PowerClimate climate entity found for power budget target %s",
                entity_id,
            )
            return

        climate_entity.clear_power_budget(entity_id)
        LOGGER.info("Power budget cleared for %s via service", entity_id)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_POWER_BUDGET,
        handle_set_power_budget,
        schema=SERVICE_SET_POWER_BUDGET_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_CLEAR_POWER_BUDGET,
        handle_clear_power_budget,
        schema=SERVICE_CLEAR_POWER_BUDGET_SCHEMA,
    )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.

    Cleans up platforms and removes integration data from hass.data.

    Args:
        hass: Home Assistant instance.
        entry: Config entry being unloaded.

    Returns:
        True if unload succeeded.
    """
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry,
        PLATFORMS,
    )
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle config entry reloads when options change.

    Args:
        hass: Home Assistant instance.
        entry: Config entry being reloaded.
    """
    await hass.config_entries.async_reload(entry.entry_id)
