"""Data models for PowerClimate.

This module contains dataclasses used throughout the integration.
Note: Some classes are kept for potential future use even if not currently imported.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class AssistTimerState:
    """Timer state for assist pump control.

    This class tracks the timer state for automatic ON/OFF control of assist pumps.
    It is persisted to disk to survive Home Assistant restarts.

    Attributes:
        on_timer_seconds: Accumulated time (seconds) that ON conditions have been met.
        off_timer_seconds: Accumulated time (seconds) that OFF conditions have been met.
        active_condition: Name of the currently active condition (e.g., "eta_high").
        running_state: Whether the pump is currently running.
        last_on: Timestamp when the pump was last turned ON.
        last_off: Timestamp when the pump was last turned OFF.
        block_reason: Reason if action is blocked (e.g., "min_off 420s").
        target_hvac_mode: Desired HVAC mode if action should be taken ("heat" or "off").
        target_reason: Reason for the target mode.
    """
    on_timer_seconds: float = 0.0
    off_timer_seconds: float = 0.0
    active_condition: str = "none"
    running_state: bool = False
    last_on: datetime | None = None
    last_off: datetime | None = None
    block_reason: str = ""
    target_hvac_mode: str | None = None
    target_reason: str = ""


    @classmethod
    def no_condition(cls) -> AssistConditionResult:
        return cls(condition_met=False, condition_name="")
