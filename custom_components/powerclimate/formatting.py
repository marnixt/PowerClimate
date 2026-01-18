"""Formatting utilities for PowerClimate sensors.

This module provides reusable formatting functions and mixins
for displaying sensor values in a human-readable format.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


class TranslationMixin:
    """Mixin providing translated string access with fallback to English."""

    def __init__(self) -> None:
        """Initialize the translation mixin."""
        self._strings: dict[str, str] = {}

    async def _load_strings(self, hass: HomeAssistant) -> None:
        """Load translated strings asynchronously.

        Args:
            hass: Home Assistant instance.
        """
        from .helpers import async_get_strings

        self._strings = await async_get_strings(hass)

    def _t(self, key: str, default: str) -> str:
        """Get translated string with fallback.

        Args:
            key: Translation key.
            default: Default value if key not found.

        Returns:
            Translated string or default.
        """
        return str(self._strings.get(key, default))


class TemperatureFormatter(TranslationMixin):
    """Formatter for temperature-related values."""

    def format_temp_pair(
        self,
        label: str,
        current: float | int | None,
        target: float | int | None,
    ) -> str:
        """Format current/target temperature pair.

        Args:
            label: Label for the temperature (e.g., "Room").
            current: Current temperature.
            target: Target temperature.

        Returns:
            Formatted string like "Room 20.5°C→21.0°C".
        """
        none_text = self._t("value_none", "none")

        if isinstance(current, (int, float)):
            parts = [f"{label} {current:.1f}°C"]
            if isinstance(target, (int, float)):
                parts.append(f"→{target:.1f}°C")
            return "".join(parts)

        if isinstance(target, (int, float)):
            return f"{label} →{target:.1f}°C"

        return f"{label} {none_text}"

    def format_derivative(
        self,
        label: str,
        value: float | int | None,
    ) -> str:
        """Format temperature derivative.

        Args:
            label: Label for the derivative.
            value: Derivative value in °C/hour.

        Returns:
            Formatted string like "ΔT 1.5°C/h".
        """
        if isinstance(value, (int, float)):
            return f"{label} {value:.1f}°C/h"
        return f"{label} {self._t('value_none', 'none')}"

    def format_eta(self, eta_hours: float | int | None) -> str:
        """Format estimated time of arrival.

        Args:
            eta_hours: ETA in hours.

        Returns:
            Formatted string like "ETA 2.5h" or "ETA 30m".
        """
        label = self._t("label_eta", "ETA")
        none_text = self._t("value_none", "none")

        if not isinstance(eta_hours, (int, float)) or eta_hours <= 0:
            return f"{label} {none_text}"

        if eta_hours >= 1:
            return f"{label} {eta_hours:.1f}h"

        minutes = eta_hours * 60.0
        if minutes >= 1:
            return f"{label} {minutes:.0f}m"

        return f"{label} {minutes * 60:.0f}s"

    def format_power(self, value: float | int | None) -> str | None:
        """Format power value.

        Args:
            value: Power in watts.

        Returns:
            Formatted string like "Power 1200 W", or None if no value.
        """
        if not isinstance(value, (int, float)):
            return None
        return f"{self._t('label_power', 'Power')} {round(value)} W"


class SensorFormatter(TemperatureFormatter):
    """Extended formatter for PowerClimate sensors."""

    @staticmethod
    def short_hp_label(raw_label: object, role: str) -> str:
        """Generate a short label for a heat pump.

        Args:
            raw_label: Raw label text.
            role: Heat pump role (e.g., "hp1").

        Returns:
            Short label like "HP1 (water)".
        """
        text = str(raw_label or "").strip()
        base = text.split()[0][:10] if text else role.upper()
        return f"{base} ({role})"

    def format_room_average(
        self,
        readings: list[float] | None,
        average: float | None,
    ) -> str | None:
        """Format room temperature average from multiple sensors.

        Args:
            readings: List of sensor readings.
            average: Calculated average.

        Returns:
            Formatted string showing calculation, or None if no data.
        """
        if not readings and not isinstance(average, (int, float)):
            return None

        avg_label = self._t("label_avg_room", "Avg room")
        avg_func = self._t("label_avg_func", "avg")
        none_text = self._t("value_none", "none")

        samples = [
            f"{value:.1f}°C"
            for value in (readings or [])
            if isinstance(value, (int, float))
        ]

        if samples and isinstance(average, (int, float)):
            return f"{avg_label} = {avg_func}({' '.join(samples)}) = {average:.1f}°C"

        if samples:
            return f"{avg_label} = {avg_func}({' '.join(samples)}) = {none_text}"

        if isinstance(average, (int, float)):
            return f"{avg_label} = {average:.1f}°C"

        return f"{avg_label} = {none_text}"

    def format_hp_snapshot(
        self,
        label: str,
        entry: dict[str, Any] | None,
    ) -> list[str]:
        """Format heat pump status snapshot.

        Args:
            label: Heat pump label.
            entry: HP status entry from summary payload.

        Returns:
            List of formatted status parts.
        """
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

        # Temperature pair
        temp_text = self.format_temp_pair(
            self._t("label_temps", "Temps"),
            entry.get("current_temperature"),
            entry.get("target_temperature"),
        )
        parts.append(temp_text)

        # Derivative
        parts.append(
            self.format_derivative(
                self._t("label_derivative", "ΔT"),
                entry.get("temperature_derivative"),
            )
        )

        # ETA
        parts.append(self.format_eta(entry.get("eta_hours")))

        # Water temperature
        water_temp = entry.get("water_temperature")
        if isinstance(water_temp, (int, float)):
            water_label = self._t("label_water", "Water")
            parts.append(f"{water_label} {water_temp:.1f}°C")

        # Power
        power_text = self.format_power(entry.get("energy"))
        if power_text:
            parts.append(power_text)

        if not parts:
            parts.append(none_text)

        return parts

    def get_condition_labels(
        self,
        eta_on_minutes: float | None,
        eta_off_minutes: float | None,
    ) -> dict[str, str]:
        """Get human-readable labels for assist conditions.

        Args:
            eta_on_minutes: ETA ON threshold in minutes.
            eta_off_minutes: ETA OFF threshold in minutes.

        Returns:
            Dictionary mapping condition names to labels.
        """
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

    def get_preset_label(self, preset_mode: str | None) -> str:
        """Get human-readable label for preset mode.

        Args:
            preset_mode: Preset mode string.

        Returns:
            Translated preset label.
        """
        if preset_mode == "boost":
            return self._t("preset_boost", "Boost")
        elif preset_mode == "Away":
            return self._t("preset_away", "Away")
        elif preset_mode == "Solar":
            return self._t("preset_solar", "Solar")
        else:
            return self._t("preset_none", "None")


def format_timer(elapsed_seconds: int, total_seconds: int) -> str:
    """Format timer display as elapsed/total.

    Args:
        elapsed_seconds: Seconds elapsed.
        total_seconds: Total seconds for timer.

    Returns:
        Formatted string like "1:30/5:00".
    """
    elapsed_seconds = max(0, int(elapsed_seconds))
    total_seconds = max(0, int(total_seconds))

    elapsed_min = int(elapsed_seconds // 60)
    elapsed_sec = int(elapsed_seconds % 60)
    total_min = int(total_seconds // 60)
    total_sec = int(total_seconds % 60)
    return f"{elapsed_min}:{elapsed_sec:02d}/{total_min}:{total_sec:02d}"
