"""PowerClimate climate entity."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    SERVICE_SET_TEMPERATURE,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import staging
from .assist_controller import AssistPumpController
from .config_accessor import ConfigAccessor
from .const import (
    CONF_ALLOW_ON_OFF_CONTROL,
    CONF_CLIMATE_ENTITY,
    CONF_ROOM_SENSOR_VALUES,
    CONF_ROOM_TEMPERATURE_KEY,
    COORDINATOR,
    DEFAULT_TARGET_TEMPERATURE,
    DOMAIN,
    MODE_BOOST,
    MODE_OFF,
    PRESET_AWAY,
    PRESET_BOOST,
    PRESET_MAIN_ONLY,
    PRESET_NONE,
    PRESET_SUPPLY_ADVICE,
    TEMPERATURE_CHANGE_THRESHOLD,
)
from .device_commands import DeviceCommander
from .helpers import (
    integration_device_info,
    summary_signal,
)
from .mode_targets import SetpointLimits, calculate_mode_target
from .summary_payload import build_hp_status, build_supply_advice_summary
from .supply_control import SupplyController
from .timer_storage import TimerStorage
from .utils import safe_float

_LOGGER = logging.getLogger(__name__)


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


def _changed_setpoint(old_state, new_state) -> float | None:
    """Return the new setpoint of a state change, or None when it did not change."""
    new_temp = safe_float((new_state.attributes if new_state else {}).get(ATTR_TEMPERATURE))
    old_temp = safe_float((old_state.attributes if old_state else {}).get(ATTR_TEMPERATURE))
    if new_temp is None:
        return None
    if old_temp is not None and abs(new_temp - old_temp) < TEMPERATURE_CHANGE_THRESHOLD:
        return None
    return new_temp


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
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL]
    # Bulky diagnostics that change every update; keep them out of the recorder.
    _unrecorded_attributes = frozenset({
        "hp_status",
        "active_devices",
        "room_sensor_values",
    })

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator) -> None:
        """Initialize the PowerClimate climate entity."""
        super().__init__(coordinator)
        self.hass = hass
        self._entry = entry
        # The climate entity is the device's main feature and takes its name.
        self._attr_has_entity_name = True
        self._attr_name = None
        self._attr_translation_key = "powerclimate"
        self._attr_unique_id = f"powerclimate_{entry.entry_id}"
        self._attr_device_info = integration_device_info(entry)
        self._attr_hvac_mode = HVACMode.HEAT
        self._attr_preset_mode = PRESET_NONE
        self._target_temperature = DEFAULT_TARGET_TEMPERATURE
        self._previous_target: float | None = None
        self._config = ConfigAccessor(entry)
        self._assist_controller = AssistPumpController(
            self._config, hass=hass, storage=TimerStorage(hass, entry.entry_id)
        )
        # Steers the water heat pump's supply temperature in the supply advice preset.
        self._supply = SupplyController(self._config)
        self._commands = DeviceCommander(
            hass, lambda: self.hvac_mode == HVACMode.OFF
        )

        self._active_devices: set[str] = set()
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
        self._mirror_entities: set[str] = set()
        self._water_overshoot_since: datetime | None = None
        self._coordinator_update_pending = False
        self._coordinator_update_task: asyncio.Task[None] | None = None

    @property
    def preset_modes(self) -> list[str] | None:
        """Return list of available preset modes."""
        modes = [PRESET_NONE, PRESET_BOOST, PRESET_AWAY, PRESET_MAIN_ONLY]
        if self._config.supply_advice_enabled:
            modes.append(PRESET_SUPPLY_ADVICE)
        return modes

    @property
    def current_temperature(self) -> float | None:
        """Return current room temperature."""
        return safe_float(self.coordinator.data.get(CONF_ROOM_TEMPERATURE_KEY))

    @property
    def target_temperature(self) -> float | None:
        """Return target temperature."""
        return self._target_temperature

    def diagnostics(self) -> dict[str, Any]:
        """Return internal control state for the diagnostics download."""
        return {
            "mode_state": self._mode_state,
            "previous_target": self._previous_target,
            "config": self._config.to_dict(),
            "assist_timers": {
                entity_id: asdict(state)
                for entity_id, state in self._assist_controller.timer_states.items()
            },
        }

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        return dict(self._summary_payload or {})

    async def async_added_to_hass(self) -> None:
        """Handle entity being added to Home Assistant."""
        await super().async_added_to_hass()

        # Load persisted timer states
        await self._assist_controller.async_load_states()

        last_state = await self.async_get_last_state()
        if last_state is not None:
            # Restore HVAC mode (the climate entity state IS the hvac_mode)
            restored_hvac = last_state.state
            if restored_hvac in (HVACMode.HEAT.value, HVACMode.COOL.value, HVACMode.OFF.value):
                self._attr_hvac_mode = HVACMode(restored_hvac)

            # Restore target temperature
            value = last_state.attributes.get(ATTR_TEMPERATURE)
            if value is not None:
                try:
                    self._target_temperature = float(value)
                except (TypeError, ValueError):
                    pass

            # Restore preset mode — validate against currently available presets
            restored_preset = last_state.attributes.get("preset_mode")
            if restored_preset is not None:
                available = self.preset_modes or []
                if restored_preset in available:
                    self._attr_preset_mode = restored_preset
                else:
                    _LOGGER.debug(
                        "Preset '%s' from last state is no longer available; "
                        "defaulting to none",
                        restored_preset,
                    )
        await self._apply_staging()

    async def async_will_remove_from_hass(self) -> None:
        """Handle entity removal from Home Assistant."""
        # Save timer states before removal
        await self._assist_controller.async_save_states()

        for unsub in self._hp_state_unsubs.values():
            unsub()
        self._hp_state_unsubs.clear()
        if self._coordinator_update_task is not None:
            self._coordinator_update_task.cancel()
            self._coordinator_update_task = None
        await super().async_will_remove_from_hass()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle coordinator data update."""
        if (
            self._coordinator_update_task is not None
            and not self._coordinator_update_task.done()
        ):
            self._coordinator_update_pending = True
            return

        self._coordinator_update_task = self.hass.async_create_task(
            self._async_process_update()
        )

    async def _async_process_update(self) -> None:
        """Process coordinator updates asynchronously without overlap."""
        try:
            while True:
                self._coordinator_update_pending = False
                await self._apply_staging()
                super()._handle_coordinator_update()
                if not self._coordinator_update_pending:
                    break
        finally:
            self._coordinator_update_task = None

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
        if hvac_mode != self._attr_hvac_mode:
            self._supply.reset()
        self._attr_hvac_mode = hvac_mode
        if self._attr_preset_mode != PRESET_NONE:
            self._attr_preset_mode = PRESET_NONE
            self._previous_target = None

        await self._apply_staging()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set preset mode."""
        # Accept legacy title-cased preset values.
        preset_mode = str(preset_mode or PRESET_NONE).strip().lower()
        if preset_mode not in self.preset_modes:
            return
        if preset_mode != self._attr_preset_mode:
            # Start the supply-temperature control afresh in the new preset.
            self._supply.reset()

        if preset_mode == PRESET_BOOST:
            await self._enter_boost_mode()
        elif preset_mode == PRESET_AWAY:
            await self._enter_away_mode()
        else:
            await self._enter_staged_preset(preset_mode)

    async def _enter_boost_mode(self) -> None:
        """Enter boost preset mode."""
        if self._attr_preset_mode == PRESET_BOOST:
            return

        self._attr_preset_mode = PRESET_BOOST
        # Preserve current HVAC mode (HEAT or COOL) so boost works for cooling too
        if self._attr_hvac_mode == HVACMode.OFF:
            self._attr_hvac_mode = HVACMode.HEAT
        await self._apply_boost_mode()

    async def _enter_away_mode(self) -> None:
        """Enter away preset mode."""
        if self._attr_preset_mode == PRESET_AWAY:
            return
        self._previous_target = self._target_temperature

        if self._is_cooling():
            # Away+Cool: stop cooling (set target to max so ACs stay off)
            self._target_temperature = self._config.max_setpoint
        else:
            # Away+Heat: minimal heating
            self._target_temperature = self._config.min_setpoint
            self._attr_hvac_mode = HVACMode.HEAT

        self._attr_preset_mode = PRESET_AWAY

        await self._apply_away_mode()

    async def _enter_staged_preset(self, preset_mode: str) -> None:
        """Enter none, main only or supply advice; the staging logic runs these."""
        if self._attr_preset_mode == preset_mode:
            return

        # Restore the target when coming from Away.
        if self._attr_preset_mode == PRESET_AWAY and self._previous_target is not None:
            self._target_temperature = self._previous_target
        self._previous_target = None

        self._attr_preset_mode = preset_mode
        # The advice is a supply temperature for heating; in Cool mode the
        # supply advice preset behaves like none.
        if preset_mode == PRESET_SUPPLY_ADVICE and self._attr_hvac_mode == HVACMode.OFF:
            self._attr_hvac_mode = HVACMode.HEAT
        await self._apply_staging()

    async def _apply_staging(self) -> None:
        """Apply staging logic to all heat pumps."""
        devices = self._config.devices
        device_payloads = self._get_device_payloads()
        self._mirror_entities = set(self._config.mirror_thermostats)
        # Filled again by the supply controller when it runs.
        self._supply.clear_summary()
        if self._attr_preset_mode == PRESET_BOOST:
            await self._apply_boost_mode()
            return
        if (
            self._attr_preset_mode == PRESET_SUPPLY_ADVICE
            and not self._config.supply_advice_enabled
        ):
            self._attr_preset_mode = PRESET_NONE
        if not devices:
            await self._handle_no_devices(device_payloads)
            return
        hvac_disabled = (
            self._attr_hvac_mode == HVACMode.OFF
            or self._target_temperature is None
        )

        if self._attr_hvac_mode == HVACMode.OFF:
            await self._turn_off_water_device(device_payloads)

        # Calculate room state
        room_temp = self.current_temperature
        self._update_room_state(room_temp)

        # Initialize tracking
        desired_devices: set[str] = set()
        desired_targets: dict[str, float] = {}
        water_temp = None
        mode = "off"

        if not hvac_disabled:
            room_at_target = staging.room_at_target(
                room_temp, self._target_temperature, self._is_cooling()
            )

            # Process water device
            water_result = await self._process_water_device(
                device_payloads, desired_devices, desired_targets
            )
            if water_result:
                water_temp, mode = water_result

            # Assists use the smoothed water temperature, so a short spike
            # (e.g. a boiler making hot water) does not turn them on.
            air_mode = await self._process_air_devices(
                room_temp,
                room_at_target,
                self._water_filtered() if water_result else None,
                device_payloads,
                desired_devices,
                desired_targets,
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
        self._attr_hvac_action = staging.hvac_action(
            self._attr_hvac_mode, bool(self._active_devices)
        )

        self.async_write_ha_state()
        self._emit_summary(devices, device_payloads)

    def _update_room_state(self, room_temp: float | None) -> None:
        """Update room temperature delta and ETA."""
        target = self._target_temperature
        self._delta = (
            room_temp - target if room_temp is not None and target is not None else None
        )
        self._room_eta_hours = staging.room_eta_hours(
            room_temp,
            target,
            safe_float(self.coordinator.data.get("room_derivative")),
            self._is_cooling(),
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
        device_payloads: dict[str, dict[str, Any]],
        desired_devices: set[str],
        desired_targets: dict[str, float],
    ) -> tuple[float | None, str] | None:
        """Process water-based heat pump.

        In cool mode the water HP is turned off (water HPs cannot cool).

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

        payload = device_payloads.get(entity_id, {})
        water_temp = safe_float(payload.get("water_temperature"))

        # Water HP cannot cool; turn it off while cooling mode is active
        if self._is_cooling():
            hvac_mode = str(payload.get("hvac_mode") or "").lower()
            if device.get(CONF_ALLOW_ON_OFF_CONTROL) and hvac_mode != HVACMode.OFF.value:
                await self._commands.ensure_mode(entity_id, HVACMode.OFF)
            self._hp_modes[entity_id] = MODE_OFF
            return water_temp, "off"

        current_temp = safe_float(payload.get("current_temperature"))
        current_target = safe_float(payload.get("target_temperature"))
        current_power = safe_float(payload.get("energy"))
        hvac_mode = str(payload.get("hvac_mode") or "").lower()
        is_running = hvac_mode == HVACMode.HEAT.value

        if await self._handle_water_overshoot_control(device, entity_id, is_running):
            self._hp_modes[entity_id] = MODE_OFF
            return water_temp, "off"

        if (
            device.get(CONF_ALLOW_ON_OFF_CONTROL)
            and hvac_mode == HVACMode.OFF.value
            and not self._water_demand()
        ):
            self._hp_modes[entity_id] = MODE_OFF
            return water_temp, "off"

        desired_devices.add(entity_id)
        if device.get(CONF_ALLOW_ON_OFF_CONTROL) and hvac_mode == HVACMode.OFF.value:
            await self._commands.ensure_mode(entity_id, HVACMode.HEAT)
            device_payloads.update(self._get_device_payloads())
            payload = device_payloads.get(entity_id, payload)
            current_temp = safe_float(payload.get("current_temperature"))
            current_target = safe_float(payload.get("target_temperature"))
            current_power = safe_float(payload.get("energy"))
            water_temp = safe_float(payload.get("water_temperature"))

        hp_mode = staging.water_mode(self._attr_preset_mode)
        self._hp_modes[entity_id] = hp_mode

        target = self._calculate_mode_target(
            hp_mode,
            current_temp,
            device,
            index,
            current_power,
            current_target,
            water_temp,
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

    async def _handle_water_overshoot_control(
        self,
        device: dict[str, Any],
        entity_id: str,
        is_running: bool,
    ) -> bool:
        """Optionally turn the water device off after sustained overshoot."""
        if not device.get(CONF_ALLOW_ON_OFF_CONTROL) or not self._water_overshoot():
            self._water_overshoot_since = None
            return False

        now = datetime.now(UTC)
        if self._water_overshoot_since is None:
            self._water_overshoot_since = now
            return False

        elapsed = (now - self._water_overshoot_since).total_seconds()
        if elapsed < self._config.assist_timer_seconds:
            return False

        if is_running:
            await self._commands.ensure_mode(entity_id, HVACMode.OFF)

        return True

    def _water_filtered(self) -> float | None:
        """Return the coordinator's smoothed water temperature."""
        return safe_float((self.coordinator.data or {}).get("water_temperature_filtered"))

    def _water_overshoot(self) -> bool:
        """Return True when the room is above target plus the maximum overshoot."""
        return staging.water_overshoot(
            self.current_temperature,
            self._target_temperature,
            self._config.maximum_overshoot,
            self._is_cooling(),
        )

    def _water_demand(self) -> bool:
        """Return True when the water heat pump should turn on."""
        return staging.water_demand(
            self.current_temperature, self._target_temperature, self._is_cooling()
        )

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
            payload = device_payloads.get(entity_id, {}) or {}
            hvac_mode = str(payload.get("hvac_mode") or "").lower()
            is_running = bool(hvac_mode) and hvac_mode != HVACMode.OFF.value

            if (
                self._attr_preset_mode == PRESET_MAIN_ONLY
                and entity_id != self._main_entity_id()
            ):
                await self._hold_assist_off(device, entity_id, is_running)
                continue

            # Update assist controller timers
            current_hvac_mode = self._attr_hvac_mode.value if self._attr_hvac_mode else "heat"
            self._assist_controller.update_timers(
                entity_id,
                room_temp,
                self._target_temperature,
                self._room_eta_hours,
                water_temp,
                room_derivative,
                is_running,
                hvac_mode=current_hvac_mode,
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
            current_target = safe_float(payload.get("target_temperature"))
            current_power = safe_float(payload.get("energy"))
            timer_state = self._assist_controller.get_timer_state(entity_id)

            assist_mode = staging.assist_mode(
                self._attr_preset_mode,
                room_at_target,
                timer_state.off_timer_seconds,
                bool(device.get(CONF_ALLOW_ON_OFF_CONTROL)),
            )
            self._hp_modes[entity_id] = assist_mode

            target = self._calculate_mode_target(
                assist_mode,
                current_temp,
                device,
                assist_index,
                current_power,
                current_target,
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

    def _main_entity_id(self) -> str | None:
        """Return the main heat pump: the water one, otherwise the first air one."""
        water = self._config.get_water_device()
        if water:
            return water[0].get(CONF_CLIMATE_ENTITY)
        air_devices = self._config.get_air_devices()
        if air_devices:
            return air_devices[0][1].get(CONF_CLIMATE_ENTITY)
        return None

    async def _hold_assist_off(
        self,
        device: dict[str, Any],
        entity_id: str,
        is_running: bool,
    ) -> None:
        """Main only: turn a non-main pump off when allowed, otherwise leave it alone."""
        self._assist_modes[entity_id] = MODE_OFF
        self._hp_modes[entity_id] = MODE_OFF
        if not device.get(CONF_ALLOW_ON_OFF_CONTROL) or not is_running:
            return
        if await self._commands.ensure_mode(entity_id, HVACMode.OFF):
            self._assist_controller.force_off(entity_id)

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
        current_hvac_mode = self._attr_hvac_mode.value if self._attr_hvac_mode else "heat"
        payload = device_payloads.get(entity_id, {}) or {}
        device_hvac_mode = str(payload.get("hvac_mode") or "").lower()
        supported_modes: list[str] = list(payload.get("hvac_modes") or [])

        # Handle mode mismatch: device is running but in the wrong mode.
        # This happens e.g. when the user switches HEAT→COOL or COOL→HEAT.
        # Switch to the desired mode if supported; otherwise turn the device off.
        if is_running and device_hvac_mode not in (HVACMode.OFF.value, current_hvac_mode):
            if not supported_modes or current_hvac_mode in supported_modes:
                target_mode = HVACMode.COOL if current_hvac_mode == "cool" else HVACMode.HEAT
                _LOGGER.info(
                    "Switching %s from %s to %s due to mode change",
                    entity_id, device_hvac_mode, current_hvac_mode,
                )
                await self._commands.ensure_mode(entity_id, target_mode, force=True)
                device_payloads.update(self._get_device_payloads())
                return True
            _LOGGER.info(
                "Turning OFF %s: mode %s not supported (supported: %s)",
                entity_id, current_hvac_mode, supported_modes,
            )
            if not await self._commands.ensure_mode(entity_id, HVACMode.OFF):
                return True
            self._assist_controller.record_turn_off(entity_id)
            device_payloads.update(self._get_device_payloads())
            return False

        action, reason = self._assist_controller.evaluate_action(
            entity_id, is_running, hvac_mode=current_hvac_mode
        )

        if action in ("heat", "cool") and not is_running:
            # Don't turn on if the device doesn't support the requested mode.
            if supported_modes and action not in supported_modes:
                _LOGGER.debug(
                    "Not turning on %s: mode %s not in supported modes %s",
                    entity_id, action, supported_modes,
                )
                return False
            target_mode = HVACMode.COOL if action == "cool" else HVACMode.HEAT
            _LOGGER.info("Turning ON %s (mode=%s): condition=%s", entity_id, action, reason)
            if not await self._commands.ensure_mode(entity_id, target_mode):
                return False
            self._assist_controller.record_turn_on(entity_id)
            device_payloads.update(self._get_device_payloads())
            return True

        if action == "off" and is_running:
            _LOGGER.info("Turning OFF %s: condition=%s", entity_id, reason)
            if not await self._commands.ensure_mode(entity_id, HVACMode.OFF):
                return True
            self._assist_controller.record_turn_off(entity_id)
            device_payloads.update(self._get_device_payloads())
            return False

        return is_running

    def _is_cooling(self) -> bool:
        """Return True when the integration is in cooling mode."""
        return getattr(self, "_attr_hvac_mode", HVACMode.HEAT) == HVACMode.COOL

    def _calculate_mode_target(
        self,
        mode: str,
        current_temp: float | None,
        device: dict[str, Any],
        index: int,
        current_power: float | None = None,
        current_target: float | None = None,
        water_temp: float | None = None,
    ) -> float:
        """Calculate target temperature for a given mode; see calculate_mode_target."""
        cooling = self._is_cooling()
        if cooling:
            lower_offset = self._config.get_device_lower_offset_cooling(device, index)
            upper_offset = self._config.get_device_upper_offset_cooling(device, index)
        else:
            lower_offset = self._config.get_device_lower_offset(device, index)
            upper_offset = self._config.get_device_upper_offset(device, index)
        limits = SetpointLimits(
            self._config.min_setpoint, self._config.max_setpoint, lower_offset, upper_offset
        )

        return calculate_mode_target(
            mode,
            current_temp,
            limits,
            target_temperature=self._target_temperature,
            is_cooling=cooling,
            current_target=current_target,
            supply_correction=lambda: self._supply.correction(
                source=self._config.supply_advice_sensor,
                advice=self._read_supply_advice()[0],
                limits=limits,
                current_temp=current_temp,
                current_target=current_target,
                water_temp=water_temp,
                water_filtered=self._water_filtered(),
                spike=bool((self.coordinator.data or {}).get("water_spike")),
                power=current_power,
                overshoot=self._water_overshoot(),
                now=datetime.now(UTC),
            ),
        )

    def _read_supply_advice(self) -> tuple[float | None, Any]:
        """Return the advised supply temperature and the sensor's raw state."""
        sensor_id = self._config.supply_advice_sensor
        if not sensor_id:
            return None, None

        state = self.hass.states.get(sensor_id)
        if state is None:
            return None, None

        return safe_float(state.state), state.state

    async def _apply_boost_mode(self) -> None:
        """Apply boost preset to all controllable heat pumps."""
        devices = self._config.devices

        # Target HVAC mode depends on current heat/cool selection
        active_hvac = (
            self._attr_hvac_mode if self._attr_hvac_mode != HVACMode.OFF else HVACMode.HEAT
        )

        # Turn on controllable devices (skip water HP in cooling mode)
        for index, device in enumerate(devices):
            if not device.get(CONF_ALLOW_ON_OFF_CONTROL) or not device.get(CONF_CLIMATE_ENTITY):
                continue
            if self._is_cooling() and self._config.is_water_device(device, index):
                continue
            await self._commands.ensure_mode(device.get(CONF_CLIMATE_ENTITY), active_hvac)

        device_payloads = self._get_device_payloads()

        # Set boost targets for all active devices
        for index, device in enumerate(devices):
            entity_id = device.get(CONF_CLIMATE_ENTITY)
            if not entity_id:
                continue

            # Water HP cannot cool; skip in cooling mode
            if self._is_cooling() and self._config.is_water_device(device, index):
                self._hp_modes[entity_id] = MODE_OFF
                continue

            payload = device_payloads.get(entity_id, {}) or {}
            device_hvac_mode = str(payload.get("hvac_mode") or "").lower()

            if device_hvac_mode not in (HVACMode.HEAT.value, HVACMode.COOL.value):
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
                await self._commands.ensure_temperature(entity_id, boost_target)
            else:
                _LOGGER.warning("Boost preset: No current temperature for %s", entity_id)

        self.async_write_ha_state()
        self._emit_summary(devices, device_payloads)

    async def _apply_away_mode(self) -> None:
        """Apply away preset behavior.

        In heating mode: water HP runs at minimum, assist pumps turn off.
        In cooling mode: all devices turn off (no cooling while away).
        """
        # Turn off assist pumps with control enabled
        for _index, device in self._config.get_air_devices():
            if not device.get(CONF_ALLOW_ON_OFF_CONTROL):
                continue
            entity_id = str(device.get(CONF_CLIMATE_ENTITY) or "").strip()
            if not entity_id:
                continue

            await self._commands.ensure_mode(entity_id, HVACMode.OFF)
            self._assist_controller.force_off(entity_id)

        await self._apply_staging()

    async def _turn_off_water_device(
        self,
        device_payloads: dict[str, dict[str, Any]],
    ) -> None:
        """Turn off the water device when PowerClimate is OFF.

        Only when the device allows on/off control; otherwise the user keeps
        control and can run it by hand while PowerClimate is off.
        """
        water_device_tuple = self._config.get_water_device()
        if not water_device_tuple:
            return

        device, _index = water_device_tuple
        entity_id = str(device.get(CONF_CLIMATE_ENTITY) or "").strip()
        if not entity_id:
            return

        payload = dict(device_payloads.get(entity_id, {}) or {})
        hvac_mode = str(payload.get("hvac_mode") or "").lower()
        if device.get(CONF_ALLOW_ON_OFF_CONTROL) and hvac_mode != HVACMode.OFF.value:
            await self._commands.ensure_mode(
                entity_id,
                HVACMode.OFF,
                allow_when_off=True,
                force=True,
            )
            payload["hvac_mode"] = HVACMode.OFF.value
            device_payloads[entity_id] = payload

        self._hp_modes[entity_id] = MODE_OFF

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

            if hvac_mode in (HVACMode.HEAT.value, HVACMode.COOL.value):
                await self._commands.ensure_temperature(entity_id, target)
            else:
                _LOGGER.debug(
                    "Skip setpoint for %s because mode=%s (not active)",
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
        entity_id = event.data.get("entity_id") if event and event.data else None
        new_state = event.data.get("new_state") if event and event.data else None
        old_state = event.data.get("old_state") if event and event.data else None

        # Handle setpoint forwarding (never skipped by a pending refresh)
        if entity_id and entity_id in self._mirror_entities:
            self._maybe_forward_setpoint(entity_id, old_state, new_state)

        if self._pending_state_refresh:
            return

        # Schedule coordinator refresh
        self._pending_state_refresh = True

        async def async_refresh_coordinator() -> None:
            try:
                await self.coordinator.async_request_refresh()
            finally:
                self._pending_state_refresh = False

        self.hass.async_create_task(async_refresh_coordinator())

    def _maybe_forward_setpoint(self, entity_id: str, old_state, new_state) -> None:
        """Forward a setpoint change of a mirrored thermostat to PowerClimate."""
        if new_state is None or self._commands.is_own_state(new_state):
            return

        temperature = _changed_setpoint(old_state, new_state)
        if temperature is None or not self.entity_id:
            return

        self.hass.async_create_task(
            self._commands.call_service(
                self.entity_id,
                SERVICE_SET_TEMPERATURE,
                {ATTR_ENTITY_ID: self.entity_id, ATTR_TEMPERATURE: temperature},
                f"forwarding setpoint from {entity_id}",
            )
        )

    def _emit_summary(
        self,
        devices: list[dict[str, Any]],
        device_payloads: dict[str, dict[str, Any]],
    ) -> None:
        """Emit summary payload via dispatcher."""
        data = self.coordinator.data or {}
        hp_status = build_hp_status(
            devices,
            device_payloads,
            data,
            is_water_device=self._config.is_water_device,
            active_devices=self._active_devices,
            assist_modes=self._assist_modes,
            hp_modes=self._hp_modes,
            assist_status=self._assist_controller.get_hp_status_info,
        )
        advised_temp, raw_state = self._read_supply_advice()

        payload = {
            "mode": self._mode_state,
            "hvac_mode": self._attr_hvac_mode.value if self._attr_hvac_mode else None,
            "stage_count": len(self._active_devices),
            "active_devices": sorted(self._active_devices),
            "delta": self._delta,
            "room_temperature": self.current_temperature,
            "room_sensor_values": data.get(CONF_ROOM_SENSOR_VALUES),
            "derivative": data.get("room_derivative"),
            "room_eta_hours": self._room_eta_hours,
            "room_eta_minutes": (
                self._room_eta_hours * 60.0 if self._room_eta_hours is not None else None
            ),
            "water_temperature": self._water_temperature,
            "water_temperature_filtered": data.get("water_temperature_filtered"),
            "water_spike": data.get("water_spike"),
            "water_derivative": data.get("water_derivative"),
            "hp_status": hp_status,
            "target_temperature": self._target_temperature,
            "preset_mode": self._attr_preset_mode,
            **build_supply_advice_summary(
                self._config.supply_advice_sensor, advised_temp, raw_state
            ),
            **self._supply.summary,
        }

        self._summary_payload = payload

        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id)
        if entry_data is not None:
            entry_data["summary_payload"] = payload

        async_dispatcher_send(self.hass, self._summary_signal, payload)
