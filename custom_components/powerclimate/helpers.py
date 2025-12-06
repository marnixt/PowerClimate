"""Helper utilities for PowerClimate.

This module provides shared utility functions used across the integration:
- Config entry data merging (data + options)
- Dispatcher signal name generation
- User-friendly entry naming
- Device info creation for HA device registry
"""

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo

from .const import (
    CONF_ENTRY_NAME,
    DEFAULT_ENTRY_NAME,
    DOMAIN,
    MANUFACTURER,
    SUMMARY_SIGNAL_TEMPLATE,
)


def merged_entry_data(entry: ConfigEntry) -> dict:
    """Combine entry data and options, with options taking precedence.

    Args:
        entry: The config entry to merge data from.

    Returns:
        Dictionary with entry.data overwritten by entry.options.
    """
    combined = dict(entry.data)
    combined.update(entry.options)
    return combined


def summary_signal(entry_id: str) -> str:
    """Return dispatcher signal name for summary updates.

    Args:
        entry_id: Unique ID of the config entry.

    Returns:
        Formatted signal string for async_dispatcher_send/connect.
    """
    return SUMMARY_SIGNAL_TEMPLATE.format(entry_id=entry_id)


def entry_friendly_name(entry: ConfigEntry) -> str:
    """Derive the user-visible name for a config entry.

    Preference order:
    1. entry.title (set during config flow)
    2. CONF_ENTRY_NAME from entry.data
    3. DEFAULT_ENTRY_NAME fallback

    Args:
        entry: The config entry to get name from.

    Returns:
        Human-readable name for the integration instance.
    """
    return (
        entry.title
        or entry.data.get(CONF_ENTRY_NAME)
        or DEFAULT_ENTRY_NAME
    )


def integration_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Build DeviceInfo shared by all entities of a config entry.

    Creates a virtual device in the HA device registry that groups
    all entities created by this integration instance.

    Args:
        entry: The config entry to create device info for.

    Returns:
        DeviceInfo dict for entity registration.
    """
    friendly_name = entry_friendly_name(entry)
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=friendly_name,
        manufacturer=MANUFACTURER,
        model="PowerClimate",
    )
