"""Tests for the pure PI controller."""

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.powerclimate.pi_controller import PIConfig, PIController

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
# kp 0.1, integral time 10 min, output within the water heat pump offsets.
CONFIG = PIConfig(kp=0.1, ti_seconds=600.0, output_min=-0.3, output_max=1.5)


def _at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def test_first_update_is_proportional_only():
    controller = PIController()

    result = controller.update(4.0, T0, CONFIG)

    assert result.output == pytest.approx(0.4)
    assert result.p_term == pytest.approx(0.4)
    assert result.i_term == 0.0
    assert result.integrating is False
    assert result.saturated is False


def test_integral_adds_one_proportional_step_per_integral_time():
    controller = PIController()
    controller.update(2.0, T0, CONFIG)

    result = controller.update(2.0, _at(300), CONFIG)

    # 300 s of a 600 s integral time adds half of kp * error.
    assert result.i_term == pytest.approx(0.1)
    assert result.output == pytest.approx(0.3)
    assert result.integrating is True


def test_time_step_is_capped():
    controller = PIController()
    controller.update(2.0, T0, CONFIG)

    result = controller.update(2.0, _at(3600), CONFIG)

    # Only max_dt_seconds (300 s) counts after a long gap.
    assert result.i_term == pytest.approx(0.1)


def test_integrate_false_freezes_integral_but_keeps_proportional():
    controller = PIController()
    controller.update(2.0, T0, CONFIG)
    controller.update(2.0, _at(300), CONFIG)

    result = controller.update(6.0, _at(600), CONFIG, integrate=False)

    assert result.i_term == pytest.approx(0.1)
    assert result.p_term == pytest.approx(0.6)
    assert result.integrating is False


def test_no_windup_while_saturated_high():
    controller = PIController()
    controller.update(20.0, T0, CONFIG)

    for step in range(1, 13):
        result = controller.update(20.0, _at(300 * step), CONFIG)

    # kp * error alone exceeds the maximum, so the integral never grows.
    assert result.output == 1.5
    assert result.saturated is True
    assert result.i_term == 0.0


def test_output_leaves_upper_limit_as_soon_as_error_turns():
    controller = PIController()
    controller.update(5.0, T0, CONFIG)
    for step in range(1, 30):
        controller.update(5.0, _at(300 * step), CONFIG)

    result = controller.update(-1.0, _at(300 * 30), CONFIG)

    # The integral stayed within the output range, so a negative error
    # brings the output below the maximum immediately.
    assert result.output < 1.5


def test_integral_stays_within_output_limits():
    controller = PIController()
    controller.update(-1.0, T0, CONFIG)

    for step in range(1, 200):
        result = controller.update(-1.0, _at(300 * step), CONFIG)

    assert result.i_term >= CONFIG.output_min
    assert result.output == CONFIG.output_min


def test_initialize_gives_bumpless_start():
    controller = PIController()
    controller.initialize(0.8, 2.0, CONFIG)

    result = controller.update(2.0, T0, CONFIG)

    assert controller.initialized is True
    assert result.output == pytest.approx(0.8)


def test_initialize_clamps_integral():
    controller = PIController()
    controller.initialize(5.0, 0.0, CONFIG)

    result = controller.update(0.0, T0, CONFIG)

    assert result.output == CONFIG.output_max


def test_reset_forgets_state():
    controller = PIController()
    controller.initialize(1.0, 0.0, CONFIG)
    controller.update(0.0, T0, CONFIG)

    controller.reset()
    result = controller.update(0.0, _at(300), CONFIG)

    assert controller.initialized is True  # update starts a fresh integral
    assert result.output == 0.0
    assert result.integrating is False  # first update after reset has no time step
