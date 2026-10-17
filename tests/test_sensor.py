"""Tests for PowerClimate diagnostic sensors."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from custom_components.powerclimate.const import (
    CONF_CLIMATE_ENTITY,
    CONF_DEVICE_ROLE,
    CONF_DEVICES,
    DEVICE_ROLE_AIR,
    DEVICE_ROLE_WATER,
    DOMAIN,
)
from custom_components.powerclimate.sensor import (
    PowerClimateHP1BehaviorSensor,
    PowerClimateSummarySensor,
    PowerClimateSupplyCorrectionSensor,
    PowerClimateTargetTemperatureSensor,
    _build_behavior_sensors,
)


def make_entry(devices):
    """Create a minimal config-entry-like object."""
    return SimpleNamespace(
        entry_id="entry-1", title="PowerClimate", data={CONF_DEVICES: devices}, options={}
    )


def _make_summary_sensor(devices=None):
    """Return a PowerClimateSummarySensor wired to a minimal hass stub."""
    hass = SimpleNamespace(
        data={DOMAIN: {}},
        config=SimpleNamespace(language="en", path=lambda *parts: ""),
    )
    entry = make_entry(devices or [])
    sensor = PowerClimateSummarySensor(hass, entry)
    sensor._strings = {}
    return sensor


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


def test_summary_formats_lowercase_preset_modes() -> None:
    """Summary text should render normalized lowercase preset IDs."""
    sensor = _make_summary_sensor()

    text = sensor._format_payload(
        {
            "preset_mode": "away",
            "room_temperature": 20.0,
            "target_temperature": 21.0,
            "derivative": 0.4,
            "room_eta_hours": 1.5,
            "hp_status": [],
        }
    )

    assert "Preset: Away" in text


def test_summary_handles_missing_optional_fields() -> None:
    """Summary should not raise when optional payload fields are absent."""
    sensor = _make_summary_sensor()

    text = sensor._format_payload(
        {
            "preset_mode": "none",
            "room_temperature": None,
            "target_temperature": None,
            "derivative": None,
            "room_eta_hours": None,
            "hp_status": [],
        }
    )

    assert isinstance(text, str)
    assert len(text) > 0


def test_summary_shows_room_temperature_when_present() -> None:
    """Room temperature should appear in the summary when provided."""
    sensor = _make_summary_sensor()

    text = sensor._format_payload(
        {
            "preset_mode": "none",
            "room_temperature": 20.5,
            "target_temperature": 21.0,
            "derivative": 0.2,
            "room_eta_hours": 2.0,
            "hp_status": [],
        }
    )

    assert "20.5" in text


def _build_with_patched_sensors(devices):
    created = []
    with patch(
        "custom_components.powerclimate.sensor.PowerClimateHP1BehaviorSensor",
        side_effect=lambda hass, entry, role, prefix, label: created.append(("water", role)),
    ), patch(
        "custom_components.powerclimate.sensor.PowerClimateHPBehaviorSensor",
        side_effect=lambda hass, entry, role, prefix, label: created.append(("air", role)),
    ):
        sensors = _build_behavior_sensors(MagicMock(), make_entry(devices))
    return sensors, created


def test_build_behavior_sensors_water_device_creates_water_sensor() -> None:
    """The water device should get the water behavior sensor."""
    devices = [{CONF_CLIMATE_ENTITY: "climate.hp1", CONF_DEVICE_ROLE: DEVICE_ROLE_WATER}]

    sensors, created = _build_with_patched_sensors(devices)

    assert len(sensors) == 1
    assert created == [("water", "hp1")]


def test_build_behavior_sensors_air_only_uses_assist_sensors() -> None:
    """Without a water device, the first air device must not get the water sensor."""
    devices = [
        {CONF_CLIMATE_ENTITY: "climate.ac1", CONF_DEVICE_ROLE: DEVICE_ROLE_AIR},
        {CONF_CLIMATE_ENTITY: "climate.ac2", CONF_DEVICE_ROLE: DEVICE_ROLE_AIR},
    ]

    _sensors, created = _build_with_patched_sensors(devices)

    assert created == [("air", "hp1"), ("air", "hp2")]


def test_total_power_sensor_converts_kw_to_w() -> None:
    """Mixed W/kW sources must be summed in watts."""
    from custom_components.powerclimate.sensor import PowerClimateTotalPowerSensor

    states = {
        "sensor.hp1_power": SimpleNamespace(state="500", attributes={"unit_of_measurement": "W"}),
        "sensor.hp2_power": SimpleNamespace(
            state="1.2", attributes={"unit_of_measurement": "kW"}
        ),
    }
    sensor = PowerClimateTotalPowerSensor.__new__(PowerClimateTotalPowerSensor)
    sensor.hass = SimpleNamespace(states=SimpleNamespace(get=states.get))
    sensor._energy_sensors = list(states)

    sensor._recalculate()

    assert sensor._attr_native_value == 1700
    assert sensor.native_unit_of_measurement == "W"


# ---------------------------------------------------------------------------
# Target temperature and supply correction
# ---------------------------------------------------------------------------


def _summary_hass(summary: dict | None = None) -> SimpleNamespace:
    entry_data = {"summary_payload": summary} if summary is not None else {}
    return SimpleNamespace(
        data={DOMAIN: {"entry-1": entry_data}},
        config=SimpleNamespace(language="en", path=lambda *parts: ""),
    )


def test_target_temperature_sensor_reports_room_target() -> None:
    """The target sensor exposes PowerClimate's room target, not a device setpoint."""
    sensor = PowerClimateTargetTemperatureSensor(
        _summary_hass({"target_temperature": 21.3}), make_entry([])
    )

    assert sensor.native_value == 21.3
    assert sensor.native_unit_of_measurement == "°C"
    assert sensor.entity_category is None


def test_target_temperature_sensor_without_summary() -> None:
    sensor = PowerClimateTargetTemperatureSensor(_summary_hass(), make_entry([]))

    assert sensor.native_value is None


def test_supply_correction_sensor_exposes_controller_state() -> None:
    sensor = PowerClimateSupplyCorrectionSensor(
        _summary_hass(
            {
                "supply_pi_active": True,
                "supply_pi_source": "mpc",
                "supply_pi_advised_temp": 30.0,
                "supply_pi_supply_temp": 28.0,
                "supply_pi_error": 2.0,
                "supply_pi_correction": 0.45,
            }
        ),
        make_entry([]),
    )

    assert sensor.native_value == 0.45
    attributes = sensor.extra_state_attributes
    assert attributes["supply_pi_source"] == "mpc"
    assert attributes["supply_pi_error"] == 2.0


def test_supply_correction_sensor_none_when_inactive() -> None:
    sensor = PowerClimateSupplyCorrectionSensor(
        _summary_hass({"supply_pi_active": False, "supply_pi_correction": None}),
        make_entry([]),
    )

    assert sensor.native_value is None


def test_hp1_behavior_shows_advice_and_correction_in_mpc_mode() -> None:
    sensor = PowerClimateHP1BehaviorSensor(_summary_hass(), make_entry([]))
    sensor._strings = {}

    text = sensor._format_payload(
        {
            "hp_status": [{"role": "hp1", "name": "Water", "powerclimate_mode": "mpc"}],
            "supply_pi_active": True,
            "supply_pi_advised_temp": 30.0,
            "supply_pi_correction": 0.45,
        }
    )

    assert "Advice 30.0°C" in text
    assert "Correction +0.5°C" in text
