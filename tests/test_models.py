"""Tests for PowerClimate data models."""

from datetime import datetime, timezone

from custom_components.powerclimate.models import AssistTimerState


def test_assist_timer_state_no_condition_returns_default_state() -> None:
    """no_condition should return an empty timer state instead of crashing."""
    assert AssistTimerState.no_condition() == AssistTimerState()


def test_assist_timer_state_default_field_values() -> None:
    """All fields should start at sensible zero/falsy defaults."""
    state = AssistTimerState()
    assert state.on_timer_seconds == 0.0
    assert state.off_timer_seconds == 0.0
    assert state.active_condition == "none"
    assert state.running_state is False
    assert state.last_on is None
    assert state.last_off is None
    assert state.block_reason == ""
    assert state.target_hvac_mode is None
    assert state.target_reason == ""


def test_assist_timer_state_is_mutable() -> None:
    """Fields should be assignable after construction."""
    state = AssistTimerState()
    now = datetime.now(timezone.utc)

    state.on_timer_seconds = 120.0
    state.running_state = True
    state.last_on = now
    state.active_condition = "eta_high"

    assert state.on_timer_seconds == 120.0
    assert state.running_state is True
    assert state.last_on is now
    assert state.active_condition == "eta_high"


def test_no_condition_is_not_same_instance_each_call() -> None:
    """Each call to no_condition should return a new independent object."""
    a = AssistTimerState.no_condition()
    b = AssistTimerState.no_condition()
    assert a is not b
    a.on_timer_seconds = 99.0
    assert b.on_timer_seconds == 0.0


def test_assist_timer_state_equality_based_on_fields() -> None:
    """Two states with identical fields should compare equal."""
    assert AssistTimerState() == AssistTimerState()
    a = AssistTimerState(on_timer_seconds=5.0, active_condition="water_hot")
    b = AssistTimerState(on_timer_seconds=5.0, active_condition="water_hot")
    assert a == b


def test_assist_timer_state_inequality_on_different_fields() -> None:
    """States that differ in any field should not compare equal."""
    a = AssistTimerState(on_timer_seconds=1.0)
    b = AssistTimerState(on_timer_seconds=2.0)
    assert a != b
