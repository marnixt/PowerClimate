"""Send HVAC mode and setpoint commands to the controlled climate devices.

The commander compares every command with the device's actual state, keeps
a per-device cooldown between calls, and tags its calls with its own
context so state changes caused by PowerClimate can be told apart from
external ones.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.components.climate.const import (
    ATTR_HVAC_MODE,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_TEMPERATURE,
    HVACMode,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceNotFound

from .const import (
    MIN_SET_CALL_INTERVAL_SECONDS,
    SERVICE_CALL_TIMEOUT_SECONDS,
    SETPOINT_COMPARISON_THRESHOLD,
)
from .utils import safe_float

_LOGGER = logging.getLogger(__name__)


class DeviceCommander:
    """Apply HVAC modes and setpoints to climate devices."""

    def __init__(
        self,
        hass: HomeAssistant,
        is_off: Callable[[], bool],
        context: Context | None = None,
    ) -> None:
        """Initialize the commander.

        Args:
            hass: Home Assistant instance.
            is_off: Returns True while PowerClimate itself is OFF; commands are
                then skipped unless explicitly allowed.
            context: Context attached to every service call.
        """
        self.hass = hass
        self._is_off = is_off
        self.context = context or Context()
        self.device_modes: dict[str, HVACMode] = {}
        self.device_targets: dict[str, float] = {}
        self.device_reported_targets: dict[str, float | None] = {}
        self.last_mode_call: dict[str, datetime] = {}
        self.last_temp_call: dict[str, datetime] = {}

    def is_own_state(self, state) -> bool:
        """Return True when a state change was caused by this commander."""
        if not state or not state.context:
            return False
        return state.context.id == self.context.id

    async def call_service(
        self,
        entity_id: str,
        service_name: str,
        service_data: dict[str, Any],
        action_description: str,
        *,
        allow_when_off: bool = False,
    ) -> bool:
        """Call a climate service with error handling.

        Returns:
            True when the call completed successfully.
        """
        if self._is_off() and not allow_when_off:
            _LOGGER.debug(
                "PowerClimate is OFF; skipping %s for %s",
                action_description, entity_id,
            )
            return False

        try:
            await asyncio.wait_for(
                self.hass.services.async_call(
                    CLIMATE_DOMAIN,
                    service_name,
                    service_data,
                    blocking=True,
                    context=self.context,
                ),
                timeout=SERVICE_CALL_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            _LOGGER.warning(
                "%s for %s timed out after %ss",
                action_description.capitalize(), entity_id, SERVICE_CALL_TIMEOUT_SECONDS,
            )
        except ServiceNotFound:
            _LOGGER.error(
                "Service %s.%s not found for %s",
                CLIMATE_DOMAIN, service_name, entity_id,
            )
        except HomeAssistantError as err:
            _LOGGER.warning("Failed %s for %s: %s", action_description, entity_id, err)
        else:
            return True
        return False

    async def ensure_mode(
        self,
        entity_id: str,
        mode: HVACMode,
        *,
        allow_when_off: bool = False,
        force: bool = False,
    ) -> bool:
        """Ensure device is in the specified HVAC mode.

        Compares against the device's actual state so that external changes
        (manual switching, device resets) are corrected; the cache is only a
        fallback when the state is unavailable.

        Returns:
            True when the device is (now) in the requested mode.
        """
        state = self.hass.states.get(entity_id)
        if state is not None:
            if state.state == mode:
                return True
        elif self.device_modes.get(entity_id) == mode:
            return True
        if not force and self._recent_call(self.last_mode_call, entity_id):
            _LOGGER.debug("Skipping HVAC mode set for %s due to cooldown", entity_id)
            return False

        success = await self.call_service(
            entity_id,
            SERVICE_SET_HVAC_MODE,
            {ATTR_ENTITY_ID: entity_id, ATTR_HVAC_MODE: mode},
            "mode change",
            allow_when_off=allow_when_off,
        )
        self._mark_call(self.last_mode_call, entity_id)
        if success:
            self.device_modes[entity_id] = mode
        return success

    async def ensure_temperature(self, entity_id: str, temperature: float) -> None:
        """Ensure device has the specified target temperature.

        Skips the call when the device already reports the target, or when we
        already sent this target and the device's setpoint has not changed
        since (devices may round, e.g. to 0.5 °C steps). A setpoint changed
        externally is therefore re-applied.
        """
        reported = self.reported_setpoint(entity_id)
        if reported is not None and abs(reported - temperature) < SETPOINT_COMPARISON_THRESHOLD:
            return
        previous = self.device_targets.get(entity_id)
        if (
            previous is not None
            and abs(previous - temperature) < SETPOINT_COMPARISON_THRESHOLD
            and reported == self.device_reported_targets.get(entity_id)
        ):
            return
        if self._recent_call(self.last_temp_call, entity_id):
            _LOGGER.debug("Skipping temperature set for %s due to cooldown", entity_id)
            return

        success = await self.call_service(
            entity_id,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: entity_id, ATTR_TEMPERATURE: temperature},
            "temperature set",
        )
        self._mark_call(self.last_temp_call, entity_id)
        if success:
            self.device_targets[entity_id] = temperature
            self.device_reported_targets[entity_id] = self.reported_setpoint(entity_id)

    def reported_setpoint(self, entity_id: str) -> float | None:
        """Return the setpoint a climate entity currently reports."""
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        return safe_float(state.attributes.get(ATTR_TEMPERATURE))

    @staticmethod
    def _recent_call(store: dict[str, datetime], entity_id: str) -> bool:
        """Check if a recent call was made for an entity."""
        last_call = store.get(entity_id)
        if not last_call:
            return False
        return (
            datetime.now(timezone.utc) - last_call
        ).total_seconds() < MIN_SET_CALL_INTERVAL_SECONDS

    @staticmethod
    def _mark_call(store: dict[str, datetime], entity_id: str) -> None:
        """Mark a call timestamp for an entity."""
        store[entity_id] = datetime.now(timezone.utc)
