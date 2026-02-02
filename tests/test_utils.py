"""Tests for PowerClimate utility functions."""
import pytest

from custom_components.powerclimate.utils import (
    clamp_setpoint,
    clamp_value,
    compute_eta_hours,
    format_timer,
    generate_device_id,
    generate_device_name,
    parse_device_offset,
    parse_offset_with_default,
    safe_float,
    safe_int,
    slugify,
)


class TestSafeFloat:
    """Tests for safe_float function."""

    def test_valid_float(self):
        assert safe_float(3.14) == 3.14

    def test_valid_int(self):
        assert safe_float(42) == 42.0

    def test_valid_string(self):
        assert safe_float("3.14") == 3.14

    def test_none_returns_default(self):
        assert safe_float(None) is None
        assert safe_float(None, 0.0) == 0.0

    def test_invalid_string(self):
        assert safe_float("invalid") is None
        assert safe_float("invalid", -1.0) == -1.0

    def test_empty_string(self):
        assert safe_float("") is None


class TestSafeInt:
    """Tests for safe_int function."""

    def test_valid_int(self):
        assert safe_int(42) == 42

    def test_valid_float(self):
        assert safe_int(3.7) == 3

    def test_valid_string(self):
        assert safe_int("42") == 42

    def test_none_returns_default(self):
        assert safe_int(None) is None
        assert safe_int(None, 0) == 0

    def test_invalid_string(self):
        assert safe_int("invalid") is None


class TestParseDeviceOffset:
    """Tests for parse_device_offset function."""

    def test_positive_value(self):
        assert parse_device_offset(1.5) == 1.5

    def test_negative_value(self):
        assert parse_device_offset(-0.5) == -0.5

    def test_zero(self):
        assert parse_device_offset(0) == 0.0

    def test_negative_zero_string(self):
        result = parse_device_offset("-0")
        assert result == -0.0
        # Check that it's actually negative zero
        assert str(result) == "-0.0"

    def test_negative_zero_decimal_string(self):
        result = parse_device_offset("-0.0")
        assert result == -0.0

    def test_none_returns_none(self):
        assert parse_device_offset(None) is None

    def test_invalid_string(self):
        assert parse_device_offset("invalid") is None


class TestParseOffsetWithDefault:
    """Tests for parse_offset_with_default function."""

    def test_valid_value(self):
        value, valid = parse_offset_with_default(1.5, 0.0)
        assert value == 1.5
        assert valid is True

    def test_invalid_value_returns_default(self):
        value, valid = parse_offset_with_default("invalid", -1.0)
        assert value == -1.0
        assert valid is False

    def test_negative_zero_preserved(self):
        value, valid = parse_offset_with_default("-0", 1.0)
        assert value == -0.0
        assert valid is True


class TestComputeEtaHours:
    """Tests for compute_eta_hours function."""

    def test_positive_delta_positive_derivative(self):
        # 2 degrees to target, warming at 1 degree/hour = 2 hours
        eta = compute_eta_hours(2.0, 1.0)
        assert eta == 2.0

    def test_negative_delta_positive_derivative(self):
        # Already past target, warming up
        eta = compute_eta_hours(-2.0, 1.0)
        assert eta is None

    def test_positive_delta_negative_derivative(self):
        # Need to warm, but cooling down
        eta = compute_eta_hours(2.0, -1.0)
        assert eta is None

    def test_zero_derivative(self):
        eta = compute_eta_hours(2.0, 0.0)
        assert eta is None

    def test_none_values(self):
        assert compute_eta_hours(None, 1.0) is None
        assert compute_eta_hours(2.0, None) is None
        assert compute_eta_hours(None, None) is None


class TestClampValue:
    """Tests for clamp_value function."""

    def test_value_in_range(self):
        assert clamp_value(5.0, 0.0, 10.0) == 5.0

    def test_value_below_minimum(self):
        assert clamp_value(-5.0, 0.0, 10.0) == 0.0

    def test_value_above_maximum(self):
        assert clamp_value(15.0, 0.0, 10.0) == 10.0

    def test_value_at_minimum(self):
        assert clamp_value(0.0, 0.0, 10.0) == 0.0

    def test_value_at_maximum(self):
        assert clamp_value(10.0, 0.0, 10.0) == 10.0


class TestClampSetpoint:
    """Tests for clamp_setpoint function."""

    def test_basic_clamping(self):
        # Target 21, current 20, offsets -1/+2, limits 16/30
        # Floor = max(20-1, 16) = 19
        # Ceiling = min(20+2, 30) = 22
        # Result = clamp(21, 19, 22) = 21
        result = clamp_setpoint(21.0, 20.0, -1.0, 2.0, 16.0, 30.0)
        assert result == 21.0

    def test_target_below_floor(self):
        # Target 17, current 20, offsets -1/+2
        # Floor = 19, ceiling = 22
        # Clamped to floor: 19
        result = clamp_setpoint(17.0, 20.0, -1.0, 2.0, 16.0, 30.0)
        assert result == 19.0

    def test_target_above_ceiling(self):
        # Target 25, current 20, offsets -1/+2
        # Floor = 19, ceiling = 22
        # Clamped to ceiling: 22
        result = clamp_setpoint(25.0, 20.0, -1.0, 2.0, 16.0, 30.0)
        assert result == 22.0

    def test_none_target_returns_min(self):
        result = clamp_setpoint(None, 20.0, -1.0, 2.0, 16.0, 30.0)
        assert result == 16.0

    def test_none_current_temp(self):
        # Without current temp, just clamp to global limits
        result = clamp_setpoint(21.0, None, -1.0, 2.0, 16.0, 30.0)
        assert result == 21.0

    def test_global_limits_applied(self):
        # Target 35, current 25, offsets 0/+10
        # Ceiling = min(35, 30) = 30
        result = clamp_setpoint(35.0, 25.0, 0.0, 10.0, 16.0, 30.0)
        assert result == 30.0


class TestFormatTimer:
    """Tests for format_timer function."""

    def test_basic_format(self):
        assert format_timer(90, 300) == "1:30/5:00"

    def test_zero_elapsed(self):
        assert format_timer(0, 300) == "0:00/5:00"

    def test_complete_timer(self):
        assert format_timer(300, 300) == "5:00/5:00"

    def test_negative_values_clamped(self):
        assert format_timer(-10, 300) == "0:00/5:00"

    def test_over_one_hour(self):
        assert format_timer(3661, 7200) == "61:01/120:00"


class TestSlugify:
    """Tests for slugify function."""

    def test_basic_slugify(self):
        assert slugify("Hello World") == "hello_world"

    def test_special_characters(self):
        assert slugify("Hello-World!@#$") == "hello_world"

    def test_multiple_underscores(self):
        assert slugify("hello___world") == "hello_world"

    def test_leading_trailing_spaces(self):
        assert slugify("  hello world  ") == "hello_world"

    def test_empty_string(self):
        assert slugify("") == ""


class TestGenerateDeviceId:
    """Tests for generate_device_id function."""

    def test_basic_id(self):
        device_id = generate_device_id("climate.living_room", set())
        assert device_id == "living_room"

    def test_duplicate_id(self):
        used = {"living_room"}
        device_id = generate_device_id("climate.living_room", used)
        assert device_id == "living_room_2"

    def test_multiple_duplicates(self):
        used = {"living_room", "living_room_2", "living_room_3"}
        device_id = generate_device_id("climate.living_room", used)
        assert device_id == "living_room_4"

    def test_empty_entity_name(self):
        device_id = generate_device_id("climate.", set())
        assert device_id == "hp"


class TestGenerateDeviceName:
    """Tests for generate_device_name function."""

    def test_basic_name(self):
        name = generate_device_name("climate.living_room")
        assert name == "Living Room"

    def test_underscores_to_spaces(self):
        name = generate_device_name("climate.master_bedroom_ac")
        assert name == "Master Bedroom Ac"

    def test_empty_name(self):
        name = generate_device_name("climate.")
        assert name == "climate."
