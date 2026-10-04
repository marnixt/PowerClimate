"""Internal thermal model for PowerClimate's Thermal MPC preset.

Implements a simplified 1R1C (single resistance, single capacitance)
building thermal model using EWMA (Exponentially Weighted Moving
Average) online learning.

Physical model::

    C × dT_room/dt = Q_emitter − U_building × (T_room − T_outdoor)
    Q_emitter      = UA_emitter × (T_water − T_room)

Parameters learned from HP observations:

    ua_emitter  (W/K): Heat transfer coefficient of the emitter system.
                       Updated when HP is active:
                       UA_obs = Q_hp / (T_water − T_room).

    u_building  (W/K): Building thermal conductance to outside.
                       Updated when HP is active and outdoor temp is
                       available:
                       U_obs = Q_hp / (T_room − T_outdoor).

Usage::

    model = ThermalModel(hass, entry_id)
    await model.async_load()
    # Called once per poll cycle (default 60 s):
    model.update(room_temp, water_temp, hp_power, outdoor_temp)
    # Query recommended setpoints:
    t_supply = model.recommended_supply_temp_heating(target, room, outdoor)
    t_set    = model.recommended_setpoint_cooling(target, room, outdoor)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.storage import Store

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------

# EWMA learning rate.  alpha = 0.05 → converges in ~20 samples (≈20 min).
_ALPHA: float = 0.05

# Minimum active HP power to trigger parameter updates.
_MIN_HP_POWER_W: float = 200.0

# Minimum (T_water − T_room) required to estimate UA_emitter.
_MIN_EMITTER_DELTA_K: float = 2.0

# Minimum (T_room − T_outdoor) required to estimate U_building.
_MIN_BUILDING_DELTA_K: float = 3.0

# Conservative initial UA_emitter.  A high initial value causes the first
# recommendation to be on the warm side, converging down with experience.
_DEFAULT_UA_EMITTER: float = 50.0  # W/K

# Initial building heat loss — typical Dutch semi-detached house.
_DEFAULT_U_BUILDING: float = 200.0  # W/K

# Effective thermal-mass multiplier used in the pull-ahead term:
#   C_eff = U_building × _THERMAL_MASS_FACTOR_S / 3600  [Wh/K]
# 4 h × 3600 s/h corresponds to ~4 h of effective thermal storage.
_THERMAL_MASS_FACTOR_S: float = 4.0 * 3600.0

# Default MPC time horizon (minutes to reach target room temperature).
DEFAULT_HORIZON_MINUTES: float = 30.0

# Minimum seconds between parameter updates (one observation per poll cycle).
MIN_UPDATE_INTERVAL_SECONDS: float = 55.0

# Seconds between periodic storage saves.
SAVE_INTERVAL_SECONDS: float = 600.0

STORAGE_VERSION = 1
STORAGE_KEY_TEMPLATE = "powerclimate_thermal_{entry_id}"


def storage_key(entry_id: str) -> str:
    """Return the Store key used for an entry's thermal model."""
    return STORAGE_KEY_TEMPLATE.format(entry_id=entry_id)


class ThermalModel:
    """Simplified 1R1C building thermal model with EWMA online learning.

    Learns two scalar parameters from observations:

    *   ``ua_emitter`` (W/K) — how effectively the emitter (radiators /
        underfloor heating) transfers heat from water to room.
    *   ``u_building`` (W/K) — how much heat the building loses per
        degree of temperature difference to outside (insulation quality).

    These parameters are used to compute:

    *   A recommended **water supply temperature** for the primary
        water-based heat pump (HP1) in heating mode.
    *   A recommended **AC setpoint** for air-based cooling devices
        (HP2+) in cooling mode.

    Model state is persisted between HA restarts in
    ``.storage/powerclimate_thermal_{entry_id}``.
    """

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialise the thermal model.

        Args:
            hass:     Home Assistant instance.
            entry_id: Config entry ID used to namespace the storage file.
        """
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, storage_key(entry_id)
        )

        # Learned parameters
        self.ua_emitter: float = _DEFAULT_UA_EMITTER
        self.u_building: float = _DEFAULT_U_BUILDING

        # Observation counters (used for convergence check and diagnostics)
        self._ua_emitter_updates: int = 0
        self._u_building_updates: int = 0

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def async_load(self) -> None:
        """Load model state from persistent storage."""
        try:
            data = await self._store.async_load()
            if isinstance(data, dict):
                self.ua_emitter = float(data.get("ua_emitter", _DEFAULT_UA_EMITTER))
                self.u_building = float(data.get("u_building", _DEFAULT_U_BUILDING))
                self._ua_emitter_updates = int(data.get("ua_emitter_updates", 0))
                self._u_building_updates = int(data.get("u_building_updates", 0))
                _LOGGER.debug(
                    "Loaded thermal model: ua_emitter=%.1f W/K (%d updates), "
                    "u_building=%.1f W/K (%d updates)",
                    self.ua_emitter,
                    self._ua_emitter_updates,
                    self.u_building,
                    self._u_building_updates,
                )
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.warning("Failed to load thermal model state: %s", err)

    async def async_save(self) -> None:
        """Save model state to persistent storage."""
        data: dict[str, Any] = {
            "ua_emitter": self.ua_emitter,
            "u_building": self.u_building,
            "ua_emitter_updates": self._ua_emitter_updates,
            "u_building_updates": self._u_building_updates,
        }
        try:
            await self._store.async_save(data)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.warning("Failed to save thermal model state: %s", err)

    # ------------------------------------------------------------------
    # Online parameter learning
    # ------------------------------------------------------------------

    def update(
        self,
        room_temp: float,
        water_temp: float | None,
        hp_power: float | None,
        outdoor_temp: float | None,
        room_derivative_per_hour: float | None = None,  # noqa: ARG002 — reserved
    ) -> None:
        """Update model parameters from a single coordinator-cycle observation.

        Parameters are estimated **only when the HP is actively delivering
        heat** (``hp_power > _MIN_HP_POWER_W``) to avoid corrupting the
        model during standby or cooling operation.

        The learning uses EWMA::

            param_new = α × observation + (1 − α) × param_old

        Args:
            room_temp:                Current room temperature (°C).
            water_temp:               Water supply temperature (°C) as reported
                                      by the HP climate entity.
            hp_power:                 HP output power (W).  May be electrical
                                      input or thermal output — the model
                                      converges to the correct ratio either way.
            outdoor_temp:             Outdoor temperature (°C).  Optional; used
                                      to update ``u_building``.
            room_derivative_per_hour: Room temperature rate of change (°C/h).
                                      Reserved for future thermal-mass correction.
        """
        if hp_power is None or hp_power <= _MIN_HP_POWER_W or water_temp is None:
            return

        # --- Update UA_emitter ---
        emitter_delta = water_temp - room_temp
        if emitter_delta > _MIN_EMITTER_DELTA_K:
            ua_obs = hp_power / emitter_delta
            ua_obs = max(5.0, min(500.0, ua_obs))  # physical bounds
            self.ua_emitter = _ALPHA * ua_obs + (1.0 - _ALPHA) * self.ua_emitter
            self._ua_emitter_updates += 1

        # --- Update U_building ---
        if outdoor_temp is not None:
            building_delta = room_temp - outdoor_temp
            if building_delta > _MIN_BUILDING_DELTA_K:
                # Steady-state approximation: Q_HP ≈ Q_building_loss
                u_obs = hp_power / building_delta
                u_obs = max(10.0, min(1000.0, u_obs))  # physical bounds
                self.u_building = _ALPHA * u_obs + (1.0 - _ALPHA) * self.u_building
                self._u_building_updates += 1

    # ------------------------------------------------------------------
    # Setpoint recommendations
    # ------------------------------------------------------------------

    def recommended_supply_temp_heating(
        self,
        target_room: float,
        current_room: float,
        outdoor_temp: float | None,
        horizon_minutes: float = DEFAULT_HORIZON_MINUTES,
        min_supply: float = 20.0,
        max_supply: float = 55.0,
    ) -> float:
        """Calculate recommended water supply temperature for heating.

        Computes the supply temperature that delivers enough heat to:

        1. Compensate steady-state heat loss to outside.
        2. Warm the room from ``current_room`` to ``target_room`` within
           ``horizon_minutes`` (pull-ahead correction).

        Formula::

            Q_steady   = U_building × (T_target − T_out)
            Q_pulldown = C_eff × (T_target − T_room) / horizon_h
            Q_total    = Q_steady + Q_pulldown
            T_supply   = T_room + Q_total / UA_emitter

        When ``outdoor_temp`` is unavailable, a fallback of 5 °C is used
        so the system still provides a sensible recommendation.

        Args:
            target_room:      Target room temperature (°C).
            current_room:     Current room temperature (°C).
            outdoor_temp:     Outdoor temperature (°C).  Optional.
            horizon_minutes:  MPC time horizon (minutes).  Lower = more
                              aggressive warm-up.
            min_supply:       Minimum allowed supply temperature (°C).
            max_supply:       Maximum allowed supply temperature (°C).

        Returns:
            Recommended water supply temperature (°C), clamped to
            ``[min_supply, max_supply]``.
        """
        # Steady-state heat demand
        t_ref = outdoor_temp if outdoor_temp is not None else 5.0
        q_steady = self.u_building * max(0.0, target_room - t_ref)

        # Pull-ahead correction
        horizon_h = max(horizon_minutes / 60.0, 0.01)
        c_eff_wh_k = self.u_building * _THERMAL_MASS_FACTOR_S / 3600.0
        q_pulldown = c_eff_wh_k * max(0.0, target_room - current_room) / horizon_h

        q_total = q_steady + q_pulldown
        t_supply = current_room + q_total / max(self.ua_emitter, 1.0)

        return max(min_supply, min(t_supply, max_supply))

    def recommended_setpoint_cooling(
        self,
        target_room: float,
        current_room: float,
        outdoor_temp: float | None,  # noqa: ARG002 — reserved for heat-gain model
        horizon_minutes: float = DEFAULT_HORIZON_MINUTES,  # noqa: ARG002 — reserved
        min_setpoint: float = 16.0,
        max_setpoint: float = 30.0,
    ) -> float:
        """Calculate recommended setpoint for air-cooling devices.

        For air-based ACs the setpoint IS the target room temperature.
        When the room is significantly above target, a small pull-down
        offset is applied to make the AC work slightly harder.  The
        offset scales linearly with the temperature excess but is capped
        at 3 °C to avoid overcooling.

        Args:
            target_room:      Target room temperature (°C).
            current_room:     Current room temperature (°C).
            outdoor_temp:     Outdoor temperature (°C).  Reserved for
                              future heat-gain extension.
            horizon_minutes:  MPC time horizon (minutes).  Reserved.
            min_setpoint:     Minimum allowed setpoint (°C).
            max_setpoint:     Maximum allowed setpoint (°C).

        Returns:
            Recommended AC setpoint (°C).
        """
        overshoot = current_room - target_room  # positive when room is too warm
        if overshoot <= 0.5:
            # Room is at or near target — no pull-down needed
            return max(min_setpoint, min(target_room, max_setpoint))

        # Pull-down: gain 0.5 → 2 °C excess gives 1 °C pull-down; cap at 3 °C
        pull_down = min(overshoot * 0.5, 3.0)
        t_set = target_room - pull_down
        return max(min_setpoint, min(t_set, max_setpoint))

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def is_converged(self) -> bool:
        """Return True once the emitter model has enough observations."""
        return self._ua_emitter_updates >= 10

    def to_dict(self) -> dict[str, Any]:
        """Return model state as a dict for coordinator data / sensors."""
        return {
            "ua_emitter": round(self.ua_emitter, 1),
            "u_building": round(self.u_building, 1),
            "ua_emitter_updates": self._ua_emitter_updates,
            "u_building_updates": self._u_building_updates,
            "is_converged": self.is_converged,
        }
