"""PowerClimate climate entity."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ATTR_HVAC_MODE,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_TEMPERATURE,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceNotFound
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .assist_controller import AssistPumpController
from .config_accessor import ConfigAccessor
from .const import (
    CONF_ALLOW_ON_OFF_CONTROL,
    CONF_CLIMATE_ENTITY,
    CONF_DEVICE_NAME,
    CONF_ROOM_SENSOR_VALUES,
    CONF_ROOM_TEMPERATURE_KEY,
    COORDINATOR,
    DEFAULT_TARGET_TEMPERATURE,
    DOMAIN,
    ETA_THRESHOLD_MET_DURATION_MINUTES,
    MIN_SET_CALL_INTERVAL_SECONDS,
    MODE_BOOST,
    MODE_MINIMAL,
    MODE_OFF,
    MODE_POWER,
    MODE_SETPOINT,
    SERVICE_CALL_TIMEOUT_SECONDS,
    SETPOINT_COMPARISON_THRESHOLD,
    TEMPERATURE_CHANGE_THRESHOLD,
)
from .helpers import (
    entry_friendly_name,
    integration_device_info,
    summary_signal,
)
from .power_budget import PowerBudgetManager
from .utils import clamp_setpoint, compute_eta_hours, safe_float

_LOGGER = logging.getLogger(__name__)

PRESET_NONE = "none"
PRESET_BOOST = "boost"
PRESET_SOLAR = "Solar"
PRESET_AWAY = "Away"
PRESET_MINIMAL_SUPPORT = "Minimal support"


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
    """Climate entity representing the PowerClimate system."""

    _attr_target_temperature_step = 0.1
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = 10.0
    _attr_max_temp = 30.0
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
    )
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_preset_modes = [PRESET_NONE, PRESET_BOOST, PRESET_AWAY, PRESET_MINIMAL_SUPPORT, PRESET_SOLAR]

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator) -> None:
        """Initialize the PowerClimate climate entity."""
        super().__init__(coordinator)
        self.hass = hass
        self._entry = entry
        self._attr_name = entry_friendly_name(entry)
        self._attr_unique_id = f"powerclimate_{entry.entry_id}"
        self._attr_device_info = integration_device_info(entry)
        self._attr_hvac_mode = HVACMode.HEAT
        self._attr_preset_mode = PRESET_NONE
        self._target_temperature = DEFAULT_TARGET_TEMPERATURE
        self._previous_target: float | None = None
        self._config = ConfigAccessor(entry)
        self._power_manager = PowerBudgetManager(hass, self._config)
        self._assist_controller = AssistPumpController(self._config)
        self._active_devices: set[str] = set()
        self._device_modes: dict[str, HVACMode] = {}
        self._device_targets: dict[str, float] = {}
        self._hp_modes: dict[str, str] = {}  # entity_id -> MODE_*
        self._hp_state_unsubs: dict[str, Callable[[], None]] = {}
        self._assist_modes: dict[str, str] = {}
        self._mode_state = "off"
        self._delta: float | None = None
        self._water_temperature: float | None = None
        self._room_eta_hours: float | None = None
        self._summary_payload: dict[str, Any] | None = None
        self._summary_signal = summary_signal(entry.entry_id)
        self._pending_state_refresh = False
        self._last_mode_call: dict[str, datetime] = {}
        self._last_temp_call: dict[str, datetime] = {}
        self._mirror_entities: set[str] = set()
        self._integration_context = Context()
        self._eta_exceeded_since: datetime | None = None

    @property
    def preset_modes(self) -> list[str] | None:
        """Return list of available preset modes."""
        modes = [PRESET_NONE, PRESET_BOOST, PRESET_AWAY, PRESET_MINIMAL_SUPPORT]
        if self._config.solar_enabled:
            modes.append(PRESET_SOLAR)
        return modes

    @property
    def entity_picture(self) -> str:
        """Return entity picture URL."""
        return "/local/community/powerclimate/icon.png"

    @property
    def current_temperature(self) -> float | None:
        """Return current room temperature."""
        return safe_float(self.coordinator.data.get(CONF_ROOM_TEMPERATURE_KEY))

    @property
    def target_temperature(self) -> float | None:
        """Return target temperature."""
        return self._target_temperature

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        eta_exceeded_duration = None
        if self._eta_exceeded_since:
            eta_exceeded_duration = (
                datetime.now(timezone.utc) - self._eta_exceeded_since
            ).total_seconds() / 60.0

        base = dict(self._summary_payload or {})
        base["eta_exceeded_duration_minutes"] = eta_exceeded_duration
        base["eta_threshold_met"] = (
            eta_exceeded_duration is not None
            and eta_exceeded_duration >= ETA_THRESHOLD_MET_DURATION_MINUTES
        )
        return base

    async def async_added_to_hass(self) -> None:
        """Handle entity being added to Home Assistant."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            value = last_state.attributes.get(ATTR_TEMPERATURE)
            if value is not None:
                try:
                    self._target_temperature = float(value)
                except (TypeError, ValueError):
                    pass
        await self._apply_staging()

    async def async_will_remove_from_hass(self) -> None:
        """Handle entity removal from Home Assistant."""
        for unsub in self._hp_state_unsubs.values():
            unsub()
        self._hp_state_unsubs.clear()
        await super().async_will_remove_from_hass()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle coordinator data update."""
        self.hass.async_create_task(self._async_process_update())

    async def _async_process_update(self) -> None:
        """Process coordinator update asynchronously."""
        await self._apply_staging()
        super()._handle_coordinator_update()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        self._target_temperature = float(temperature)
        await self._apply_staging()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set HVAC mode."""
        if hvac_mode not in self.hvac_modes:
            return
        self._attr_hvac_mode = hvac_mode
        if self._attr_preset_mode != PRESET_NONE:
            self._attr_preset_mode = PRESET_NONE
            self._previous_target = None

        await self._apply_staging()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set preset mode."""
        if preset_mode not in self.preset_modes:
            return

        if preset_mode == PRESET_BOOST:
            await self._enter_boost_mode()
        elif preset_mode == PRESET_AWAY:
            await self._enter_away_mode()
        elif preset_mode == PRESET_MINIMAL_SUPPORT:
            await self._enter_minimal_support_mode()
        elif preset_mode == PRESET_SOLAR:
            await self._enter_solar_mode()
        elif preset_mode == PRESET_NONE:
            await self._exit_preset_mode()

    async def _enter_boost_mode(self) -> None:
        """Enter boost preset mode."""
        if self._attr_preset_mode == PRESET_BOOST:
            return

        self._attr_preset_mode = PRESET_BOOST
        self._attr_hvac_mode = HVACMode.HEAT
        self.async_write_ha_state()  # Immediate UI feedback
        self.hass.async_create_task(self._apply_boost_mode())  # Background

    async def _enter_away_mode(self) -> None:
        """Enter away preset mode."""
        if self._attr_preset_mode == PRESET_AWAY:
            return
        self._previous_target = self._target_temperature
        self._target_temperature = self._config.min_setpoint

        self._attr_preset_mode = PRESET_AWAY
        self._attr_hvac_mode = HVACMode.HEAT
        self._power_manager.clear_all()
        self.async_write_ha_state()  # Immediate UI feedback

        self.hass.async_create_task(self._apply_away_mode())  # Background

    async def _enter_minimal_support_mode(self) -> None:
        """Enter minimal support preset mode.

        In this mode:
        - Water heat pump is boosted (current + upper offset)
        - Air heat pumps are set to minimal mode (current + lower offset)
        """
        if self._attr_preset_mode == PRESET_MINIMAL_SUPPORT:
            return

        # Restore target if coming from Away
        if self._attr_preset_mode == PRESET_AWAY and self._previous_target is not None:
            self._target_temperature = self._previous_target
        self._previous_target = None

        self._attr_preset_mode = PRESET_MINIMAL_SUPPORT
        self._attr_hvac_mode = HVACMode.HEAT
        self._power_manager.clear_all()
        self.async_write_ha_state()  # Immediate UI feedback
        self.hass.async_create_task(self._apply_minimal_support_mode())  # Background

    async def _enter_solar_mode(self) -> None:
        """Enter solar preset mode."""
        if self._attr_preset_mode == PRESET_SOLAR:
            return

        # Restore target if coming from Away
        if self._attr_preset_mode == PRESET_AWAY and self._previous_target is not None:
            self._target_temperature = self._previous_target
        self._previous_target = None

        self._attr_preset_mode = PRESET_SOLAR
        self._attr_hvac_mode = HVACMode.HEAT
        self.async_write_ha_state()  # Immediate UI feedback
        self.hass.async_create_task(self._apply_staging())  # Background

    async def _exit_preset_mode(self) -> None:
        """Exit current preset mode to normal operation."""
        if self._attr_preset_mode == PRESET_NONE:
            return

        # Restore target if coming from Away
        if self._attr_preset_mode == PRESET_AWAY and self._previous_target is not None:
            self._target_temperature = self._previous_target
        self._previous_target = None

        self._attr_preset_mode = PRESET_NONE
        self._power_manager.clear_all()
        self.async_write_ha_state()  # Immediate UI feedback
        self.hass.async_create_task(self._apply_staging())  # Background

    async def _apply_staging(self) -> None:
        """Apply staging logic to all heat pumps."""
        devices = self._config.devices
        device_payloads = self._get_device_payloads()
        self._mirror_entities = set(self._config.mirror_thermostats)
        if self._attr_preset_mode == PRESET_BOOST:
            await self._apply_boost_mode()
            return
        if self._attr_preset_mode == PRESET_MINIMAL_SUPPORT:
            await self._apply_minimal_support_mode()
            return
        if self._attr_preset_mode == PRESET_SOLAR:
            if not self._config.solar_enabled:
                self._attr_preset_mode = PRESET_NONE
                self._power_manager.clear_all()
            else:
                self._power_manager.update_budgets(devices)
        else:
            self._power_manager.clear_all()
        if not devices:
            await self._handle_no_devices(device_payloads)
            return
        hvac_disabled = (
            self._attr_hvac_mode == HVACMode.OFF
            or self._target_temperature is None
        )

        # Calculate room state
        room_temp = self.current_temperature
        self._update_room_state(room_temp)

        # Initialize tracking
        desired_devices: set[str] = set()
        desired_targets: dict[str, float] = {}
        water_temp = None
        mode = "off"

        if not hvac_disabled:
            room_at_target = self._is_room_at_target(room_temp)

            # Process water device
            water_result = await self._process_water_device(
                room_at_target, device_payloads, desired_devices, desired_targets
            )
            if water_result:
                water_temp, mode = water_result

            # Process air devices
            air_mode = await self._process_air_devices(
                room_temp, room_at_target, water_temp, device_payloads,
                desired_devices, desired_targets
            )
            if air_mode:
                mode = air_mode

        # Sync devices and state
        await self._sync_devices(devices, desired_devices, device_payloads, desired_targets)
        device_entities = {
            d.get(CONF_CLIMATE_ENTITY)
            for d in devices
            if d.get(CONF_CLIMATE_ENTITY)
        }
        self._sync_state_listeners(device_entities | self._mirror_entities)

        # Update state
        actual_running = {
            eid for eid, payload in device_payloads.items()
            if str(payload.get("hvac_mode") or "").lower() != HVACMode.OFF.value
        }
        self._active_devices = desired_devices | actual_running
        self._water_temperature = water_temp
        self._mode_state = mode

        self.async_write_ha_state()
        self._emit_summary(devices, device_payloads)

    def _update_room_state(self, room_temp: float | None) -> None:
        """Update room temperature state and ETA."""
        if room_temp is not None and self._target_temperature is not None:
            self._delta = room_temp - self._target_temperature
            delta_to_target = self._target_temperature - room_temp
        else:
            self._delta = None
            delta_to_target = None

        self._room_eta_hours = compute_eta_hours(
            delta_to_target,
            safe_float(self.coordinator.data.get("room_derivative")),
        )

    def _is_room_at_target(self, room_temp: float | None) -> bool:
        """Check if room temperature is at or above target."""
        return (
            room_temp is not None
            and self._target_temperature is not None
            and room_temp >= self._target_temperature
        )

    async def _handle_no_devices(
        self,
        device_payloads: dict[str, dict[str, Any]],
    ) -> None:
        """Handle case when no devices are configured."""
        await self._sync_devices([], set(), device_payloads, {})
        self._sync_state_listeners(set())
        self._active_devices = set()
        self._mode_state = "off"
        self._delta = None
        self._water_temperature = None
        self._assist_modes = {}
        self.async_write_ha_state()
        self._emit_summary([], device_payloads)

    async def _process_water_device(
        self,
        room_at_target: bool,
        device_payloads: dict[str, dict[str, Any]],
        desired_devices: set[str],
        desired_targets: dict[str, float],
    ) -> tuple[float | None, str] | None:
        """Process water-based heat pump.

        Returns:
            Tuple of (water_temp, mode) or None if no water device.
        """
        water_device_tuple = self._config.get_water_device()
        if not water_device_tuple:
            return None

        device, index = water_device_tuple
        entity_id = device.get(CONF_CLIMATE_ENTITY)
        if not entity_id:
            return None

        desired_devices.add(entity_id)
        payload = device_payloads.get(entity_id, {})
        current_temp = safe_float(payload.get("current_temperature"))
        current_power = safe_float(payload.get("energy"))
        water_temp = safe_float(payload.get("water_temperature"))

        # Determine mode
        hp_mode = self._determine_hp1_mode(room_at_target, entity_id)
        self._hp_modes[entity_id] = hp_mode

        # Calculate target
        target = self._calculate_mode_target(
            hp_mode, current_temp, device, index, current_power
        )
        desired_targets[entity_id] = target

        _LOGGER.debug(
            "Water HP: mode=%s, setpoint=%.1f, current=%s -> %.1f",
            hp_mode,
            self._target_temperature or 0.0,
            current_temp,
            target,
        )

        return water_temp, "water_hp_only"

    async def _process_air_devices(
        self,
        room_temp: float | None,
        room_at_target: bool,
        water_temp: float | None,
        device_payloads: dict[str, dict[str, Any]],
        desired_devices: set[str],
        desired_targets: dict[str, float],
    ) -> str | None:
        """Process air-based (assist) heat pumps.

        Returns:
            Updated mode string or None.
        """
        assist_devices = [
            (idx, device) for idx, device in self._config.get_air_devices()
            if device.get(CONF_CLIMATE_ENTITY)
        ]

        if not assist_devices:
            self._assist_modes = {}
            return None

        room_derivative = safe_float(self.coordinator.data.get("room_derivative"))
        managed_any = False

        for assist_index, device in assist_devices:
            entity_id = device.get(CONF_CLIMATE_ENTITY)
            if not entity_id:
                continue

            payload = device_payloads.get(entity_id, {}) or {}
            hvac_mode = str(payload.get("hvac_mode") or "").lower()
            is_running = hvac_mode and hvac_mode != HVACMode.OFF.value

            # Update assist controller timers
            self._assist_controller.update_timers(
                entity_id,
                room_temp,
                self._target_temperature,
                self._room_eta_hours,
                water_temp,
                room_derivative,
                is_running,
            )

            # Handle ON/OFF control if enabled
            if device.get(CONF_ALLOW_ON_OFF_CONTROL):
                is_running = await self._handle_assist_control(
                    entity_id, is_running, device_payloads
                )

            # Skip if not running
            if not is_running:
                self._assist_modes[entity_id] = MODE_OFF
                self._hp_modes[entity_id] = MODE_OFF
                continue

            # Determine mode and target
            current_temp = safe_float(payload.get("current_temperature"))
            current_power = safe_float(payload.get("energy"))
            timer_state = self._assist_controller.get_timer_state(entity_id)
            is_automatic = device.get(CONF_ALLOW_ON_OFF_CONTROL, False)

            assist_mode = self._determine_assist_mode(
                room_at_target, timer_state.off_timer_seconds, entity_id, is_automatic
            )
            self._hp_modes[entity_id] = assist_mode

            target = self._calculate_mode_target(
                assist_mode, current_temp, device, assist_index, current_power
            )

            desired_devices.add(entity_id)
            desired_targets[entity_id] = target
            self._assist_modes[entity_id] = assist_mode
            managed_any = True

            _LOGGER.debug(
                "Assist HP%d (%s): mode=%s, current=%s -> %.1f, "
                "on_timer=%.1fs, off_timer=%.1fs, condition=%s",
                assist_index + 1,
                entity_id,
                assist_mode,
                current_temp,
                target,
                timer_state.on_timer_seconds,
                timer_state.off_timer_seconds,
                timer_state.active_condition,
            )

        return "air_hp_assist" if managed_any else None

    async def _handle_assist_control(
        self,
        entity_id: str,
        is_running: bool,
        device_payloads: dict[str, dict[str, Any]],
    ) -> bool:
        """Handle ON/OFF control for an assist pump.

        Returns:
            Updated is_running state.
        """
        action, reason = self._assist_controller.evaluate_action(entity_id, is_running)

        if action == "heat" and not is_running:
            _LOGGER.info("Turning ON %s: condition=%s", entity_id, reason)
            await self._ensure_device_mode(entity_id, HVACMode.HEAT)
            self._assist_controller.record_turn_on(entity_id)
            # Refresh payload
            device_payloads.update(self._get_device_payloads())
            return True

        elif action == "off" and is_running:
            _LOGGER.info("Turning OFF %s: condition=%s", entity_id, reason)
            await self._ensure_device_mode(entity_id, HVACMode.OFF)
            self._assist_controller.record_turn_off(entity_id)
            device_payloads.update(self._get_device_payloads())
            return False

        return is_running

    def _determine_hp1_mode(self, room_at_target: bool, entity_id: str) -> str:
        """Determine operating mode for HP1 (water-based heat pump)."""
        if self._attr_preset_mode == PRESET_BOOST:
            return MODE_BOOST
        if self._attr_preset_mode == PRESET_MINIMAL_SUPPORT:
            return MODE_BOOST
        if self._attr_preset_mode == PRESET_AWAY:
            return MODE_MINIMAL
        if self._power_manager.get_budget(entity_id) > 0:
            return MODE_POWER
        return MODE_SETPOINT

    def _determine_assist_mode(
        self,
        room_at_target: bool,
        off_timer: float,
        entity_id: str,
        is_automatic: bool = False,
    ) -> str:
        """Determine operating mode for assist pump.

        Args:
            room_at_target: Whether room temperature is at or above target.
            off_timer: Time since OFF condition was met (for automatic pumps).
            entity_id: The entity ID of the heat pump.
            is_automatic: Whether this is an automatic pump (allow_on_off_control=True).
        """
        if self._attr_preset_mode == PRESET_BOOST:
            return MODE_BOOST
        if self._attr_preset_mode == PRESET_MINIMAL_SUPPORT:
            return MODE_MINIMAL
        if self._power_manager.get_budget(entity_id) > 0:
            return MODE_POWER
        # For automatic pumps, check off_timer to keep running briefly after target is reached
        if is_automatic and off_timer > 0:
            return MODE_MINIMAL
        if room_at_target:
            return MODE_MINIMAL
        return MODE_SETPOINT

    def _calculate_mode_target(
        self,
        mode: str,
        current_temp: float | None,
        device: dict[str, Any],
        index: int,
        current_power: float | None = None,
    ) -> float:
        """Calculate target temperature for a given mode."""
        min_sp = self._config.min_setpoint
        max_sp = self._config.max_setpoint
        entity_id = device.get(CONF_CLIMATE_ENTITY, "")

        if current_temp is None:
            return min_sp

        lower_offset = self._config.get_device_lower_offset(device, index)
        upper_offset = self._config.get_device_upper_offset(device, index)

        if mode == MODE_BOOST:
            target = current_temp + upper_offset
            return max(min_sp, min(target, max_sp))

        elif mode == MODE_MINIMAL:
            target = current_temp + lower_offset
            return clamp_setpoint(target, current_temp, lower_offset, upper_offset, min_sp, max_sp)

        elif mode == MODE_SETPOINT:
            return clamp_setpoint(
                self._target_temperature, current_temp,
                lower_offset, upper_offset, min_sp, max_sp
            )

        elif mode == MODE_POWER:
            return self._power_manager.calculate_setpoint(
                entity_id, current_power, min_sp, max_sp
            )

        return min_sp

    async def _apply_boost_mode(self) -> None:
        """Apply boost preset to all controllable heat pumps."""
        devices = self._config.devices
        device_payloads = self._get_device_payloads()

        # Turn on controllable devices
        for device in devices:
            if device.get(CONF_ALLOW_ON_OFF_CONTROL) and device.get(CONF_CLIMATE_ENTITY):
                await self._ensure_device_mode(device.get(CONF_CLIMATE_ENTITY), HVACMode.HEAT)

        # Refresh payloads
        device_payloads = self._get_device_payloads()

        # Set boost targets for all heating devices
        for index, device in enumerate(devices):
            entity_id = device.get(CONF_CLIMATE_ENTITY)
            if not entity_id:
                continue

            payload = device_payloads.get(entity_id, {}) or {}
            hvac_mode = str(payload.get("hvac_mode") or "").lower()

            if hvac_mode != HVACMode.HEAT.value:
                self._hp_modes[entity_id] = MODE_OFF
                continue

            current_temp = safe_float(payload.get("current_temperature"))
            if current_temp is not None:
                self._hp_modes[entity_id] = MODE_BOOST
                boost_target = self._calculate_mode_target(
                    MODE_BOOST, current_temp, device, index
                )
                _LOGGER.debug(
                    "Boost preset: Setting %s to mode=%s, target=%.1f°C",
                    entity_id, MODE_BOOST, boost_target,
                )
                await self._ensure_device_temperature(entity_id, boost_target)
            else:
                _LOGGER.warning("Boost preset: No current temperature for %s", entity_id)

        self.async_write_ha_state()
        self._emit_summary(devices, device_payloads)

    async def _apply_away_mode(self) -> None:
        """Apply away preset behavior."""
        devices = self._config.devices

        # Turn off assist pumps with control enabled
        for device in devices[1:]:
            if not device.get(CONF_ALLOW_ON_OFF_CONTROL):
                continue
            entity_id = str(device.get(CONF_CLIMATE_ENTITY) or "").strip()
            if not entity_id:
                continue

            await self._ensure_device_mode(entity_id, HVACMode.OFF)
            self._assist_controller.force_off(entity_id)

        await self._apply_staging()

    async def _apply_minimal_support_mode(self) -> None:
        """Apply minimal support preset behavior.

        Water heat pump is boosted, air heat pumps are set to minimal.
        """
        devices = self._config.devices
        device_payloads = self._get_device_payloads()

        # Process water device (boost mode)
        water_device_tuple = self._config.get_water_device()
        if water_device_tuple:
            device, index = water_device_tuple
            entity_id = device.get(CONF_CLIMATE_ENTITY)
            if entity_id:
                payload = device_payloads.get(entity_id, {}) or {}
                current_temp = safe_float(payload.get("current_temperature"))
                if current_temp is not None:
                    self._hp_modes[entity_id] = MODE_BOOST
                    boost_target = self._calculate_mode_target(
                        MODE_BOOST, current_temp, device, index
                    )
                    _LOGGER.debug(
                        "Minimal support preset: Water HP %s boosted to %.1f°C",
                        entity_id, boost_target,
                    )
                    await self._ensure_device_temperature(entity_id, boost_target)

        # Refresh payloads after water device changes
        device_payloads = self._get_device_payloads()

        # Process air devices (minimal mode)
        for assist_index, device in self._config.get_air_devices():
            entity_id = device.get(CONF_CLIMATE_ENTITY)
            if not entity_id:
                continue

            payload = device_payloads.get(entity_id, {}) or {}
            hvac_mode = str(payload.get("hvac_mode") or "").lower()

            if hvac_mode != HVACMode.HEAT.value:
                self._hp_modes[entity_id] = MODE_OFF
                self._assist_modes[entity_id] = MODE_OFF
                continue

            current_temp = safe_float(payload.get("current_temperature"))
            if current_temp is not None:
                self._hp_modes[entity_id] = MODE_MINIMAL
                self._assist_modes[entity_id] = MODE_MINIMAL
                minimal_target = self._calculate_mode_target(
                    MODE_MINIMAL, current_temp, device, assist_index
                )
                _LOGGER.debug(
                    "Minimal support preset: Air HP%d %s set to minimal at %.1f°C",
                    assist_index + 1, entity_id, minimal_target,
                )
                await self._ensure_device_temperature(entity_id, minimal_target)

        self.async_write_ha_state()
        self._emit_summary(devices, device_payloads)

    # --- Device Sync ---

    def _get_device_payloads(self) -> dict[str, dict[str, Any]]:
        """Get current device payloads from coordinator."""
        payloads: dict[str, dict[str, Any]] = {}
        coordinator_data = self.coordinator.data or {}
        for device in coordinator_data.get("devices", []):
            entity_id = device.get(CONF_CLIMATE_ENTITY)
            if entity_id:
                payloads[entity_id] = device
        return payloads

    async def _sync_devices(
        self,
        devices: list[dict[str, Any]],
        desired_devices: set[str],
        device_payloads: dict[str, dict[str, Any]],
        desired_targets: dict[str, float],
    ) -> None:
        """Sync device setpoints."""
        if self.hvac_mode == HVACMode.OFF:
            _LOGGER.debug("PowerClimate is OFF; skipping device sync")
            return

        for device in devices:
            entity_id = device.get(CONF_CLIMATE_ENTITY)
            if not entity_id or entity_id not in desired_devices:
                continue

            target = desired_targets.get(entity_id)
            if target is None:
                continue

            payload = device_payloads.get(entity_id, {}) or {}
            hvac_mode = str(payload.get("hvac_mode") or "").lower()

            if hvac_mode == HVACMode.HEAT.value:
                await self._ensure_device_temperature(entity_id, target)
            else:
                _LOGGER.debug(
                    "Skip setpoint for %s because mode=%s (not heating)",
                    entity_id, hvac_mode,
                )

    def _sync_state_listeners(self, entity_ids: set[str]) -> None:
        """Synchronize state change listeners."""
        current = set(self._hp_state_unsubs)

        # Remove stale listeners
        for entity_id in current - entity_ids:
            unsub = self._hp_state_unsubs.pop(entity_id, None)
            if unsub:
                unsub()

        # Add new listeners
        for entity_id in entity_ids - current:
            if not entity_id:
                continue
            unsub = async_track_state_change_event(
                self.hass, [entity_id], self._handle_hp_state_change
            )
            if unsub:
                self._hp_state_unsubs[entity_id] = unsub

    @callback
    def _handle_hp_state_change(self, event) -> None:
        """Handle heat pump state change events."""
        if self._pending_state_refresh:
            return

        entity_id = event.data.get("entity_id") if event and event.data else None
        new_state = event.data.get("new_state") if event and event.data else None
        old_state = event.data.get("old_state") if event and event.data else None

        # Handle setpoint forwarding
        if entity_id and entity_id in self._mirror_entities:
            self._maybe_forward_setpoint(entity_id, old_state, new_state)

        # Schedule coordinator refresh
        self._pending_state_refresh = True

        async def async_refresh_coordinator() -> None:
            try:
                await self.coordinator.async_request_refresh()
            finally:
                self._pending_state_refresh = False

        self.hass.async_create_task(async_refresh_coordinator())

    def _maybe_forward_setpoint(self, entity_id: str, old_state, new_state) -> None:
        """Forward setpoint changes to PowerClimate."""
        if new_state is None:
            return
        if self._state_context_is_integration(new_state):
            return

        changed, temperature = self._has_temperature_change(old_state, new_state)
        if not changed or temperature is None:
            return

        self.hass.async_create_task(
            self._forward_setpoint_to_powerclimate(temperature, entity_id)
        )

    def _state_context_is_integration(self, state) -> bool:
        """Check if state change originated from this integration."""
        if not state or not state.context:
            return False
        return state.context.id == self._integration_context.id

    def _has_temperature_change(
        self, old_state, new_state
    ) -> tuple[bool, float | None]:
        """Detect if temperature attribute changed."""
        new_temp = safe_float(
            (new_state.attributes if new_state else {}).get(ATTR_TEMPERATURE)
        )
        old_temp = safe_float(
            (old_state.attributes if old_state else {}).get(ATTR_TEMPERATURE)
        )

        if new_temp is None:
            return False, None
        if old_temp is not None and abs(new_temp - old_temp) < TEMPERATURE_CHANGE_THRESHOLD:
            return False, new_temp
        return True, new_temp

    async def _forward_setpoint_to_powerclimate(
        self, temperature: float, source_entity: str | None = None
    ) -> None:
        """Forward temperature setpoint to PowerClimate entity."""
        if not self.entity_id:
            return

        await self._call_climate_service(
            self.entity_id,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: self.entity_id, ATTR_TEMPERATURE: temperature},
            f"forwarding setpoint from {source_entity or 'unknown'}",
        )

    async def _call_climate_service(
        self,
        entity_id: str,
        service_name: str,
        service_data: dict[str, Any],
        action_description: str,
    ) -> None:
        """Call a climate service with error handling."""
        if self.hvac_mode == HVACMode.OFF:
            _LOGGER.debug(
                "PowerClimate is OFF; skipping %s for %s",
                action_description, entity_id,
            )
            return

        try:
            await asyncio.wait_for(
                self.hass.services.async_call(
                    CLIMATE_DOMAIN,
                    service_name,
                    service_data,
                    blocking=True,
                    context=self._integration_context,
                ),
                timeout=SERVICE_CALL_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
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

    async def _ensure_device_mode(self, entity_id: str, mode: HVACMode) -> None:
        """Ensure device is in the specified HVAC mode."""
        if self._device_modes.get(entity_id) == mode:
            return
        if self._recent_call(self._last_mode_call, entity_id):
            _LOGGER.debug("Skipping HVAC mode set for %s due to cooldown", entity_id)
            return

        await self._call_climate_service(
            entity_id,
            SERVICE_SET_HVAC_MODE,
            {ATTR_ENTITY_ID: entity_id, ATTR_HVAC_MODE: mode},
            "mode change",
        )
        self._device_modes[entity_id] = mode
        self._mark_call(self._last_mode_call, entity_id)

    async def _ensure_device_temperature(
        self, entity_id: str, temperature: float
    ) -> None:
        """Ensure device has the specified target temperature."""
        previous = self._device_targets.get(entity_id)
        if previous is not None and abs(previous - temperature) < SETPOINT_COMPARISON_THRESHOLD:
            return
        if self._recent_call(self._last_temp_call, entity_id):
            _LOGGER.debug("Skipping temperature set for %s due to cooldown", entity_id)
            return

        await self._call_climate_service(
            entity_id,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: entity_id, ATTR_TEMPERATURE: temperature},
            "temperature set",
        )
        self._device_targets[entity_id] = temperature
        self._mark_call(self._last_temp_call, entity_id)

    def _recent_call(self, store: dict[str, datetime], entity_id: str) -> bool:
        """Check if a recent call was made for an entity."""
        last_call = store.get(entity_id)
        if not last_call:
            return False
        return (
            datetime.now(timezone.utc) - last_call
        ).total_seconds() < MIN_SET_CALL_INTERVAL_SECONDS

    def _mark_call(self, store: dict[str, datetime], entity_id: str) -> None:
        """Mark a call timestamp for an entity."""
        store[entity_id] = datetime.now(timezone.utc)

    def set_power_budget(self, entity_id: str, power_watts: float) -> None:
        """Set power budget for a device (service API)."""
        self._power_manager.set_budget(entity_id, power_watts)

    def clear_power_budget(self, entity_id: str) -> None:
        """Clear power budget for a device (service API)."""
        self._power_manager.clear_budget(entity_id)

    def _emit_summary(
        self,
        devices: list[dict[str, Any]],
        device_payloads: dict[str, dict[str, Any]],
    ) -> None:
        """Emit summary payload via dispatcher."""
        target_temp = self._current_target_temperature()
        hp_status = self._build_hp_status(devices, device_payloads)

        payload = {
            "mode": self._mode_state,
            "stage_count": len(self._active_devices),
            "active_devices": sorted(self._active_devices),
            "delta": self._delta,
            "room_temperature": self.current_temperature,
            "room_sensor_values": self.coordinator.data.get(CONF_ROOM_SENSOR_VALUES),
            "derivative": self.coordinator.data.get("room_derivative"),
            "room_eta_hours": self._room_eta_hours,
            "room_eta_minutes": (
                self._room_eta_hours * 60.0 if self._room_eta_hours is not None else None
            ),
            "water_temperature": self._water_temperature,
            "water_derivative": self.coordinator.data.get("water_derivative"),
            "hp_status": hp_status,
            "target_temperature": target_temp,
            "preset_mode": self._attr_preset_mode,
            "assist_timer_seconds": self._config.assist_timer_seconds,
            "assist_on_eta_threshold_minutes": self._config.assist_on_eta_threshold_minutes,
            "assist_off_eta_threshold_minutes": self._config.assist_off_eta_threshold_minutes,
            "assist_min_on_minutes": self._config.assist_min_on_minutes,
            "assist_min_off_minutes": self._config.assist_min_off_minutes,
            **self._power_manager.get_diagnostics(),
        }

        self._summary_payload = payload

        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id)
        if entry_data is not None:
            entry_data["summary_payload"] = payload

        async_dispatcher_send(self.hass, self._summary_signal, payload)

    def _build_hp_status(
        self,
        devices: list[dict[str, Any]],
        device_payloads: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Build HP status list for summary payload."""
        status: list[dict[str, Any]] = []
        coordinator_data = self.coordinator.data or {}

        for index, device in enumerate(devices):
            entity_id = device.get(CONF_CLIMATE_ENTITY)
            if not entity_id:
                continue

            payload = device_payloads.get(entity_id, {}) or {}
            hvac_mode = str(payload.get("hvac_mode") or "").lower()
            is_running = hvac_mode and hvac_mode != HVACMode.OFF.value

            # Water derivative
            if index == 0:
                water_derivative = safe_float(coordinator_data.get("water_derivative"))
            else:
                water_derivative = safe_float(payload.get("water_derivative"))

            # Base info
            hp_info: dict[str, Any] = {
                "role": f"hp{index + 1}",
                "name": device.get(CONF_DEVICE_NAME) or f"HP{index + 1}",
                "entity_id": entity_id,
                "active": entity_id in self._active_devices or is_running,
                "hvac_mode": payload.get("hvac_mode"),
                "assist_mode": self._assist_modes.get(entity_id, "off") if index > 0 else None,
                "powerclimate_mode": self._hp_modes.get(entity_id, MODE_OFF),
                "current_temperature": safe_float(payload.get("current_temperature")),
                "target_temperature": safe_float(payload.get("target_temperature")),
                "temperature_derivative": safe_float(payload.get("temperature_derivative")),
                "water_temperature": safe_float(payload.get("water_temperature")),
                "water_derivative": water_derivative,
                "eta_hours": compute_eta_hours(
                    (
                        safe_float(payload.get("target_temperature"))
                        - safe_float(payload.get("current_temperature"))
                    )
                    if payload.get("target_temperature") is not None
                    and payload.get("current_temperature") is not None
                    else None,
                    safe_float(payload.get("temperature_derivative")),
                ),
                "energy": safe_float(payload.get("energy")),
            }

            # Assist-specific info
            if index > 0:
                hp_info["allow_on_off_control"] = device.get(CONF_ALLOW_ON_OFF_CONTROL, False)
                hp_info.update(self._assist_controller.get_hp_status_info(entity_id))

            status.append(hp_info)

        return status

    def _current_target_temperature(self) -> float | None:
        """Get current target temperature from state or internal."""
        state = self.hass.states.get(self.entity_id)
        if state:
            value = state.attributes.get(ATTR_TEMPERATURE)
            if value is not None:
                return float(value)
        return self._target_temperature
