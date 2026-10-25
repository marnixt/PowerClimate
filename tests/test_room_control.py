"""Tests for the room control of the water heat pump (experimental)."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.powerclimate.mode_targets import SetpointLimits
from custom_components.powerclimate.room_control import RoomController

T0 = datetime(2026, 1, 1, tzinfo=UTC)
# The water heat pump's heating offsets around its measured temperature.
LIMITS = SetpointLimits(16.0, 30.0, -0.3, 1.5)


def _controller() -> RoomController:
    """Return a controller with a 30 minute integral time and a 40 °C threshold."""
    return RoomController(
        SimpleNamespace(room_pi_ti_minutes=30.0, assist_water_temp_threshold=40.0)
    )


def _setpoint(
    controller: RoomController,
    at: datetime = T0,
    *,
    room: float | None = 21.7,
    target: float | None = 22.0,
    current_temp: float | None = 21.7,
    water_filtered: float | None = 30.0,
    assist_running: bool = False,
    overshoot: bool = False,
) -> float | None:
    """Return the water heat pump setpoint the correction leads to."""
    correction = controller.correction(
        room=room,
        target=target,
        limits=LIMITS,
        current_temp=current_temp,
        water_filtered=water_filtered,
        assist_running=assist_running,
        overshoot=overshoot,
        now=at,
    )
    if correction is None or current_temp is None:
        return None
    return round(current_temp + correction, 1)


def _run(controller: RoomController, start: datetime, minutes: int, **kwargs) -> datetime:
    """Update the controller once a minute; return the time of the last update."""
    at = start
    for minute in range(1, minutes + 1):
        at = start + timedelta(minutes=minute)
        _setpoint(controller, at, **kwargs)
    return at


def test_starts_without_an_integral() -> None:
    """The first setpoint is the device temperature plus the room error."""
    controller = _controller()

    assert _setpoint(controller) == 22.0
    summary = controller.summary
    assert summary["room_pi_active"] is True
    assert summary["room_pi_error"] == 0.3
    assert summary["room_pi_p"] == 0.3
    assert summary["room_pi_i"] == 0.0


def test_start_during_night_setback_does_not_wind_up() -> None:
    """A restart with the target far below the room keeps the integral at zero."""
    controller = _controller()

    assert _setpoint(controller, room=21.2, target=18.0, current_temp=21.4) == 21.1
    _run(controller, T0, 60, room=21.2, target=18.0, current_temp=21.4)

    assert controller.summary["room_pi_i"] == 0.0
    # Back to the day target: only the room error pushes.
    morning = T0 + timedelta(hours=2)
    assert _setpoint(controller, morning, room=21.2, target=21.3, current_temp=21.4) == 21.5


def test_passes_on_the_room_error_relative_to_the_device_temperature() -> None:
    """A device that reads warmer than the room still sees the full room error."""
    controller = _controller()

    # The device reads 21.9, the room 21.7: the setpoint is 21.9 + 0.3.
    assert _setpoint(controller, current_temp=21.9) == 22.2


def test_integral_grows_while_the_shortage_lasts() -> None:
    """After one integral time the integral has added the room error once more."""
    controller = _controller()
    _setpoint(controller)

    _run(controller, T0, 30)

    assert controller.summary["room_pi_i"] == pytest.approx(0.3, abs=0.01)
    assert controller.at_limit is False


def test_integral_stops_growing_once_the_supply_is_hot() -> None:
    """At the assist water threshold the assist pumps take over."""
    controller = _controller()
    _setpoint(controller, water_filtered=40.0)

    _run(controller, T0, 30, water_filtered=40.0)

    assert controller.summary["room_pi_i"] == 0.0
    assert controller.summary["room_pi_supply_hot"] is True
    assert controller.at_limit is True


def test_integral_does_not_shrink_while_an_assist_heats() -> None:
    """A room above target is the assist's doing; the push stays for afterwards."""
    controller = _controller()
    _setpoint(controller)
    at = _run(controller, T0, 30)
    built_up = controller.summary["room_pi_i"]

    at = _run(controller, at, 30, room=22.2, assist_running=True)
    assert controller.summary["room_pi_i"] == built_up

    _run(controller, at, 30, room=22.2)
    # Without the assist the integral drains by the room error per integral time.
    assert controller.summary["room_pi_i"] == pytest.approx(built_up - 0.2, abs=0.01)


def test_integral_still_grows_while_an_assist_heats() -> None:
    """A room below target despite the assist means the water heat pump must push harder."""
    controller = _controller()
    _setpoint(controller, assist_running=True)

    _run(controller, T0, 30, assist_running=True)

    assert controller.summary["room_pi_i"] == pytest.approx(0.3, abs=0.01)


def test_at_limit_when_the_setpoint_reaches_the_upper_offset() -> None:
    """With the setpoint at its ceiling the water heat pump cannot push harder."""
    controller = _controller()

    assert _setpoint(controller, room=19.0, target=21.0, current_temp=19.0) == 20.5
    assert controller.at_limit is True
    assert controller.summary["room_pi_at_limit"] is True


def test_overshoot_sends_the_lowest_setpoint() -> None:
    """Above target plus the maximum overshoot the water heat pump gets its floor."""
    controller = _controller()

    assert _setpoint(controller, room=22.6, current_temp=22.6, overshoot=True) == 22.3


def test_small_changes_keep_the_setpoint() -> None:
    """Room noise below the deadband does not send a new setpoint."""
    controller = _controller()
    assert _setpoint(controller) == 22.0

    assert _setpoint(controller, T0 + timedelta(minutes=1), room=21.6) == 22.0
    assert _setpoint(controller, T0 + timedelta(minutes=2), room=21.4) == 22.3


def test_without_readings_the_controller_waits() -> None:
    """Without a room or device temperature the normal setpoint logic applies."""
    controller = _controller()

    assert _setpoint(controller, room=None) is None
    assert _setpoint(controller, current_temp=None) is None
    assert controller.initialized is False
    assert controller.at_limit is None


def test_reset_and_clear_summary() -> None:
    """Reset starts afresh; clearing the summary marks the controller inactive."""
    controller = _controller()
    _setpoint(controller)

    controller.clear_summary()
    assert controller.summary["room_pi_active"] is False
    assert controller.at_limit is None

    controller.reset()
    assert controller.initialized is False
