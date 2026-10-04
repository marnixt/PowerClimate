"""Tests for PowerClimate assist controller."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from custom_components.powerclimate.assist_controller import AssistPumpController
from custom_components.powerclimate.models import AssistTimerState


class DummyConfig:
    """Minimal config stub for assist controller tests."""

    assist_timer_seconds = 60.0
    assist_min_on_minutes = 5.0
    assist_min_off_minutes = 5.0
    assist_on_eta_threshold_minutes = 30.0
    assist_off_eta_threshold_minutes = 10.0
    assist_water_temp_threshold = 30.0
    assist_stall_temp_delta = 0.1


def _make_controller(*, storage: bool = True) -> AssistPumpController:
    hass = MagicMock()
    hass.async_create_task.side_effect = lambda coro: coro.close()
    store = MagicMock() if storage else None
    return AssistPumpController(DummyConfig(), hass=hass, storage=store)


# ---------------------------------------------------------------------------
# Persistence scheduling
# ---------------------------------------------------------------------------


def test_force_off_schedules_persistence() -> None:
    """Force-off should schedule persistence for the mutated timer state."""
    hass = MagicMock()
    hass.async_create_task.side_effect = lambda coro: coro.close()
    storage = MagicMock()
    controller = AssistPumpController(DummyConfig(), hass=hass, storage=storage)

    controller.force_off("climate.hp2")

    hass.async_create_task.assert_called_once()


def test_record_turn_off_schedules_persistence() -> None:
    """Turn-off transitions should schedule persistence for the updated timer state."""
    hass = MagicMock()
    hass.async_create_task.side_effect = lambda coro: coro.close()
    storage = MagicMock()
    controller = AssistPumpController(DummyConfig(), hass=hass, storage=storage)

    controller.record_turn_off("climate.hp2")

    hass.async_create_task.assert_called_once()


# ---------------------------------------------------------------------------
# get_timer_state
# ---------------------------------------------------------------------------


def test_get_timer_state_creates_default_for_new_entity() -> None:
    controller = _make_controller()
    state = controller.get_timer_state("climate.hp_new")
    assert isinstance(state, AssistTimerState)
    assert state.on_timer_seconds == 0.0
    assert state.running_state is False


def test_get_timer_state_returns_same_object_for_known_entity() -> None:
    controller = _make_controller()
    s1 = controller.get_timer_state("climate.hp1")
    s2 = controller.get_timer_state("climate.hp1")
    assert s1 is s2


# ---------------------------------------------------------------------------
# record_turn_on / record_turn_off
# ---------------------------------------------------------------------------


def test_record_turn_on_sets_running_state_and_last_on() -> None:
    controller = _make_controller()
    controller.record_turn_on("climate.hp1")
    state = controller.get_timer_state("climate.hp1")
    assert state.running_state is True
    assert state.last_on is not None


def test_record_turn_off_sets_running_state_and_last_off() -> None:
    controller = _make_controller()
    controller.record_turn_off("climate.hp1")
    state = controller.get_timer_state("climate.hp1")
    assert state.running_state is False
    assert state.last_off is not None


# ---------------------------------------------------------------------------
# force_off
# ---------------------------------------------------------------------------


def test_force_off_resets_timers_and_marks_last_off() -> None:
    controller = _make_controller()
    state = controller.get_timer_state("climate.hp2")
    state.on_timer_seconds = 120.0
    state.active_condition = "eta_high"
    state.running_state = True

    controller.force_off("climate.hp2")

    assert state.on_timer_seconds == 0.0
    assert state.off_timer_seconds == 0.0
    assert state.active_condition == "none"
    assert state.running_state is False
    assert state.last_off is not None


# ---------------------------------------------------------------------------
# reset_timers
# ---------------------------------------------------------------------------


def test_reset_timers_clears_both_timers_and_condition() -> None:
    controller = _make_controller()
    state = controller.get_timer_state("climate.hp3")
    state.on_timer_seconds = 55.0
    state.off_timer_seconds = 30.0
    state.active_condition = "overshoot"

    controller.reset_timers("climate.hp3")

    assert state.on_timer_seconds == 0.0
    assert state.off_timer_seconds == 0.0
    assert state.active_condition == "none"


# ---------------------------------------------------------------------------
# update_timers
# ---------------------------------------------------------------------------


def test_update_timers_accumulates_on_timer_when_on_condition_met() -> None:
    """ON timer should grow when room is below target and ETA is high."""
    controller = _make_controller()
    # Seed a previous update so delta > 0 on the second call
    controller.update_timers(
        "climate.hp1",
        room_temp=18.0,
        target_temp=21.0,
        room_eta_hours=2.0,   # 120 min > 30 min threshold → eta_high
        water_temp=25.0,
        room_derivative=0.1,
        is_running=False,
    )
    state = controller.update_timers(
        "climate.hp1",
        room_temp=18.0,
        target_temp=21.0,
        room_eta_hours=2.0,
        water_temp=25.0,
        room_derivative=0.1,
        is_running=False,
    )
    assert state.on_timer_seconds > 0.0
    assert state.off_timer_seconds == 0.0
    assert state.active_condition == "eta_high"


def test_update_timers_accumulates_off_timer_when_off_condition_met() -> None:
    """OFF timer should grow when room has overshot the target."""
    controller = _make_controller()
    controller.update_timers(
        "climate.hp1",
        room_temp=21.5,  # above target → overshoot
        target_temp=21.0,
        room_eta_hours=5.0,  # ETA is high, but overshoot takes priority for OFF
        water_temp=25.0,
        room_derivative=0.1,
        is_running=True,
    )
    state = controller.update_timers(
        "climate.hp1",
        room_temp=21.5,
        target_temp=21.0,
        room_eta_hours=5.0,
        water_temp=25.0,
        room_derivative=0.1,
        is_running=True,
    )
    assert state.off_timer_seconds > 0.0
    assert state.on_timer_seconds == 0.0
    assert state.active_condition == "overshoot"


def test_update_timers_resets_both_timers_when_no_condition() -> None:
    """When no condition is met, both timers should be zeroed."""
    controller = _make_controller()
    state = controller.get_timer_state("climate.hp1")
    state.on_timer_seconds = 50.0
    state.off_timer_seconds = 10.0
    state.active_condition = "eta_high"

    controller.update_timers(
        "climate.hp1",
        room_temp=20.9,  # just below target but close (< stall_delta from target)
        target_temp=21.0,
        room_eta_hours=None,  # no ETA
        water_temp=25.0,
        room_derivative=0.1,  # rising → not stalled
        is_running=True,
    )

    assert state.on_timer_seconds == 0.0
    assert state.off_timer_seconds == 0.0
    assert state.active_condition == "none"


def test_update_timers_tracks_elapsed_time_per_entity() -> None:
    """Each assist pump should accumulate time from its own update cadence."""
    controller = _make_controller()
    start = datetime(2026, 10, 4, tzinfo=timezone.utc)
    timestamps = [
        start,
        start,
        start + timedelta(seconds=30),
        start + timedelta(seconds=30),
        start + timedelta(seconds=60),
        start + timedelta(seconds=60),
    ]

    with patch("custom_components.powerclimate.assist_controller.datetime") as mock_datetime:
        mock_datetime.now.side_effect = timestamps
        for entity_id in ("climate.hp1", "climate.hp2") * 3:
            controller.update_timers(
                entity_id,
                room_temp=18.0,
                target_temp=21.0,
                room_eta_hours=2.0,
                water_temp=25.0,
                room_derivative=0.1,
                is_running=False,
            )

    assert controller.get_timer_state("climate.hp1").on_timer_seconds == 60.0
    assert controller.get_timer_state("climate.hp2").on_timer_seconds == 60.0


# ---------------------------------------------------------------------------
# evaluate_action
# ---------------------------------------------------------------------------


def test_evaluate_action_returns_none_when_timer_below_threshold() -> None:
    controller = _make_controller()
    state = controller.get_timer_state("climate.hp1")
    state.on_timer_seconds = 30.0  # below 60s threshold
    state.active_condition = "eta_high"

    action, reason = controller.evaluate_action("climate.hp1", is_running=False)
    assert action is None


def test_evaluate_action_returns_heat_when_on_timer_exceeds_threshold() -> None:
    controller = _make_controller()
    state = controller.get_timer_state("climate.hp1")
    state.on_timer_seconds = 65.0  # above 60s threshold
    state.active_condition = "eta_high"

    action, reason = controller.evaluate_action("climate.hp1", is_running=False)
    assert action == "heat"
    assert reason == "eta_high"


def test_evaluate_action_returns_off_when_off_timer_exceeds_threshold() -> None:
    controller = _make_controller()
    state = controller.get_timer_state("climate.hp1")
    state.off_timer_seconds = 65.0
    state.active_condition = "overshoot"

    action, reason = controller.evaluate_action("climate.hp1", is_running=True)
    assert action == "off"
    assert reason == "overshoot"


def test_evaluate_action_blocks_on_within_min_off_period() -> None:
    """Anti-short-cycle: turning ON blocked if OFF for less than min_off_minutes."""
    controller = _make_controller()
    state = controller.get_timer_state("climate.hp1")
    state.on_timer_seconds = 65.0
    state.active_condition = "eta_high"
    # Device just turned off 10 seconds ago; min_off = 5 min = 300s
    state.last_off = datetime.now(timezone.utc) - timedelta(seconds=10)

    action, _ = controller.evaluate_action("climate.hp1", is_running=False)
    assert action is None
    assert "min_off" in state.block_reason


def test_evaluate_action_blocks_off_within_min_on_period() -> None:
    """Anti-short-cycle: turning OFF blocked if ON for less than min_on_minutes."""
    controller = _make_controller()
    state = controller.get_timer_state("climate.hp1")
    state.off_timer_seconds = 65.0
    state.active_condition = "overshoot"
    # Device just turned on 10 seconds ago; min_on = 5 min = 300s
    state.last_on = datetime.now(timezone.utc) - timedelta(seconds=10)

    action, _ = controller.evaluate_action("climate.hp1", is_running=True)
    assert action is None
    assert "min_on" in state.block_reason


def test_evaluate_action_uses_cool_mode_for_cooling_hvac() -> None:
    """When hvac_mode is 'cool', the ON action should request 'cool', not 'heat'."""
    controller = _make_controller()
    state = controller.get_timer_state("climate.hp1")
    state.on_timer_seconds = 65.0
    state.active_condition = "eta_high"

    action, _ = controller.evaluate_action("climate.hp1", is_running=False, hvac_mode="cool")
    assert action == "cool"


# ---------------------------------------------------------------------------
# get_hp_status_info
# ---------------------------------------------------------------------------


def test_get_hp_status_info_returns_expected_keys() -> None:
    controller = _make_controller()
    state = controller.get_timer_state("climate.hp1")
    state.on_timer_seconds = 42.0
    state.active_condition = "water_hot"
    state.block_reason = ""

    info = controller.get_hp_status_info("climate.hp1")

    assert set(info.keys()) == {
        "on_timer_seconds",
        "off_timer_seconds",
        "active_condition",
        "blocked_by",
        "target_hvac_mode",
        "target_reason",
    }
    assert info["on_timer_seconds"] == 42.0
    assert info["active_condition"] == "water_hot"