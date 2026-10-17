"""Tests for the pure mode target calculation."""

from unittest.mock import MagicMock

import pytest

from custom_components.powerclimate.const import (
    MODE_BOOST,
    MODE_MINIMAL,
    MODE_OFF,
    MODE_SETPOINT,
    MODE_SUPPLY_ADVICE,
)
from custom_components.powerclimate.mode_targets import (
    SetpointLimits,
    calculate_mode_target,
)

LIMITS = SetpointLimits(min_setpoint=16.0, max_setpoint=30.0, lower_offset=-2.0, upper_offset=3.0)


def _target(mode, current_temp=20.0, *, target=21.0, cooling=False, **kwargs):
    return calculate_mode_target(
        mode,
        current_temp,
        kwargs.pop("limits", LIMITS),
        target_temperature=target,
        is_cooling=cooling,
        **kwargs,
    )


@pytest.mark.parametrize(
    ("cooling", "expected"),
    [(False, 23.0), (True, 18.0)],
)
def test_boost_uses_most_aggressive_offset(cooling, expected):
    assert _target(MODE_BOOST, cooling=cooling) == expected


def test_boost_is_clamped_to_limits():
    assert _target(MODE_BOOST, current_temp=29.0) == 30.0


@pytest.mark.parametrize(
    ("cooling", "expected"),
    [(False, 18.0), (True, 23.0)],
)
def test_minimal_uses_least_aggressive_offset(cooling, expected):
    assert _target(MODE_MINIMAL, cooling=cooling) == expected


def test_setpoint_follows_room_target_within_offsets():
    assert _target(MODE_SETPOINT, target=21.5) == 21.5
    assert _target(MODE_SETPOINT, target=28.0) == 23.0


def test_without_device_temperature_keeps_current_setpoint():
    assert _target(MODE_SETPOINT, None, current_target=22.0) == 22.0
    assert _target(MODE_SETPOINT, None, current_target=35.0) == 30.0


def test_without_any_temperature_falls_back_to_room_target_then_minimum():
    assert _target(MODE_SETPOINT, None, target=19.0) == 19.0
    assert _target(MODE_SETPOINT, None, target=None) == 16.0


def test_supply_advice_heating_applies_correction():
    # Device measures 20.0; the correction moves the room setpoint around it.
    assert _target(MODE_SUPPLY_ADVICE, supply_correction=lambda: 1.24) == 21.2
    assert _target(MODE_SUPPLY_ADVICE, supply_correction=lambda: -0.3) == 19.7


def test_supply_correction_is_clamped_to_global_limits():
    assert _target(MODE_SUPPLY_ADVICE, 29.5, supply_correction=lambda: 1.5) == 30.0


def test_supply_advice_falls_back_to_room_target_without_correction():
    assert _target(MODE_SUPPLY_ADVICE, supply_correction=lambda: None, target=21.0) == 21.0


def test_supply_correction_not_used_when_cooling():
    correction = MagicMock(return_value=1.0)

    _target(MODE_SUPPLY_ADVICE, cooling=True, supply_correction=correction)

    correction.assert_not_called()


def test_supply_correction_only_evaluated_in_supply_advice_with_temperature():
    correction = MagicMock(return_value=1.0)

    _target(MODE_SETPOINT, supply_correction=correction)
    _target(MODE_SUPPLY_ADVICE, None, supply_correction=correction)

    correction.assert_not_called()


def test_unknown_mode_returns_minimum():
    assert _target(MODE_OFF) == 16.0
