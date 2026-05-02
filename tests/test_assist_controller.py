"""Tests for PowerClimate assist controller."""

from unittest.mock import MagicMock

from custom_components.powerclimate.assist_controller import AssistPumpController


class DummyConfig:
    """Minimal config stub for assist controller tests."""

    assist_timer_seconds = 60.0
    assist_min_on_minutes = 5.0
    assist_min_off_minutes = 5.0
    assist_on_eta_threshold_minutes = 30.0
    assist_off_eta_threshold_minutes = 10.0
    assist_water_temp_threshold = 30.0
    assist_stall_temp_delta = 0.1


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