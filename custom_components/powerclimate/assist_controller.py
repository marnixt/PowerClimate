"""Assist pump controller for PowerClimate.

This module manages the state and control logic for assist heat pumps,
including timer tracking, anti-short-cycle protection, and ON/OFF control.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from .assist_conditions import AssistConditionChecker
from .models import AssistTimerState

if TYPE_CHECKING:
    from .config_accessor import ConfigAccessor

_LOGGER = logging.getLogger(__name__)


class AssistPumpController:
    """Controls assist pump behavior.

    This class manages:
    - Timer state for ON/OFF condition tracking
    - Anti-short-cycle protection
    - Condition evaluation and state transitions
    """

    def __init__(self, config: ConfigAccessor) -> None:
        """Initialize the assist pump controller.

        Args:
            config: ConfigAccessor for reading configuration.
        """
        self._config = config
        self._condition_checker = AssistConditionChecker(config)

        # Timer state by entity_id
        self._timer_states: dict[str, AssistTimerState] = {}
        self._last_timer_update: datetime | None = None

    def get_timer_state(self, entity_id: str) -> AssistTimerState:
        """Get or create timer state for an entity.

        Args:
            entity_id: Climate entity ID.

        Returns:
            AssistTimerState for the entity.
        """
        if entity_id not in self._timer_states:
            self._timer_states[entity_id] = AssistTimerState()
        return self._timer_states[entity_id]

    def update_timers(
        self,
        entity_id: str,
        room_temp: float | None,
        target_temp: float | None,
        room_eta_hours: float | None,
        water_temp: float | None,
        room_derivative: float | None,
        is_running: bool,
    ) -> AssistTimerState:
        """Update timer state based on current conditions.

        Args:
            entity_id: Climate entity ID.
            room_temp: Current room temperature.
            target_temp: Target room temperature.
            room_eta_hours: Estimated time to reach target in hours.
            water_temp: Current water temperature.
            room_derivative: Room temperature change rate.
            is_running: Whether the device is currently running.

        Returns:
            Updated AssistTimerState.
        """
        now = datetime.now(timezone.utc)
        state = self.get_timer_state(entity_id)

        # Calculate time delta
        delta_seconds = 0.0
        if self._last_timer_update is not None:
            delta_seconds = (now - self._last_timer_update).total_seconds()
        self._last_timer_update = now

        # Track state transitions
        if state.running_state != is_running:
            state.running_state = is_running
            if is_running:
                state.last_on = now
            else:
                state.last_off = now

        # Clear block reason
        state.block_reason = ""

        # Convert ETA to minutes for condition checking
        room_eta_minutes = (
            room_eta_hours * 60.0 if room_eta_hours is not None else None
        )

        # Check conditions
        on_result = self._condition_checker.check_on_conditions(
            room_temp, target_temp, room_eta_minutes, water_temp, room_derivative
        )
        off_result = self._condition_checker.check_off_conditions(
            room_temp, target_temp, room_eta_minutes, room_derivative
        )

        # Update timers based on conditions (mutually exclusive)
        if on_result.met:
            state.on_timer_seconds += delta_seconds
            state.off_timer_seconds = 0.0
            state.active_condition = on_result.name
        elif off_result.met:
            state.off_timer_seconds += delta_seconds
            state.on_timer_seconds = 0.0
            state.active_condition = off_result.name
        else:
            state.on_timer_seconds = 0.0
            state.off_timer_seconds = 0.0
            state.active_condition = "none"

        return state

    def evaluate_action(
        self,
        entity_id: str,
        is_running: bool,
    ) -> tuple[str | None, str]:
        """Evaluate what action should be taken for an assist pump.

        Args:
            entity_id: Climate entity ID.
            is_running: Whether the device is currently running.

        Returns:
            Tuple of (target_hvac_mode, reason) where target_hvac_mode
            is "heat", "off", or None if no action needed.
        """
        state = self.get_timer_state(entity_id)
        timer_threshold = self._config.assist_timer_seconds
        now = datetime.now(timezone.utc)

        # Clear previous target
        state.target_hvac_mode = None
        state.target_reason = ""

        # Check if ON action should be taken
        if not is_running and state.on_timer_seconds >= timer_threshold:
            state.target_hvac_mode = "heat"
            state.target_reason = state.active_condition

            # Check anti-short-cycle
            if self._is_off_blocked(entity_id, state, now):
                return None, ""

            return "heat", state.active_condition

        # Check if OFF action should be taken
        if is_running and state.off_timer_seconds >= timer_threshold:
            state.target_hvac_mode = "off"
            state.target_reason = state.active_condition

            # Check anti-short-cycle
            if self._is_on_blocked(entity_id, state, now):
                return None, ""

            return "off", state.active_condition

        return None, ""

    def _is_off_blocked(
        self,
        entity_id: str,
        state: AssistTimerState,
        now: datetime,
    ) -> bool:
        """Check if turning ON is blocked by min_off_minutes."""
        min_off_seconds = self._config.assist_min_off_minutes * 60.0

        if state.last_off is not None:
            seconds_since_off = (now - state.last_off).total_seconds()
            if seconds_since_off < min_off_seconds:
                remaining = int(min_off_seconds - seconds_since_off)
                state.block_reason = f"min_off {remaining}s"
                _LOGGER.debug(
                    "Assist ON blocked (anti-short-cycle) for %s: remaining=%ss",
                    entity_id,
                    remaining,
                )
                return True

        return False

    def _is_on_blocked(
        self,
        entity_id: str,
        state: AssistTimerState,
        now: datetime,
    ) -> bool:
        """Check if turning OFF is blocked by min_on_minutes."""
        min_on_seconds = self._config.assist_min_on_minutes * 60.0

        if state.last_on is not None:
            seconds_since_on = (now - state.last_on).total_seconds()
            if seconds_since_on < min_on_seconds:
                remaining = int(min_on_seconds - seconds_since_on)
                state.block_reason = f"min_on {remaining}s"
                _LOGGER.debug(
                    "Assist OFF blocked (anti-short-cycle) for %s: remaining=%ss",
                    entity_id,
                    remaining,
                )
                return True

        return False

    def record_turn_on(self, entity_id: str) -> None:
        """Record that a device was turned on.

        Args:
            entity_id: Climate entity ID.
        """
        state = self.get_timer_state(entity_id)
        state.last_on = datetime.now(timezone.utc)
        state.running_state = True
        _LOGGER.info(
            "Assist ON for %s: condition=%s, timer=%.1fs",
            entity_id,
            state.active_condition,
            state.on_timer_seconds,
        )

    def record_turn_off(self, entity_id: str) -> None:
        """Record that a device was turned off.

        Args:
            entity_id: Climate entity ID.
        """
        state = self.get_timer_state(entity_id)
        state.last_off = datetime.now(timezone.utc)
        state.running_state = False
        _LOGGER.info(
            "Assist OFF for %s: condition=%s, timer=%.1fs",
            entity_id,
            state.active_condition,
            state.off_timer_seconds,
        )

    def reset_timers(self, entity_id: str) -> None:
        """Reset all timers for an entity.

        Args:
            entity_id: Climate entity ID.
        """
        state = self.get_timer_state(entity_id)
        state.on_timer_seconds = 0.0
        state.off_timer_seconds = 0.0
        state.active_condition = "none"

    def force_off(self, entity_id: str) -> None:
        """Force a device to off state (e.g., for Away mode).

        Args:
            entity_id: Climate entity ID.
        """
        state = self.get_timer_state(entity_id)
        state.on_timer_seconds = 0.0
        state.off_timer_seconds = 0.0
        state.active_condition = "none"
        state.last_off = datetime.now(timezone.utc)
        state.running_state = False

    def get_hp_status_info(self, entity_id: str) -> dict[str, Any]:
        """Get status info for summary payload.

        Args:
            entity_id: Climate entity ID.

        Returns:
            Dictionary with timer and condition information.
        """
        state = self.get_timer_state(entity_id)
        return {
            "on_timer_seconds": state.on_timer_seconds,
            "off_timer_seconds": state.off_timer_seconds,
            "active_condition": state.active_condition,
            "blocked_by": state.block_reason,
            "target_hvac_mode": state.target_hvac_mode,
            "target_reason": state.target_reason,
        }
