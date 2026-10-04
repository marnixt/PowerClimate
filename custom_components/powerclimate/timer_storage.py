"""Persistent timer storage for PowerClimate.

This module provides persistent storage for assist pump timer states,
ensuring that timer data survives Home Assistant restarts.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.storage import Store

from .models import AssistTimerState

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY_TEMPLATE = "powerclimate_timers_{entry_id}"


def _datetime_to_iso(dt: datetime | None) -> str | None:
    """Convert datetime to ISO string."""
    if dt is None:
        return None
    return dt.isoformat()


def _iso_to_datetime(iso_str: str | None) -> datetime | None:
    """Convert ISO string to datetime."""
    if iso_str is None:
        return None
    try:
        return datetime.fromisoformat(iso_str)
    except (TypeError, ValueError):
        return None


def storage_key(entry_id: str) -> str:
    """Return the Store key used for an entry's timer state."""
    return STORAGE_KEY_TEMPLATE.format(entry_id=entry_id)


class TimerStorage:
    """Persistent storage for assist pump timer states.

    Uses Home Assistant's Store helper (atomic writes in ``.storage``) so that
    timer progress is preserved across restarts.
    """

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the timer storage.

        Args:
            hass: Home Assistant instance.
            entry_id: Config entry ID for namespacing.
        """
        self._entry_id = entry_id
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, storage_key(entry_id)
        )

    async def async_load(self) -> dict[str, AssistTimerState]:
        """Load timer states from storage.

        Returns:
            Dictionary mapping entity_id to AssistTimerState.
        """
        try:
            data = await self._store.async_load()
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.warning("Failed to load timer storage: %s", err)
            return {}

        if not isinstance(data, dict):
            return {}

        states = self._deserialize_states(data.get("timers") or {})
        _LOGGER.debug(
            "Loaded %d timer states from storage for entry %s",
            len(states),
            self._entry_id,
        )
        return states

    async def async_save(self, states: dict[str, AssistTimerState]) -> None:
        """Save timer states to storage.

        Args:
            states: Dictionary mapping entity_id to AssistTimerState.
        """
        try:
            await self._store.async_save({"timers": self._serialize_states(states)})
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.warning("Failed to save timer storage: %s", err)

    async def async_remove(self) -> None:
        """Remove the storage file."""
        await self._store.async_remove()

    def _serialize_states(
        self, states: dict[str, AssistTimerState]
    ) -> dict[str, dict[str, Any]]:
        """Serialize timer states to JSON-compatible format."""
        result: dict[str, dict[str, Any]] = {}
        for entity_id, state in states.items():
            result[entity_id] = {
                "on_timer_seconds": state.on_timer_seconds,
                "off_timer_seconds": state.off_timer_seconds,
                "active_condition": state.active_condition,
                "running_state": state.running_state,
                "last_on": _datetime_to_iso(state.last_on),
                "last_off": _datetime_to_iso(state.last_off),
                "block_reason": state.block_reason,
                "target_hvac_mode": state.target_hvac_mode,
                "target_reason": state.target_reason,
            }
        return result

    def _deserialize_states(
        self, data: dict[str, dict[str, Any]]
    ) -> dict[str, AssistTimerState]:
        """Deserialize timer states from JSON format."""
        result: dict[str, AssistTimerState] = {}
        for entity_id, state_data in data.items():
            try:
                state = AssistTimerState(
                    on_timer_seconds=float(state_data.get("on_timer_seconds", 0.0)),
                    off_timer_seconds=float(state_data.get("off_timer_seconds", 0.0)),
                    active_condition=str(state_data.get("active_condition", "none")),
                    running_state=bool(state_data.get("running_state", False)),
                    last_on=_iso_to_datetime(state_data.get("last_on")),
                    last_off=_iso_to_datetime(state_data.get("last_off")),
                    block_reason=str(state_data.get("block_reason", "")),
                    target_hvac_mode=state_data.get("target_hvac_mode"),
                    target_reason=str(state_data.get("target_reason", "")),
                )
                result[entity_id] = state
            except (TypeError, ValueError) as err:
                _LOGGER.warning(
                    "Failed to deserialize timer state for %s: %s",
                    entity_id,
                    err,
                )
        return result
