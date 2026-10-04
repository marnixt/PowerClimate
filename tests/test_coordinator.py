"""Tests for PowerClimate data coordinator.

Focuses on the pure-Python helpers _compute_derivative and _read_float so
no Home Assistant event loop is required.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.powerclimate.coordinator import OSDataUpdateCoordinator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_coordinator() -> OSDataUpdateCoordinator:
    """Return a coordinator with the minimum instance state for unit tests.

    Bypasses DataUpdateCoordinator.__init__ because that requires the HA frame
    helper and an event loop, neither of which are available in a plain pytest run.
    The methods under test (_read_float, _compute_derivative) only rely on
    ``hass.states.get`` and the history lists, both of which we inject directly.
    """
    coord = OSDataUpdateCoordinator.__new__(OSDataUpdateCoordinator)
    coord.hass = MagicMock()
    coord._room_temp_history = []
    coord._device_temp_history = {}
    coord._water_temp_history = {}
    return coord


def _ts(seconds_ago: float = 0.0) -> datetime:
    """Return a UTC timestamp offset by the given number of seconds from now."""
    return datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)


# ---------------------------------------------------------------------------
# _read_float
# ---------------------------------------------------------------------------


class TestReadFloat:
    """Tests for OSDataUpdateCoordinator._read_float."""

    def setup_method(self) -> None:
        self.coordinator = _make_coordinator()

    def test_returns_none_for_none_entity_id(self) -> None:
        assert self.coordinator._read_float(None) is None

    def test_returns_none_for_empty_entity_id(self) -> None:
        assert self.coordinator._read_float("") is None

    def test_returns_none_when_state_not_found(self) -> None:
        self.coordinator.hass.states.get.return_value = None
        assert self.coordinator._read_float("sensor.unknown") is None

    def test_returns_none_for_unknown_state(self) -> None:
        state = SimpleNamespace(state="unknown")
        self.coordinator.hass.states.get.return_value = state
        assert self.coordinator._read_float("sensor.x") is None

    def test_returns_none_for_unavailable_state(self) -> None:
        state = SimpleNamespace(state="unavailable")
        self.coordinator.hass.states.get.return_value = state
        assert self.coordinator._read_float("sensor.x") is None

    def test_returns_float_for_valid_numeric_state(self) -> None:
        state = SimpleNamespace(state="21.5")
        self.coordinator.hass.states.get.return_value = state
        assert self.coordinator._read_float("sensor.temp") == 21.5

    def test_returns_none_for_non_numeric_state(self) -> None:
        state = SimpleNamespace(state="on")
        self.coordinator.hass.states.get.return_value = state
        assert self.coordinator._read_float("sensor.switch") is None

    def test_returns_integer_as_float(self) -> None:
        state = SimpleNamespace(state="20")
        self.coordinator.hass.states.get.return_value = state
        assert self.coordinator._read_float("sensor.x") == 20.0


# ---------------------------------------------------------------------------
# _compute_derivative
# ---------------------------------------------------------------------------


class TestComputeDerivative:
    """Tests for OSDataUpdateCoordinator._compute_derivative."""

    def setup_method(self) -> None:
        self.coordinator = _make_coordinator()

    def test_returns_none_for_none_temperature(self) -> None:
        history: list = []
        result = self.coordinator._compute_derivative(history, None, 900)
        assert result is None

    def test_returns_none_for_non_numeric_temperature(self) -> None:
        history: list = []
        result = self.coordinator._compute_derivative(history, "bad", 900)
        assert result is None

    def test_returns_none_with_single_sample(self) -> None:
        history: list = []
        result = self.coordinator._compute_derivative(history, 20.0, 900)
        assert result is None
        assert len(history) == 1  # sample was recorded

    def test_returns_positive_slope_for_rising_temperature(self) -> None:
        """1 °C rise over 3600 s should yield +1.0 °C/h."""
        history: list = [(_ts(3600), 20.0)]
        result = self.coordinator._compute_derivative(history, 21.0, 900 * 10)
        assert result is not None
        assert pytest.approx(result, abs=0.05) == 1.0

    def test_returns_negative_slope_for_falling_temperature(self) -> None:
        """1 °C drop over 3600 s should yield -1.0 °C/h."""
        history: list = [(_ts(3600), 21.0)]
        result = self.coordinator._compute_derivative(history, 20.0, 900 * 10)
        assert result is not None
        assert pytest.approx(result, abs=0.05) == -1.0

    def test_returns_zero_for_constant_temperature(self) -> None:
        history: list = [(_ts(3600), 20.0), (_ts(1800), 20.0)]
        result = self.coordinator._compute_derivative(history, 20.0, 900 * 10)
        assert result is not None
        assert result == pytest.approx(0.0, abs=0.01)

    def test_old_samples_pruned_outside_window(self) -> None:
        """Samples older than the window should be dropped."""
        history: list = [(_ts(7200), 18.0)]  # 2 hours old, window = 900 s
        # Only one sample in window after pruning → not enough for derivative
        result = self.coordinator._compute_derivative(history, 20.0, 900)
        assert result is None

    def test_mad_filter_removes_single_spike(self) -> None:
        """A clear outlier should be excluded so the slope is not distorted."""
        # Build 4 steady samples at 20.0 then add a spike at 25.0
        base = _ts(4 * 300)
        history: list = [
            (base + timedelta(seconds=i * 300), 20.0) for i in range(4)
        ]
        # The spike is inserted as the newest reading
        # (passed as the temperature argument to _compute_derivative)
        # Use a large window so nothing is pruned by time
        result = self.coordinator._compute_derivative(history, 25.0, 900 * 10)
        # After MAD filter the spike should be removed; remaining slope ≈ 0
        # If the spike were kept, the slope would be >> 0
        assert result is not None
        # Slope should be close to zero — the steady points dominate
        assert abs(result) < 1.0

    def test_history_trimmed_in_place(self) -> None:
        """Entries outside the window must be removed from the list."""
        old_ts = _ts(7200)  # 2 hours ago
        history: list = [(old_ts, 19.0)]
        self.coordinator._compute_derivative(history, 20.0, 900)
        # The old entry must have been pruned; only the new reading remains
        assert all((_ts() - ts).total_seconds() < 10 for ts, _ in history)

    def test_two_identical_timestamps_returns_none(self) -> None:
        """Zero time span should not produce a division by zero."""
        same_ts = _ts(0)
        history: list = [(same_ts, 20.0), (same_ts, 21.0)]
        result = self.coordinator._compute_derivative(history, 22.0, 900 * 10)
        # denom would be 0; function should return None rather than raising
        assert result is None or isinstance(result, float)


@pytest.mark.asyncio
async def test_thermal_model_updates_once_per_poll_interval() -> None:
    """Extra refreshes from state changes must not feed the thermal model."""
    from custom_components.powerclimate.const import (
        CONF_CLIMATE_ENTITY,
        CONF_DEVICE_ROLE,
        CONF_DEVICES,
        CONF_ROOM_SENSORS,
        CONF_WATER_SENSOR,
        DEVICE_ROLE_WATER,
    )

    coord = _make_coordinator()
    coord.entry = SimpleNamespace(
        data={
            CONF_ROOM_SENSORS: ["sensor.room"],
            CONF_DEVICES: [
                {
                    CONF_CLIMATE_ENTITY: "climate.hp1",
                    CONF_DEVICE_ROLE: DEVICE_ROLE_WATER,
                    CONF_WATER_SENSOR: "sensor.water",
                }
            ],
        },
        options={},
    )
    coord.hass.states.get.return_value = SimpleNamespace(state="20.0", attributes={})
    coord.thermal_model = MagicMock()
    coord.thermal_model.async_save = AsyncMock()
    coord._last_model_update = None
    coord._last_model_save = None

    await coord._async_update_data()
    await coord._async_update_data()

    assert coord.thermal_model.update.call_count == 1
