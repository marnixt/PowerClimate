"""Pytest configuration and shared fixtures for PowerClimate tests."""
import pytest
from unittest.mock import MagicMock, AsyncMock
from pathlib import Path


@pytest.fixture
def hass():
    """Create a mock Home Assistant instance."""
    mock_hass = MagicMock()
    mock_hass.config.path = MagicMock(side_effect=lambda *args: str(Path("/config").joinpath(*args)))
    mock_hass.states.get = MagicMock(return_value=None)
    mock_hass.async_add_executor_job = AsyncMock()
    return mock_hass


@pytest.fixture
def mock_config():
    """Create a mock configuration accessor."""
    config = MagicMock()
    config.assist_on_eta_threshold_minutes = 60.0
    config.assist_off_eta_threshold_minutes = 15.0
    config.assist_water_temp_threshold = 35.0
    config.assist_stall_temp_delta = 0.5
    config.assist_min_on_seconds = 300
    config.assist_min_off_seconds = 300
    config.house_power_sensor = None
    return config
