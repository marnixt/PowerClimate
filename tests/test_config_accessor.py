"""Tests for PowerClimate ConfigAccessor.

Verifies property defaults, backward compatibility, device role detection,
and offset resolution across all access paths.
"""

from types import SimpleNamespace

from custom_components.powerclimate.config_accessor import ConfigAccessor
from custom_components.powerclimate.const import (
    CONF_ASSIST_TIMER_SECONDS,
    CONF_DEVICE_ROLE,
    CONF_DEVICES,
    CONF_HOUSE_POWER_SENSOR,
    CONF_LOWER_SETPOINT_OFFSET_COOLING,
    CONF_LOWER_SETPOINT_OFFSET_HEATING,
    CONF_MIN_SETPOINT_OVERRIDE,
    CONF_MIRROR_CLIMATE_ENTITIES,
    CONF_MPC_TEMPERATURE_SENSOR,
    CONF_UPPER_SETPOINT_OFFSET_COOLING,
    CONF_UPPER_SETPOINT_OFFSET_HEATING,
    DEFAULT_ASSIST_MIN_OFF_MINUTES,
    DEFAULT_ASSIST_MIN_ON_MINUTES,
    DEFAULT_ASSIST_STALL_TEMP_DELTA,
    DEFAULT_ASSIST_TIMER_SECONDS,
    DEFAULT_ASSIST_WATER_TEMP_THRESHOLD,
    DEFAULT_LOWER_SETPOINT_OFFSET_ASSIST,
    DEFAULT_LOWER_SETPOINT_OFFSET_COOLING,
    DEFAULT_LOWER_SETPOINT_OFFSET_HP1,
    DEFAULT_MAX_SETPOINT,
    DEFAULT_MIN_SETPOINT,
    DEFAULT_UPPER_SETPOINT_OFFSET_ASSIST,
    DEFAULT_UPPER_SETPOINT_OFFSET_COOLING,
    DEFAULT_UPPER_SETPOINT_OFFSET_HP1,
    DEVICE_ROLE_AIR,
    DEVICE_ROLE_WATER,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(data: dict | None = None, options: dict | None = None) -> SimpleNamespace:
    """Return a minimal config-entry-like object."""
    return SimpleNamespace(data=data or {}, options=options or {})


def _make_accessor(data: dict | None = None, options: dict | None = None) -> ConfigAccessor:
    return ConfigAccessor(_make_entry(data, options))


# ---------------------------------------------------------------------------
# Global defaults
# ---------------------------------------------------------------------------


class TestGlobalDefaults:
    """Verify that all properties return correct defaults when not configured."""

    def test_min_setpoint_default(self) -> None:
        assert _make_accessor().min_setpoint == DEFAULT_MIN_SETPOINT

    def test_max_setpoint_default(self) -> None:
        assert _make_accessor().max_setpoint == DEFAULT_MAX_SETPOINT

    def test_assist_timer_seconds_default(self) -> None:
        assert _make_accessor().assist_timer_seconds == DEFAULT_ASSIST_TIMER_SECONDS

    def test_assist_min_on_minutes_default(self) -> None:
        assert _make_accessor().assist_min_on_minutes == DEFAULT_ASSIST_MIN_ON_MINUTES

    def test_assist_min_off_minutes_default(self) -> None:
        assert _make_accessor().assist_min_off_minutes == DEFAULT_ASSIST_MIN_OFF_MINUTES

    def test_assist_water_temp_threshold_default(self) -> None:
        assert _make_accessor().assist_water_temp_threshold == DEFAULT_ASSIST_WATER_TEMP_THRESHOLD

    def test_assist_stall_temp_delta_default(self) -> None:
        assert _make_accessor().assist_stall_temp_delta == DEFAULT_ASSIST_STALL_TEMP_DELTA

    def test_house_power_sensor_none_by_default(self) -> None:
        assert _make_accessor().house_power_sensor is None

    def test_solar_disabled_by_default(self) -> None:
        assert _make_accessor().solar_enabled is False

    def test_mpc_sensor_none_by_default(self) -> None:
        assert _make_accessor().mpc_temperature_sensor is None

    def test_mpc_disabled_by_default(self) -> None:
        assert _make_accessor().mpc_enabled is False

    def test_mirror_thermostats_empty_by_default(self) -> None:
        assert _make_accessor().mirror_thermostats == []

    def test_devices_empty_by_default(self) -> None:
        assert _make_accessor().devices == []


# ---------------------------------------------------------------------------
# Options override data
# ---------------------------------------------------------------------------


class TestOptionsOverrideData:
    """Options values should take precedence over data values."""

    def test_min_setpoint_from_options_overrides_data(self) -> None:
        accessor = _make_accessor(
            data={CONF_MIN_SETPOINT_OVERRIDE: 10.0},
            options={CONF_MIN_SETPOINT_OVERRIDE: 18.0},
        )
        assert accessor.min_setpoint == 18.0

    def test_assist_timer_from_options(self) -> None:
        accessor = _make_accessor(options={CONF_ASSIST_TIMER_SECONDS: 600.0})
        assert accessor.assist_timer_seconds == 600.0

    def test_invalidate_cache_reloads_options(self) -> None:
        entry = _make_entry(data={}, options={CONF_MIN_SETPOINT_OVERRIDE: 17.0})
        accessor = ConfigAccessor(entry)
        assert accessor.min_setpoint == 17.0
        entry.options = {CONF_MIN_SETPOINT_OVERRIDE: 19.0}
        accessor.invalidate_cache()
        assert accessor.min_setpoint == 19.0


# ---------------------------------------------------------------------------
# Optional sensors
# ---------------------------------------------------------------------------


class TestOptionalSensors:
    """house_power_sensor and mpc_temperature_sensor should strip blank values."""

    def test_solar_enabled_when_sensor_configured(self) -> None:
        accessor = _make_accessor(data={CONF_HOUSE_POWER_SENSOR: "sensor.net"})
        assert accessor.solar_enabled is True
        assert accessor.house_power_sensor == "sensor.net"

    def test_solar_disabled_for_whitespace_only_value(self) -> None:
        accessor = _make_accessor(data={CONF_HOUSE_POWER_SENSOR: "   "})
        assert accessor.solar_enabled is False

    def test_mpc_enabled_when_sensor_configured(self) -> None:
        accessor = _make_accessor(data={CONF_MPC_TEMPERATURE_SENSOR: "sensor.mpc"})
        assert accessor.mpc_enabled is True

    def test_mpc_disabled_for_empty_string(self) -> None:
        accessor = _make_accessor(data={CONF_MPC_TEMPERATURE_SENSOR: ""})
        assert accessor.mpc_enabled is False


# ---------------------------------------------------------------------------
# Mirror thermostats
# ---------------------------------------------------------------------------


class TestMirrorThermostats:
    """mirror_thermostats should deduplicate and strip blank entries."""

    def test_returns_unique_ordered_list(self) -> None:
        accessor = _make_accessor(
            data={
                CONF_MIRROR_CLIMATE_ENTITIES: [
                    "climate.a",
                    "climate.b",
                    "climate.a",  # duplicate
                ]
            }
        )
        result = accessor.mirror_thermostats
        assert result == ["climate.a", "climate.b"]

    def test_ignores_blank_entries(self) -> None:
        accessor = _make_accessor(
            data={CONF_MIRROR_CLIMATE_ENTITIES: ["climate.a", "  ", ""]}
        )
        assert accessor.mirror_thermostats == ["climate.a"]

    def test_non_list_value_returns_empty(self) -> None:
        accessor = _make_accessor(
            data={CONF_MIRROR_CLIMATE_ENTITIES: "climate.a"}
        )
        assert accessor.mirror_thermostats == []


# ---------------------------------------------------------------------------
# Device role detection
# ---------------------------------------------------------------------------


class TestDeviceRoleDetection:
    """get_device_role should use explicit role only; no index-based fallback."""

    def test_explicit_water_role_honoured(self) -> None:
        accessor = _make_accessor()
        device = {CONF_DEVICE_ROLE: DEVICE_ROLE_WATER}
        assert accessor.get_device_role(device, 99) == DEVICE_ROLE_WATER

    def test_explicit_air_role_honoured(self) -> None:
        accessor = _make_accessor()
        device = {CONF_DEVICE_ROLE: DEVICE_ROLE_AIR}
        assert accessor.get_device_role(device, 0) == DEVICE_ROLE_AIR

    def test_no_role_returns_none(self) -> None:
        accessor = _make_accessor()
        for index in (0, 1, 2, 10):
            assert accessor.get_device_role({}, index) is None

    def test_is_water_device_requires_explicit_role(self) -> None:
        accessor = _make_accessor()
        assert accessor.is_water_device({CONF_DEVICE_ROLE: DEVICE_ROLE_WATER}, 0) is True
        assert accessor.is_water_device({}, 0) is False
        assert accessor.is_water_device({}, 1) is False

    def test_is_air_device_requires_explicit_role(self) -> None:
        accessor = _make_accessor()
        assert accessor.is_air_device({CONF_DEVICE_ROLE: DEVICE_ROLE_AIR}, 0) is True
        assert accessor.is_air_device({}, 0) is False
        assert accessor.is_air_device({}, 1) is False


# ---------------------------------------------------------------------------
# get_water_device / get_air_devices
# ---------------------------------------------------------------------------


class TestDeviceAccessors:
    """get_water_device and get_air_devices should partition devices correctly."""

    def _accessor_with_devices(self, *roles: str) -> ConfigAccessor:
        devices = [
            {CONF_DEVICE_ROLE: r, "climate_entity_id": f"climate.hp{i}"}
            for i, r in enumerate(roles)
        ]
        return _make_accessor(data={CONF_DEVICES: devices})

    def test_get_water_device_returns_first_water(self) -> None:
        accessor = self._accessor_with_devices(DEVICE_ROLE_WATER, DEVICE_ROLE_AIR)
        result = accessor.get_water_device()
        assert result is not None
        device, index = result
        assert index == 0
        assert device["climate_entity_id"] == "climate.hp0"

    def test_get_water_device_returns_none_when_absent(self) -> None:
        accessor = self._accessor_with_devices(DEVICE_ROLE_AIR, DEVICE_ROLE_AIR)
        assert accessor.get_water_device() is None

    def test_get_air_devices_returns_all_air(self) -> None:
        accessor = self._accessor_with_devices(DEVICE_ROLE_WATER, DEVICE_ROLE_AIR, DEVICE_ROLE_AIR)
        air_devices = accessor.get_air_devices()
        assert len(air_devices) == 2
        indices = [idx for idx, _ in air_devices]
        assert indices == [1, 2]

    def test_get_air_devices_empty_when_none(self) -> None:
        accessor = self._accessor_with_devices(DEVICE_ROLE_WATER)
        assert accessor.get_air_devices() == []


# ---------------------------------------------------------------------------
# Setpoint offset resolution
# ---------------------------------------------------------------------------


class TestSetpointOffsets:
    """Offsets should use the heating keys, then the role default."""

    def test_lower_offset_from_heating_key(self) -> None:
        accessor = _make_accessor()
        device = {CONF_LOWER_SETPOINT_OFFSET_HEATING: -2.0}
        assert accessor.get_device_lower_offset(device, 1) == -2.0

    def test_lower_offset_ignores_legacy_key(self) -> None:
        accessor = _make_accessor()
        device = {CONF_DEVICE_ROLE: DEVICE_ROLE_AIR, "lower_setpoint_offset": -3.0}
        assert accessor.get_device_lower_offset(device, 1) == DEFAULT_LOWER_SETPOINT_OFFSET_ASSIST

    def test_lower_offset_returns_water_default_for_water_device(self) -> None:
        accessor = _make_accessor()
        device = {CONF_DEVICE_ROLE: DEVICE_ROLE_WATER}
        assert accessor.get_device_lower_offset(device, 0) == DEFAULT_LOWER_SETPOINT_OFFSET_HP1

    def test_lower_offset_returns_air_default_for_air_device(self) -> None:
        accessor = _make_accessor()
        device = {CONF_DEVICE_ROLE: DEVICE_ROLE_AIR}
        assert accessor.get_device_lower_offset(device, 1) == DEFAULT_LOWER_SETPOINT_OFFSET_ASSIST

    def test_upper_offset_from_heating_key(self) -> None:
        accessor = _make_accessor()
        device = {CONF_UPPER_SETPOINT_OFFSET_HEATING: 3.0}
        assert accessor.get_device_upper_offset(device, 1) == 3.0

    def test_upper_offset_returns_water_default(self) -> None:
        accessor = _make_accessor()
        device = {CONF_DEVICE_ROLE: DEVICE_ROLE_WATER}
        assert accessor.get_device_upper_offset(device, 0) == DEFAULT_UPPER_SETPOINT_OFFSET_HP1

    def test_upper_offset_returns_air_default(self) -> None:
        accessor = _make_accessor()
        device = {CONF_DEVICE_ROLE: DEVICE_ROLE_AIR}
        assert accessor.get_device_upper_offset(device, 1) == DEFAULT_UPPER_SETPOINT_OFFSET_ASSIST

    def test_cooling_lower_offset_from_key(self) -> None:
        accessor = _make_accessor()
        device = {CONF_LOWER_SETPOINT_OFFSET_COOLING: -5.0}
        assert accessor.get_device_lower_offset_cooling(device, 1) == -5.0

    def test_cooling_lower_offset_default(self) -> None:
        accessor = _make_accessor()
        result = accessor.get_device_lower_offset_cooling({}, 1)
        assert result == DEFAULT_LOWER_SETPOINT_OFFSET_COOLING

    def test_cooling_upper_offset_from_key(self) -> None:
        accessor = _make_accessor()
        device = {CONF_UPPER_SETPOINT_OFFSET_COOLING: 1.0}
        assert accessor.get_device_upper_offset_cooling(device, 1) == 1.0

    def test_cooling_upper_offset_default(self) -> None:
        accessor = _make_accessor()
        result = accessor.get_device_upper_offset_cooling({}, 1)
        assert result == DEFAULT_UPPER_SETPOINT_OFFSET_COOLING


# ---------------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------------


class TestToDict:
    """to_dict should export a snapshot of all configuration values."""

    def test_to_dict_contains_expected_keys(self) -> None:
        result = _make_accessor().to_dict()
        expected_keys = {
            "min_setpoint",
            "max_setpoint",
            "assist_timer_seconds",
            "assist_on_eta_threshold_minutes",
            "assist_off_eta_threshold_minutes",
            "assist_min_on_minutes",
            "assist_min_off_minutes",
            "assist_water_temp_threshold",
            "assist_stall_temp_delta",
            "maximum_overshoot",
            "solar_enabled",
            "house_power_sensor",
            "mpc_enabled",
            "mpc_temperature_sensor",
            "mirror_thermostats",
            "device_count",
        }
        assert expected_keys.issubset(result.keys())

    def test_to_dict_device_count_reflects_devices_list(self) -> None:
        accessor = _make_accessor(
            data={CONF_DEVICES: [{}, {}]}
        )
        assert accessor.to_dict()["device_count"] == 2
