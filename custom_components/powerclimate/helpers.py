"""Helper utilities for PowerClimate.

This module provides shared utility functions used across the integration:
- Config entry data merging (data + options)
- Dispatcher signal name generation
- User-friendly entry naming
- Device info creation for HA device registry
- Lightweight translation loading with fallback to English
"""

from __future__ import annotations

import json
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo

from .const import (
    CONF_ENTRY_NAME,
    DEFAULT_ENTRY_NAME,
    DOMAIN,
    MANUFACTURER,
    SUMMARY_SIGNAL_TEMPLATE,
)

_STRING_CACHE: dict[str, dict[str, str]] = {}


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


def _load_strings_from_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}

    # Legacy: some integrations placed translations under a top-level "strings" key.
    strings = data.get("strings") or {}

    # Preferred: translations are namespaced under the integration domain (or another top-level key).
    # Search for a nested "strings" key if top-level isn't present.
    if not strings:
        for v in data.values():
            if isinstance(v, dict) and "strings" in v:
                nested = v.get("strings") or {}
                if isinstance(nested, dict):
                    strings = nested
                    break

    if not isinstance(strings, dict):
        return {}

    return {str(key): str(value) for key, value in strings.items()}


def get_strings(hass: HomeAssistant, language: str | None = None) -> dict[str, str]:
    """Load translated strings for the integration.

    We keep a tiny cache per language and fall back to English if the
    requested language is unavailable.
    """

    lang = (language or hass.config.language or "en").split("-")[0]
    if lang in _STRING_CACHE:
        return _STRING_CACHE[lang]

    translations_dir = Path(
        hass.config.path("custom_components", DOMAIN, "translations")
    )
    if not translations_dir.exists():
        translations_dir = Path(__file__).resolve().parent / "translations"

    strings: dict[str, str] = {}
    for candidate in (lang, "en"):
        strings = _load_strings_from_file(
            translations_dir / f"{candidate}.json"
        )
        if strings:
            break

    _STRING_CACHE[lang] = strings
    return strings


async def async_get_strings(
    hass: HomeAssistant,
    language: str | None = None,
) -> dict[str, str]:
    """Async wrapper around get_strings for use in entities."""

    return await hass.async_add_executor_job(get_strings, hass, language)
