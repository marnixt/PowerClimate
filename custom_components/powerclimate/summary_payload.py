"""Build the parts of the summary payload that the diagnostic sensors show.

Pure functions: the climate entity gathers the inputs and passes them in.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from homeassistant.components.climate.const import HVACMode

from .const import (
    CONF_ALLOW_ON_OFF_CONTROL,
    CONF_CLIMATE_ENTITY,
    CONF_DEVICE_NAME,
    MODE_OFF,
)
from .utils import compute_eta_hours, safe_float


def build_mpc_summary(
    sensor_id: str | None,
    advised_temp: float | None,
    raw_state: Any,
    attrs: Mapping[str, Any],
) -> dict[str, Any]:
    """Build diagnostics for the optional external MPC sensor."""
    if not sensor_id:
        return {
            "mpc_enabled": False,
            "mpc_sensor_entity_id": None,
            "mpc_advised_temperature": None,
            "mpc_raw_state": None,
            "mpc_state_available": False,
        }

    forecast_6h = attrs.get("forecast_6h")
    return {
        "mpc_enabled": True,
        "mpc_sensor_entity_id": sensor_id,
        "mpc_advised_temperature": advised_temp,
        "mpc_raw_state": raw_state,
        "mpc_state_available": advised_temp is not None,
        "mpc_model_source": attrs.get("model_source"),
        "mpc_heat_demand_w": safe_float(attrs.get("heat_demand_w")),
        "mpc_net_demand_w": safe_float(attrs.get("net_demand_w")),
        "mpc_outdoor_temp": safe_float(attrs.get("outdoor_temp")),
        "mpc_flow_lph": safe_float(attrs.get("flow_lph")),
        "mpc_return_temp": safe_float(attrs.get("return_temp")),
        "mpc_forecast_6h": forecast_6h if isinstance(forecast_6h, list) else None,
    }


def build_thermal_summary(
    thermal_state: Mapping[str, Any],
    recommended_temp: float | None,
) -> dict[str, Any]:
    """Build diagnostics for the internal thermal MPC model."""
    return {
        "thermal_ua_emitter": thermal_state.get("ua_emitter"),
        "thermal_u_building": thermal_state.get("u_building"),
        "thermal_ua_emitter_updates": thermal_state.get("ua_emitter_updates"),
        "thermal_u_building_updates": thermal_state.get("u_building_updates"),
        "thermal_is_converged": thermal_state.get("is_converged"),
        "thermal_recommended_temp": recommended_temp,
    }


def build_hp_status(
    devices: list[dict[str, Any]],
    device_payloads: Mapping[str, Mapping[str, Any]],
    coordinator_data: Mapping[str, Any],
    *,
    is_water_device: Callable[[dict[str, Any], int], bool],
    active_devices: set[str],
    assist_modes: Mapping[str, str],
    hp_modes: Mapping[str, str],
    assist_status: Callable[[str], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build the per-heat-pump status list.

    Args:
        devices: Configured devices, in order.
        device_payloads: Latest state per climate entity ID.
        coordinator_data: Latest coordinator data.
        is_water_device: Returns True for the water heat pump.
        active_devices: Entity IDs PowerClimate currently runs.
        assist_modes: Assist mode per air heat pump.
        hp_modes: PowerClimate mode per heat pump.
        assist_status: Returns assist timer info for an air heat pump.
    """
    status: list[dict[str, Any]] = []

    for index, device in enumerate(devices):
        entity_id = device.get(CONF_CLIMATE_ENTITY)
        if not entity_id:
            continue

        payload = device_payloads.get(entity_id, {}) or {}
        hvac_mode = str(payload.get("hvac_mode") or "").lower()
        is_running = hvac_mode and hvac_mode != HVACMode.OFF.value
        is_water = is_water_device(device, index)

        if is_water:
            water_derivative = safe_float(coordinator_data.get("water_derivative"))
        else:
            water_derivative = safe_float(payload.get("water_derivative"))

        current = safe_float(payload.get("current_temperature"))
        target = safe_float(payload.get("target_temperature"))
        derivative = safe_float(payload.get("temperature_derivative"))
        hp_info: dict[str, Any] = {
            "role": f"hp{index + 1}",
            "name": device.get(CONF_DEVICE_NAME) or f"HP{index + 1}",
            "entity_id": entity_id,
            "active": entity_id in active_devices or is_running,
            "hvac_mode": payload.get("hvac_mode"),
            "assist_mode": None if is_water else assist_modes.get(entity_id, "off"),
            "powerclimate_mode": hp_modes.get(entity_id, MODE_OFF),
            "current_temperature": current,
            "target_temperature": target,
            "temperature_derivative": derivative,
            "water_temperature": safe_float(payload.get("water_temperature")),
            "water_derivative": water_derivative,
            "eta_hours": compute_eta_hours(
                target - current if target is not None and current is not None else None,
                derivative,
            ),
            "energy": safe_float(payload.get("energy")),
        }

        if not is_water:
            hp_info["allow_on_off_control"] = device.get(CONF_ALLOW_ON_OFF_CONTROL, False)
            hp_info.update(assist_status(entity_id))

        status.append(hp_info)

    return status
