"""Tests for the summary payload builders."""

from custom_components.powerclimate.const import CONF_CLIMATE_ENTITY, CONF_DEVICE_NAME
from custom_components.powerclimate.summary_payload import (
    build_hp_status,
    build_mpc_summary,
    build_thermal_summary,
)


def test_mpc_summary_disabled_without_sensor():
    summary = build_mpc_summary(None, None, None, {})
    assert summary["mpc_enabled"] is False
    assert summary["mpc_state_available"] is False


def test_mpc_summary_reads_attributes():
    summary = build_mpc_summary(
        "sensor.mpc",
        31.5,
        "31.5",
        {"heat_demand_w": "1200", "forecast_6h": [1, 2], "model_source": "fit"},
    )
    assert summary["mpc_state_available"] is True
    assert summary["mpc_heat_demand_w"] == 1200.0
    assert summary["mpc_forecast_6h"] == [1, 2]
    assert summary["mpc_model_source"] == "fit"


def test_mpc_summary_ignores_invalid_forecast():
    summary = build_mpc_summary("sensor.mpc", None, "unknown", {"forecast_6h": "x"})
    assert summary["mpc_forecast_6h"] is None
    assert summary["mpc_state_available"] is False


def test_thermal_summary():
    summary = build_thermal_summary({"ua_emitter": 150.0, "is_converged": True}, 32.0)
    assert summary["thermal_ua_emitter"] == 150.0
    assert summary["thermal_is_converged"] is True
    assert summary["thermal_recommended_temp"] == 32.0


def _status(devices, payloads, **overrides):
    kwargs = {
        "is_water_device": lambda device, index: index == 0,
        "active_devices": set(),
        "assist_modes": {},
        "hp_modes": {},
        "assist_status": lambda entity_id: {"on_timer_seconds": 5.0},
    }
    kwargs.update(overrides)
    return build_hp_status(devices, payloads, {"water_derivative": 1.5}, **kwargs)


def test_hp_status_water_and_air():
    devices = [
        {CONF_CLIMATE_ENTITY: "climate.water", CONF_DEVICE_NAME: "Water"},
        {CONF_CLIMATE_ENTITY: "climate.air"},
    ]
    payloads = {
        "climate.water": {"hvac_mode": "heat"},
        "climate.air": {
            "hvac_mode": "off",
            "current_temperature": 20.0,
            "target_temperature": 21.0,
            "temperature_derivative": 0.5,
        },
    }

    water, air = _status(devices, payloads, hp_modes={"climate.air": "minimal"})

    assert water["name"] == "Water"
    assert water["active"]
    assert water["assist_mode"] is None
    assert water["water_derivative"] == 1.5
    assert "on_timer_seconds" not in water

    assert air["name"] == "HP2"
    assert not air["active"]
    assert air["assist_mode"] == "off"
    assert air["powerclimate_mode"] == "minimal"
    assert air["eta_hours"] == 2.0
    assert air["on_timer_seconds"] == 5.0


def test_hp_status_skips_devices_without_entity_and_handles_bad_values():
    devices = [{}, {CONF_CLIMATE_ENTITY: "climate.air"}]
    payloads = {"climate.air": {"current_temperature": "n/a", "target_temperature": 21.0}}

    (air,) = _status(devices, payloads)

    assert air["role"] == "hp2"
    assert air["eta_hours"] is None
