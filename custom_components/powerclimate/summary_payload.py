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
from .pi_controller import PIResult
from .utils import compute_eta_hours, safe_float


def build_supply_advice_summary(
    sensor_id: str | None,
    advised_temp: float | None,
    raw_state: Any,
) -> dict[str, Any]:
    """Build diagnostics for the optional supply advice sensor."""
    return {
        "supply_advice_enabled": bool(sensor_id),
        "supply_advice_sensor_entity_id": sensor_id or None,
        "supply_advice_temperature": advised_temp if sensor_id else None,
        "supply_advice_raw_state": raw_state if sensor_id else None,
        "supply_advice_available": bool(sensor_id) and advised_temp is not None,
    }


def build_supply_pi_summary(
    source: str | None,
    *,
    advised_temp: float | None = None,
    supply_temp: float | None = None,
    supply_filtered: float | None = None,
    spike: bool = False,
    result: PIResult | None = None,
    correction: float | None = None,
) -> dict[str, Any]:
    """Build diagnostics for the supply-temperature controller.

    Args:
        source: The sensor the advice came from; None while the
            controller is not running.
        advised_temp: Advised supply temperature.
        supply_temp: Measured (raw) supply temperature.
        supply_filtered: Smoothed supply temperature the controller uses.
        spike: True while a supply spike holds the controller.
        result: Outcome of the last controller update.
        correction: Correction applied to the device temperature.
    """

    def rounded(value: float | None) -> float | None:
        return round(value, 2) if value is not None else None

    active = source is not None and result is not None
    return {
        "supply_pi_active": active,
        "supply_pi_source": source if active else None,
        "supply_pi_advised_temp": advised_temp if active else None,
        "supply_pi_supply_temp": supply_temp if active else None,
        "supply_pi_supply_filtered": rounded(supply_filtered) if active else None,
        "supply_pi_spike": spike if active else None,
        "supply_pi_error": rounded(result.error) if active else None,
        "supply_pi_p": rounded(result.p_term) if active else None,
        "supply_pi_i": rounded(result.i_term) if active else None,
        "supply_pi_correction": rounded(correction) if active else None,
        "supply_pi_integrating": result.integrating if active else None,
        "supply_pi_saturated": result.saturated if active else None,
    }


def build_room_pi_summary(
    *,
    result: PIResult | None = None,
    correction: float | None = None,
    supply_hot: bool = False,
    assist_running: bool = False,
    at_limit: bool = False,
) -> dict[str, Any]:
    """Build diagnostics for the water heat pump's room control.

    Args:
        result: Outcome of the last controller update; None while the
            controller is not running.
        correction: Correction applied to the device temperature.
        supply_hot: True when the supply has reached the assist water
            threshold (the integral does not grow).
        assist_running: True while an assist pump heats (the integral
            does not shrink).
        at_limit: True when the water heat pump cannot push harder.
    """

    def rounded(value: float | None) -> float | None:
        return round(value, 2) if value is not None else None

    active = result is not None
    return {
        "room_pi_active": active,
        "room_pi_error": rounded(result.error) if active else None,
        "room_pi_p": rounded(result.p_term) if active else None,
        "room_pi_i": rounded(result.i_term) if active else None,
        "room_pi_correction": rounded(correction) if active else None,
        "room_pi_integrating": result.integrating if active else None,
        "room_pi_supply_hot": supply_hot if active else None,
        "room_pi_assist_running": assist_running if active else None,
        "room_pi_at_limit": at_limit if active else None,
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
