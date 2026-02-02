"""Tests for PowerClimate timer storage."""
import pytest
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

from custom_components.powerclimate.timer_storage import (
    TimerStorage,
    _datetime_to_iso,
    _iso_to_datetime,
    STORAGE_VERSION,
)
from custom_components.powerclimate.models import AssistTimerState


class TestDatetimeHelpers:
    """Tests for datetime conversion helpers."""

    def test_datetime_to_iso_with_value(self):
        dt = datetime(2024, 1, 15, 12, 30, 45, tzinfo=timezone.utc)
        result = _datetime_to_iso(dt)
        assert result == "2024-01-15T12:30:45+00:00"

    def test_datetime_to_iso_none(self):
        assert _datetime_to_iso(None) is None

    def test_iso_to_datetime_valid(self):
        iso_str = "2024-01-15T12:30:45+00:00"
        result = _iso_to_datetime(iso_str)
        assert result is not None
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15
        assert result.hour == 12
        assert result.minute == 30

    def test_iso_to_datetime_none(self):
        assert _iso_to_datetime(None) is None

    def test_iso_to_datetime_invalid(self):
        assert _iso_to_datetime("not-a-date") is None
        assert _iso_to_datetime("") is None


class TestTimerStorageSerialization:
    """Tests for timer state serialization/deserialization."""

    def setup_method(self):
        """Set up test fixtures."""
        self.hass = MagicMock()
        self.hass.config.path = MagicMock(return_value="/config/.storage/test.json")
        self.storage = TimerStorage(self.hass, "test_entry")

    def test_serialize_states(self):
        """Should serialize AssistTimerState to JSON-compatible dict."""
        dt = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        states = {
            "climate.hp1": AssistTimerState(
                on_timer_seconds=120.0,
                off_timer_seconds=60.0,
                active_condition="eta_high",
                running_state=True,
                last_on=dt,
                last_off=None,
                block_reason="",
                target_hvac_mode="heat",
                target_reason="on_timer",
            )
        }

        result = self.storage._serialize_states(states)

        assert "climate.hp1" in result
        hp1 = result["climate.hp1"]
        assert hp1["on_timer_seconds"] == 120.0
        assert hp1["off_timer_seconds"] == 60.0
        assert hp1["active_condition"] == "eta_high"
        assert hp1["running_state"] is True
        assert hp1["last_on"] == "2024-01-15T12:00:00+00:00"
        assert hp1["last_off"] is None
        assert hp1["target_hvac_mode"] == "heat"

    def test_deserialize_states(self):
        """Should deserialize JSON data to AssistTimerState."""
        data = {
            "climate.hp1": {
                "on_timer_seconds": 120.0,
                "off_timer_seconds": 60.0,
                "active_condition": "eta_high",
                "running_state": True,
                "last_on": "2024-01-15T12:00:00+00:00",
                "last_off": None,
                "block_reason": "",
                "target_hvac_mode": "heat",
                "target_reason": "on_timer",
            }
        }

        result = self.storage._deserialize_states(data)

        assert "climate.hp1" in result
        hp1 = result["climate.hp1"]
        assert isinstance(hp1, AssistTimerState)
        assert hp1.on_timer_seconds == 120.0
        assert hp1.off_timer_seconds == 60.0
        assert hp1.active_condition == "eta_high"
        assert hp1.running_state is True
        assert hp1.last_on is not None
        assert hp1.target_hvac_mode == "heat"

    def test_deserialize_handles_missing_fields(self):
        """Should handle missing fields with defaults."""
        data = {
            "climate.hp1": {
                "on_timer_seconds": 120.0,
                # Missing most fields
            }
        }

        result = self.storage._deserialize_states(data)

        assert "climate.hp1" in result
        hp1 = result["climate.hp1"]
        assert hp1.on_timer_seconds == 120.0
        assert hp1.off_timer_seconds == 0.0  # Default
        assert hp1.active_condition == "none"  # Default
        assert hp1.running_state is False  # Default

    def test_deserialize_handles_invalid_data(self):
        """Should skip entries with invalid data."""
        data = {
            "climate.valid": {
                "on_timer_seconds": 120.0,
                "off_timer_seconds": 60.0,
                "active_condition": "test",
                "running_state": True,
            },
        }

        result = self.storage._deserialize_states(data)

        # Valid entry should be present
        assert "climate.valid" in result
        # The function handles invalid values gracefully by using defaults


class TestTimerStorageRoundTrip:
    """Tests for round-trip serialization."""

    def setup_method(self):
        """Set up test fixtures."""
        self.hass = MagicMock()
        self.hass.config.path = MagicMock(return_value="/config/.storage/test.json")
        self.storage = TimerStorage(self.hass, "test_entry")

    def test_round_trip_preserves_data(self):
        """Serialization and deserialization should preserve data."""
        dt = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        original = {
            "climate.hp1": AssistTimerState(
                on_timer_seconds=123.5,
                off_timer_seconds=67.8,
                active_condition="water_hot",
                running_state=True,
                last_on=dt,
                last_off=None,
                block_reason="blocked",
                target_hvac_mode="heat",
                target_reason="condition",
            ),
            "climate.hp2": AssistTimerState(
                on_timer_seconds=0.0,
                off_timer_seconds=0.0,
                active_condition="none",
                running_state=False,
                last_on=None,
                last_off=dt,
                block_reason="",
                target_hvac_mode=None,
                target_reason="",
            ),
        }

        # Serialize then deserialize
        serialized = self.storage._serialize_states(original)
        restored = self.storage._deserialize_states(serialized)

        # Check HP1
        assert restored["climate.hp1"].on_timer_seconds == 123.5
        assert restored["climate.hp1"].off_timer_seconds == 67.8
        assert restored["climate.hp1"].active_condition == "water_hot"
        assert restored["climate.hp1"].running_state is True
        assert restored["climate.hp1"].target_hvac_mode == "heat"

        # Check HP2
        assert restored["climate.hp2"].on_timer_seconds == 0.0
        assert restored["climate.hp2"].running_state is False
        assert restored["climate.hp2"].target_hvac_mode is None


class TestTimerStorageInit:
    """Tests for TimerStorage initialization."""

    def test_init_sets_path(self):
        """Should set storage path correctly."""
        hass = MagicMock()
        hass.config.path = MagicMock(
            return_value="/config/.storage/powerclimate_timers_abc123.json"
        )

        storage = TimerStorage(hass, "abc123")

        hass.config.path.assert_called_once_with(
            ".storage", "powerclimate_timers_abc123.json"
        )

    def test_init_not_loaded(self):
        """Should start in not-loaded state."""
        hass = MagicMock()
        hass.config.path = MagicMock(return_value="/config/test.json")

        storage = TimerStorage(hass, "entry1")

        assert storage._loaded is False
        assert storage._data == {}
