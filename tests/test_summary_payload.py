"""Tests for the summary payload builders."""

from custom_components.powerclimate.const import CONF_CLIMATE_ENTITY, CONF_DEVICE_NAME
from custom_components.powerclimate.pi_controller import PIResult
from custom_components.powerclimate.summary_payload import (
    build_hp_status,
    build_supply_advice_summary,
    build_supply_pi_summary,
)


def test_supply_pi_summary_inactive():
    summary = build_supply_pi_summary(None)
    assert summary["supply_pi_active"] is False
    assert summary["supply_pi_correction"] is None
    assert summary["supply_pi_source"] is None


def test_supply_pi_summary_reports_controller_state():
    result = PIResult(
        output=0.4567, error=2.0, p_term=0.2, i_term=0.2567,
        integrating=True, saturated=False,
    )
    summary = build_supply_pi_summary(
        "sensor.supply_advice",
        advised_temp=30.0,
        supply_temp=28.0,
        result=result,
        correction=0.4567,
    )
    assert summary["supply_pi_active"] is True
    assert summary["supply_pi_source"] == "sensor.supply_advice"
    assert summary["supply_pi_advised_temp"] == 30.0
    assert summary["supply_pi_supply_temp"] == 28.0
    assert summary["supply_pi_error"] == 2.0
    assert summary["supply_pi_i"] == 0.26
    assert summary["supply_pi_correction"] == 0.46
    assert summary["supply_pi_integrating"] is True
    assert summary["supply_pi_saturated"] is False


def test_supply_advice_summary_disabled_without_sensor():
    summary = build_supply_advice_summary(None, None, None)
    assert summary["supply_advice_enabled"] is False
    assert summary["supply_advice_available"] is False
    assert summary["supply_advice_temperature"] is None


def test_supply_advice_summary_reports_advice():
    summary = build_supply_advice_summary("sensor.supply_advice", 31.5, "31.5")
    assert summary["supply_advice_enabled"] is True
    assert summary["supply_advice_available"] is True
    assert summary["supply_advice_temperature"] == 31.5


def test_supply_advice_summary_unavailable_without_value():
    summary = build_supply_advice_summary("sensor.supply_advice", None, "unknown")
    assert summary["supply_advice_available"] is False
    assert summary["supply_advice_raw_state"] == "unknown"


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
