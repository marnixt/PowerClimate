"""Assist summary and per-heat-pump behavior sensors."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory

from ..helpers import (
    integration_device_info,
    summary_signal,
)
from .common import SummaryPayloadTextSensor, TranslationMixin, snapshot_summary


class PowerClimateAssistSummarySensor(SummaryPayloadTextSensor):
    """Sensor providing human-readable assist pump control logic summary."""

    _attr_icon = "mdi:timer-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the assist summary sensor."""
        super().__init__(
            hass,
            entry,
            translation_key="assist_summary",
            unique_id_prefix="powerclimate_text_assist_summary",
        )

    def _format_payload(self, payload: dict | None) -> str:
        return self._format_assist_summary(payload)

    def _format_room_state_overview(self, payload: dict) -> list[str]:
        """Format room temperature, derivative, and ETA information."""
        parts: list[str] = []
        room_temp = payload.get("room_temperature")
        target_temp = payload.get("target_temperature")
        derivative = payload.get("derivative")
        eta_hours = payload.get("room_eta_hours")

        if isinstance(room_temp, (int, float)) and isinstance(target_temp, (int, float)):
            delta = room_temp - target_temp
            room_label = self._t("label_room", "Room")
            target_label = self._t("label_target", "target")
            delta_label = self._t("label_delta", "Δ")
            parts.append(
                f"{room_label}: {room_temp:.1f}°C "
                f"({target_label} {target_temp:.1f}°C, {delta_label}{delta:+.1f}°C)"
            )

        if isinstance(derivative, (int, float)):
            trend_label = self._t("label_trend", "Trend")
            if derivative > 0:
                trend = self._t("trend_warming", "warming")
            elif derivative < 0:
                trend = self._t("trend_cooling", "cooling")
            else:
                trend = self._t("trend_stable", "stable")
            parts.append(f"{trend_label}: {trend} ({derivative:+.1f}°C/h)")

        if isinstance(eta_hours, (int, float)) and eta_hours > 0:
            eta_label = self._t("label_eta", "ETA")
            hours_unit = self._t("unit_hours_short", "h")
            minutes_unit = self._t("unit_minutes_short", "min")
            eta_text = (
                f"{eta_hours:.1f}{hours_unit}"
                if eta_hours >= 1
                else f"{int(eta_hours * 60)}{minutes_unit}"
            )
            parts.append(f"{eta_label}: {eta_text}")

        return parts

    def _format_assist_summary(self, payload: dict | None) -> str:
        """Format assist pump control logic into a human-readable summary."""
        if not payload:
            return self._t("unavailable", "unavailable")

        parts = self._format_room_state_overview(payload)

        assist_timer_seconds = payload.get("assist_timer_seconds")
        eta_on_minutes = payload.get("assist_on_eta_threshold_minutes")
        eta_off_minutes = payload.get("assist_off_eta_threshold_minutes")

        condition_labels = self._condition_labels(
            eta_on_minutes,
            eta_off_minutes,
        )
        timer_total_seconds = self._timer_total_seconds(assist_timer_seconds)

        # Assist pump status
        hp_status = payload.get("hp_status", [])
        assist_pumps = [hp for hp in hp_status if hp.get("assist_mode") is not None]

        if not assist_pumps:
            parts.append(self._t("assist_no_pumps", "No assist pumps configured"))
            return " | ".join(parts)

        for hp in assist_pumps:
            raw_label = hp.get("name") or hp.get("role") or "HP"
            role = hp.get("role") or "hp?"
            hp_name = self._short_hp_label(raw_label, role)

            hvac_mode = (hp.get("hvac_mode") or "").lower()
            is_on = hvac_mode != "off"
            allow_control = hp.get("allow_on_off_control", False)

            hp_parts: list[str] = [hp_name]

            # State
            if is_on:
                hp_parts.append(self._t("state_on", "ON"))
            else:
                hp_parts.append(self._t("state_off", "OFF"))

            # Timer information
            if allow_control:
                on_timer = hp.get("on_timer_seconds", 0.0)
                off_timer = hp.get("off_timer_seconds", 0.0)
                condition = hp.get("active_condition", "none")
                blocked_by = str(hp.get("blocked_by") or "").strip()
                target_hvac_mode = str(hp.get("target_hvac_mode") or "").strip().lower()
                target_reason = str(hp.get("target_reason") or "").strip()

                if condition != "none":
                    condition_text = condition_labels.get(condition, condition)

                    if isinstance(on_timer, (int, float)) and on_timer > 0:
                        hp_parts.append(
                            f"{condition_text} "
                            f"ON:{self._format_timer(int(on_timer), int(timer_total_seconds))}"
                        )
                    elif isinstance(off_timer, (int, float)) and off_timer > 0:
                        hp_parts.append(
                            f"{condition_text} "
                            f"OFF:{self._format_timer(int(off_timer), int(timer_total_seconds))}"
                        )
                else:
                    hp_parts.append(self._t("assist_no_condition", "No condition"))

                # Explicitly show when PowerClimate is about to toggle HVAC mode.
                # This is separate from the timer direction above (which is a countdown).
                if target_hvac_mode in {"heat", "off"}:
                    reason_key = target_reason or condition
                    reason_text = (
                        condition_labels.get(reason_key, reason_key)
                        if reason_key
                        else ""
                    )
                    target_text = (
                        self._t("assist_target_on", "TargetON")
                        if target_hvac_mode == "heat"
                        else self._t("assist_target_off", "TargetOFF")
                    )
                    if reason_text:
                        hp_parts.append(f"{target_text}({reason_text})")
                    else:
                        hp_parts.append(target_text)

                if blocked_by:
                    blocked_label = self._t("assist_blocked", "Blocked")
                    hp_parts.append(f"{blocked_label}({blocked_by})")
            else:
                hp_parts.append(self._t("assist_manual_control", "Manual control"))

            parts.append(" ".join(hp_parts))

        return " | ".join(parts)

    @staticmethod
    def _timer_total_seconds(value) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        return 300.0

    def _condition_labels(self, eta_on_minutes, eta_off_minutes) -> dict[str, str]:
        return {
            "eta_high": (
                f"ETA>{int(eta_on_minutes)}m"
                if isinstance(eta_on_minutes, (int, float))
                else self._t("assist_condition_eta_high", "ETA high")
            ),
            "water_hot": self._t(
                "assist_condition_water_hot",
                "Water≥40°C",
            ),
            "stalled_below_target": self._t(
                "assist_condition_stalled_below_target",
                "Stalled",
            ),
            "eta_low": (
                f"ETA<{int(eta_off_minutes)}m"
                if isinstance(eta_off_minutes, (int, float))
                else self._t("assist_condition_eta_low", "ETA low")
            ),
            "stalled_at_target": self._t(
                "assist_condition_stalled_at_target",
                "At target",
            ),
            "overshoot": self._t(
                "assist_condition_overshoot",
                "Overshoot",
            ),
        }

    @staticmethod
    def _format_timer(elapsed_seconds: int, total_seconds: int) -> str:
        elapsed_seconds = max(0, int(elapsed_seconds))
        total_seconds = max(0, int(total_seconds))

        timer_min = int(elapsed_seconds // 60)
        timer_sec = int(elapsed_seconds % 60)
        total_min = int(total_seconds // 60)
        total_sec = int(total_seconds % 60)
        return f"{timer_min}:{timer_sec:02d}/{total_min}:{total_sec:02d}"


class _AssistBehaviorFormatter(TranslationMixin):
    def __init__(self) -> None:
        super().__init__()

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
        parts.append(f"{self._t('label_hvac', 'HVAC')} {hvac}")

        # Format temperature with optional (Boost) indicator
        temp_text = self._format_temp_pair(
            self._t("label_temps", "Temps"),
            entry.get("current_temperature"),
            entry.get("target_temperature"),
        )
        # Add (Boost) indicator if boost preset is active in payload
        payload = getattr(self, "_payload", None)
        if payload and payload.get("preset_mode") == "boost":
            temp_text = f"{temp_text} ({self._t('preset_boost', 'Boost')})"
        parts.append(temp_text)
        parts.append(
            self._format_derivative_fragment(
                self._t("label_derivative", "ΔT"),
                entry.get("temperature_derivative"),
            )
        )
        parts.append(self._format_eta_fragment(entry.get("eta_hours")))
        water_temp = entry.get("water_temperature")
        if isinstance(water_temp, (int, float)):
            water_label = self._t("label_water", "Water")
            parts.append(f"{water_label} {water_temp:.1f}°C")
        power_text = self._format_power_w(entry.get("energy"))
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
    _is_water_device = False

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        role: str,
        prefix: str,
        label: str,
    ) -> None:
        """Initialize the assist behavior sensor."""
        super().__init__()
        self.hass = hass
        self._entry = entry
        self._entry_id = entry.entry_id
        self._role = role
        self._label = label
        self._prefix = prefix
        self._signal = summary_signal(self._entry_id)
        self._unsub = None
        self._payload: dict | None = None
        self._hp_entry: dict | None = None
        self._value = self._format_payload(
            snapshot_summary(hass, self._entry_id),
        )
        self._attr_unique_id = (
            f"powerclimate_text_{prefix}_behavior_{self._entry_id}"
        )
        self._attr_translation_key = "hp_behavior"
        self._attr_translation_placeholders = {"label": label}
        self._attr_has_entity_name = True
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
            f"{self._prefix}_powerclimate_mode": entry.get("powerclimate_mode"),
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
            snapshot_summary(self.hass, self._entry_id),
        )
        self._unsub = async_dispatcher_connect(
            self.hass,
            self._signal,
            self._handle_summary,
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None
        await super().async_will_remove_from_hass()

    def _handle_summary(self, payload: dict | None) -> None:
        self._value = self._format_payload(payload)
        self.schedule_update_ha_state()

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
        # For HP1 we want to show water ΔT before power. Remove any existing
        # power fragment produced by the generic snapshot and then append
        # sensor-specific parts which will include water ΔT and power (if any).
        if self._is_water_device:
            power_prefix = f"{self._t('label_power', 'Power')} "
            parts = [p for p in parts if not p.startswith(power_prefix)]

        parts.extend(self._sensor_specific_parts(hp_entry))
        return " | ".join(parts)

    @staticmethod
    def _find_hp_entry(payload: dict, role: str) -> dict | None:
        for entry in payload.get("hp_status") or []:
            if entry.get("role") == role:
                return entry
        return None

    @staticmethod
    def _label_from_hp(entry: dict, fallback: str, role: str) -> str:
        raw_label = entry.get("name") or fallback or role.upper()
        return TranslationMixin._short_hp_label(raw_label, role)

    def _sensor_specific_parts(self, entry: dict) -> list[str]:
        parts: list[str] = []
        # Add PowerClimate mode if present
        mode = entry.get("powerclimate_mode")
        if mode:
            mode_label = self._t("label_mode", "Mode")
            parts.append(f"{mode_label}: {mode}")
        # Show thermal recommended temp when in thermal MPC mode
        if mode == "thermal_mpc":
            payload = self._payload or {}
            recommended = payload.get("thermal_recommended_temp")
            if isinstance(recommended, (int, float)):
                suggested_label = self._t("label_suggested", "Suggested")
                parts.append(f"{suggested_label} {recommended:.1f}\u00b0C")
        return parts


class PowerClimateHPBehaviorSensor(_AssistBehaviorSensor):
    """Sensor showing HP2+ assist behavior status (parameterized)."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        role: str,
        prefix: str,
        label: str,
    ) -> None:
        super().__init__(
            hass,
            entry,
            role=role,
            prefix=prefix,
            label=label,
        )


class PowerClimateHP1BehaviorSensor(_AssistBehaviorSensor):
    """Sensor showing water heat pump behavior with water temperature."""

    _is_water_device = True

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        role: str = "hp1",
        prefix: str = "hp1",
        label: str = "HP1",
    ) -> None:
        """Initialize the water heat pump behavior sensor."""
        super().__init__(
            hass,
            entry,
            role=role,
            prefix=prefix,
            label=label,
        )

    def _sensor_specific_parts(self, entry: dict) -> list[str]:
        parts: list[str] = []
        # Add PowerClimate mode if present
        mode = entry.get("powerclimate_mode")
        if mode:
            mode_label = self._t("label_mode", "Mode")
            parts.append(f"{mode_label}: {mode}")

        # Show thermal recommended temp when in thermal MPC mode
        if mode == "thermal_mpc":
            payload = self._payload or {}
            recommended = payload.get("thermal_recommended_temp")
            if isinstance(recommended, (int, float)):
                suggested_label = self._t("label_suggested", "Suggested")
                parts.append(f"{suggested_label} {recommended:.1f}°C")

        water_label = self._t("label_water", "Water")
        d_label = self._t("label_derivative", "ΔT")
        parts.append(
            self._format_derivative_fragment(
                f"{water_label} {d_label}",
                entry.get("water_derivative"),
            )
        )

        power_text = self._format_power_w(entry.get("energy"))
        if power_text:
            parts.append(power_text)

        return parts
