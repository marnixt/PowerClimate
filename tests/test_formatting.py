"""Tests for PowerClimate formatting utilities.

Covers TemperatureFormatter and SensorFormatter without requiring
a running Home Assistant instance (strings are resolved from empty cache,
falling back to the hard-coded defaults).
"""


from custom_components.powerclimate.formatting import SensorFormatter, TemperatureFormatter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _formatter() -> TemperatureFormatter:
    """Return a formatter with an empty string cache (uses all defaults)."""
    fmt = TemperatureFormatter()
    fmt._strings = {}
    return fmt


def _sensor_formatter() -> SensorFormatter:
    fmt = SensorFormatter()
    fmt._strings = {}
    return fmt


# ---------------------------------------------------------------------------
# format_temp_pair
# ---------------------------------------------------------------------------


class TestFormatTempPair:

    def test_both_current_and_target(self) -> None:
        result = _formatter().format_temp_pair("Room", 20.5, 21.0)
        assert result == "Room 20.5°C→21.0°C"

    def test_current_only(self) -> None:
        result = _formatter().format_temp_pair("Room", 20.5, None)
        assert result == "Room 20.5°C"

    def test_target_only(self) -> None:
        result = _formatter().format_temp_pair("Room", None, 21.0)
        assert result == "Room →21.0°C"

    def test_neither_value(self) -> None:
        result = _formatter().format_temp_pair("Room", None, None)
        assert "Room" in result
        assert "none" in result

    def test_integer_values_formatted_as_one_decimal(self) -> None:
        result = _formatter().format_temp_pair("Water", 40, 42)
        assert result == "Water 40.0°C→42.0°C"


# ---------------------------------------------------------------------------
# format_derivative
# ---------------------------------------------------------------------------


class TestFormatDerivative:

    def test_positive_derivative(self) -> None:
        result = _formatter().format_derivative("ΔT", 1.5)
        assert result == "ΔT 1.5°C/h"

    def test_negative_derivative(self) -> None:
        result = _formatter().format_derivative("ΔT", -0.8)
        assert result == "ΔT -0.8°C/h"

    def test_zero_derivative(self) -> None:
        result = _formatter().format_derivative("ΔT", 0.0)
        assert result == "ΔT 0.0°C/h"

    def test_none_derivative_shows_none(self) -> None:
        result = _formatter().format_derivative("ΔT", None)
        assert "ΔT" in result
        assert "none" in result

    def test_integer_value_formatted(self) -> None:
        result = _formatter().format_derivative("ΔT", 2)
        assert result == "ΔT 2.0°C/h"


# ---------------------------------------------------------------------------
# format_eta
# ---------------------------------------------------------------------------


class TestFormatEta:

    def test_hours_format_for_eta_above_one_hour(self) -> None:
        result = _formatter().format_eta(2.5)
        assert result == "ETA 2.5h"

    def test_minutes_format_for_eta_below_one_hour(self) -> None:
        result = _formatter().format_eta(0.5)
        assert result == "ETA 30m"

    def test_seconds_format_for_eta_below_one_minute(self) -> None:
        result = _formatter().format_eta(0.5 / 60.0)  # 30 seconds
        assert "ETA" in result
        assert "s" in result

    def test_none_eta_shows_none(self) -> None:
        result = _formatter().format_eta(None)
        assert "ETA" in result
        assert "none" in result

    def test_zero_eta_shows_none(self) -> None:
        result = _formatter().format_eta(0.0)
        assert "none" in result

    def test_negative_eta_shows_none(self) -> None:
        result = _formatter().format_eta(-1.0)
        assert "none" in result

    def test_exactly_one_hour(self) -> None:
        result = _formatter().format_eta(1.0)
        assert result == "ETA 1.0h"


# ---------------------------------------------------------------------------
# format_power
# ---------------------------------------------------------------------------


class TestFormatPower:

    def test_integer_watts_formatted(self) -> None:
        result = _formatter().format_power(1200)
        assert result == "Power 1200 W"

    def test_float_watts_rounded(self) -> None:
        result = _formatter().format_power(1234.7)
        assert result == "Power 1235 W"

    def test_zero_watts(self) -> None:
        result = _formatter().format_power(0)
        assert result == "Power 0 W"

    def test_none_returns_none(self) -> None:
        assert _formatter().format_power(None) is None

    def test_string_value_returns_none(self) -> None:
        assert _formatter().format_power("1000") is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# SensorFormatter.short_hp_label
# ---------------------------------------------------------------------------


class TestShortHpLabel:

    def test_uses_first_word_of_label(self) -> None:
        result = SensorFormatter.short_hp_label("Panasonic CU-Z35", "hp2")
        assert result == "Panasonic (hp2)"

    def test_falls_back_to_uppercase_role_on_empty_label(self) -> None:
        result = SensorFormatter.short_hp_label("", "hp1")
        assert result == "HP1 (hp1)"

    def test_falls_back_on_none_label(self) -> None:
        result = SensorFormatter.short_hp_label(None, "hp1")
        assert result == "HP1 (hp1)"

    def test_long_first_word_is_truncated(self) -> None:
        result = SensorFormatter.short_hp_label("VeryLongBrandName Model", "hp3")
        # First word capped at 10 chars
        assert len(result.split(" (")[0]) <= 10


# ---------------------------------------------------------------------------
# SensorFormatter.format_room_average
# ---------------------------------------------------------------------------


class TestFormatRoomAverage:

    def test_multiple_readings_with_average(self) -> None:
        fmt = _sensor_formatter()
        result = fmt.format_room_average([20.0, 21.0], 20.5)
        assert result is not None
        assert "20.5°C" in result
        assert "20.0°C" in result
        assert "21.0°C" in result

    def test_single_reading_with_average(self) -> None:
        fmt = _sensor_formatter()
        result = fmt.format_room_average([20.5], 20.5)
        assert result is not None
        assert "20.5°C" in result

    def test_none_readings_and_none_average_returns_none(self) -> None:
        fmt = _sensor_formatter()
        assert fmt.format_room_average(None, None) is None

    def test_empty_readings_with_average(self) -> None:
        fmt = _sensor_formatter()
        result = fmt.format_room_average([], 21.0)
        assert result is not None
        assert "21.0°C" in result

    def test_empty_readings_without_average_returns_none(self) -> None:
        fmt = _sensor_formatter()
        assert fmt.format_room_average([], None) is None
