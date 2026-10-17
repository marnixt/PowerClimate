"""Tests for PowerClimate diagnostic sensors."""

from types import SimpleNamespace

from custom_components.powerclimate.const import (
    CONF_CLIMATE_ENTITY,
    CONF_DEVICES,
    DOMAIN,
)
from custom_components.powerclimate.sensor import (
    PowerClimateHeatPumpModeSensor,
    PowerClimateSupplyCorrectionSensor,
    PowerClimateTargetTemperatureSensor,
    _build_heat_pump_sensors,
)


def make_entry(devices):
    """Create a minimal config-entry-like object."""
    return SimpleNamespace(
        entry_id="entry-1", title="PowerClimate", data={CONF_DEVICES: devices}, options={}
    )


def test_build_heat_pump_sensors_includes_all_configured_devices() -> None:
    """A mode sensor is created for every configured device, not only the first five."""
    devices = [{CONF_CLIMATE_ENTITY: f"climate.hp{index}"} for index in range(1, 7)]

    sensors = _build_heat_pump_sensors(_summary_hass(), make_entry(devices))

    assert [sensor._role for sensor in sensors] == [f"hp{index}" for index in range(1, 7)]
    assert sensors[0].unique_id == "powerclimate_text_hp1_behavior_entry-1"


def test_build_heat_pump_sensors_skips_devices_without_entity() -> None:
    devices = [{CONF_CLIMATE_ENTITY: "climate.hp1"}, {}, {CONF_CLIMATE_ENTITY: "climate.hp3"}]

    sensors = _build_heat_pump_sensors(_summary_hass(), make_entry(devices))

    assert [sensor._role for sensor in sensors] == ["hp1", "hp3"]


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
                "supply_pi_source": "sensor.supply_advice",
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
    assert attributes["supply_pi_source"] == "sensor.supply_advice"
    assert attributes["supply_pi_error"] == 2.0


def test_supply_correction_sensor_none_when_inactive() -> None:
    sensor = PowerClimateSupplyCorrectionSensor(
        _summary_hass({"supply_pi_active": False, "supply_pi_correction": None}),
        make_entry([]),
    )

    assert sensor.native_value is None


def test_heat_pump_mode_sensor_reports_mode_and_status() -> None:
    sensor = PowerClimateHeatPumpModeSensor(
        _summary_hass(
            {
                "hp_status": [
                    {"role": "hp1", "powerclimate_mode": "supply_advice", "energy": 800.0},
                    {"role": "hp2", "powerclimate_mode": "minimal", "on_timer_seconds": 30.0},
                ]
            }
        ),
        make_entry([]),
        role="hp2",
        label="HP2",
    )

    assert sensor.native_value == "minimal"
    assert sensor.native_value in sensor.options
    assert sensor.extra_state_attributes == {
        "powerclimate_mode": "minimal",
        "on_timer_seconds": 30.0,
    }


def test_heat_pump_mode_sensor_without_summary() -> None:
    sensor = PowerClimateHeatPumpModeSensor(
        _summary_hass(), make_entry([]), role="hp1", label="HP1"
    )

    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {}
