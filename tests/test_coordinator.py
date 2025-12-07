import logging
from datetime import datetime, timedelta, timezone

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powerclimate.const import (
    DERIVATIVE_WINDOW_SECONDS,
    DOMAIN,
)
from custom_components.powerclimate.coordinator import OSDataUpdateCoordinator


@pytest.mark.asyncio
async def test_compute_derivative_uses_oldest_newest(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    coordinator = OSDataUpdateCoordinator(
        hass,
        entry,
        logging.getLogger(__name__),
    )

    history: list[tuple[datetime, float]] = [
        (datetime.now(timezone.utc) - timedelta(minutes=10), 20.0)
    ]

    derivative = coordinator._compute_derivative(  # pylint: disable=protected-access
        history,
        21.0,
        DERIVATIVE_WINDOW_SECONDS,
    )

    expected = ((21.0 - 20.0) / 600.0) * 3600.0
    assert derivative == pytest.approx(expected)


@pytest.mark.asyncio
async def test_compute_derivative_handles_insufficient_data(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    coordinator = OSDataUpdateCoordinator(
        hass,
        entry,
        logging.getLogger(__name__),
    )

    history: list[tuple[datetime, float]] = []

    # None reading should be ignored
    assert (
        coordinator._compute_derivative(  # pylint: disable=protected-access
            history,
            None,
            DERIVATIVE_WINDOW_SECONDS,
        )
        is None
    )

    # First valid reading should not produce a derivative
    assert (
        coordinator._compute_derivative(  # pylint: disable=protected-access
            history,
            20.0,
            DERIVATIVE_WINDOW_SECONDS,
        )
        is None
    )
*** End File