from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_DEVICES,
    CONF_ENERGY_SENSOR,
    CONF_ROOM_SENSOR,
    CONF_WATER_SENSOR,
    DEFAULT_SCAN_INTERVAL,
    DERIVATIVE_WATER_WINDOW_SECONDS,
    DERIVATIVE_WINDOW_SECONDS,
)
from .helpers import merged_entry_data


class OSDataUpdateCoordinator(DataUpdateCoordinator):
    """Coordinator that polls Home Assistant states for device data.

    This coordinator is responsible for:
    - Polling configured sensors at regular intervals (default: 60s)
    - Reading room temp, device states, energy, and water temperature
    - Computing temperature derivatives using linear regression
    - Maintaining temperature history for derivative calculations

    The derivative uses linear regression over configurable time windows:
    - Room: DERIVATIVE_WINDOW_SECONDS (default: 900s / 15 minutes)
    - Water: DERIVATIVE_WATER_WINDOW_SECONDS (default: 600s / 10 min)

    Derivatives are returned in °C/hour units.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        logger,
    ) -> None:
        """Initialize the coordinator.

        Args:
            hass: Home Assistant instance.
            entry: Config entry for this integration instance.
            logger: Logger for debug/error output.
        """
        self.entry = entry
        self._room_temp_history: list[tuple[datetime, float]] = []
        self._device_temp_history: dict[
            str,
            list[tuple[datetime, float]],
        ] = {}
        self._water_temp_history: dict[
            str,
            list[tuple[datetime, float]],
        ] = {}
        super().__init__(
            hass,
            logger,
            name="powerclimate_coordinator",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Home Assistant states.

        Returns:
            Dictionary containing:
            - room_sensor_entity_id: Current room temperature
            - room_derivative: Room temperature change rate (°C/hour)
            - water_derivative: Water temperature change rate (°C/hour)
            - devices: List of device payloads with state and temps
        """
        data: dict[str, Any] = {
            "devices": [],
        }
        entry_data = merged_entry_data(self.entry)

        room_sensor = entry_data.get(CONF_ROOM_SENSOR)

        room_value = self._read_float(room_sensor)
        data[CONF_ROOM_SENSOR] = room_value
        derivative = self._compute_derivative(
            self._room_temp_history,
            room_value,
            DERIVATIVE_WINDOW_SECONDS,
        )
        if derivative is not None:
            derivative = round(derivative, 1)
        data["room_derivative"] = derivative

        devices = entry_data.get(CONF_DEVICES, [])
        hass = self.hass
        water_derivative: float | None = None

        for device in devices:
            climate_id = device.get("climate_entity_id")
            climate_state = hass.states.get(climate_id) if climate_id else None
            energy_id = device.get(CONF_ENERGY_SENSOR)
            water_id = device.get(CONF_WATER_SENSOR)

            device_payload: dict[str, Any] = dict(device)
            if climate_state:
                device_payload["hvac_mode"] = climate_state.state
                device_payload[
                    "current_temperature"
                ] = climate_state.attributes.get("current_temperature")
                device_payload[
                    "target_temperature"
                ] = climate_state.attributes.get("temperature")
                device_history = self._device_temp_history.setdefault(
                    climate_id, []
                )
                temp_derivative = self._compute_derivative(
                    device_history,
                    device_payload["current_temperature"],
                    DERIVATIVE_WINDOW_SECONDS,
                )
                if temp_derivative is not None:
                    temp_derivative = round(temp_derivative, 1)
                device_payload["temperature_derivative"] = temp_derivative

            device_payload["energy"] = self._read_float(energy_id)
            if water_id:
                device_payload["water_temperature"] = self._read_float(
                    water_id
                )
                if water_derivative is None:
                    water_history = self._water_temp_history.setdefault(
                        water_id, []
                    )
                    water_derivative = self._compute_derivative(
                        water_history,
                        device_payload["water_temperature"],
                        DERIVATIVE_WATER_WINDOW_SECONDS,
                    )
                    if water_derivative is not None:
                        water_derivative = round(water_derivative, 1)

            data["devices"].append(device_payload)

        if water_derivative is not None:
            water_derivative = round(water_derivative, 1)
        data["water_derivative"] = water_derivative

        return data

    def _read_float(self, entity_id: str | None) -> float | None:
        """Read a numeric state from an entity.

        Args:
            entity_id: Entity ID to read from.

        Returns:
            Float value or None if unavailable/invalid.
        """
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if not state or state.state in ("unknown", "unavailable"):
            return None
        try:
            return float(state.state)
        except (TypeError, ValueError):
            return None

    def _compute_derivative(
        self,
        history: list[tuple[datetime, float]],
        temperature: float | None,
        window_seconds: int,
    ) -> float | None:
        """Compute temperature derivative using linear regression.

        Uses least-squares linear regression over a sliding time window to
        calculate the rate of temperature change.

        Args:
            history: List of (timestamp, temp) tuples. Modified in-place.
            temperature: Current temperature reading to add to history.
            window_seconds: Size of the sliding window in seconds.

        Returns:
            Derivative in °C/hour, or None if insufficient data.
        """
        if temperature is None:
            return None

        try:
            current = float(temperature)
        except (TypeError, ValueError):
            return None

        now = datetime.now(timezone.utc)
        window = timedelta(seconds=window_seconds)

        # Prune old entries and add new reading
        history[:] = [(ts, temp) for ts, temp in history if now - ts <= window]
        history.append((now, current))

        if len(history) < 2:
            return None

        # Match Home Assistant Derivative helper: use oldest and newest value
        t0, temp0 = history[0]
        t1, temp1 = history[-1]
        dt = (t1 - t0).total_seconds()
        if dt == 0:
            return None

        # Slope in deg/sec, convert to deg/hour
        slope = (temp1 - temp0) / dt
        return slope * 3600.0
