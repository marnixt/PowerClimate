"""Tests for the supply-temperature control (supply advice preset)."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from custom_components.powerclimate.const import (
    SUPPLY_FILTER_TAU_SECONDS,
    SUPPLY_SPIKE_KELVIN,
    SUPPLY_SPIKE_MAX_SECONDS,
)
from custom_components.powerclimate.mode_targets import SetpointLimits
from custom_components.powerclimate.supply_control import SupplyController
from custom_components.powerclimate.supply_filter import SupplyFilter

T0 = datetime(2026, 1, 1, tzinfo=UTC)
# The water heat pump's heating offsets around its measured temperature.
LIMITS = SetpointLimits(16.0, 30.0, -0.3, 1.5)


def _controller() -> SupplyController:
    """Return a controller with kp 0.1 and a 10 minute integral time.

    It gets a supply filter, which the coordinator owns in the integration.
    """
    controller = SupplyController(
        SimpleNamespace(supply_pi_kp=0.1, supply_pi_ti_minutes=10.0, supply_pi_min_power_w=200.0)
    )
    controller.test_filter = SupplyFilter(
        SUPPLY_FILTER_TAU_SECONDS, SUPPLY_SPIKE_KELVIN, SUPPLY_SPIKE_MAX_SECONDS
    )
    return controller


def _setpoint(
    controller: SupplyController,
    at: datetime = T0,
    *,
    advice: float | None = 30.0,
    current_temp: float = 21.0,
    current_target: float | None = 21.0,
    water_temp: float | None = 28.0,
    power: float | None = 1000.0,
    overshoot: bool = False,
) -> float | None:
    """Return the water heat pump setpoint the correction leads to."""
    reading = controller.test_filter.update(water_temp, at) if water_temp is not None else None
    correction = controller.correction(
        source="sensor.supply_advice",
        advice=advice,
        limits=LIMITS,
        current_temp=current_temp,
        current_target=current_target,
        water_temp=water_temp,
        water_filtered=reading.filtered if reading else None,
        spike=reading.spike if reading else False,
        power=power,
        overshoot=overshoot,
        now=at,
    )
    return None if correction is None else round(current_temp + correction, 1)


def test_starts_from_current_device_offset() -> None:
    """Entering the preset keeps the device setpoint where it is (bumpless start)."""
    controller = _controller()

    assert _setpoint(controller, current_target=21.5) == 21.5
    summary = controller.summary
    assert summary["supply_pi_active"] is True
    assert summary["supply_pi_source"] == "sensor.supply_advice"
    assert summary["supply_pi_advised_temp"] == 30.0
    assert summary["supply_pi_error"] == 2.0
    assert summary["supply_pi_correction"] == 0.5


def test_setpoint_rises_while_supply_is_below_advice() -> None:
    """A supply temperature below the advice raises the room setpoint over time."""
    controller = _controller()

    first = _setpoint(controller)
    second = _setpoint(controller, T0 + timedelta(seconds=300))
    third = _setpoint(controller, T0 + timedelta(seconds=600))

    assert first == 21.0
    # Each 300 s of a 600 s integral time adds half of kp * error (0.1);
    # the first 0.1 stays within the setpoint deadband.
    assert second == 21.0
    assert third == 21.2


def test_deadband_never_leaves_device_offsets() -> None:
    """A held setpoint is dropped when holding it would exceed the offsets."""
    controller = _controller()

    first = _setpoint(controller, advice=45.0, current_target=None, water_temp=25.0)
    later = _setpoint(
        controller,
        T0 + timedelta(seconds=60),
        advice=45.0,
        current_temp=20.85,  # device temperature dropped 0.15 °C
        current_target=first,
        water_temp=25.0,
    )

    assert first == 22.5  # 21.0 + upper offset 1.5
    # Holding 22.5 would be +1.65 above 20.85; the setpoint follows instead.
    assert later == 22.4  # round(20.85 + 1.5, 1)


def test_holds_correction_during_supply_spike() -> None:
    """A sudden supply jump (e.g. boiler hot water) does not move the setpoint."""
    controller = _controller()

    first = _setpoint(controller, current_target=21.5)
    spike = _setpoint(controller, T0 + timedelta(seconds=60), water_temp=57.0)

    assert spike == first == 21.5
    assert controller.summary["supply_pi_spike"] is True
    assert controller.summary["supply_pi_supply_filtered"] == 28.0


def test_accepts_lasting_supply_change() -> None:
    """A jump that lasts longer than a spike is used as the new supply temperature."""
    controller = _controller()

    _setpoint(controller, current_target=21.5)
    _setpoint(controller, T0 + timedelta(seconds=60), water_temp=40.0)
    setpoint = _setpoint(controller, T0 + timedelta(seconds=700), water_temp=40.0)

    assert controller.summary["supply_pi_spike"] is False
    assert setpoint == 20.7  # supply far above advice: lower offset


def test_correction_is_limited_to_device_offsets() -> None:
    """The correction never leaves the water device's heating offsets."""
    controller = _controller()

    assert _setpoint(controller, advice=45.0, current_target=None, water_temp=25.0) == 22.5


def test_integral_frozen_while_compressor_idle() -> None:
    """Without compressor power the supply temperature does not drive the integral."""
    controller = _controller()

    _setpoint(controller, power=50.0)
    setpoint = _setpoint(controller, T0 + timedelta(seconds=300), power=50.0)

    assert setpoint == 21.0
    assert controller.summary["supply_pi_integrating"] is False


def test_overshoot_forces_lower_offset() -> None:
    """Above target plus maximum overshoot the setpoint goes to the lower offset."""
    controller = _controller()

    assert _setpoint(controller, overshoot=True) == 20.7  # 21.0 + lower offset -0.3


def test_waits_without_advice() -> None:
    """Without advice the caller uses the normal setpoint logic; the controller waits."""
    controller = _controller()

    assert _setpoint(controller, advice=None) is None
    assert controller.initialized is False
    assert controller.summary["supply_pi_active"] is False


def test_waits_without_supply_reading() -> None:
    controller = _controller()

    assert _setpoint(controller, water_temp=None) is None
    assert controller.initialized is False


def test_reset_starts_afresh() -> None:
    controller = _controller()
    _setpoint(controller, current_target=21.5)

    controller.reset()

    assert controller.initialized is False
    assert _setpoint(controller, T0 + timedelta(seconds=60), current_target=21.2) == 21.2
