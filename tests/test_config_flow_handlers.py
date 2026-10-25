"""Tests for PowerClimate config flow handlers.

These tests focus on pure utility functions that don't require complex Home Assistant setup.
"""
import json
from pathlib import Path

import pytest

from custom_components.powerclimate.config_flow_handlers import (
    advanced_form_defaults,
    air_device_defaults,
    build_advanced_schema,
    build_experimental_schema,
    build_global_schema,
    entry_name_from_input,
    experimental_form_defaults,
    flatten_section_data,
    parse_offset,
    process_advanced_input,
    process_air_device_input,
    process_experimental_input,
    process_global_input,
    process_water_device_input,
    validate_advanced_input,
    water_device_defaults,
)
from custom_components.powerclimate.const import (
    CONF_ALLOW_ON_OFF_CONTROL,
    CONF_CLIMATE_ENTITY,
    CONF_ENERGY_SENSOR,
    CONF_ENTRY_NAME,
    CONF_LOWER_SETPOINT_OFFSET_COOLING,
    CONF_LOWER_SETPOINT_OFFSET_HEATING,
    CONF_MAXIMUM_OVERSHOOT,
    CONF_MIRROR_CLIMATE_ENTITIES,
    CONF_ROOM_PI_ENABLED,
    CONF_ROOM_PI_TI_MINUTES,
    CONF_ROOM_SENSORS,
    CONF_SUPPLY_ADVICE_SENSOR,
    CONF_SUPPLY_PI_KP,
    CONF_SUPPLY_PI_MIN_POWER_W,
    CONF_SUPPLY_PI_TI_MINUTES,
    CONF_UPPER_SETPOINT_OFFSET_HEATING,
    CONF_WATER_SENSOR,
    DEFAULT_ENTRY_NAME,
    DEFAULT_LOWER_SETPOINT_OFFSET_ASSIST,
    DEFAULT_LOWER_SETPOINT_OFFSET_COOLING,
)
from custom_components.powerclimate.number_options import ADVANCED_OPTIONS, number_default


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

    def test_experimental_form_defaults_include_supply_advice_sensor(self):
        """Defaults should include the configured supply advice sensor."""
        base = {CONF_SUPPLY_ADVICE_SENSOR: "sensor.supply_advice"}

        defaults = experimental_form_defaults(base, None)

        assert defaults[CONF_SUPPLY_ADVICE_SENSOR] == "sensor.supply_advice"

    def test_experimental_form_defaults_fill_supply_control(self):
        """Supply-control fields show stored values, else the defaults."""
        defaults = experimental_form_defaults({CONF_SUPPLY_PI_KP: 0.3}, None)

        assert defaults[CONF_SUPPLY_PI_KP] == 0.3
        assert defaults[CONF_SUPPLY_PI_TI_MINUTES] == number_default(CONF_SUPPLY_PI_TI_MINUTES)
        assert defaults[CONF_SUPPLY_PI_MIN_POWER_W] == number_default(CONF_SUPPLY_PI_MIN_POWER_W)

    def test_process_experimental_input_keeps_supply_advice_sensor(self):
        """Experimental input should normalize the optional supply advice sensor."""
        processed = process_experimental_input(
            {CONF_SUPPLY_ADVICE_SENSOR: " sensor.supply_advice "}
        )

        assert processed == {
            CONF_SUPPLY_ADVICE_SENSOR: "sensor.supply_advice",
        }

    def test_process_experimental_input_keeps_supply_control(self):
        """Submitted supply-control values are stored."""
        processed = process_experimental_input(
            {
                CONF_SUPPLY_PI_KP: 0.2,
                CONF_SUPPLY_PI_TI_MINUTES: 60,
                CONF_SUPPLY_PI_MIN_POWER_W: 300,
            }
        )

        assert processed[CONF_SUPPLY_PI_KP] == 0.2
        assert processed[CONF_SUPPLY_PI_TI_MINUTES] == 60
        assert processed[CONF_SUPPLY_PI_MIN_POWER_W] == 300

    def test_room_control_defaults_off_and_is_stored(self):
        """Room control is off until enabled; its integral time has a default."""
        defaults = experimental_form_defaults({}, None)
        assert defaults[CONF_ROOM_PI_ENABLED] is False
        assert defaults[CONF_ROOM_PI_TI_MINUTES] == number_default(CONF_ROOM_PI_TI_MINUTES)

        processed = process_experimental_input(
            {CONF_ROOM_PI_ENABLED: True, CONF_ROOM_PI_TI_MINUTES: 20}
        )
        assert processed[CONF_ROOM_PI_ENABLED] is True
        assert processed[CONF_ROOM_PI_TI_MINUTES] == 20

    def test_experimental_schema_sections_flatten(self):
        """Nested experimental form data flattens to the processor contract."""
        schema = build_experimental_schema(experimental_form_defaults({}, None))
        submitted = schema(
            {
                "supply_control": {
                    CONF_SUPPLY_ADVICE_SENSOR: "sensor.supply_advice",
                    CONF_SUPPLY_PI_KP: 0.25,
                },
                "room_control": {},
            }
        )

        processed = process_experimental_input(flatten_section_data(submitted))

        assert processed[CONF_SUPPLY_ADVICE_SENSOR] == "sensor.supply_advice"
        assert processed[CONF_SUPPLY_PI_KP] == 0.25
        assert processed[CONF_SUPPLY_PI_TI_MINUTES] == number_default(CONF_SUPPLY_PI_TI_MINUTES)

    def test_process_experimental_input_clears_omitted_sensors(self):
        """HA omits emptied optional selectors; that must clear the option."""
        processed = process_experimental_input({})

        assert processed == {
            CONF_SUPPLY_ADVICE_SENSOR: None,
        }


class TestCollapsibleSections:
    """Tests for config-flow section payload handling."""

    def test_global_schema_sections_flatten_for_existing_processor(self):
        """Nested form data should keep the existing flat processor contract."""
        submitted = build_global_schema(
            {
                CONF_ENTRY_NAME: "Home",
                CONF_ROOM_SENSORS: ["sensor.living_room"],
            }
        )(
            {
                "general": {
                    CONF_ENTRY_NAME: "PowerClimate",
                    CONF_ROOM_SENSORS: ["sensor.living_room"],
                },
                "mirrors": {
                    CONF_MIRROR_CLIMATE_ENTITIES: ["climate.living_room"],
                },
            }
        )

        flattened = flatten_section_data(submitted)
        entry_name, data, errors = process_global_input(flattened, None)

        assert errors == {}
        assert entry_name == "PowerClimate"
        assert data == {
            CONF_ROOM_SENSORS: ["sensor.living_room"],
            CONF_MIRROR_CLIMATE_ENTITIES: ["climate.living_room"],
        }

    def test_flatten_section_data_preserves_top_level_values(self):
        """Non-section values should remain available to existing flows."""
        assert flatten_section_data(
            {
                "section": {"value": 1},
                "top_level": True,
            }
        ) == {"value": 1, "top_level": True}

    def test_advanced_translation_uses_readable_field_labels(self):
        """Advanced options should not expose internal configuration keys."""
        translation_path = (
            Path(__file__).parents[1]
            / "custom_components"
            / "powerclimate"
            / "translations"
            / "en.json"
        )
        translations = json.loads(translation_path.read_text(encoding="utf-8"))
        advanced = translations["options"]["step"]["advanced"]
        setpoint_data = advanced["sections"]["setpoints"]["data"]

        assert setpoint_data == {
            "min_setpoint_override": "Minimum temperature",
            "max_setpoint_override": "Maximum temperature",
            "maximum_overshoot": "Maximum overshoot",
        }
        assert "data" not in advanced


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

    def test_device_defaults_fall_back_for_unset_values(self):
        """A stored None falls back to the role default; stored values are kept."""
        defaults = air_device_defaults(
            {
                CONF_ENERGY_SENSOR: "sensor.hp2_power",
                CONF_LOWER_SETPOINT_OFFSET_HEATING: None,
                CONF_LOWER_SETPOINT_OFFSET_COOLING: -2.0,
            },
            None,
        )

        assert defaults[CONF_ENERGY_SENSOR] == "sensor.hp2_power"
        assert defaults[CONF_LOWER_SETPOINT_OFFSET_HEATING] == DEFAULT_LOWER_SETPOINT_OFFSET_ASSIST
        assert defaults[CONF_LOWER_SETPOINT_OFFSET_COOLING] == -2.0
        assert defaults[CONF_ALLOW_ON_OFF_CONTROL] is False

    def test_air_device_defaults_without_existing_device(self):
        defaults = air_device_defaults(None, None)

        assert defaults[CONF_ENERGY_SENSOR] is None
        assert defaults[CONF_LOWER_SETPOINT_OFFSET_COOLING] == DEFAULT_LOWER_SETPOINT_OFFSET_COOLING

    @pytest.mark.parametrize(
        "processor, input_data, climate_entity",
        [
            (
                process_water_device_input,
                {
                    CONF_ENERGY_SENSOR: "sensor.hp1_power",
                    CONF_WATER_SENSOR: "sensor.hp1_water",
                    CONF_LOWER_SETPOINT_OFFSET_HEATING: 2.0,
                    CONF_UPPER_SETPOINT_OFFSET_HEATING: 0.0,
                },
                "climate.hp1",
            ),
            (
                process_air_device_input,
                {
                    CONF_ENERGY_SENSOR: "sensor.hp2_power",
                    CONF_LOWER_SETPOINT_OFFSET_HEATING: 2.0,
                    CONF_UPPER_SETPOINT_OFFSET_HEATING: 0.0,
                },
                "climate.hp2",
            ),
        ],
    )
    def test_device_input_rejects_reversed_heating_offsets(
        self, processor, input_data, climate_entity
    ):
        """Both device processors should share the same offset validation."""
        device, errors = processor(input_data, climate_entity, set())

        assert device is None
        assert errors["base"] == "invalid_offsets"


class TestAdvancedOptions:
    """Tests for advanced option helpers."""

    def test_process_advanced_input_keeps_maximum_overshoot(self):
        """Advanced input should retain maximum overshoot."""
        processed = process_advanced_input({CONF_MAXIMUM_OVERSHOOT: 1.2})

        assert processed[CONF_MAXIMUM_OVERSHOOT] == 1.2

    def test_advanced_schema_round_trips_defaults(self):
        """Every advanced option is in the form; submitting it unchanged stores the defaults."""
        schema = build_advanced_schema(advanced_form_defaults({}, None))

        processed = process_advanced_input(
            flatten_section_data(schema({"setpoints": {}, "assist": {}}))
        )

        assert processed == {option.key: option.default for option in ADVANCED_OPTIONS}

    def test_validate_advanced_input_accepts_defaults(self):
        assert validate_advanced_input({}) == {}

    def test_validate_advanced_input_rejects_inverted_setpoints(self):
        errors = validate_advanced_input(
            {"min_setpoint_override": 25.0, "max_setpoint_override": 20.0}
        )
        assert errors["base"] == "invalid_setpoint_range"

    def test_validate_advanced_input_rejects_inverted_eta_thresholds(self):
        errors = validate_advanced_input(
            {
                "assist_on_eta_threshold_minutes": 10.0,
                "assist_off_eta_threshold_minutes": 30.0,
            }
        )
        assert errors["base"] == "invalid_eta_thresholds"


class TestAdvancedOptionsStep:
    """The options flow advanced step must validate and save."""

    @staticmethod
    def _make_flow():
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from custom_components.powerclimate.config_flow import (
            PowerClimateOptionsFlowHandler,
        )

        entry = SimpleNamespace(data={}, options={}, title="PowerClimate")
        flow = PowerClimateOptionsFlowHandler(entry)
        flow.async_show_form = MagicMock(return_value="form")
        flow.async_create_entry = MagicMock(return_value="created")
        return flow

    def test_advanced_step_saves_valid_input(self):
        import asyncio

        flow = self._make_flow()
        result = asyncio.run(
            flow.async_step_advanced(
                {"setpoints": {"min_setpoint_override": 17.0, CONF_MAXIMUM_OVERSHOOT: 0.8}}
            )
        )

        assert result == "created"
        saved = flow.async_create_entry.call_args.kwargs["data"]
        assert saved["min_setpoint_override"] == 17.0

    def test_advanced_step_shows_errors(self):
        import asyncio

        flow = self._make_flow()
        result = asyncio.run(
            flow.async_step_advanced(
                {
                    "setpoints": {
                        "min_setpoint_override": 25.0,
                        "max_setpoint_override": 20.0,
                    }
                }
            )
        )

        assert result == "form"
        errors = flow.async_show_form.call_args.kwargs["errors"]
        assert errors["base"] == "invalid_setpoint_range"
