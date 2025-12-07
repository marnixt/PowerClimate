"""Diagnostic sensors for PowerClimate.

This module provides diagnostic sensor entities that expose internal state
and calculations from the PowerClimate integration:

- **Temperature Derivative**: Rate of room temperature change (°C/hour)
- **Water Derivative**: Rate of water temperature change (°C/hour)
- **Thermal Summary**: Human-readable summary of system state
- **Assist Behavior**: Simple per-stage view showing HVAC state and assist mode
- **Total Power**: Aggregated power consumption from all configured heat pumps

All sensors are marked as diagnostic entities and grouped under the
integration's virtual device in the Home Assistant device registry.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import (
    COORDINATOR,
    DOMAIN,
    CONF_CLIMATE_ENTITY,
    CONF_DEVICES,
    CONF_ENERGY_SENSOR,
    SENSOR_POLL_INTERVAL_SECONDS,
)
from .helpers import (
    async_get_strings,
    entry_friendly_name,
    integration_device_info,
    merged_entry_data,
    summary_signal,
)


class _TranslationMixin:
    """Small helper to provide translated fragments with English fallback."""

    def __init__(self) -> None:
        self._strings: dict[str, str] = {}

    async def _load_strings(self, hass: HomeAssistant) -> None:
        self._strings = await async_get_strings(hass)

    def _t(self, key: str, default: str) -> str:
        return str(self._strings.get(key, default))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities for the config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data[COORDINATOR]

    derivative_sensor = PowerClimateDerivativeSensor(coordinator, entry)
    water_derivative_sensor = PowerClimateWaterDerivativeSensor(
        coordinator,
        entry,
    )
    thermal_summary_sensor = PowerClimateThermalSummarySensor(hass, entry)
    total_power_sensor = PowerClimateTotalPowerSensor(
        hass,
        coordinator,
        entry,
    )

    sensors: list[SensorEntity] = [
        derivative_sensor,
        water_derivative_sensor,
        thermal_summary_sensor,
        total_power_sensor,
    ]

    sensors.extend(_build_behavior_sensors(hass, entry))

    async_add_entities(sensors)


def _build_behavior_sensors(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> list[SensorEntity]:
    sensors: list[SensorEntity] = []
    config = merged_entry_data(entry)
    devices = config.get(CONF_DEVICES, []) or []
    role_builders: list[tuple[str, Callable[[HomeAssistant, ConfigEntry], SensorEntity]]] = [
        ("hp1", PowerClimateHP1BehaviorSensor),
        ("hp2", PowerClimateHP2BehaviorSensor),
        ("hp3", PowerClimateHP3BehaviorSensor),
        ("hp4", PowerClimateHP4BehaviorSensor),
        ("hp5", PowerClimateHP5BehaviorSensor),
    ]

    for index, device in enumerate(devices[:5]):
        if not device or not device.get(CONF_CLIMATE_ENTITY):
            continue
        if index >= len(role_builders):
            break
        _, builder = role_builders[index]
        sensors.append(builder(hass, entry))

    return sensors


class PowerClimateDerivativeSensor(CoordinatorEntity, SensorEntity):
    """Sensor tracking room temperature change rate."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = "°C/h"
    _attr_icon = "mdi:chart-line"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the derivative sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"powerclimate_derivative_{entry.entry_id}"
        friendly = entry_friendly_name(entry)
        self._attr_name = f"{friendly} Temperature Derivative"
        self._attr_device_info = integration_device_info(entry)

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.get("room_derivative")


class PowerClimateWaterDerivativeSensor(CoordinatorEntity, SensorEntity):
    """Sensor tracking water temperature change rate."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = "°C/h"
    _attr_icon = "mdi:chart-line"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the water derivative sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = (
            f"powerclimate_water_derivative_{entry.entry_id}"
        )
        friendly = entry_friendly_name(entry)
        self._attr_name = f"{friendly} Water Derivative"
        self._attr_device_info = integration_device_info(entry)

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.get("water_derivative")


def _snapshot_summary(
    hass: HomeAssistant,
    entry_id: str,
) -> dict[str, Any] | None:
    """Retrieve the current summary payload for a config entry."""
    entry_data = hass.data.get(DOMAIN, {}).get(entry_id)
    if not entry_data:
        return None
    payload = entry_data.get("summary_payload")
    if payload:
        return payload
    climate = entry_data.get("climate_entity")
    if climate is None:
        return None
    attrs = getattr(climate, "extra_state_attributes", {}) or {}
    coordinator = getattr(climate, "coordinator", None)
    derivative = None
    if coordinator and coordinator.data:
        derivative = coordinator.data.get("room_derivative")
    return {
        "mode": attrs.get("mode"),
        "stage_count": attrs.get("stage_count"),
        "active_devices": attrs.get("active_devices"),
        "delta": attrs.get("delta"),
        "room_temperature": attrs.get("room_temperature"),
        "derivative": derivative,
        "room_eta_hours": attrs.get("room_eta_hours"),
        "water_temperature": attrs.get("water_temperature"),
        "water_derivative": attrs.get("water_derivative"),
        "hp_status": attrs.get("hp_status"),
        "target_temperature": climate.target_temperature,
    }


class PowerClimateThermalSummarySensor(_TranslationMixin, SensorEntity):
    """Sensor providing a human-readable thermal summary."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:radiator"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the thermal summary sensor."""
        super().__init__()
        _TranslationMixin.__init__(self)
        self.hass = hass
        self._entry = entry
        self._entry_id = entry.entry_id
        self._signal = summary_signal(self._entry_id)
        self._unsub = None
        friendly = entry_friendly_name(entry)
        self._attr_name = f"{friendly} Thermal Summary"
        self._value = self._format_summary(
            _snapshot_summary(hass, self._entry_id),
        )
        self._attr_unique_id = (
            f"powerclimate_thermal_summary_{self._entry_id}"
        )
        self._attr_device_info = integration_device_info(entry)
        self._poll_unsub = None

    @property
    def native_value(self) -> str:
        return self._value

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self._load_strings(self.hass)
        self._value = self._format_summary(
            _snapshot_summary(self.hass, self._entry_id),
        )
        self._unsub = async_dispatcher_connect(
            self.hass,
            self._signal,
            self._handle_summary,
        )
        self._poll_unsub = async_track_time_interval(
            self.hass,
            self._handle_poll,
            timedelta(seconds=SENSOR_POLL_INTERVAL_SECONDS),
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None
        if self._poll_unsub:
            self._poll_unsub()
            self._poll_unsub = None
        await super().async_will_remove_from_hass()

    def _handle_summary(self, payload: dict | None) -> None:
        self._value = self._format_summary(payload)
        self.schedule_update_ha_state()

    def _handle_poll(self, now) -> None:  # pragma: no cover - timer callback
        payload = _snapshot_summary(self.hass, self._entry_id)
        self._handle_summary(payload)

    def _format_summary(self, payload: dict | None) -> str:
        if not payload:
            return self._t("unavailable", "unavailable")

        parts: list[str] = []

        room_text = self._format_temp_pair(
            self._t("label_room", "Room"),
            payload.get("room_temperature"),
            payload.get("target_temperature"),
        )
        room_derivative = self._format_derivative_fragment(
            self._t("label_derivative", "dT"),
            payload.get("derivative"),
        )
        room_eta = self._format_eta_fragment(payload.get("room_eta_hours"))
        parts.append(room_text)
        parts.append(room_derivative)
        parts.append(room_eta)

        # Compute total power from configured energy sensors (if any)
        total_power: int | None = None
        config = merged_entry_data(self._entry)
        devices = config.get(CONF_DEVICES, [])
        configured_sources = 0
        active_sources = 0
        total = 0.0
        for device in devices:
            sensor_id = device.get(CONF_ENERGY_SENSOR)
            if not sensor_id:
                continue
            configured_sources += 1
            state = self.hass.states.get(sensor_id)
            if not state:
                continue
            value = state.state
            if value in (None, "unknown", "unavailable"):
                continue
            try:
                pv = float(value)
            except (TypeError, ValueError):
                normalized = (
                    value.replace(",", ".") if isinstance(value, str) else value
                )
                try:
                    pv = float(normalized)
                except (TypeError, ValueError):
                    continue
            total += pv
            active_sources += 1

        if configured_sources > 0:
            # If at least one sensor configured, show power (0 if none active)
            if active_sources == 0:
                total_power = 0
            else:
                total_power = round(total)

        if total_power is not None:
            power_label = self._t("label_power", "Power")
            parts.append(f"{power_label} {total_power} W")

        return " | ".join(parts)

    def _format_hp_entry(self, entry: dict) -> str:
        raw_label = entry.get("name") or entry.get("role") or "HP"
        text = str(raw_label).strip()
        if not text:
            base = "HP"
        else:
            base = text.split()[0][:10]
        role = entry.get("role") or "hp?"
        label = f"{base} ({role})"
        current = entry.get("current_temperature")
        target = entry.get("target_temperature")
        hvac_mode = (entry.get("hvac_mode") or "").lower()
        active = entry.get("active")
        if hvac_mode == "off" and not active:
            if isinstance(current, (int, float)):
                return f"{label} off ({current:.1f}°C)"
            return f"{label} off"
        return self._format_temp_pair(
            label,
            current,
            target,
            entry.get("eta_hours"),
        )

    def _format_temp_pair(
        self,
        label: str,
        current,
        target,
    ) -> str:
        if (
            isinstance(current, (int, float))
            and isinstance(target, (int, float))
        ):
            base = f"{label} {current:.1f}°C→{target:.1f}°C"
        elif isinstance(current, (int, float)):
            base = f"{label} {current:.1f}°C"
        elif isinstance(target, (int, float)):
            base = f"{label} →{target:.1f}°C"
        else:
            base = f"{label} {self._t('value_none', 'none')}"

        return base

    def _format_eta_fragment(self, eta_hours) -> str:
        if not isinstance(eta_hours, (int, float)):
            return "{label} {value}".format(
                label=self._t("label_eta", "ETA"),
                value=self._t("value_none", "none"),
            )
        if eta_hours <= 0:
            return "{label} {value}".format(
                label=self._t("label_eta", "ETA"),
                value=self._t("value_none", "none"),
            )
        if eta_hours >= 1:
            return f"{self._t('label_eta', 'ETA')} {eta_hours:.1f}h"
        minutes = eta_hours * 60.0
        if minutes >= 1:
            return f"{self._t('label_eta', 'ETA')} {minutes:.0f}m"
        seconds = minutes * 60.0
        return f"{self._t('label_eta', 'ETA')} {seconds:.0f}s"

    def _format_derivative_fragment(self, label: str, value) -> str:
        if isinstance(value, (int, float)):
            return f"{label} {value:.1f}°C/h"
        return f"{label} {self._t('value_none', 'none')}"

class _AssistBehaviorFormatter(_TranslationMixin):
    def __init__(self) -> None:
        super().__init__()

    def _format_temp_pair(self, current, target) -> str:
        temps_label = self._t("label_temps", "Temps")
        none_text = self._t("value_none", "none")
        if (
            isinstance(current, (int, float))
            and isinstance(target, (int, float))
        ):
            return f"{temps_label} {current:.1f}°C→{target:.1f}°C"
        if isinstance(current, (int, float)):
            return f"{temps_label} {current:.1f}°C"
        if isinstance(target, (int, float)):
            return f"{temps_label} →{target:.1f}°C"
        return f"{temps_label} {none_text}"

    def _format_power(self, value) -> str | None:
        if not isinstance(value, (int, float)):
            return None
        power_label = self._t("label_power", "Power")
        return f"{power_label} {round(value)} W"

    def _format_derivative(self, value) -> str:
        label = self._t("label_derivative", "dT")
        if isinstance(value, (int, float)):
            return f"{label} {value:.1f}°C/h"
        return f"{label} {self._t('value_none', 'none')}"

    def _format_eta_fragment(self, value) -> str:
        label = self._t("label_eta", "ETA")
        if not isinstance(value, (int, float)):
            return f"{label} {self._t('value_none', 'none')}"
        if value <= 0:
            return f"{label} {self._t('value_none', 'none')}"
        if value >= 1:
            return f"{label} {value:.1f}h"
        minutes = value * 60.0
        if minutes >= 1:
            return f"{label} {minutes:.0f}m"
        seconds = minutes * 60.0
        return f"{label} {seconds:.0f}s"

    def _format_hp_snapshot(self, label: str, entry: dict | None) -> list[str]:
        none_text = self._t("value_none", "none")
        if not entry:
            return [f"{label} {self._t('hp_not_configured', 'not configured')}"]
        parts: list[str] = []
        state_active = self._t("state_active", "active")
        state_idle = self._t("state_idle", "idle")
        parts.append(
            f"{label} {state_active if entry.get('active') else state_idle}"
        )
        hvac = (entry.get("hvac_mode") or self._t("value_unknown", "unknown")).upper()
        parts.append(f"HVAC {hvac}")
        parts.append(
            self._format_temp_pair(
                entry.get("current_temperature"),
                entry.get("target_temperature"),
            ),
        )
        parts.append(
            self._format_derivative(entry.get("temperature_derivative")),
        )
        parts.append(self._format_eta_fragment(entry.get("eta_hours")))
        water_temp = entry.get("water_temperature")
        if isinstance(water_temp, (int, float)):
            water_label = self._t("label_water", "Water")
            parts.append(f"{water_label} {water_temp:.1f}°C")
        power_text = self._format_power(entry.get("energy"))
        if power_text:
            parts.append(power_text)
        if not parts:
            parts.append(none_text)
        return parts


class _AssistBehaviorSensor(_AssistBehaviorFormatter, SensorEntity):
    """Base class for heat pump behavior sensors."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:engine-outline"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        role: str,
        prefix: str,
        label: str,
        include_assist_line: bool = True,
    ) -> None:
        """Initialize the assist behavior sensor."""
        super().__init__()
        self.hass = hass
        self._entry = entry
        self._entry_id = entry.entry_id
        self._role = role
        self._label = label
        self._prefix = prefix
        self._include_assist_line = include_assist_line
        self._signal = summary_signal(self._entry_id)
        self._unsub = None
        self._poll_unsub = None
        self._payload: dict | None = None
        self._hp_entry: dict | None = None
        self._value = self._format_payload(
            _snapshot_summary(hass, self._entry_id),
        )
        self._attr_unique_id = (
            f"powerclimate_{prefix}_behavior_{self._entry_id}"
        )
        friendly = entry_friendly_name(entry)
        self._attr_name = f"{friendly} {label} Behavior"
        self._attr_device_info = integration_device_info(entry)

    @property
    def native_value(self) -> str:
        return self._value

    @property
    def extra_state_attributes(self) -> dict:
        entry = self._hp_entry or {}
        attrs: dict[str, Any] = {
            f"{self._prefix}_assist_mode": entry.get("assist_mode"),
            f"{self._prefix}_hvac_mode": entry.get("hvac_mode"),
            f"{self._prefix}_active": entry.get("active"),
            f"{self._prefix}_current_temperature": entry.get(
                "current_temperature",
            ),
            f"{self._prefix}_target_temperature": entry.get(
                "target_temperature",
            ),
            f"{self._prefix}_temperature_derivative": entry.get(
                "temperature_derivative",
            ),
            f"{self._prefix}_water_temperature": entry.get(
                "water_temperature",
            ),
            f"{self._prefix}_water_derivative": entry.get(
                "water_derivative",
            ),
        }
        energy = entry.get("energy")
        attrs[f"{self._prefix}_power_w"] = (
            round(energy)
            if isinstance(energy, (int, float))
            else None
        )
        return attrs

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self._load_strings(self.hass)
        self._value = self._format_payload(
            _snapshot_summary(self.hass, self._entry_id),
        )
        self._unsub = async_dispatcher_connect(
            self.hass,
            self._signal,
            self._handle_summary,
        )
        self._poll_unsub = async_track_time_interval(
            self.hass,
            self._handle_poll,
            timedelta(seconds=SENSOR_POLL_INTERVAL_SECONDS),
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None
        if self._poll_unsub:
            self._poll_unsub()
            self._poll_unsub = None
        await super().async_will_remove_from_hass()

    def _handle_summary(self, payload: dict | None) -> None:
        self._value = self._format_payload(payload)
        self.schedule_update_ha_state()

    def _handle_poll(self, now) -> None:  # pragma: no cover - timer callback
        payload = _snapshot_summary(self.hass, self._entry_id)
        self._handle_summary(payload)

    def _format_payload(self, payload: dict | None) -> str:
        if not payload:
            self._payload = None
            self._hp_entry = None
            return self._t("unavailable", "unavailable")

        self._payload = payload
        hp_entry = self._find_hp_entry(payload, self._role)
        self._hp_entry = hp_entry
        if not hp_entry:
            return "{label} {status}".format(
                label=self._label,
                status=self._t("hp_not_configured", "not configured"),
            )

        parts: list[str] = []
        label = self._label_from_hp(hp_entry, self._label, self._role)
        parts.extend(self._format_hp_snapshot(label, hp_entry))
        # For HP1 we want to show water dT before power. Remove any existing
        # power fragment produced by the generic snapshot and then append
        # sensor-specific parts which will include water dT and power (if any).
        if self._role == "hp1":
            parts = [p for p in parts if not p.startswith("Power ")]

        parts.extend(self._sensor_specific_parts(hp_entry))
        if self._include_assist_line:
            parts.append(self._format_assist_line(hp_entry))
        return " | ".join(parts)

    def _format_assist_line(self, entry: dict) -> str:
        assist_mode = (entry.get("assist_mode") or "off").lower()
        if assist_mode in ("off", "none"):
            return f"{self._t('label_assist', 'Assist')} {self._t('assist_off', 'off')}"
        return f"{self._t('label_assist', 'Assist')} {assist_mode}"

    @staticmethod
    def _find_hp_entry(payload: dict, role: str) -> dict | None:
        for entry in payload.get("hp_status") or []:
            if entry.get("role") == role:
                return entry
        return None

    @staticmethod
    def _label_from_hp(entry: dict, fallback: str, role: str) -> str:
        raw_label = entry.get("name") or fallback or role.upper()
        text = str(raw_label).strip()
        base = text.split()[0][:10] if text else role.upper()
        return f"{base} ({role})"

    def _sensor_specific_parts(self, entry: dict) -> list[str]:
        return []


class PowerClimateHP2BehaviorSensor(_AssistBehaviorSensor):
    """Sensor showing HP2 assist behavior status."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the HP2 behavior sensor."""
        super().__init__(
            hass,
            entry,
            role="hp2",
            prefix="hp2",
            label="HP2",
        )


class PowerClimateHP3BehaviorSensor(_AssistBehaviorSensor):
    """Sensor showing HP3 assist behavior status."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the HP3 behavior sensor."""
        super().__init__(
            hass,
            entry,
            role="hp3",
            prefix="hp3",
            label="HP3",
        )


class PowerClimateHP4BehaviorSensor(_AssistBehaviorSensor):
    """Sensor showing HP4 assist behavior status."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the HP4 behavior sensor."""
        super().__init__(
            hass,
            entry,
            role="hp4",
            prefix="hp4",
            label="HP4",
        )


class PowerClimateHP5BehaviorSensor(_AssistBehaviorSensor):
    """Sensor showing HP5 assist behavior status."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the HP5 behavior sensor."""
        super().__init__(
            hass,
            entry,
            role="hp5",
            prefix="hp5",
            label="HP5",
        )


class PowerClimateHP1BehaviorSensor(_AssistBehaviorSensor):
    """Sensor showing HP1 behavior with water temperature."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the HP1 behavior sensor."""
        super().__init__(
            hass,
            entry,
            role="hp1",
            prefix="hp1",
            label="HP1",
            include_assist_line=False,
        )

    def _sensor_specific_parts(self, entry: dict) -> list[str]:
        parts: list[str] = []
        value = entry.get("water_derivative")
        if isinstance(value, (int, float)):
            water_label = self._t("label_water", "Water")
            d_label = self._t("label_derivative", "dT")
            parts.append(f"{water_label} {d_label} {value:.1f}°C/h")
        else:
            water_label = self._t("label_water", "Water")
            d_label = self._t("label_derivative", "dT")
            parts.append(
                f"{water_label} {d_label} {self._t('value_none', 'none')}"
            )

        energy = entry.get("energy")
        if isinstance(energy, (int, float)):
            power_label = self._t("label_power", "Power")
            parts.append(f"{power_label} {round(energy)} W")

        return parts


class PowerClimateTotalPowerSensor(CoordinatorEntity, SensorEntity):
    """Sensor aggregating power consumption from all configured heat pumps."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:flash"

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: DataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the total power sensor."""
        super().__init__(coordinator)
        self.hass = hass
        self._entry = entry
        friendly = entry_friendly_name(entry)
        self._attr_name = f"{friendly} Total Power"
        self._attr_unique_id = f"powerclimate_total_power_{entry.entry_id}"
        self._attr_extra_state_attributes = {}
        self._attr_native_unit_of_measurement = None
        self._energy_sensors = self._configured_energy_sensors()
        self._sensor_unsubs: list[Callable[[], None]] = []
        self._attr_device_info = integration_device_info(entry)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self._energy_sensors:
            unsub = async_track_state_change_event(
                self.hass,
                self._energy_sensors,
                self._handle_energy_change,
            )
            if unsub:
                self._sensor_unsubs.append(unsub)

    async def async_will_remove_from_hass(self) -> None:
        for unsub in self._sensor_unsubs:
            unsub()
        self._sensor_unsubs.clear()
        await super().async_will_remove_from_hass()

    async def _handle_energy_change(self, event) -> None:
        self.async_schedule_update_ha_state(True)

    @property
    def native_value(self) -> float | None:
        self._ensure_unit()
        config = merged_entry_data(self._entry)
        devices = config.get(CONF_DEVICES, [])
        total = 0.0
        configured_sources = 0
        active_sources = 0
        missing_sources: list[str] = []
        contributions: list[dict[str, object]] = []

        for device in devices:
            sensor_id = device.get(CONF_ENERGY_SENSOR)
            if not sensor_id:
                continue
            configured_sources += 1
            value = self._read_sensor_value(sensor_id)
            if value is None:
                missing_sources.append(sensor_id)
                continue
            power = round(value)
            total += power
            active_sources += 1
            contributions.append(
                {
                    "sensor": sensor_id,
                    "value": power,
                },
            )

        attributes: dict[str, object] = {
            "source_count": configured_sources,
            "active_sources": active_sources,
        }
        if missing_sources:
            attributes["missing_sources"] = missing_sources
        if contributions:
            attributes["sources"] = contributions
        self._attr_extra_state_attributes = attributes

        if configured_sources == 0:
            return None
        if active_sources == 0:
            return 0.0
        return round(total)

    def _ensure_unit(self) -> None:
        if self._attr_native_unit_of_measurement:
            return
        for sensor_id in self._energy_sensors:
            if not sensor_id:
                continue
            state = self.hass.states.get(sensor_id)
            if not state:
                continue
            unit = state.attributes.get("unit_of_measurement")
            if unit:
                self._attr_native_unit_of_measurement = unit
                return

    def _configured_energy_sensors(self) -> list[str]:
        sensors: list[str] = []
        config = merged_entry_data(self._entry)
        for device in config.get(CONF_DEVICES, []):
            sensor_id = device.get(CONF_ENERGY_SENSOR)
            if sensor_id:
                sensors.append(sensor_id)
        return sensors

    def _read_sensor_value(self, sensor_id: str) -> float | None:
        state = self.hass.states.get(sensor_id)
        if not state:
            return None
        value = state.state
        if value in (None, "unknown", "unavailable"):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            normalized = (
                value.replace(",", ".")
                if isinstance(value, str)
                else value
            )
            try:
                return float(normalized)
            except (TypeError, ValueError):
                return None
