"""Tests for PowerClimate diagnostic sensors."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from custom_components.powerclimate.const import (
    CONF_CLIMATE_ENTITY,
    CONF_DEVICES,
    CONF_ENERGY_SENSOR,
    DOMAIN,
)
from custom_components.powerclimate.sensor import (
    PowerClimateThermalModelTextSensor,
    PowerClimateThermalRecommendedSensor,
    PowerClimateThermalSummarySensor,
    PowerClimateAssistSummarySensor,
    PowerClimateTotalPowerSensor,
    _build_behavior_sensors,
)


def make_entry(devices):
    """Create a minimal config-entry-like object."""
    return SimpleNamespace(entry_id="entry-1", title="PowerClimate", data={CONF_DEVICES: devices}, options={})


def _make_summary_sensor(devices=None):
    """Return a PowerClimateThermalSummarySensor wired to a minimal hass stub."""
    hass = SimpleNamespace(
        data={DOMAIN: {}},
        config=SimpleNamespace(language="en", path=lambda *parts: ""),
    )
    entry = make_entry(devices or [])
    sensor = PowerClimateThermalSummarySensor(hass, entry)
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


def test_thermal_summary_formats_lowercase_preset_modes() -> None:
    """Thermal summary text should render normalized lowercase preset IDs."""
    sensor = _make_summary_sensor()

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


def test_thermal_summary_handles_missing_optional_fields() -> None:
    """Thermal summary should not raise when optional payload fields are absent."""
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


def test_thermal_summary_shows_room_temperature_when_present() -> None:
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


def test_build_behavior_sensors_single_device_creates_hp1_sensor() -> None:
    """A config with only one device should produce exactly one HP1 behavior sensor."""
    devices = [{CONF_CLIMATE_ENTITY: "climate.hp1"}]
    entry = make_entry(devices)

    created = []

    with patch(
        "custom_components.powerclimate.sensor.PowerClimateHP1BehaviorSensor",
        side_effect=lambda hass, entry: created.append("hp1") or "hp1",
    ), patch(
        "custom_components.powerclimate.sensor.PowerClimateHPBehaviorSensor",
        side_effect=lambda hass, entry, role, prefix, label: created.append("hpN") or "hpN",
    ):
        sensors = _build_behavior_sensors(MagicMock(), entry)

    assert len(sensors) == 1
    assert "hp1" in created
    assert "hpN" not in created


def test_total_power_sensor_normalizes_mixed_units_to_watts() -> None:
    """Total power should add W and kW sources in one unit."""
    hass = MagicMock()
    states = {
        "sensor.hp1_power": SimpleNamespace(
            state="1000",
            attributes={"unit_of_measurement": "W"},
        ),
        "sensor.hp2_power": SimpleNamespace(
            state="1.5",
            attributes={"unit_of_measurement": "kW"},
        ),
    }
    hass.states.get.side_effect = states.get
    entry = make_entry(
        [
            {
                CONF_CLIMATE_ENTITY: "climate.hp1",
                CONF_ENERGY_SENSOR: "sensor.hp1_power",
            },
            {
                CONF_CLIMATE_ENTITY: "climate.hp2",
                CONF_ENERGY_SENSOR: "sensor.hp2_power",
            },
        ]
    )
    sensor = PowerClimateTotalPowerSensor(hass, MagicMock(), entry)

    assert sensor.native_value == 2500
    assert sensor.native_unit_of_measurement == "W"
    assert sensor.extra_state_attributes["sources"] == [
        {"sensor": "sensor.hp1_power", "value": 1000},
        {"sensor": "sensor.hp2_power", "value": 1500},
    ]


def test_assist_summary_includes_first_air_device_without_water_device() -> None:
    """An air-only installation must not hide its first assist pump."""
    hass = SimpleNamespace(
        data={DOMAIN: {}},
        config=SimpleNamespace(language="en", path=lambda *parts: ""),
    )
    sensor = PowerClimateAssistSummarySensor(hass, make_entry([]))
    sensor._strings = {}

    text = sensor._format_payload(
        {
            "room_temperature": 21.0,
            "target_temperature": 21.0,
            "hp_status": [
                {
                    "role": "hp1",
                    "name": "Living Room",
                    "assist_mode": "off",
                    "hvac_mode": "off",
                }
            ],
        }
    )

    assert "No assist pumps configured" not in text
    assert "Living" in text


# ---------------------------------------------------------------------------
# PowerClimateThermalModelTextSensor
# ---------------------------------------------------------------------------

def _make_thermal_model_text_sensor():
    """Return a PowerClimateThermalModelTextSensor with a minimal hass stub."""
    hass = SimpleNamespace(
        data={DOMAIN: {}},
        config=SimpleNamespace(language="en", path=lambda *parts: ""),
    )
    entry = make_entry([])
    sensor = PowerClimateThermalModelTextSensor(hass, entry)
    sensor._strings = {}
    return sensor


def test_thermal_model_text_sensor_shows_learning_when_not_converged() -> None:
    """Sensor text should indicate learning progress when model is not yet converged."""
    sensor = _make_thermal_model_text_sensor()

    text = sensor._format_payload({
        "thermal_is_converged": False,
        "thermal_ua_emitter_updates": 5,
        "thermal_ua_emitter": 45.2,
        "thermal_u_building": 210.5,
        "thermal_recommended_temp": 42.0,
        "hvac_mode": "heat",
    })

    assert "Learning" in text
    assert "5/10" in text
    assert "42.0" in text


def test_thermal_model_text_sensor_shows_converged() -> None:
    """Sensor text should indicate convergence when model has enough updates."""
    sensor = _make_thermal_model_text_sensor()

    text = sensor._format_payload({
        "thermal_is_converged": True,
        "thermal_ua_emitter_updates": 20,
        "thermal_ua_emitter": 55.0,
        "thermal_u_building": 180.0,
        "thermal_recommended_temp": 38.5,
        "hvac_mode": "heat",
    })

    assert "Converged" in text
    assert "55.0" in text
    assert "180.0" in text
    assert "38.5" in text


def test_thermal_model_text_sensor_labels_ac_setpoint_in_cool_mode() -> None:
    """In cooling mode, suggested temperature should be labelled as AC setpoint."""
    sensor = _make_thermal_model_text_sensor()

    text = sensor._format_payload({
        "thermal_is_converged": True,
        "thermal_ua_emitter_updates": 15,
        "thermal_ua_emitter": 40.0,
        "thermal_u_building": 190.0,
        "thermal_recommended_temp": 22.0,
        "hvac_mode": "cool",
    })

    assert "AC" in text
    assert "22.0" in text


def test_thermal_model_text_sensor_handles_unavailable_payload() -> None:
    """Sensor should return 'unavailable' text when payload is None."""
    sensor = _make_thermal_model_text_sensor()
    assert sensor._format_payload(None) == "unavailable"


def test_thermal_model_text_sensor_extra_state_attributes() -> None:
    """extra_state_attributes should expose all thermal model fields."""
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": {"summary_payload": {
            "thermal_ua_emitter": 50.0,
            "thermal_u_building": 200.0,
            "thermal_ua_emitter_updates": 12,
            "thermal_u_building_updates": 10,
            "thermal_is_converged": True,
            "thermal_recommended_temp": 41.0,
            "preset_mode": "thermal",
            "hvac_mode": "heat",
        }}}},
        config=SimpleNamespace(language="en", path=lambda *parts: ""),
    )
    entry = make_entry([])
    sensor = PowerClimateThermalModelTextSensor(hass, entry)
    attrs = sensor.extra_state_attributes

    assert attrs["ua_emitter"] == 50.0
    assert attrs["u_building"] == 200.0
    assert attrs["is_converged"] is True
    assert attrs["recommended_temp"] == 41.0
    assert attrs["preset_mode"] == "thermal"


# ---------------------------------------------------------------------------
# PowerClimateThermalRecommendedSensor
# ---------------------------------------------------------------------------

def _make_thermal_recommended_sensor(summary: dict | None = None):
    """Return a PowerClimateThermalRecommendedSensor with a minimal hass stub."""
    entry_data = {"summary_payload": summary} if summary is not None else {}
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": entry_data}},
        config=SimpleNamespace(language="en", path=lambda *parts: ""),
    )
    entry = make_entry([])
    sensor = PowerClimateThermalRecommendedSensor(hass, entry)
    sensor._payload = summary
    return sensor


def test_thermal_recommended_sensor_returns_recommended_temp() -> None:
    """native_value should return the thermal_recommended_temp from the payload."""
    sensor = _make_thermal_recommended_sensor({
        "thermal_recommended_temp": 43.5,
        "preset_mode": "thermal",
        "hvac_mode": "heat",
    })

    assert sensor.native_value == 43.5


def test_thermal_recommended_sensor_returns_none_when_no_payload() -> None:
    """native_value should return None when there is no summary payload."""
    sensor = _make_thermal_recommended_sensor(None)

    assert sensor.native_value is None


def test_thermal_recommended_sensor_returns_none_when_key_missing() -> None:
    """native_value should return None when the key is absent from the payload."""
    sensor = _make_thermal_recommended_sensor({
        "preset_mode": "thermal",
        "hvac_mode": "heat",
    })

    assert sensor.native_value is None


def test_thermal_recommended_sensor_extra_state_attributes() -> None:
    """extra_state_attributes should expose model diagnostics."""
    sensor = _make_thermal_recommended_sensor({
        "thermal_recommended_temp": 40.0,
        "thermal_ua_emitter": 47.3,
        "thermal_u_building": 195.0,
        "thermal_is_converged": False,
        "thermal_ua_emitter_updates": 7,
        "preset_mode": "thermal",
        "hvac_mode": "heat",
    })

    attrs = sensor.extra_state_attributes
    assert attrs["ua_emitter"] == 47.3
    assert attrs["u_building"] == 195.0
    assert attrs["is_converged"] is False
    assert attrs["ua_emitter_updates"] == 7
    assert attrs["preset_mode"] == "thermal"


# ---------------------------------------------------------------------------
# PowerClimateThermalSummarySensor — thermal preset fragment
# ---------------------------------------------------------------------------

def test_thermal_summary_shows_thermal_info_when_preset_is_thermal() -> None:
    """Thermal Summary should include model state when preset is 'thermal'."""
    sensor = _make_summary_sensor()

    text = sensor._format_payload({
        "preset_mode": "thermal",
        "hvac_mode": "heat",
        "room_temperature": 19.0,
        "target_temperature": 21.0,
        "derivative": 0.5,
        "room_eta_hours": 1.0,
        "thermal_is_converged": False,
        "thermal_ua_emitter_updates": 3,
        "thermal_recommended_temp": 44.0,
        "hp_status": [],
    })

    assert "Learning" in text
    assert "3/10" in text
    assert "44.0" in text


def test_thermal_summary_hides_thermal_info_when_preset_is_none() -> None:
    """Thermal Summary should NOT include model state when preset is not 'thermal'."""
    sensor = _make_summary_sensor()

    text = sensor._format_payload({
        "preset_mode": "none",
        "hvac_mode": "heat",
        "room_temperature": 19.0,
        "target_temperature": 21.0,
        "derivative": 0.5,
        "room_eta_hours": 1.0,
        "thermal_is_converged": False,
        "thermal_ua_emitter_updates": 3,
        "thermal_recommended_temp": 44.0,
        "hp_status": [],
    })

    assert "Learning" not in text
    assert "Suggested" not in text