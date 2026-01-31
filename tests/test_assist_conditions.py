"""Tests for PowerClimate assist conditions."""
import pytest
from unittest.mock import MagicMock

from custom_components.powerclimate.assist_conditions import (
    AssistConditionChecker,
    ConditionResult,
)


class MockConfig:
    """Mock configuration accessor for testing."""

    def __init__(
        self,
        assist_on_eta_threshold_minutes: float = 60.0,
        assist_off_eta_threshold_minutes: float = 15.0,
        assist_water_temp_threshold: float = 35.0,
        assist_stall_temp_delta: float = 0.5,
    ):
        self.assist_on_eta_threshold_minutes = assist_on_eta_threshold_minutes
        self.assist_off_eta_threshold_minutes = assist_off_eta_threshold_minutes
        self.assist_water_temp_threshold = assist_water_temp_threshold
        self.assist_stall_temp_delta = assist_stall_temp_delta


class TestConditionResult:
    """Tests for ConditionResult dataclass."""

    def test_met_condition(self):
        result = ConditionResult(met=True, name="test_condition")
        assert result.met is True
        assert result.name == "test_condition"

    def test_not_met(self):
        result = ConditionResult.not_met()
        assert result.met is False
        assert result.name == ""


class TestAssistConditionChecker:
    """Tests for AssistConditionChecker class."""

    # --- ON Conditions ---

    def test_eta_high_triggers_on(self):
        """High ETA while below target should trigger ON."""
        config = MockConfig(assist_on_eta_threshold_minutes=60)
        checker = AssistConditionChecker(config)

        result = checker.check_on_conditions(
            room_temp=19.0,
            target_temp=21.0,
            room_eta_minutes=90.0,  # Above 60 minute threshold
            water_temp=30.0,
            room_derivative=0.5,
        )

        assert result.met is True
        assert result.name == "eta_high"

    def test_eta_high_not_triggered_when_eta_low(self):
        """Low ETA should not trigger eta_high."""
        config = MockConfig(assist_on_eta_threshold_minutes=60)
        checker = AssistConditionChecker(config)

        result = checker.check_on_conditions(
            room_temp=19.0,
            target_temp=21.0,
            room_eta_minutes=30.0,  # Below threshold
            water_temp=30.0,
            room_derivative=0.5,
        )

        # No condition should match
        assert result.met is False

    def test_eta_high_not_triggered_when_above_target(self):
        """Above target should not trigger eta_high."""
        config = MockConfig(assist_on_eta_threshold_minutes=60)
        checker = AssistConditionChecker(config)

        result = checker.check_on_conditions(
            room_temp=22.0,  # Above target
            target_temp=21.0,
            room_eta_minutes=90.0,
            water_temp=30.0,
            room_derivative=0.5,
        )

        assert result.met is False

    def test_water_hot_triggers_on(self):
        """Hot water while below target should trigger ON."""
        config = MockConfig(assist_water_temp_threshold=35.0)
        checker = AssistConditionChecker(config)

        result = checker.check_on_conditions(
            room_temp=19.0,
            target_temp=21.0,
            room_eta_minutes=30.0,  # Below eta threshold
            water_temp=38.0,  # Above water threshold
            room_derivative=0.5,
        )

        assert result.met is True
        assert result.name == "water_hot"

    def test_water_hot_not_triggered_when_water_cool(self):
        """Cool water should not trigger water_hot."""
        config = MockConfig(assist_water_temp_threshold=35.0)
        checker = AssistConditionChecker(config)

        result = checker.check_on_conditions(
            room_temp=19.0,
            target_temp=21.0,
            room_eta_minutes=30.0,
            water_temp=30.0,  # Below threshold
            room_derivative=0.5,
        )

        assert result.met is False

    def test_stalled_below_target_triggers_on(self):
        """Stalled room temp below target should trigger ON."""
        config = MockConfig(assist_stall_temp_delta=0.5)
        checker = AssistConditionChecker(config)

        result = checker.check_on_conditions(
            room_temp=19.0,  # More than 0.5 below target
            target_temp=21.0,
            room_eta_minutes=None,  # No ETA
            water_temp=30.0,
            room_derivative=0.0,  # Stalled
        )

        assert result.met is True
        assert result.name == "stalled_below_target"

    def test_stalled_below_target_not_triggered_when_rising(self):
        """Rising temp should not trigger stalled_below_target."""
        config = MockConfig(assist_stall_temp_delta=0.5)
        checker = AssistConditionChecker(config)

        result = checker.check_on_conditions(
            room_temp=19.0,
            target_temp=21.0,
            room_eta_minutes=None,
            water_temp=30.0,
            room_derivative=0.5,  # Rising
        )

        # Only stalled_below_target could match, but derivative is positive
        assert result.met is False

    def test_stalled_below_target_not_triggered_when_close_to_target(self):
        """Room temp close to target should not trigger stalled_below_target."""
        config = MockConfig(assist_stall_temp_delta=0.5)
        checker = AssistConditionChecker(config)

        result = checker.check_on_conditions(
            room_temp=20.8,  # Within 0.5 of target
            target_temp=21.0,
            room_eta_minutes=None,
            water_temp=30.0,
            room_derivative=0.0,
        )

        assert result.met is False

    # --- OFF Conditions ---

    def test_eta_low_triggers_off(self):
        """Low ETA should trigger OFF."""
        config = MockConfig(assist_off_eta_threshold_minutes=15)
        checker = AssistConditionChecker(config)

        result = checker.check_off_conditions(
            room_temp=20.5,
            target_temp=21.0,
            room_eta_minutes=10.0,  # Below 15 minute threshold
            room_derivative=0.5,
        )

        assert result.met is True
        assert result.name == "eta_low"

    def test_eta_low_not_triggered_when_eta_high(self):
        """High ETA should not trigger eta_low."""
        config = MockConfig(assist_off_eta_threshold_minutes=15)
        checker = AssistConditionChecker(config)

        result = checker.check_off_conditions(
            room_temp=19.0,
            target_temp=21.0,
            room_eta_minutes=30.0,  # Above threshold
            room_derivative=0.5,
        )

        assert result.met is False

    def test_overshoot_triggers_off(self):
        """Room above target should trigger OFF."""
        config = MockConfig()
        checker = AssistConditionChecker(config)

        result = checker.check_off_conditions(
            room_temp=21.5,  # Above target
            target_temp=21.0,
            room_eta_minutes=None,
            room_derivative=-0.1,
        )

        assert result.met is True
        assert result.name == "overshoot"

    def test_overshoot_at_target_triggers_off(self):
        """Room exactly at target should trigger OFF."""
        config = MockConfig()
        checker = AssistConditionChecker(config)

        result = checker.check_off_conditions(
            room_temp=21.0,  # At target
            target_temp=21.0,
            room_eta_minutes=None,
            room_derivative=0.0,
        )

        assert result.met is True
        assert result.name == "overshoot"

    def test_stalled_at_target_triggers_off(self):
        """Stalled temp close to target should trigger OFF."""
        config = MockConfig(assist_stall_temp_delta=0.5)
        checker = AssistConditionChecker(config)

        result = checker.check_off_conditions(
            room_temp=20.6,  # Within 0.5 of target
            target_temp=21.0,
            room_eta_minutes=None,  # No ETA available
            room_derivative=0.0,  # Stalled
        )

        assert result.met is True
        assert result.name == "stalled_at_target"

    def test_stalled_at_target_not_triggered_when_rising(self):
        """Rising temp should not trigger stalled_at_target."""
        config = MockConfig(assist_stall_temp_delta=0.5)
        checker = AssistConditionChecker(config)

        result = checker.check_off_conditions(
            room_temp=20.6,
            target_temp=21.0,
            room_eta_minutes=None,
            room_derivative=0.5,  # Rising
        )

        assert result.met is False

    def test_stalled_at_target_not_triggered_when_far_from_target(self):
        """Room far from target should not trigger stalled_at_target."""
        config = MockConfig(assist_stall_temp_delta=0.5)
        checker = AssistConditionChecker(config)

        result = checker.check_off_conditions(
            room_temp=19.0,  # More than 0.5 below target
            target_temp=21.0,
            room_eta_minutes=None,
            room_derivative=0.0,
        )

        assert result.met is False

    # --- Priority Tests ---

    def test_on_condition_priority_eta_first(self):
        """eta_high should take priority if multiple conditions match."""
        config = MockConfig(
            assist_on_eta_threshold_minutes=60,
            assist_water_temp_threshold=35.0,
        )
        checker = AssistConditionChecker(config)

        result = checker.check_on_conditions(
            room_temp=19.0,
            target_temp=21.0,
            room_eta_minutes=90.0,  # eta_high matches
            water_temp=40.0,  # water_hot also matches
            room_derivative=0.5,
        )

        assert result.met is True
        assert result.name == "eta_high"  # eta_high has priority

    def test_off_condition_priority_eta_first(self):
        """eta_low should take priority if multiple conditions match."""
        config = MockConfig(assist_off_eta_threshold_minutes=15)
        checker = AssistConditionChecker(config)

        result = checker.check_off_conditions(
            room_temp=21.5,  # overshoot matches
            target_temp=21.0,
            room_eta_minutes=10.0,  # eta_low also matches
            room_derivative=-0.1,
        )

        assert result.met is True
        assert result.name == "eta_low"  # eta_low has priority

    # --- Edge Cases ---

    def test_none_values_handled_gracefully_on(self):
        """None values should not cause crashes in ON checks."""
        config = MockConfig()
        checker = AssistConditionChecker(config)

        result = checker.check_on_conditions(
            room_temp=None,
            target_temp=None,
            room_eta_minutes=None,
            water_temp=None,
            room_derivative=None,
        )

        assert result.met is False

    def test_none_values_handled_gracefully_off(self):
        """None values should not cause crashes in OFF checks."""
        config = MockConfig()
        checker = AssistConditionChecker(config)

        result = checker.check_off_conditions(
            room_temp=None,
            target_temp=None,
            room_eta_minutes=None,
            room_derivative=None,
        )

        assert result.met is False
