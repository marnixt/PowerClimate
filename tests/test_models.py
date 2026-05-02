"""Tests for PowerClimate data models."""

from custom_components.powerclimate.models import AssistTimerState


def test_assist_timer_state_no_condition_returns_default_state() -> None:
    """no_condition should return an empty timer state instead of crashing."""
    assert AssistTimerState.no_condition() == AssistTimerState()
