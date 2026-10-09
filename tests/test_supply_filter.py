"""Tests for the supply temperature filter."""

import math
from datetime import datetime, timedelta, timezone

import pytest

from custom_components.powerclimate.supply_filter import SupplyFilter

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def _filter() -> SupplyFilter:
    return SupplyFilter(tau_seconds=120.0, spike_kelvin=5.0, max_spike_seconds=600.0)


def test_first_reading_is_taken_as_is():
    reading = _filter().update(30.0, T0)

    assert reading.filtered == 30.0
    assert reading.spike is False


def test_moving_average_follows_with_time_constant():
    supply = _filter()
    supply.update(30.0, T0)

    reading = supply.update(32.0, _at(120))

    # One time constant closes 1 - 1/e of the gap.
    assert reading.filtered == pytest.approx(30.0 + 2.0 * (1 - math.exp(-1)))


def test_noise_is_damped():
    supply = _filter()
    supply.update(30.0, T0)

    reading = supply.update(30.5, _at(10))

    assert 30.0 < reading.filtered < 30.1


def test_spike_holds_average():
    supply = _filter()
    supply.update(30.0, T0)

    reading = supply.update(57.0, _at(30))

    assert reading.spike is True
    assert reading.filtered == 30.0


def test_average_resumes_after_spike():
    supply = _filter()
    supply.update(30.0, T0)
    supply.update(57.0, _at(30))

    reading = supply.update(30.4, _at(90))

    assert reading.spike is False
    assert 30.0 < reading.filtered < 30.4


def test_lasting_jump_is_accepted():
    supply = _filter()
    supply.update(30.0, T0)
    supply.update(40.0, _at(10))

    reading = supply.update(40.0, _at(620))

    assert reading.spike is False
    assert reading.filtered == 40.0


def test_drop_is_not_a_spike():
    supply = _filter()
    supply.update(30.0, T0)

    reading = supply.update(20.0, _at(10))

    assert reading.spike is False
    assert reading.filtered < 30.0


def test_reset_starts_over():
    supply = _filter()
    supply.update(30.0, T0)
    supply.reset()

    reading = supply.update(45.0, _at(10))

    assert reading.filtered == 45.0
    assert reading.spike is False
