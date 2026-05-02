"""Tests for PowerClimate diagnostic sensors."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from custom_components.powerclimate.const import CONF_CLIMATE_ENTITY, CONF_DEVICES, DOMAIN
from custom_components.powerclimate.sensor import (
    PowerClimateThermalSummarySensor,
    _build_behavior_sensors,
)


def make_entry(devices):
    """Create a minimal config-entry-like object."""
    return SimpleNamespace(entry_id="entry-1", title="PowerClimate", data={CONF_DEVICES: devices}, options={})


def test_build_behavior_sensors_includes_all_configured_devices() -> None:
    """Behavior sensors should be created for every configured device, not only the first five."""
    devices = [{CONF_CLIMATE_ENTITY: f"climate.hp{index}"} for index in range(1, 7)]
    entry = make_entry(devices)

    with patch(
        "custom_components.powerclimate.sensor.PowerClimateHP1BehaviorSensor",
        side_effect=lambda hass, entry: f"hp1:{entry.entry_id}",
    ), patch(
        "custom_components.powerclimate.sensor.PowerClimateHPBehaviorSensor",
        side_effect=lambda hass, entry, role, prefix, label: f"{role}:{entry.entry_id}",
    ):
        sensors = _build_behavior_sensors(MagicMock(), entry)

    assert len(sensors) == 6


def test_thermal_summary_formats_lowercase_preset_modes() -> None:
    """Thermal summary text should render normalized lowercase preset IDs."""
    hass = SimpleNamespace(data={DOMAIN: {}}, config=SimpleNamespace(language="en", path=lambda *parts: ""))
    entry = make_entry([])
    sensor = PowerClimateThermalSummarySensor(hass, entry)
    sensor._strings = {}

    text = sensor._format_payload(
        {
            "preset_mode": "solar",
            "room_temperature": 20.0,
            "target_temperature": 21.0,
            "derivative": 0.4,
            "room_eta_hours": 1.5,
            "hp_status": [],
        }
    )

    assert "Preset: Solar" in text