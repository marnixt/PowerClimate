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
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ALLOW_ON_OFF_CONTROL,
    CONF_ASSIST_MIN_OFF_MINUTES,
    CONF_ASSIST_MIN_ON_MINUTES,
    CONF_ASSIST_OFF_ETA_THRESHOLD_MINUTES,
    CONF_ASSIST_ON_ETA_THRESHOLD_MINUTES,
    CONF_ASSIST_STALL_TEMP_DELTA,
    CONF_ASSIST_TIMER_SECONDS,
    CONF_ASSIST_WATER_TEMP_THRESHOLD,
    CONF_CLIMATE_ENTITY,
    CONF_COPY_SETPOINT_TO_POWERCLIMATE,
    CONF_DEVICE_NAME,
    CONF_DEVICES,
    CONF_HOUSE_POWER_SENSOR,
    CONF_LOWER_SETPOINT_OFFSET,
    CONF_MAX_SETPOINT_OVERRIDE,
    CONF_MIN_SETPOINT_OVERRIDE,
    CONF_ROOM_SENSOR_VALUES,
    CONF_ROOM_TEMPERATURE_KEY,
    CONF_UPPER_SETPOINT_OFFSET,
    COORDINATOR,
    DEFAULT_ASSIST_MIN_OFF_MINUTES,
    DEFAULT_ASSIST_MIN_ON_MINUTES,
    DEFAULT_ASSIST_OFF_ETA_THRESHOLD_MINUTES,
    DEFAULT_ASSIST_ON_ETA_THRESHOLD_MINUTES,
    DEFAULT_ASSIST_STALL_TEMP_DELTA,
    DEFAULT_ASSIST_TIMER_SECONDS,
    DEFAULT_ASSIST_WATER_TEMP_THRESHOLD,
    DEFAULT_LOWER_SETPOINT_OFFSET_ASSIST,
    DEFAULT_LOWER_SETPOINT_OFFSET_HP1,
    DEFAULT_MAX_SETPOINT,
    DEFAULT_MIN_SETPOINT,
    DEFAULT_POWER_BUDGET_UPDATE_INTERVAL_SECONDS,
    DEFAULT_POWER_MAX_BUDGET_PER_DEVICE_W,
    DEFAULT_POWER_MIN_BUDGET_W,
    DEFAULT_POWER_MODE_ADJUSTMENT_INTERVAL_SECONDS,
    DEFAULT_POWER_MODE_DEADBAND_PERCENT,
    DEFAULT_POWER_MODE_STEP_SIZE,
    DEFAULT_POWER_SURPLUS_RESERVE_W,
    DEFAULT_UPPER_SETPOINT_OFFSET_ASSIST,
    DEFAULT_UPPER_SETPOINT_OFFSET_HP1,
    DOMAIN,
    MIN_SET_CALL_INTERVAL_SECONDS,
    MODE_BOOST,
    MODE_MINIMAL,
    MODE_OFF,
    MODE_POWER,
    MODE_SETPOINT,
    SERVICE_CALL_TIMEOUT_SECONDS,
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


def _parse_device_offset(value: Any) -> float | None:
    """Parse an offset while preserving a leading -0 string."""
    if value is None:
        return None

    raw_str = str(value).strip()
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None

    if parsed == 0 and raw_str.startswith("-0"):
        return -0.0

    return parsed


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
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
    )
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_preset_modes = ["none", "boost", "Solar"]

    def __init__(self, hass, entry, coordinator):
        super().__init__(coordinator)
        self.hass = hass
        self._entry = entry
        self._attr_name = entry_friendly_name(entry)
        self._attr_unique_id = f"powerclimate_{entry.entry_id}"
        self._attr_device_info = integration_device_info(entry)
        self._attr_hvac_mode = HVACMode.HEAT
        self._target_temperature = DEFAULT_TARGET_TEMPERATURE
        self._attr_preset_mode = "none"
        self._previous_target: float | None = None
        self._active_devices: set[str] = set()
        self._device_modes: dict[str, HVACMode] = {}
        self._device_targets: dict[str, float] = {}
        self._mode_state = "off"
        self._delta: float | None = None
        self._summary_signal = summary_signal(entry.entry_id)
        self._water_temperature: float | None = None
        self._summary_payload: dict[str, Any] | None = None
        self._room_eta_hours: float | None = None
        self._assist_modes: dict[str, str] = {}
        # Heat pump mode tracking: explicit modes for each device
        self._hp_modes: dict[str, str] = {}  # entity_id -> MODE_*
        self._hp_state_unsubs: dict[str, Callable[[], None]] = {}
        self._pending_state_refresh = False
        self._last_mode_call: dict[str, datetime] = {}
        self._last_temp_call: dict[str, datetime] = {}
        self._copy_enabled_entities: set[str] = set()
        self._integration_context = Context()
        self._eta_exceeded_since: datetime | None = None
        # In-memory timers for assist pump ON/OFF control (seconds)
        self._assist_on_timers: dict[str, float] = {}
        self._assist_off_timers: dict[str, float] = {}
        self._assist_active_condition: dict[str, str] = {}
        # Assist ON/OFF *intent* (what PowerClimate is trying to do next)
        self._assist_target_hvac_mode: dict[str, str | None] = {}
        self._assist_target_reason: dict[str, str] = {}
        self._last_timer_update: datetime | None = None
        # Anti-short-cycle tracking for assist pump ON/OFF control
        self._assist_running_state: dict[str, bool] = {}
        self._assist_last_on: dict[str, datetime] = {}
        self._assist_last_off: dict[str, datetime] = {}
        self._assist_block_reason: dict[str, str] = {}
        # Power mode tracking: power budget per device and last adjustment time
        self._power_budget: dict[str, float] = {}  # entity_id -> target watts
        self._power_mode_last_adjustment: dict[str, datetime] = {}
        self._power_mode_current_setpoint: dict[str, float] = {}  # persisted setpoint
        self._power_budget_last_update: datetime | None = None
        self._house_net_power_w: float | None = None
        self._power_available_w: float | None = None
        self._power_budget_remaining_w: float | None = None

    @property
    def entity_picture(self) -> str:
        return "/local/community/powerclimate/icon.png"

    @property
    def current_temperature(self) -> float | None:
        return self.coordinator.data.get(CONF_ROOM_TEMPERATURE_KEY)

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
        await self._apply_staging()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode not in self.hvac_modes:
            return
        self._attr_hvac_mode = hvac_mode
        # Clear any active preset when user explicitly sets HVAC mode
        if self._attr_preset_mode != "none":
            self._attr_preset_mode = "none"
            self._previous_target = None
        await self._apply_staging()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set a preset mode. Supported: 'boost', 'Solar' and 'none'."""
        if preset_mode not in self.preset_modes:
            return

        # Enter boost: set all controllable heat pumps to HEAT with upper offset
        if preset_mode == "boost":
            if self._attr_preset_mode == "boost":
                return
            self._attr_preset_mode = "boost"
            self._attr_hvac_mode = HVACMode.HEAT
            await self._apply_boost_mode()
            return

        # Exit boost preset: keep running heat pumps running
        if preset_mode == "none":
            if self._attr_preset_mode == "none":
                return
            self._attr_preset_mode = "none"
            # Clear budgets when leaving Solar preset.
            self._clear_all_power_budgets()
            # Don't turn off devices, just switch back to normal control
            await self._apply_staging()

        # Enter Solar preset: enable system, then apply normal staging with budgets
        if preset_mode == "Solar":
            if self._attr_preset_mode == "Solar":
                return
            self._attr_preset_mode = "Solar"
            self._attr_hvac_mode = HVACMode.HEAT
            await self._apply_staging()

    def _clear_all_power_budgets(self) -> None:
        # Clear budgets and local power-mode state.
        self._power_budget.clear()
        self._power_mode_current_setpoint.clear()
        self._power_mode_last_adjustment.clear()
        self._power_budget_last_update = None
        self._house_net_power_w = None
        self._power_available_w = None
        self._power_budget_remaining_w = None

    def _read_house_net_power_w(self) -> float | None:
        """Read signed house net active power in W.

        Expected convention for this integration: negative means exporting
        (solar surplus). This is common in HA ecosystems, but depends on the
        meter/integration.
        """
        config = merged_entry_data(self._entry)
        sensor_entity_id = str(config.get(CONF_HOUSE_POWER_SENSOR) or "").strip()
        if not sensor_entity_id:
            return None

        state = self.hass.states.get(sensor_entity_id)
        if state is None:
            return None

        value = _safe_float(state.state)
        if value is None:
            return None

        unit = str(state.attributes.get("unit_of_measurement") or "").strip()
        if unit.lower() == "kw":
            return value * 1000.0

        return value

    def _update_power_budgets(self, devices: list[dict[str, Any]]) -> None:
        """Update per-device power budgets (HP1, HP2, ...) from house net power."""
        now = dt_util.utcnow()
        if self._power_budget_last_update is not None:
            elapsed = (now - self._power_budget_last_update).total_seconds()
            if elapsed < DEFAULT_POWER_BUDGET_UPDATE_INTERVAL_SECONDS:
                return

        self._power_budget_last_update = now

        net_power_w = self._read_house_net_power_w()
        if net_power_w is None:
            # No sensor configured or invalid value: don't steer via power.
            self._clear_all_power_budgets()
            return

        self._house_net_power_w = float(net_power_w)

        reserve_w = DEFAULT_POWER_SURPLUS_RESERVE_W
        # Surplus/export is negative (e.g. -800W means 800W export).
        available_w = max(0.0, -net_power_w - reserve_w)
        self._power_available_w = float(available_w)

        remaining_w = available_w
        new_budgets: dict[str, float] = {}

        for device in devices:
            entity_id = str(device.get(CONF_CLIMATE_ENTITY) or "").strip()
            if not entity_id:
                continue

            budget = min(DEFAULT_POWER_MAX_BUDGET_PER_DEVICE_W, remaining_w)
            if budget >= DEFAULT_POWER_MIN_BUDGET_W:
                new_budgets[entity_id] = float(budget)
                remaining_w -= budget
            else:
                # Stop allocating further (priority order HP1->HP2...)
                break

        # Apply new budgets.
        # Clear any budgets for devices no longer allocated.
        for entity_id in list(self._power_budget.keys()):
            if entity_id not in new_budgets:
                self.clear_power_budget(entity_id)

        for entity_id, budget in new_budgets.items():
            self.set_power_budget(entity_id, budget)

        self._power_budget_remaining_w = float(max(0.0, remaining_w))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        eta_exceeded_duration = None
        if self._eta_exceeded_since:
            eta_exceeded_duration = (
                datetime.now(timezone.utc) - self._eta_exceeded_since
            ).total_seconds() / 60.0  # in minutes

        base = dict(self._summary_payload or {})
        base["eta_exceeded_duration_minutes"] = eta_exceeded_duration
        base["eta_threshold_met"] = (
            eta_exceeded_duration is not None and eta_exceeded_duration >= 5.0
        )
        return base

    async def _apply_boost_mode(self) -> None:
        """Apply boost preset: set controllable heat pumps to HEAT, then boost all HEAT pumps."""
        config = merged_entry_data(self._entry)
        devices = config.get(CONF_DEVICES, [])
        device_payloads = self._coordinator_devices()

        # Get controllable devices (those with "allow_on_off_control" enabled)
        controllable_devices = [
            (index, device)
            for index, device in enumerate(devices)
            if device.get(CONF_ALLOW_ON_OFF_CONTROL)
            and device.get(CONF_CLIMATE_ENTITY)
        ]

        # Step 1: Set all controllable devices to HEAT mode
        for _index, device in controllable_devices:
            entity_id = device.get(CONF_CLIMATE_ENTITY)
            if entity_id:
                await self._ensure_device_mode(entity_id, HVACMode.HEAT)

        # Refresh device payloads after mode changes
        device_payloads = self._coordinator_devices()

        # Step 2: Set boost mode for ALL devices that are now in HEAT mode
        for index, device in enumerate(devices):
            entity_id = device.get(CONF_CLIMATE_ENTITY)
            if not entity_id:
                continue

            payload = device_payloads.get(entity_id, {}) or {}
            hvac_mode = str(payload.get("hvac_mode") or "").lower()

            # Only boost devices in HEAT mode
            if hvac_mode != HVACMode.HEAT.value:
                self._hp_modes[entity_id] = MODE_OFF
                continue

            current_temp = _safe_float(payload.get("current_temperature"))

            if current_temp is not None:
                # Set mode to BOOST
                self._hp_modes[entity_id] = MODE_BOOST
                boost_target = self._calculate_mode_target(
                    MODE_BOOST,
                    current_temp,
                    device,
                    index,
                )

                _LOGGER.debug(
                    "Boost preset: Setting %s to mode=%s, target=%.1f°C",
                    entity_id,
                    MODE_BOOST,
                    boost_target,
                )

                await self._ensure_device_temperature(entity_id, boost_target)
            else:
                _LOGGER.warning("Boost preset: No current temperature for %s", entity_id)

        self.async_write_ha_state()
        self._emit_summary(devices, device_payloads)

    def _check_assist_on_conditions(
        self,
        room_temp: float | None,
        room_eta_minutes: float | None,
        water_temp: float | None,
        room_derivative: float | None,
        eta_on_threshold: float,
        water_temp_threshold: float,
        stall_temp_delta: float,
    ) -> tuple[bool, str]:
        """Check if any assist pump ON condition is met."""
        if (
            room_eta_minutes is not None
            and room_eta_minutes > eta_on_threshold
            and room_temp is not None
            and self._target_temperature is not None
            and room_temp < self._target_temperature
        ):
            return True, "eta_high"

        if (
            water_temp is not None
            and water_temp >= water_temp_threshold
            and room_temp is not None
            and self._target_temperature is not None
            and room_temp < self._target_temperature
        ):
            return True, "water_hot"

        if (
            room_derivative is not None
            and room_derivative <= 0.0
            and room_temp is not None
            and self._target_temperature is not None
            and room_temp < (self._target_temperature - stall_temp_delta)
        ):
            return True, "stalled_below_target"

        return False, ""

    def _check_assist_off_conditions(
        self,
        room_temp: float | None,
        room_eta_minutes: float | None,
        room_derivative: float | None,
        eta_off_threshold: float,
        stall_temp_delta: float,
    ) -> tuple[bool, str]:
        """Check if any assist pump OFF condition is met."""
        if (
            room_eta_minutes is not None
            and room_eta_minutes < eta_off_threshold
        ):
            return True, "eta_low"

        if (
            room_temp is not None
            and self._target_temperature is not None
            and room_temp >= self._target_temperature
        ):
            return True, "overshoot"

        if (
            room_derivative is not None
            and room_derivative <= 0.0
            and room_temp is not None
            and self._target_temperature is not None
            and (self._target_temperature - room_temp) <= stall_temp_delta
        ):
            return True, "stalled_at_target"

        return False, ""

    async def _apply_staging(self) -> None:
        config = merged_entry_data(self._entry)
        devices = config.get(CONF_DEVICES, [])
        device_payloads = self._coordinator_devices()
        self._copy_enabled_entities = {
            device.get(CONF_CLIMATE_ENTITY)
            for device in devices
            if device.get(CONF_COPY_SETPOINT_TO_POWERCLIMATE)
            and device.get(CONF_CLIMATE_ENTITY)
        }

        # If in boost mode, use boost logic instead
        if self._attr_preset_mode == "boost":
            await self._apply_boost_mode()
            return

        # Solar preset: compute budgets (HP1 -> HP2 -> ...). This does not
        # change which devices are allowed to run; it only steers setpoints
        # via MODE_POWER when a positive budget is allocated.
        if self._attr_preset_mode == "Solar":
            self._update_power_budgets(devices)
        else:
            # If not in Solar preset, ensure we are not steering.
            self._clear_all_power_budgets()

        if not devices:
            await self._sync_devices([], set(), device_payloads, {})
            self._sync_state_listeners(set())
            self._active_devices = set()
            self._update_mode("off")
            self._delta = None
            self._water_temperature = None
            self._assist_modes = {}
            self.async_write_ha_state()
            self._emit_summary([], device_payloads)
            return

        hvac_disabled = (
            self._attr_hvac_mode == HVACMode.OFF
            or self._target_temperature is None
        )

        desired_devices: set[str] = set()
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
        self._assist_target_hvac_mode = {}
        self._assist_target_reason = {}

        if not hvac_disabled:
            # Calculate room_at_target for mode determination
            room_at_target = (
                room_temp is not None
                and self._target_temperature is not None
                and room_temp >= self._target_temperature
            )

            hp1_device = devices[0]
            hp1_entity = hp1_device.get(CONF_CLIMATE_ENTITY)
            if hp1_entity:
                desired_devices.add(hp1_entity)
                hp1_payload = device_payloads.get(hp1_entity, {})
                hp1_current = _safe_float(
                    hp1_payload.get("current_temperature"),
                )
                hp1_power = _safe_float(hp1_payload.get("energy"))
                water_temp = _safe_float(hp1_payload.get("water_temperature"))

                # Determine HP1 mode based on preset and power budget
                hp1_mode = self._determine_hp1_mode(
                    room_at_target,
                    self._attr_preset_mode,
                    hp1_entity,
                )
                self._hp_modes[hp1_entity] = hp1_mode

                hp1_target = self._calculate_mode_target(
                    hp1_mode,
                    hp1_current,
                    hp1_device,
                    index=0,
                    current_power=hp1_power,
                )
                desired_targets[hp1_entity] = hp1_target

                _LOGGER.debug(
                    "HP1: mode=%s, setpoint=%.1f, current=%s -> %.1f",
                    hp1_mode,
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
                    # Get advanced options (with fallback to defaults)
                    assist_timer_seconds = config.get(
                        CONF_ASSIST_TIMER_SECONDS, DEFAULT_ASSIST_TIMER_SECONDS
                    )
                    eta_on_threshold_minutes = config.get(
                        CONF_ASSIST_ON_ETA_THRESHOLD_MINUTES,
                        DEFAULT_ASSIST_ON_ETA_THRESHOLD_MINUTES,
                    )
                    eta_off_threshold_minutes = config.get(
                        CONF_ASSIST_OFF_ETA_THRESHOLD_MINUTES,
                        DEFAULT_ASSIST_OFF_ETA_THRESHOLD_MINUTES,
                    )

                    # Anti-short-cycle settings (minutes)
                    min_on_minutes = float(
                        config.get(CONF_ASSIST_MIN_ON_MINUTES, DEFAULT_ASSIST_MIN_ON_MINUTES)
                    )
                    min_off_minutes = float(
                        config.get(CONF_ASSIST_MIN_OFF_MINUTES, DEFAULT_ASSIST_MIN_OFF_MINUTES)
                    )
                    water_temp_threshold = config.get(
                        CONF_ASSIST_WATER_TEMP_THRESHOLD,
                        DEFAULT_ASSIST_WATER_TEMP_THRESHOLD,
                    )
                    stall_temp_delta = config.get(
                        CONF_ASSIST_STALL_TEMP_DELTA, DEFAULT_ASSIST_STALL_TEMP_DELTA
                    )

                    # Update timer deltas
                    now = datetime.now(timezone.utc)
                    delta_seconds = 0.0
                    if self._last_timer_update is not None:
                        delta_seconds = (now - self._last_timer_update).total_seconds()
                    self._last_timer_update = now

                    room_derivative = self.coordinator.data.get("room_derivative")

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

                        # Track state transitions (also catches manual toggles)
                        prev_running = self._assist_running_state.get(entity)
                        if prev_running is None:
                            self._assist_running_state[entity] = is_running
                        elif prev_running != is_running:
                            self._assist_running_state[entity] = is_running
                            if is_running:
                                self._assist_last_on[entity] = now
                            else:
                                self._assist_last_off[entity] = now

                        self._assist_block_reason[entity] = ""

                        # Default: no pending target action.
                        if entity not in self._assist_target_hvac_mode:
                            self._assist_target_hvac_mode[entity] = None
                        if entity not in self._assist_target_reason:
                            self._assist_target_reason[entity] = ""

                        # Initialize timers if needed
                        if entity not in self._assist_on_timers:
                            self._assist_on_timers[entity] = 0.0
                        if entity not in self._assist_off_timers:
                            self._assist_off_timers[entity] = 0.0

                        # Check mutually exclusive ON/OFF conditions
                        room_eta_minutes = (
                            self._room_eta_hours * 60.0
                            if self._room_eta_hours is not None
                            else None
                        )

                        on_condition_met, on_condition_name = self._check_assist_on_conditions(
                            room_temp,
                            room_eta_minutes,
                            water_temp,
                            room_derivative,
                            eta_on_threshold_minutes,
                            water_temp_threshold,
                            stall_temp_delta,
                        )

                        off_condition_met, off_condition_name = self._check_assist_off_conditions(
                            room_temp,
                            room_eta_minutes,
                            room_derivative,
                            eta_off_threshold_minutes,
                            stall_temp_delta,
                        )

                        # Mutually exclusive timer logic
                        if on_condition_met:
                            # ON condition active: increment ON timer, reset OFF timer
                            self._assist_on_timers[entity] += delta_seconds
                            self._assist_off_timers[entity] = 0.0
                            self._assist_active_condition[entity] = on_condition_name
                        elif off_condition_met:
                            # OFF condition active: increment OFF timer, reset ON timer
                            self._assist_off_timers[entity] += delta_seconds
                            self._assist_on_timers[entity] = 0.0
                            self._assist_active_condition[entity] = off_condition_name
                        else:
                            # No condition active: reset both timers
                            self._assist_on_timers[entity] = 0.0
                            self._assist_off_timers[entity] = 0.0
                            self._assist_active_condition[entity] = "none"

                        # Apply ON/OFF control if allow_on_off_control is enabled
                        if device.get(CONF_ALLOW_ON_OFF_CONTROL):
                            on_timer = self._assist_on_timers[entity]
                            off_timer = self._assist_off_timers[entity]

                            min_on_seconds = max(0.0, min_on_minutes) * 60.0
                            min_off_seconds = max(0.0, min_off_minutes) * 60.0
                            seconds_since_on = None
                            seconds_since_off = None

                            last_on = self._assist_last_on.get(entity)
                            if last_on is not None:
                                seconds_since_on = (now - last_on).total_seconds()
                            last_off = self._assist_last_off.get(entity)
                            if last_off is not None:
                                seconds_since_off = (now - last_off).total_seconds()

                            if not is_running and on_timer >= assist_timer_seconds:
                                self._assist_target_hvac_mode[entity] = HVACMode.HEAT.value
                                self._assist_target_reason[entity] = on_condition_name
                                if (
                                    seconds_since_off is not None
                                    and seconds_since_off < min_off_seconds
                                ):
                                    remaining = int(min_off_seconds - seconds_since_off)
                                    self._assist_block_reason[entity] = (
                                        f"min_off {remaining}s"
                                    )
                                    _LOGGER.debug(
                                        (
                                            "Assist ON blocked (anti-short-cycle) for %s: "
                                            "remaining=%ss"
                                        ),
                                        entity,
                                        remaining,
                                    )
                                else:
                                    _LOGGER.info(
                                        "Turning ON %s: condition=%s, timer=%.1fs",
                                        entity,
                                        on_condition_name,
                                        on_timer,
                                    )
                                    await self._ensure_device_mode(entity, HVACMode.HEAT)
                                    self._assist_last_on[entity] = now
                                # Refresh payload after mode change
                                device_payloads = self._coordinator_devices()
                                payload = device_payloads.get(entity, {}) or {}
                                hvac_mode = str(payload.get("hvac_mode") or "").lower()
                                is_running = hvac_mode and hvac_mode != HVACMode.OFF.value
                            elif is_running and off_timer >= assist_timer_seconds:
                                self._assist_target_hvac_mode[entity] = HVACMode.OFF.value
                                self._assist_target_reason[entity] = off_condition_name
                                if (
                                    seconds_since_on is not None
                                    and seconds_since_on < min_on_seconds
                                ):
                                    remaining = int(min_on_seconds - seconds_since_on)
                                    self._assist_block_reason[entity] = (
                                        f"min_on {remaining}s"
                                    )
                                    _LOGGER.debug(
                                        (
                                            "Assist OFF blocked (anti-short-cycle) for %s: "
                                            "remaining=%ss"
                                        ),
                                        entity,
                                        remaining,
                                    )
                                else:
                                    _LOGGER.info(
                                        "Turning OFF %s: condition=%s, timer=%.1fs",
                                        entity,
                                        off_condition_name,
                                        off_timer,
                                    )
                                    await self._ensure_device_mode(entity, HVACMode.OFF)
                                    self._assist_last_off[entity] = now
                                device_payloads = self._coordinator_devices()
                                payload = device_payloads.get(entity, {}) or {}
                                hvac_mode = str(payload.get("hvac_mode") or "").lower()
                                is_running = hvac_mode and hvac_mode != HVACMode.OFF.value

                        # Only manage setpoint if device is running
                        if not is_running:
                            self._assist_modes[entity] = MODE_OFF
                            self._hp_modes[entity] = MODE_OFF
                            continue

                        current_temp = _safe_float(
                            payload.get("current_temperature"),
                        )
                        current_power = _safe_float(payload.get("energy"))

                        # Determine mode based on conditions, preset, and power budget
                        off_timer = self._assist_off_timers.get(entity, 0.0)
                        assist_mode = self._determine_assist_mode(
                            room_at_target,
                            off_timer,
                            self._attr_preset_mode,
                            entity,
                        )
                        self._hp_modes[entity] = assist_mode

                        target_for_device = self._calculate_mode_target(
                            assist_mode,
                            current_temp,
                            device,
                            assist_index,
                            current_power=current_power,
                        )

                        desired_devices.add(entity)
                        desired_targets[entity] = target_for_device
                        self._assist_modes[entity] = assist_mode
                        managed_any = True

                        _LOGGER.debug(
                            "Assist HP%d (%s): mode=%s, current=%s -> %.1f, "
                            "on_timer=%.1fs, off_timer=%.1fs, condition=%s",
                            assist_index + 1,
                            entity,
                            assist_mode,
                            current_temp,
                            target_for_device,
                            self._assist_on_timers.get(entity, 0.0),
                            self._assist_off_timers.get(entity, 0.0),
                            self._assist_active_condition.get(entity, "none"),
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
        self._emit_summary(devices, device_payloads)

    async def _sync_devices(
        self,
        devices: list[dict[str, Any]],
        desired_devices: set[str],
        device_payloads: dict[str, dict[str, Any]],
        desired_targets: dict[str, float],
    ) -> None:
        # If PowerClimate is turned off, do not touch underlying devices.
        if self.hvac_mode == HVACMode.OFF:
            _LOGGER.debug("PowerClimate is OFF; skipping device sync")
            return
        for device in devices:
            entity_id = device.get(CONF_CLIMATE_ENTITY)
            if not entity_id:
                continue

            if entity_id in desired_devices:
                target = desired_targets.get(entity_id)
                if target is not None:
                    payload = device_payloads.get(entity_id, {}) or {}
                    hvac_mode = str(payload.get("hvac_mode") or "").lower()
                    if hvac_mode == HVACMode.HEAT.value:
                        await self._ensure_device_temperature(entity_id, target)
                    else:
                        _LOGGER.debug(
                            "Skip setpoint for %s because mode=%s (not heating)",
                            entity_id,
                            hvac_mode,
                        )
            # If PowerClimate is not driving a device, leave its HVAC mode
            # untouched; only adjust temperatures when explicitly desired.

    def _minimal_mode_target(
        self,
        current_temp: float | None,
        device: dict[str, Any],
        index: int,
    ) -> float:
        config = merged_entry_data(self._entry)
        min_setpoint = config.get(CONF_MIN_SETPOINT_OVERRIDE, DEFAULT_MIN_SETPOINT)

        if current_temp is None:
            return min_setpoint
        target = current_temp + self._device_lower_offset(device, index)
        return self._clamp_setpoint(target, current_temp, device, index)

    def _clamp_setpoint(
        self,
        target: float | None,
        current_temp: float | None,
        device: dict[str, Any],
        index: int,
    ) -> float:
        config = merged_entry_data(self._entry)
        min_setpoint = config.get(CONF_MIN_SETPOINT_OVERRIDE, DEFAULT_MIN_SETPOINT)
        max_setpoint = config.get(CONF_MAX_SETPOINT_OVERRIDE, DEFAULT_MAX_SETPOINT)

        if target is None:
            return min_setpoint

        lower_offset = self._device_lower_offset(device, index)
        upper_offset = self._device_upper_offset(device, index)

        if current_temp is None:
            floor = min_setpoint
            ceiling = max_setpoint
        else:
            floor = current_temp + lower_offset
            ceiling = current_temp + upper_offset
            floor = max(floor, min_setpoint)
            ceiling = min(ceiling, max_setpoint)

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

    def _calculate_device_offset(
        self,
        device: dict[str, Any],
        index: int,
        offset_type: str,
    ) -> float:
        """Calculate device offset (lower or upper) with defaults based on role."""
        if offset_type == "lower":
            value = device.get(CONF_LOWER_SETPOINT_OFFSET)
            default_hp1 = DEFAULT_LOWER_SETPOINT_OFFSET_HP1
            default_assist = DEFAULT_LOWER_SETPOINT_OFFSET_ASSIST
        else:  # upper
            value = device.get(CONF_UPPER_SETPOINT_OFFSET)
            default_hp1 = DEFAULT_UPPER_SETPOINT_OFFSET_HP1
            default_assist = DEFAULT_UPPER_SETPOINT_OFFSET_ASSIST

        parsed = _parse_device_offset(value)
        if parsed is not None:
            return parsed
        return default_hp1 if index == 0 else default_assist

    def _device_lower_offset(self, device: dict[str, Any], index: int) -> float:
        return self._calculate_device_offset(device, index, "lower")

    def _device_upper_offset(self, device: dict[str, Any], index: int) -> float:
        return self._calculate_device_offset(device, index, "upper")

    def _calculate_mode_target(
        self,
        mode: str,
        current_temp: float | None,
        device: dict[str, Any],
        index: int,
        current_power: float | None = None,
    ) -> float:
        """Calculate target temperature for a given mode."""
        config = merged_entry_data(self._entry)
        min_setpoint = config.get(CONF_MIN_SETPOINT_OVERRIDE, DEFAULT_MIN_SETPOINT)
        max_setpoint = config.get(CONF_MAX_SETPOINT_OVERRIDE, DEFAULT_MAX_SETPOINT)
        entity_id = device.get(CONF_CLIMATE_ENTITY, "")

        if current_temp is None:
            return min_setpoint

        if mode == MODE_BOOST:
            # Boost: current + upper offset
            upper_offset = self._device_upper_offset(device, index)
            target = current_temp + upper_offset
            return max(min_setpoint, min(target, max_setpoint))

        elif mode == MODE_MINIMAL:
            # Minimal: current + lower offset
            lower_offset = self._device_lower_offset(device, index)
            target = current_temp + lower_offset
            return self._clamp_setpoint(target, current_temp, device, index)

        elif mode == MODE_SETPOINT:
            # Setpoint: PowerClimate target, clamped to offsets
            return self._clamp_setpoint(
                self._target_temperature,
                current_temp,
                device,
                index,
            )

        elif mode == MODE_POWER:
            # Power mode: adjust setpoint to match power budget
            return self._calculate_power_mode_setpoint(
                entity_id,
                current_power,
                min_setpoint,
                max_setpoint,
            )

        else:
            # Unknown mode or OFF
            return min_setpoint

    def _calculate_power_mode_setpoint(
        self,
        entity_id: str,
        current_power: float | None,
        min_setpoint: float,
        max_setpoint: float,
    ) -> float:
        """Calculate setpoint to match power budget using simple step algorithm.

        Algorithm:
        1. Only adjust every ADJUSTMENT_INTERVAL seconds (prevents oscillation)
        2. Use deadband - no adjustment if within ±DEADBAND_PERCENT of target
        3. Small fixed step size per adjustment
        4. Direction: power too low → raise setpoint, too high → lower setpoint
        """
        target_power = self._power_budget.get(entity_id, 0.0)
        now = dt_util.utcnow()

        # Get current setpoint or initialize to midpoint
        current_setpoint = self._power_mode_current_setpoint.get(entity_id)
        if current_setpoint is None:
            current_setpoint = (min_setpoint + max_setpoint) / 2.0
            self._power_mode_current_setpoint[entity_id] = current_setpoint

        # If no power budget set or no current reading, return current setpoint
        if target_power <= 0 or current_power is None:
            return current_setpoint

        # Check if enough time has passed since last adjustment
        last_adjustment = self._power_mode_last_adjustment.get(entity_id)
        if last_adjustment is not None:
            elapsed = (now - last_adjustment).total_seconds()
            if elapsed < DEFAULT_POWER_MODE_ADJUSTMENT_INTERVAL_SECONDS:
                return current_setpoint

        # Calculate error
        power_error = target_power - current_power
        power_error_percent = abs(power_error) / target_power

        # Within deadband - no adjustment needed
        if power_error_percent < DEFAULT_POWER_MODE_DEADBAND_PERCENT:
            return current_setpoint

        # Determine adjustment direction and apply step
        if power_error > 0:
            # Need more power - raise setpoint
            new_setpoint = current_setpoint + DEFAULT_POWER_MODE_STEP_SIZE
        else:
            # Need less power - lower setpoint
            new_setpoint = current_setpoint - DEFAULT_POWER_MODE_STEP_SIZE

        # Clamp to bounds
        new_setpoint = max(min_setpoint, min(new_setpoint, max_setpoint))

        # Store new setpoint and update timestamp
        self._power_mode_current_setpoint[entity_id] = new_setpoint
        self._power_mode_last_adjustment[entity_id] = now

        _LOGGER.debug(
            "Power mode %s: target=%dW current=%dW error=%.0f%% setpoint %.1f→%.1f",
            entity_id,
            target_power,
            current_power,
            power_error_percent * 100,
            current_setpoint,
            new_setpoint,
        )

        return new_setpoint

    def set_power_budget(self, entity_id: str, power_watts: float) -> None:
        """Set the power budget for a device in power mode."""
        self._power_budget[entity_id] = power_watts
        _LOGGER.info("Power budget set for %s: %d W", entity_id, power_watts)

    def clear_power_budget(self, entity_id: str) -> None:
        """Clear the power budget for a device, exiting power mode."""
        self._power_budget.pop(entity_id, None)
        self._power_mode_current_setpoint.pop(entity_id, None)
        self._power_mode_last_adjustment.pop(entity_id, None)
        _LOGGER.info("Power budget cleared for %s", entity_id)

    def _determine_hp1_mode(
        self,
        room_at_target: bool,
        preset_mode: str,
        entity_id: str = "",
    ) -> str:
        """Determine the operating mode for HP1 (water-based heat pump)."""
        if preset_mode == "boost":
            return MODE_BOOST

        # Check if power budget is set for this device
        if entity_id and self._power_budget.get(entity_id, 0.0) > 0:
            return MODE_POWER

        # Normal operation: use setpoint mode
        return MODE_SETPOINT

    def _determine_assist_mode(
        self,
        room_at_target: bool,
        off_timer: float,
        preset_mode: str,
        entity_id: str = "",
    ) -> str:
        """Determine the operating mode for an assist heat pump."""
        if preset_mode == "boost":
            return MODE_BOOST

        # Check if power budget is set for this device
        if entity_id and self._power_budget.get(entity_id, 0.0) > 0:
            return MODE_POWER

        # If OFF condition active (off_timer > 0), switch to minimal
        if off_timer > 0:
            return MODE_MINIMAL

        # Normal operation based on room temperature
        if room_at_target:
            return MODE_MINIMAL
        else:
            return MODE_SETPOINT

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

    def _build_hp_status(
        self,
        devices: list[dict[str, Any]],
        device_payloads: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        status: list[dict[str, Any]] = []
        coordinator_data = self.coordinator.data or {}
        for index, device in enumerate(devices):
            entity_id = device.get(CONF_CLIMATE_ENTITY)
            if not entity_id:
                continue
            payload = device_payloads.get(entity_id, {}) or {}
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

            hp_info = {
                "role": f"hp{index + 1}",
                "name": device.get(CONF_DEVICE_NAME) or f"HP{index + 1}",
                "entity_id": entity_id,
                "active": entity_id in self._active_devices or is_running,
                "hvac_mode": payload.get("hvac_mode"),
                "assist_mode": assist_mode,
                "powerclimate_mode": self._hp_modes.get(entity_id, MODE_OFF),
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
            }

            # Add timer information for assist pumps
            if index > 0:
                hp_info["on_timer_seconds"] = self._assist_on_timers.get(entity_id, 0.0)
                hp_info["off_timer_seconds"] = self._assist_off_timers.get(entity_id, 0.0)
                hp_info["active_condition"] = self._assist_active_condition.get(entity_id, "none")
                hp_info["allow_on_off_control"] = device.get(CONF_ALLOW_ON_OFF_CONTROL, False)
                hp_info["blocked_by"] = self._assist_block_reason.get(entity_id, "")
                hp_info["target_hvac_mode"] = self._assist_target_hvac_mode.get(entity_id)
                hp_info["target_reason"] = self._assist_target_reason.get(entity_id, "")

            status.append(hp_info)
        return status

    def _emit_summary(
        self,
        devices: list[dict[str, Any]],
        device_payloads: dict[str, dict[str, Any]],
    ) -> None:
        config = merged_entry_data(self._entry)
        target_temp = self._current_target_temperature()
        hp_status = self._build_hp_status(devices, device_payloads)
        payload = {
            "mode": self._mode_state,
            "stage_count": len(self._active_devices),
            "active_devices": sorted(self._active_devices),
            "delta": self._delta,
            "room_temperature": self.current_temperature,
            "room_sensor_values": self.coordinator.data.get(
                CONF_ROOM_SENSOR_VALUES
            ),
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
            "assist_timer_seconds": config.get(
                CONF_ASSIST_TIMER_SECONDS,
                DEFAULT_ASSIST_TIMER_SECONDS,
            ),
            "assist_on_eta_threshold_minutes": config.get(
                CONF_ASSIST_ON_ETA_THRESHOLD_MINUTES,
                DEFAULT_ASSIST_ON_ETA_THRESHOLD_MINUTES,
            ),
            "assist_off_eta_threshold_minutes": config.get(
                CONF_ASSIST_OFF_ETA_THRESHOLD_MINUTES,
                DEFAULT_ASSIST_OFF_ETA_THRESHOLD_MINUTES,
            ),
            "assist_min_on_minutes": config.get(
                CONF_ASSIST_MIN_ON_MINUTES,
                DEFAULT_ASSIST_MIN_ON_MINUTES,
            ),
            "assist_min_off_minutes": config.get(
                CONF_ASSIST_MIN_OFF_MINUTES,
                DEFAULT_ASSIST_MIN_OFF_MINUTES,
            ),
            # Solar preset / budget diagnostics
            "house_net_power_w": self._house_net_power_w,
            "power_available_w": self._power_available_w,
            "power_budget_remaining_w": self._power_budget_remaining_w,
            "power_budget_total_w": (
                sum(float(v) for v in self._power_budget.values())
                if self._power_budget
                else 0.0
            ),
            "power_budget_by_entity_w": dict(self._power_budget),
        }

        self._summary_payload = payload

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

        async def async_refresh_coordinator() -> None:
            try:
                await self.coordinator.async_request_refresh()
            finally:
                self._pending_state_refresh = False

        self.hass.async_create_task(async_refresh_coordinator())

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

    async def _call_climate_service(
        self,
        entity_id: str,
        service_name: str,
        service_data: dict[str, Any],
        action_description: str,
    ) -> None:
        """Common helper for calling climate services with error handling."""
        if self.hvac_mode == HVACMode.OFF:
            _LOGGER.debug(
                "PowerClimate is OFF; skipping %s for %s",
                action_description,
                entity_id,
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
                action_description.capitalize(),
                entity_id,
                SERVICE_CALL_TIMEOUT_SECONDS,
            )
        except ServiceNotFound:
            _LOGGER.error(
                "Service %s.%s not found for %s",
                CLIMATE_DOMAIN,
                service_name,
                entity_id,
            )
        except HomeAssistantError as err:
            _LOGGER.warning(
                "Failed %s for %s: %s",
                action_description,
                entity_id,
                err,
            )

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

        await self._call_climate_service(
            entity_id,
            SERVICE_SET_HVAC_MODE,
            {ATTR_ENTITY_ID: entity_id, ATTR_HVAC_MODE: mode},
            "mode change",
        )
        self._device_modes[entity_id] = mode
        self._mark_call(self._last_mode_call, entity_id)

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

        await self._call_climate_service(
            entity_id,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: entity_id, ATTR_TEMPERATURE: temperature},
            "temperature set",
        )
        self._device_targets[entity_id] = temperature
        self._mark_call(self._last_temp_call, entity_id)

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
