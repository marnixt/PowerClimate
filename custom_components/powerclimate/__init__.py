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

See README.md for detailed documentation of the control algorithm.
"""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    COORDINATOR,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import OSDataUpdateCoordinator
from .thermal_model import STORAGE_VERSION as THERMAL_STORAGE_VERSION
from .thermal_model import storage_key as thermal_storage_key
from .timer_storage import STORAGE_VERSION as TIMER_STORAGE_VERSION
from .timer_storage import storage_key as timer_storage_key

LOGGER = logging.getLogger(__name__)


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
    await coordinator.async_setup()

    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        COORDINATOR: coordinator,
        "entry": entry,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


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
        entry_data = hass.data[DOMAIN].pop(entry.entry_id)
        await entry_data[COORDINATOR].thermal_model.async_save()
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove persisted state when a config entry is deleted."""
    await Store(hass, TIMER_STORAGE_VERSION, timer_storage_key(entry.entry_id)).async_remove()
    await Store(
        hass, THERMAL_STORAGE_VERSION, thermal_storage_key(entry.entry_id)
    ).async_remove()


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle config entry reloads when options change.

    Args:
        hass: Home Assistant instance.
        entry: Config entry being reloaded.
    """
    await hass.config_entries.async_reload(entry.entry_id)
