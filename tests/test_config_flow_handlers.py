"""Tests for PowerClimate config flow handlers.

These tests focus on pure utility functions that don't require complex Home Assistant setup.
"""
import pytest
import voluptuous as vol

from custom_components.powerclimate.config_flow_handlers import (
    process_advanced_input,
    process_water_device_input,
    water_device_defaults,
    experimental_form_defaults,
    parse_offset,
    process_experimental_input,
    slugify,
    generate_device_id,
    generate_device_name,
    entry_name_from_input,
)
from custom_components.powerclimate.const import (
    CONF_ALLOW_ON_OFF_CONTROL,
    CONF_CLIMATE_ENTITY,
    CONF_ENERGY_SENSOR,
    CONF_ENTRY_NAME,
    CONF_HOUSE_POWER_SENSOR,
    CONF_MAXIMUM_OVERSHOOT,
    CONF_MPC_TEMPERATURE_SENSOR,
    CONF_WATER_SENSOR,
    DEFAULT_ENTRY_NAME,
)


class TestParseOffset:
    """Tests for parse_offset function."""

    def test_valid_positive_value(self):
        """Should parse positive offset value."""
        value, valid = parse_offset(2.5, 0.0)
        assert valid is True
        assert value == 2.5

    def test_valid_negative_value(self):
        """Should parse negative offset value."""
        value, valid = parse_offset(-1.5, 0.0)
        assert valid is True
        assert value == -1.5

    def test_valid_zero(self):
        """Should parse zero value."""
        value, valid = parse_offset(0, 1.0)
        assert valid is True
        assert value == 0.0

    def test_negative_zero_preserved(self):
        """Should preserve negative zero."""
        value, valid = parse_offset("-0", 1.0)
        assert valid is True
        assert value == -0.0
        assert str(value) == "-0.0"

    def test_negative_zero_decimal(self):
        """Should preserve negative zero with decimals."""
        value, valid = parse_offset("-0.0", 1.0)
        assert valid is True
        assert value == -0.0

    def test_invalid_returns_default(self):
        """Should return default for invalid input."""
        value, valid = parse_offset("invalid", 2.0)
        assert valid is False
        assert value == 2.0

    def test_none_returns_default(self):
        """Should return default for None input."""
        value, valid = parse_offset(None, 3.0)
        assert valid is False
        assert value == 3.0

    def test_string_number(self):
        """Should parse string representation of number."""
        value, valid = parse_offset("1.5", 0.0)
        assert valid is True
        assert value == 1.5


class TestSlugify:
    """Tests for slugify function."""

    def test_basic_slugify(self):
        """Should convert to lowercase with underscores."""
        assert slugify("Hello World") == "hello_world"

    def test_special_characters(self):
        """Should replace special characters."""
        assert slugify("Hello-World!@#$") == "hello_world"

    def test_multiple_spaces(self):
        """Should collapse multiple spaces."""
        assert slugify("hello   world") == "hello_world"

    def test_multiple_underscores(self):
        """Should collapse multiple underscores."""
        assert slugify("hello___world") == "hello_world"

    def test_leading_trailing(self):
        """Should strip leading/trailing whitespace."""
        assert slugify("  hello world  ") == "hello_world"

    def test_empty_string(self):
        """Should handle empty string."""
        assert slugify("") == ""

    def test_only_special_chars(self):
        """Should handle string with only special chars."""
        assert slugify("@#$%") == ""


class TestGenerateDeviceId:
    """Tests for generate_device_id function."""

    def test_basic_id(self):
        """Should generate ID from entity name."""
        device_id = generate_device_id("climate.living_room", set())
        assert device_id == "living_room"

    def test_duplicate_id(self):
        """Should append number for duplicates."""
        used = {"living_room"}
        device_id = generate_device_id("climate.living_room", used)
        assert device_id == "living_room_2"

    def test_multiple_duplicates(self):
        """Should increment number for multiple duplicates."""
        used = {"living_room", "living_room_2", "living_room_3"}
        device_id = generate_device_id("climate.living_room", used)
        assert device_id == "living_room_4"

    def test_empty_entity_name(self):
        """Should use default for empty name."""
        device_id = generate_device_id("climate.", set())
        assert device_id == "hp"

    def test_complex_entity_name(self):
        """Should handle complex entity names."""
        device_id = generate_device_id("climate.master_bedroom_heat_pump", set())
        assert device_id == "master_bedroom_heat_pump"


class TestGenerateDeviceName:
    """Tests for generate_device_name function."""

    def test_basic_name(self):
        """Should generate title-case name."""
        name = generate_device_name("climate.living_room")
        assert name == "Living Room"

    def test_underscores_to_spaces(self):
        """Should convert underscores to spaces."""
        name = generate_device_name("climate.master_bedroom_ac")
        assert name == "Master Bedroom Ac"

    def test_empty_name(self):
        """Should return full entity ID for empty name part."""
        name = generate_device_name("climate.")
        # Returns the full entity when split produces empty string
        assert name == "climate."


class TestEntryNameFromInput:
    """Tests for entry_name_from_input function."""

    def test_uses_user_input(self):
        """Should use name from user input."""
        user_input = {CONF_ENTRY_NAME: "My Climate System"}
        name = entry_name_from_input(user_input, None)
        assert name == "My Climate System"

    def test_falls_back_to_base(self):
        """Should fall back to base data when input missing."""
        base = {CONF_ENTRY_NAME: "Base Name"}
        user_input = {}
        name = entry_name_from_input(user_input, base)
        assert name == "Base Name"

    def test_uses_default_when_both_missing(self):
        """Should use default when both input and base missing."""
        name = entry_name_from_input({}, None)
        assert name == DEFAULT_ENTRY_NAME

    def test_strips_whitespace(self):
        """Should strip whitespace from name."""
        user_input = {CONF_ENTRY_NAME: "  My Climate  "}
        name = entry_name_from_input(user_input, None)
        assert name == "My Climate"

    def test_empty_name_uses_default(self):
        """Should use default for empty name."""
        user_input = {CONF_ENTRY_NAME: "  "}
        name = entry_name_from_input(user_input, None)
        assert name == DEFAULT_ENTRY_NAME


class TestExperimentalOptions:
    """Tests for experimental option helpers."""

    def test_experimental_form_defaults_include_mpc_sensor(self):
        """Defaults should include the configured MPC sensor."""
        base = {
            CONF_HOUSE_POWER_SENSOR: "sensor.house_net",
            CONF_MPC_TEMPERATURE_SENSOR: "sensor.quatt_mpc",
        }

        defaults = experimental_form_defaults(base, None)

        assert defaults[CONF_HOUSE_POWER_SENSOR] == "sensor.house_net"
        assert defaults[CONF_MPC_TEMPERATURE_SENSOR] == "sensor.quatt_mpc"

    def test_process_experimental_input_keeps_mpc_sensor(self):
        """Experimental input should normalize the optional MPC sensor."""
        processed = process_experimental_input(
            {
                CONF_HOUSE_POWER_SENSOR: " sensor.house_net ",
                CONF_MPC_TEMPERATURE_SENSOR: " sensor.quatt_mpc ",
            }
        )

        assert processed == {
            CONF_HOUSE_POWER_SENSOR: "sensor.house_net",
            CONF_MPC_TEMPERATURE_SENSOR: "sensor.quatt_mpc",
        }


class TestWaterDeviceOptions:
    """Tests for water-device specific helpers."""

    def test_water_device_defaults_include_allow_on_off(self):
        """Water defaults should retain the allow-on-off flag."""
        defaults = water_device_defaults(
            {
                CONF_ENERGY_SENSOR: "sensor.hp1_power",
                CONF_WATER_SENSOR: "sensor.hp1_water",
                CONF_ALLOW_ON_OFF_CONTROL: True,
            },
            None,
        )

        assert defaults[CONF_ALLOW_ON_OFF_CONTROL] is True

    def test_process_water_device_input_keeps_allow_on_off(self):
        """Water device input processing should keep allow-on-off."""
        device, errors = process_water_device_input(
            {
                CONF_ENERGY_SENSOR: "sensor.hp1_power",
                CONF_WATER_SENSOR: "sensor.hp1_water",
                CONF_ALLOW_ON_OFF_CONTROL: True,
            },
            "climate.hp1",
            set(),
        )

        assert errors == {}
        assert device is not None
        assert device[CONF_CLIMATE_ENTITY] == "climate.hp1"
        assert device[CONF_ALLOW_ON_OFF_CONTROL] is True


class TestAdvancedOptions:
    """Tests for advanced option helpers."""

    def test_process_advanced_input_keeps_maximum_overshoot(self):
        """Advanced input should retain maximum overshoot."""
        processed = process_advanced_input({CONF_MAXIMUM_OVERSHOOT: 1.2})

        assert processed[CONF_MAXIMUM_OVERSHOOT] == 1.2
