"""Tests for the diagnostics download."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from homeassistant.helpers.json import JSONEncoder

from custom_components.powerclimate.const import COORDINATOR, DOMAIN
from custom_components.powerclimate.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.powerclimate.models import AssistTimerState


def _entry():
    return SimpleNamespace(
        entry_id="entry-1",
        title="Living",
        version=1,
        data={"room_sensor_entity_ids": ["sensor.room"]},
        options={"maximum_overshoot": 0.5},
    )


def test_diagnostics_without_runtime_data():
    hass = SimpleNamespace(data={})
    result = asyncio.run(async_get_config_entry_diagnostics(hass, _entry()))

    assert result["entry"]["title"] == "Living"
    assert result["entry"]["options"] == {"maximum_overshoot": 0.5}
    assert result["coordinator"] is None
    assert result["climate"] is None


def test_diagnostics_include_runtime_state():
    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.data = {"room_temperature": 20.5, "devices": []}
    coordinator.thermal_model.to_dict.return_value = {"is_converged": False}

    climate = MagicMock()
    climate.entity_id = "climate.living"
    climate.diagnostics.return_value = {
        "mode_state": "heat",
        "assist_timers": {"climate.air": AssistTimerState().__dict__},
    }

    state = SimpleNamespace(state="heat", attributes={"preset_mode": "none"})
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": {COORDINATOR: coordinator, "climate_entity": climate}}},
        states=SimpleNamespace(get=lambda entity_id: state),
    )

    result = asyncio.run(async_get_config_entry_diagnostics(hass, _entry()))

    assert result["coordinator"]["data"]["room_temperature"] == 20.5
    assert result["thermal_model"] == {"is_converged": False}
    assert result["climate"]["state"] == "heat"
    assert result["climate"]["attributes"] == {"preset_mode": "none"}
    assert result["climate"]["mode_state"] == "heat"
    # The download is serialized with Home Assistant's JSON encoder.
    json.dumps(result, cls=JSONEncoder)


def test_climate_entity_diagnostics_serializes_timer_state():
    from custom_components.powerclimate.assist_controller import AssistPumpController
    from custom_components.powerclimate.climate import PowerClimateClimate

    entity = PowerClimateClimate.__new__(PowerClimateClimate)
    entity._mode_state = "heat"
    entity._previous_target = None
    entity._config = MagicMock()
    entity._config.to_dict.return_value = {"device_count": 1}
    entity._assist_controller = AssistPumpController.__new__(AssistPumpController)
    entity._assist_controller._timer_states = {
        "climate.air": AssistTimerState(on_timer_seconds=42.0)
    }

    result = entity.diagnostics()

    assert result["config"] == {"device_count": 1}
    assert result["assist_timers"]["climate.air"]["on_timer_seconds"] == 42.0
    json.dumps(result, cls=JSONEncoder)
