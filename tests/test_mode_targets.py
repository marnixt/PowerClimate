"""Tests for the pure mode target calculation."""

from unittest.mock import MagicMock

import pytest

from custom_components.powerclimate.const import (
    MODE_BOOST,
    MODE_MINIMAL,
    MODE_MPC,
    MODE_OFF,
    MODE_POWER,
    MODE_SETPOINT,
    MODE_THERMAL_MPC,
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


def test_mpc_uses_advice_when_available():
    assert _target(MODE_MPC, mpc_target=lambda: 32.0) == 30.0
    assert _target(MODE_MPC, mpc_target=lambda: None, target=21.0) == 21.0


def test_thermal_mpc_uses_model_when_available():
    assert _target(MODE_THERMAL_MPC, thermal_target=lambda: 27.5) == 27.5
    assert _target(MODE_THERMAL_MPC, thermal_target=lambda: None, target=21.0) == 21.0


def test_power_mode_uses_power_target():
    assert _target(MODE_POWER, power_target=lambda: 24.5) == 24.5


def test_lazy_inputs_only_evaluated_for_their_mode():
    mpc = MagicMock(return_value=25.0)
    thermal = MagicMock(return_value=25.0)
    power = MagicMock(return_value=25.0)

    _target(MODE_SETPOINT, mpc_target=mpc, thermal_target=thermal, power_target=power)
    _target(MODE_POWER, None, mpc_target=mpc, thermal_target=thermal, power_target=power)

    mpc.assert_not_called()
    thermal.assert_not_called()
    power.assert_not_called()


def test_unknown_mode_returns_minimum():
    assert _target(MODE_OFF) == 16.0
