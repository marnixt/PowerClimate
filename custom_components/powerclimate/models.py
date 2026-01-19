"""Data models for PowerClimate."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class DeviceConfig:
    """Heat pump device configuration."""
    device_id: str
    device_name: str
    device_role: str  # "water" or "air"
    climate_entity: str
    energy_sensor: str | None = None
    water_sensor: str | None = None
    allow_on_off_control: bool = False
    lower_setpoint_offset: float = 0.0
    upper_setpoint_offset: float = 0.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeviceConfig:
        from .const import (
            CONF_ALLOW_ON_OFF_CONTROL,
            CONF_CLIMATE_ENTITY,
            CONF_DEVICE_ID,
            CONF_DEVICE_NAME,
            CONF_DEVICE_ROLE,
            CONF_ENERGY_SENSOR,
            CONF_LOWER_SETPOINT_OFFSET,
            CONF_UPPER_SETPOINT_OFFSET,
            CONF_WATER_SENSOR,
        )
        return cls(
            device_id=str(data.get(CONF_DEVICE_ID) or ""),
            device_name=str(data.get(CONF_DEVICE_NAME) or ""),
            device_role=str(data.get(CONF_DEVICE_ROLE) or ""),
            climate_entity=str(data.get(CONF_CLIMATE_ENTITY) or ""),
            energy_sensor=data.get(CONF_ENERGY_SENSOR),
            water_sensor=data.get(CONF_WATER_SENSOR),
            allow_on_off_control=bool(data.get(CONF_ALLOW_ON_OFF_CONTROL, False)),
            lower_setpoint_offset=float(data.get(CONF_LOWER_SETPOINT_OFFSET, 0.0) or 0.0),
            upper_setpoint_offset=float(data.get(CONF_UPPER_SETPOINT_OFFSET, 0.0) or 0.0),
        )

    def to_dict(self) -> dict[str, Any]:
        from .const import (
            CONF_ALLOW_ON_OFF_CONTROL,
            CONF_CLIMATE_ENTITY,
            CONF_DEVICE_ID,
            CONF_DEVICE_NAME,
            CONF_DEVICE_ROLE,
            CONF_ENERGY_SENSOR,
            CONF_LOWER_SETPOINT_OFFSET,
            CONF_UPPER_SETPOINT_OFFSET,
            CONF_WATER_SENSOR,
        )
        return {
            CONF_DEVICE_ID: self.device_id, CONF_DEVICE_NAME: self.device_name,
            CONF_DEVICE_ROLE: self.device_role, CONF_CLIMATE_ENTITY: self.climate_entity,
            CONF_ENERGY_SENSOR: self.energy_sensor, CONF_WATER_SENSOR: self.water_sensor,
            CONF_ALLOW_ON_OFF_CONTROL: self.allow_on_off_control,
            CONF_LOWER_SETPOINT_OFFSET: self.lower_setpoint_offset,
            CONF_UPPER_SETPOINT_OFFSET: self.upper_setpoint_offset,
        }

    @property
    def is_water_device(self) -> bool:
        from .const import DEVICE_ROLE_WATER
        return self.device_role == DEVICE_ROLE_WATER

    @property
    def is_air_device(self) -> bool:
        from .const import DEVICE_ROLE_AIR
        return self.device_role == DEVICE_ROLE_AIR


@dataclass
class DevicePayload:
    """Runtime state for a heat pump device."""
    entity_id: str
    hvac_mode: str | None = None
    current_temperature: float | None = None
    target_temperature: float | None = None
    temperature_derivative: float | None = None
    water_temperature: float | None = None
    water_derivative: float | None = None
    energy: float | None = None

    @classmethod
    def from_dict(cls, entity_id: str, data: dict[str, Any]) -> DevicePayload:
        from .utils import safe_float
        return cls(
            entity_id=entity_id, hvac_mode=data.get("hvac_mode"),
            current_temperature=safe_float(data.get("current_temperature")),
            target_temperature=safe_float(data.get("target_temperature")),
            temperature_derivative=safe_float(data.get("temperature_derivative")),
            water_temperature=safe_float(data.get("water_temperature")),
            water_derivative=safe_float(data.get("water_derivative")),
            energy=safe_float(data.get("energy")),
        )

    @property
    def is_running(self) -> bool:
        return bool(self.hvac_mode and self.hvac_mode.lower() != "off")


@dataclass
class AssistTimerState:
    """Timer state for assist pump control."""
    on_timer_seconds: float = 0.0
    off_timer_seconds: float = 0.0
    active_condition: str = "none"
    running_state: bool = False
    last_on: datetime | None = None
    last_off: datetime | None = None
    block_reason: str = ""
    target_hvac_mode: str | None = None
    target_reason: str = ""


@dataclass
class PowerBudgetState:
    """Power budget tracking state."""
    budget_watts: float = 0.0
    current_setpoint: float | None = None
    last_adjustment: datetime | None = None


@dataclass
class CoordinatorData:
    """Coordinator data wrapper."""
    room_temperature: float | None = None
    room_sensor_values: list[float] = field(default_factory=list)
    room_derivative: float | None = None
    water_derivative: float | None = None
    devices: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> CoordinatorData:
        if data is None:
            return cls()
        from .const import CONF_ROOM_SENSOR_VALUES, CONF_ROOM_TEMPERATURE_KEY
        from .utils import safe_float
        return cls(
            room_temperature=safe_float(data.get(CONF_ROOM_TEMPERATURE_KEY)),
            room_sensor_values=data.get(CONF_ROOM_SENSOR_VALUES) or [],
            room_derivative=safe_float(data.get("room_derivative")),
            water_derivative=safe_float(data.get("water_derivative")),
            devices=data.get("devices") or [],
        )


@dataclass
class AssistConditionResult:
    """Assist pump condition check result."""
    condition_met: bool
    condition_name: str = ""

    @classmethod
    def no_condition(cls) -> AssistConditionResult:
        return cls(condition_met=False, condition_name="")
