"""PowerClimate climate entity.

HP1 (water-based) has its HVAC mode controlled by PowerClimate. Assist heat
pumps (HP2, HP3, …) are user-controlled for HVAC mode; when they are ON,
PowerClimate only adjusts their temperature setpoints.

Assist pumps operate in two modes:
- minimal mode: room temperature >= target →
  setpoint = current temp + lower offset
- setpoint mode: room temperature < target →
  setpoint = (PowerClimate target)
  clamped to [current temp + lower offset, current temp + upper offset]

All pumps are clamped between DEFAULT_MIN_SETPOINT and DEFAULT_MAX_SETPOINT.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Set

from homeassistant.components.climate import (
    DOMAIN as CLIMATE_DOMAIN,
    ClimateEntity,
)
from homeassistant.components.climate.const import (
    ATTR_HVAC_MODE,
    HVACMode,
    ClimateEntityFeature,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_TEMPERATURE,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE
from homeassistant.const import UnitOfTemperature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceNotFound
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_CLIMATE_ENTITY,
    CONF_COPY_SETPOINT_TO_POWERCLIMATE,
    CONF_DEVICE_NAME,
    CONF_DEVICES,
    CONF_LOWER_SETPOINT_OFFSET,
    CONF_ROOM_SENSOR,
    CONF_UPPER_SETPOINT_OFFSET,
    COORDINATOR,
    DEFAULT_LOWER_SETPOINT_OFFSET_ASSIST,
    DEFAULT_LOWER_SETPOINT_OFFSET_HP1,
    DEFAULT_MAX_SETPOINT,
    DEFAULT_MIN_SETPOINT,
    MIN_SET_CALL_INTERVAL_SECONDS,
    SERVICE_CALL_TIMEOUT_SECONDS,
    DEFAULT_UPPER_SETPOINT_OFFSET_ASSIST,
    DEFAULT_UPPER_SETPOINT_OFFSET_HP1,
    DOMAIN,
)
from .helpers import (
    entry_friendly_name,
    integration_device_info,
    merged_entry_data,
    summary_signal,
)

_LOGGER = logging.getLogger(__name__)
DEFAULT_TARGET_TEMPERATURE = 21.0


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the PowerClimate climate entity from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]
    entity = PowerClimateClimate(hass, entry, coordinator)
    hass.data[DOMAIN][entry.entry_id]["climate_entity"] = entity
    async_add_entities([entity])


class PowerClimateClimate(CoordinatorEntity, ClimateEntity, RestoreEntity):
    _attr_target_temperature_step = 0.1
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = 10.0
    _attr_max_temp = 30.0
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]

    def __init__(self, hass, entry, coordinator):
        super().__init__(coordinator)
        self.hass = hass
        self._entry = entry
        self._attr_name = entry_friendly_name(entry)
        self._attr_unique_id = f"powerclimate_{entry.entry_id}"
        self._attr_device_info = integration_device_info(entry)
        self._attr_hvac_mode = HVACMode.HEAT
        self._target_temperature = DEFAULT_TARGET_TEMPERATURE
        self._active_devices: set[str] = set()
        self._device_modes: dict[str, HVACMode] = {}
        self._device_targets: dict[str, float] = {}
        self._mode_state = "off"
        self._delta: float | None = None
        self._summary_signal = summary_signal(entry.entry_id)
        self._water_temperature: float | None = None
        self._devices_snapshot: list[dict[str, Any]] = []
        self._device_payload_cache: dict[str, dict[str, Any]] = {}
        self._hp_status_snapshot: list[dict[str, Any]] = []
        self._room_eta_hours: float | None = None
        self._assist_modes: dict[str, str] = {}
        self._hp_state_unsubs: dict[str, Callable[[], None]] = {}
        self._pending_state_refresh = False
        self._last_mode_call: dict[str, datetime] = {}
        self._last_temp_call: dict[str, datetime] = {}
        self._copy_enabled_entities: set[str] = set()
        self._integration_context = Context()

    @property
    def current_temperature(self) -> float | None:
        return self.coordinator.data.get(CONF_ROOM_SENSOR)

    @property
    def target_temperature(self) -> float | None:
        return self._target_temperature

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            value = last_state.attributes.get(ATTR_TEMPERATURE)
            try:
                if value is not None:
                    self._target_temperature = float(value)
            except (TypeError, ValueError):
                pass
        await self._apply_staging()

    async def async_will_remove_from_hass(self) -> None:
        for unsub in self._hp_state_unsubs.values():
            unsub()
        self._hp_state_unsubs.clear()
        await super().async_will_remove_from_hass()

    @callback
    def _handle_coordinator_update(self) -> None:
        self.hass.async_create_task(self._async_process_update())

    async def _async_process_update(self) -> None:
        await self._apply_staging()
        super()._handle_coordinator_update()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        self._target_temperature = float(temperature)
        if self.hvac_mode == HVACMode.OFF:
            self._attr_hvac_mode = HVACMode.HEAT
        await self._apply_staging()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode not in self.hvac_modes:
            return
        self._attr_hvac_mode = hvac_mode
        await self._apply_staging()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "active_devices": sorted(self._active_devices),
            "stage_count": len(self._active_devices),
            "mode": self._mode_state,
            "delta": self._delta,
            "room_temperature": self.current_temperature,
            "derivative": self.coordinator.data.get("room_derivative"),
            "room_eta_hours": self._room_eta_hours,
            "water_temperature": self._water_temperature,
            "water_derivative": self.coordinator.data.get("water_derivative"),
            "hp_status": self._hp_status_snapshot,
        }

    async def _apply_staging(self) -> None:
        config = merged_entry_data(self._entry)
        devices = config.get(CONF_DEVICES, [])
        device_payloads = self._coordinator_devices()
        self._devices_snapshot = [dict(device) for device in devices]
        self._device_payload_cache = device_payloads
        self._copy_enabled_entities = {
            device.get(CONF_CLIMATE_ENTITY)
            for device in devices
            if device.get(CONF_COPY_SETPOINT_TO_POWERCLIMATE)
            and device.get(CONF_CLIMATE_ENTITY)
        }

        if not devices:
            await self._sync_devices([], set(), device_payloads, {})
            self._sync_state_listeners(set())
            self._active_devices = set()
            self._update_mode("off")
            self._delta = None
            self._water_temperature = None
            self._hp_status_snapshot = []
            self._assist_modes = {}
            self.async_write_ha_state()
            self._emit_summary()
            return

        hvac_disabled = (
            self._attr_hvac_mode == HVACMode.OFF
            or self._target_temperature is None
        )

        desired_devices: Set[str] = set()
        desired_targets: dict[str, float] = {}
        room_temp = self.current_temperature

        if room_temp is not None and self._target_temperature is not None:
            self._delta = room_temp - self._target_temperature
        else:
            self._delta = None

        self._room_eta_hours = self._compute_eta_hours(
            (self._target_temperature - room_temp)
            if (self._target_temperature is not None and room_temp is not None)
            else None,
            self.coordinator.data.get("room_derivative"),
        )

        water_temp = None
        mode = "off"
        self._assist_modes = {}

        if not hvac_disabled:
            hp1_device = devices[0]
            hp1_entity = hp1_device.get(CONF_CLIMATE_ENTITY)
            if hp1_entity:
                desired_devices.add(hp1_entity)
                hp1_payload = device_payloads.get(hp1_entity, {})
                hp1_current = _safe_float(
                    hp1_payload.get("current_temperature"),
                )
                water_temp = _safe_float(hp1_payload.get("water_temperature"))

                hp1_target = self._clamp_setpoint(
                    self._target_temperature,
                    hp1_current,
                    hp1_device,
                    index=0,
                )
                desired_targets[hp1_entity] = hp1_target

                _LOGGER.debug(
                    "HP1 target computed: setpoint=%.1f, current=%s -> %.1f",
                    self._target_temperature or 0.0,
                    hp1_current,
                    hp1_target,
                )

                mode = "hp1_only"

                assist_devices = [
                    (index, device)
                    for index, device in enumerate(devices[1:], start=1)
                    if device.get(CONF_CLIMATE_ENTITY)
                ]

                if assist_devices:
                    room_at_target = (
                        room_temp is not None
                        and self._target_temperature is not None
                        and room_temp >= self._target_temperature
                    )

                    managed_any = False
                    for assist_index, device in assist_devices:
                        entity = device.get(CONF_CLIMATE_ENTITY)
                        if not entity:
                            continue

                        payload = device_payloads.get(entity, {}) or {}
                        hvac_mode = str(payload.get("hvac_mode") or "").lower()
                        is_running = (
                            hvac_mode and hvac_mode != HVACMode.OFF.value
                        )

                        if not is_running:
                            self._assist_modes[entity] = "off"
                            continue

                        current_temp = _safe_float(
                            payload.get("current_temperature"),
                        )
                        if room_at_target:
                            assist_mode = "minimal"
                            target_for_device = self._minimal_mode_target(
                                current_temp,
                                device,
                                assist_index,
                            )
                        else:
                            assist_mode = "setpoint"
                            target_for_device = self._clamp_setpoint(
                                self._target_temperature,
                                current_temp,
                                device,
                                assist_index,
                            )

                        desired_devices.add(entity)
                        desired_targets[entity] = target_for_device
                        self._assist_modes[entity] = assist_mode
                        managed_any = True

                        _LOGGER.debug(
                            "Assist HP%d (%s): mode=%s, current=%s -> %.1f",
                            assist_index + 1,
                            entity,
                            assist_mode,
                            current_temp,
                            target_for_device,
                        )

                    if managed_any:
                        mode = "hp2_assist"

        await self._sync_devices(
            devices,
            desired_devices,
            device_payloads,
            desired_targets,
        )

        self._sync_state_listeners(
            {
                device.get(CONF_CLIMATE_ENTITY)
                for device in devices
                if device.get(CONF_CLIMATE_ENTITY)
            }
        )

        actual_running = {
            entity_id
            for entity_id, payload in device_payloads.items()
            if (
                str(payload.get("hvac_mode") or "").lower()
                != HVACMode.OFF.value
            )
        }
        self._active_devices = desired_devices | actual_running
        self._water_temperature = water_temp
        self._update_mode(mode)
        self.async_write_ha_state()
        self._emit_summary()

    async def _sync_devices(
        self,
        devices: list[dict[str, Any]],
        desired_devices: Set[str],
        device_payloads: dict[str, dict[str, Any]],
        desired_targets: dict[str, float],
    ) -> None:
        for index, device in enumerate(devices):
            entity_id = device.get(CONF_CLIMATE_ENTITY)
            if not entity_id:
                continue

            is_hp1 = index == 0

            if entity_id in desired_devices:
                if is_hp1:
                    await self._ensure_device_mode(entity_id, HVACMode.HEAT)
                target = desired_targets.get(entity_id)
                if target is not None:
                    await self._ensure_device_temperature(entity_id, target)
            else:
                if is_hp1:
                    await self._ensure_device_mode(entity_id, HVACMode.OFF)

    def _minimal_mode_target(
        self,
        current_temp: float | None,
        device: dict[str, Any],
        index: int,
    ) -> float:
        if current_temp is None:
            return DEFAULT_MIN_SETPOINT
        target = current_temp + self._device_lower_offset(device, index)
        return self._clamp_setpoint(target, current_temp, device, index)

    def _clamp_setpoint(
        self,
        target: float | None,
        current_temp: float | None,
        device: dict[str, Any],
        index: int,
    ) -> float:
        if target is None:
            return DEFAULT_MIN_SETPOINT

        lower_offset = self._device_lower_offset(device, index)
        upper_offset = self._device_upper_offset(device, index)

        if current_temp is None:
            floor = DEFAULT_MIN_SETPOINT
            ceiling = DEFAULT_MAX_SETPOINT
        else:
            floor = current_temp + lower_offset
            ceiling = current_temp + upper_offset
            floor = max(floor, DEFAULT_MIN_SETPOINT)
            ceiling = min(ceiling, DEFAULT_MAX_SETPOINT)

        clamped = max(floor, min(target, ceiling))

        if clamped != target:
            _LOGGER.debug(
                "Target %.1f clamped to %.1f (floor=%.1f, ceiling=%.1f)",
                target,
                clamped,
                floor,
                ceiling,
            )

        return clamped

    def _device_lower_offset(
        self,
        device: dict[str, Any],
        index: int,
    ) -> float:
        value = device.get(CONF_LOWER_SETPOINT_OFFSET)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                pass
        return (
            DEFAULT_LOWER_SETPOINT_OFFSET_HP1
            if index == 0
            else DEFAULT_LOWER_SETPOINT_OFFSET_ASSIST
        )

    def _device_upper_offset(
        self,
        device: dict[str, Any],
        index: int,
    ) -> float:
        value = device.get(CONF_UPPER_SETPOINT_OFFSET)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                pass
        return (
            DEFAULT_UPPER_SETPOINT_OFFSET_HP1
            if index == 0
            else DEFAULT_UPPER_SETPOINT_OFFSET_ASSIST
        )

    def _coordinator_devices(self) -> dict[str, dict[str, Any]]:
        payloads: dict[str, dict[str, Any]] = {}
        coordinator_data = self.coordinator.data or {}
        for device in coordinator_data.get("devices", []):
            entity_id = device.get(CONF_CLIMATE_ENTITY)
            if entity_id:
                payloads[entity_id] = device
        return payloads

    def _compute_eta_hours(
        self,
        delta_to_target: float | None,
        derivative: float | None,
    ) -> float | None:
        if delta_to_target is None or derivative is None:
            return None
        if derivative == 0:
            return None
        if delta_to_target * derivative <= 0:
            return None
        hours = delta_to_target / derivative
        if hours < 0:
            return None
        return hours

    def _update_mode(self, mode: str) -> None:
        if mode != self._mode_state:
            self._mode_state = mode

    def _build_hp_status(self) -> list[dict[str, Any]]:
        status: list[dict[str, Any]] = []
        coordinator_data = self.coordinator.data or {}
        for index, device in enumerate(self._devices_snapshot):
            entity_id = device.get(CONF_CLIMATE_ENTITY)
            if not entity_id:
                continue
            payload = self._device_payload_cache.get(entity_id, {}) or {}
            hvac_mode = str(payload.get("hvac_mode") or "").lower()
            is_running = hvac_mode and hvac_mode != HVACMode.OFF.value

            assist_mode = None
            if index > 0:
                assist_mode = self._assist_modes.get(entity_id, "off")

            if index == 0:
                water_derivative = _safe_float(
                    coordinator_data.get("water_derivative"),
                )
            else:
                water_derivative = _safe_float(
                    payload.get("water_derivative"),
                )

            status.append(
                {
                    "role": f"hp{index + 1}",
                    "name": device.get(CONF_DEVICE_NAME) or f"HP{index + 1}",
                    "entity_id": entity_id,
                    "active": entity_id in self._active_devices or is_running,
                    "hvac_mode": payload.get("hvac_mode"),
                    "assist_mode": assist_mode,
                    "current_temperature": _safe_float(
                        payload.get("current_temperature"),
                    ),
                    "target_temperature": _safe_float(
                        payload.get("target_temperature"),
                    ),
                    "temperature_derivative": _safe_float(
                        payload.get("temperature_derivative"),
                    ),
                    "water_temperature": _safe_float(
                        payload.get("water_temperature"),
                    ),
                    "water_derivative": water_derivative,
                    "eta_hours": self._compute_eta_hours(
                        (
                            _safe_float(payload.get("target_temperature"))
                            - _safe_float(payload.get("current_temperature"))
                        )
                        if (
                            payload.get("target_temperature") is not None
                            and payload.get("current_temperature") is not None
                        )
                        else None,
                        _safe_float(payload.get("temperature_derivative")),
                    ),
                    "energy": _safe_float(payload.get("energy")),
                },
            )
        return status

    def _emit_summary(self) -> None:
        target_temp = self._current_target_temperature()
        hp_status = self._build_hp_status()
        self._hp_status_snapshot = hp_status
        payload = {
            "mode": self._mode_state,
            "stage_count": len(self._active_devices),
            "active_devices": sorted(self._active_devices),
            "delta": self._delta,
            "room_temperature": self.current_temperature,
            "derivative": self.coordinator.data.get("room_derivative"),
            "room_eta_hours": self._room_eta_hours,
            "water_temperature": self._water_temperature,
            "water_derivative": self.coordinator.data.get("water_derivative"),
            "hp_status": hp_status,
            "target_temperature": target_temp,
        }

        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id)
        if entry_data is not None:
            entry_data["summary_payload"] = payload
        async_dispatcher_send(self.hass, self._summary_signal, payload)

    def _sync_state_listeners(self, entity_ids: set[str]) -> None:
        current = set(self._hp_state_unsubs)
        for entity_id in current - entity_ids:
            unsub = self._hp_state_unsubs.pop(entity_id, None)
            if unsub:
                unsub()

        for entity_id in entity_ids - current:
            if not entity_id:
                continue
            unsub = async_track_state_change_event(
                self.hass,
                [entity_id],
                self._handle_hp_state_change,
            )
            if unsub:
                self._hp_state_unsubs[entity_id] = unsub

    @callback
    def _handle_hp_state_change(self, event) -> None:
        pending_refresh = self._pending_state_refresh
        entity_id = event.data.get("entity_id") if event and event.data else None
        new_state = event.data.get("new_state") if event and event.data else None
        old_state = event.data.get("old_state") if event and event.data else None

        if entity_id and entity_id in self._copy_enabled_entities:
            self._maybe_forward_setpoint(entity_id, old_state, new_state)

        if pending_refresh:
            return

        self._pending_state_refresh = True

        async def _refresh() -> None:
            try:
                await self.coordinator.async_request_refresh()
            finally:
                self._pending_state_refresh = False

        self.hass.async_create_task(_refresh())

    def _state_context_is_integration(self, state) -> bool:
        if not state or not state.context:
            return False
        return state.context.id == self._integration_context.id

    def _has_temperature_change(
        self,
        old_state,
        new_state,
    ) -> tuple[bool, float | None]:
        new_temp = _safe_float(
            (new_state.attributes if new_state else {}).get(ATTR_TEMPERATURE),
        )
        old_temp = _safe_float(
            (old_state.attributes if old_state else {}).get(ATTR_TEMPERATURE),
        )
        if new_temp is None:
            return False, None
        if old_temp is not None and abs(new_temp - old_temp) < 0.01:
            return False, new_temp
        return True, new_temp

    def _maybe_forward_setpoint(self, entity_id, old_state, new_state) -> None:
        if new_state is None:
            return
        if self._state_context_is_integration(new_state):
            return

        changed, temperature = self._has_temperature_change(old_state, new_state)
        if not changed or temperature is None:
            return

        async def _forward() -> None:
            await self._forward_setpoint_to_powerclimate(
                temperature,
                source_entity=entity_id,
            )

        self.hass.async_create_task(_forward())

    async def _forward_setpoint_to_powerclimate(
        self,
        temperature: float,
        source_entity: str | None = None,
    ) -> None:
        if not self.entity_id:
            return
        try:
            await asyncio.wait_for(
                self.hass.services.async_call(
                    CLIMATE_DOMAIN,
                    SERVICE_SET_TEMPERATURE,
                    {
                        ATTR_ENTITY_ID: self.entity_id,
                        ATTR_TEMPERATURE: temperature,
                    },
                    blocking=True,
                    context=self._integration_context,
                ),
                timeout=SERVICE_CALL_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            _LOGGER.warning(
                "Forwarding setpoint from %s to %s timed out after %ss",
                source_entity or "unknown",
                self.entity_id,
                SERVICE_CALL_TIMEOUT_SECONDS,
            )
        except ServiceNotFound:
            _LOGGER.error(
                "Service %s.%s not found while forwarding to %s",
                CLIMATE_DOMAIN,
                SERVICE_SET_TEMPERATURE,
                self.entity_id,
            )
        except HomeAssistantError as err:
            _LOGGER.warning(
                "Failed to forward setpoint from %s to %s: %s",
                source_entity or "unknown",
                self.entity_id,
                err,
            )

    def _current_target_temperature(self) -> float | None:
        state = self.hass.states.get(self.entity_id)
        if state:
            value = state.attributes.get(ATTR_TEMPERATURE)
            if value is not None:
                return float(value)
        return self._target_temperature

    async def _ensure_device_mode(
        self,
        entity_id: str,
        mode: HVACMode,
    ) -> None:
        if self._device_modes.get(entity_id) == mode:
            return
        if self._recent_call(self._last_mode_call, entity_id):
            _LOGGER.debug(
                "Skipping HVAC mode set for %s due to cooldown", entity_id
            )
            return
        try:
            await asyncio.wait_for(
                self.hass.services.async_call(
                    CLIMATE_DOMAIN,
                    SERVICE_SET_HVAC_MODE,
                    {
                        ATTR_ENTITY_ID: entity_id,
                        ATTR_HVAC_MODE: mode,
                    },
                    blocking=True,
                    context=self._integration_context,
                ),
                timeout=SERVICE_CALL_TIMEOUT_SECONDS,
            )
            self._device_modes[entity_id] = mode
            self._mark_call(self._last_mode_call, entity_id)
        except asyncio.TimeoutError:
            _LOGGER.warning(
                "Setting HVAC mode for %s timed out after %ss",
                entity_id,
                SERVICE_CALL_TIMEOUT_SECONDS,
            )
        except ServiceNotFound:
            _LOGGER.error(
                "Service %s.%s not found for %s",
                CLIMATE_DOMAIN,
                SERVICE_SET_HVAC_MODE,
                entity_id,
            )
        except HomeAssistantError as err:
            _LOGGER.warning(
                "Failed to set HVAC mode for %s: %s",
                entity_id,
                err,
            )

    async def _ensure_device_temperature(
        self,
        entity_id: str,
        temperature: float,
    ) -> None:
        previous = self._device_targets.get(entity_id)
        if previous is not None and abs(previous - temperature) < 0.1:
            return
        if self._recent_call(self._last_temp_call, entity_id):
            _LOGGER.debug(
                "Skipping temperature set for %s due to cooldown", entity_id
            )
            return
        try:
            await asyncio.wait_for(
                self.hass.services.async_call(
                    CLIMATE_DOMAIN,
                    SERVICE_SET_TEMPERATURE,
                    {
                        ATTR_ENTITY_ID: entity_id,
                        ATTR_TEMPERATURE: temperature,
                    },
                    blocking=True,
                    context=self._integration_context,
                ),
                timeout=SERVICE_CALL_TIMEOUT_SECONDS,
            )
            self._device_targets[entity_id] = temperature
            self._mark_call(self._last_temp_call, entity_id)
        except asyncio.TimeoutError:
            _LOGGER.warning(
                "Setting temperature for %s timed out after %ss",
                entity_id,
                SERVICE_CALL_TIMEOUT_SECONDS,
            )
        except ServiceNotFound:
            _LOGGER.error(
                "Service %s.%s not found for %s",
                CLIMATE_DOMAIN,
                SERVICE_SET_TEMPERATURE,
                entity_id,
            )
        except HomeAssistantError as err:
            _LOGGER.warning(
                "Failed to set temperature for %s: %s",
                entity_id,
                err,
            )

    def _recent_call(
        self,
        store: dict[str, datetime],
        entity_id: str,
    ) -> bool:
        last_call = store.get(entity_id)
        if not last_call:
            return False
        return (
            datetime.now(timezone.utc) - last_call
        ).total_seconds() < MIN_SET_CALL_INTERVAL_SECONDS

    def _mark_call(self, store: dict[str, datetime], entity_id: str) -> None:
        store[entity_id] = datetime.now(timezone.utc)
