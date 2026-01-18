"""Utility functions for PowerClimate."""
from __future__ import annotations

import re
from typing import Any


def safe_float(value: Any, default: float | None = None) -> float | None:
    """Safely convert value to float."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int | None = None) -> int | None:
    """Safely convert value to int."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_device_offset(value: Any) -> float | None:
    """Parse offset while preserving -0 for UI display."""
    if value is None:
        return None
    raw_str = str(value).strip()
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed == 0 and raw_str.startswith("-0"):
        return -0.0
    return parsed


def parse_offset_with_default(raw: Any, default: float) -> tuple[float, bool]:
    """Parse offset with default, returns (value, is_valid)."""
    raw_str = str(raw).strip() if raw is not None else None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default, False
    if raw_str and re.match(r"^-0(\.0+)?$", raw_str):
        return -0.0, True
    return value, True


def compute_eta_hours(delta_to_target: float | None, derivative: float | None) -> float | None:
    """Compute ETA in hours to reach target temperature."""
    if delta_to_target is None or derivative is None or derivative == 0:
        return None
    if delta_to_target * derivative <= 0:  # Not moving toward target
        return None
    hours = delta_to_target / derivative
    return hours if hours >= 0 else None


def clamp_value(value: float, minimum: float, maximum: float) -> float:
    """Clamp value between minimum and maximum."""
    return max(minimum, min(value, maximum))


def clamp_setpoint(
    target: float | None,
    current_temp: float | None,
    lower_offset: float,
    upper_offset: float,
    min_setpoint: float,
    max_setpoint: float,
) -> float:
    """Clamp setpoint to [current+lower, current+upper] and [min, max]."""
    if target is None:
        return min_setpoint
    if current_temp is None:
        return max(min_setpoint, min(target, max_setpoint))
    floor = max(current_temp + lower_offset, min_setpoint)
    ceiling = min(current_temp + upper_offset, max_setpoint)
    return max(floor, min(target, ceiling))


def format_timer(elapsed_seconds: int, total_seconds: int) -> str:
    """Format timer as MM:SS/MM:SS."""
    elapsed_seconds = max(0, int(elapsed_seconds))
    total_seconds = max(0, int(total_seconds))
    em, es = divmod(elapsed_seconds, 60)
    tm, ts = divmod(total_seconds, 60)
    return f"{em}:{es:02d}/{tm}:{ts:02d}"


def slugify(value: str) -> str:
    """Convert string to lowercase slug with underscores."""
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9_]+", "_", value)
    value = re.sub(r"_+", "_", value)
    return value.strip("_")


def generate_device_id(climate_entity: str, used_ids: set[str]) -> str:
    """Generate unique device ID from climate entity."""
    base = slugify(climate_entity.split(".")[-1]) or "hp"
    candidate = base
    counter = 2
    while candidate in used_ids:
        candidate = f"{base}_{counter}"
        counter += 1
    return candidate


def generate_device_name(climate_entity: str) -> str:
    """Generate human-readable device name from entity ID."""
    raw = climate_entity.split(".")[-1].replace("_", " ")
    return raw.title() if raw else climate_entity
