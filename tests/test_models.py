"""Tests for PowerClimate data models."""

from datetime import UTC, datetime

from custom_components.powerclimate.models import AssistTimerState


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
    now = datetime.now(UTC)

    state.on_timer_seconds = 120.0
    state.running_state = True
    state.last_on = now
    state.active_condition = "eta_high"

    assert state.on_timer_seconds == 120.0
    assert state.running_state is True
    assert state.last_on is now
    assert state.active_condition == "eta_high"
