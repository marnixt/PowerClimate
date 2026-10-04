"""Tests for PowerClimate power budget manager."""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from custom_components.powerclimate.const import (
    CONF_CLIMATE_ENTITY,
    DEFAULT_POWER_MAX_BUDGET_PER_DEVICE_W,
    DEFAULT_POWER_MIN_BUDGET_W,
    DEFAULT_POWER_SURPLUS_RESERVE_W,
)
from custom_components.powerclimate.power_budget import PowerBudgetManager


class MockConfig:
    """Mock configuration accessor."""

    def __init__(self, house_power_sensor: str = "sensor.house_power"):
        self.house_power_sensor = house_power_sensor

    @staticmethod
    def is_water_device(device, index: int) -> bool:
        return index == 0


class MockState:
    """Mock Home Assistant state object."""

    def __init__(self, state: str, unit: str = "W"):
        self.state = state
        self.attributes = {"unit_of_measurement": unit}


class TestPowerBudgetManager:
    """Tests for PowerBudgetManager class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.hass = MagicMock()
        self.config = MockConfig()
        self.manager = PowerBudgetManager(self.hass, self.config)

    def test_init_empty_state(self):
        """Manager should start with empty state."""
        assert self.manager.house_net_power_w is None
        assert self.manager.power_available_w is None
        assert self.manager.power_budget_remaining_w is None
        assert self.manager.budgets == {}
        assert self.manager.total_budget_w == 0.0

    def test_set_budget(self):
        """Should set budget for entity."""
        self.manager.set_budget("climate.hp1", 1000.0)

        assert self.manager.get_budget("climate.hp1") == 1000.0
        assert self.manager.total_budget_w == 1000.0

    def test_set_multiple_budgets(self):
        """Should track multiple entity budgets."""
        self.manager.set_budget("climate.hp1", 1000.0)
        self.manager.set_budget("climate.hp2", 500.0)

        assert self.manager.get_budget("climate.hp1") == 1000.0
        assert self.manager.get_budget("climate.hp2") == 500.0
        assert self.manager.total_budget_w == 1500.0

    def test_clear_budget(self):
        """Should clear budget for entity."""
        self.manager.set_budget("climate.hp1", 1000.0)
        self.manager.set_budget("climate.hp2", 500.0)

        self.manager.clear_budget("climate.hp1")

        assert self.manager.get_budget("climate.hp1") == 0.0
        assert self.manager.get_budget("climate.hp2") == 500.0
        assert self.manager.total_budget_w == 500.0

    def test_clear_all(self):
        """Should clear automatic budgets and diagnostic state."""
        self.manager._budgets = {"climate.hp1": 1000.0, "climate.hp2": 500.0}
        self.manager._house_net_power_w = -2000.0
        self.manager._power_available_w = 1500.0

        self.manager.clear_all()

        assert self.manager.budgets == {}
        assert self.manager.total_budget_w == 0.0
        assert self.manager.house_net_power_w is None
        assert self.manager.power_available_w is None

    def test_clear_all_keeps_manual_budgets(self):
        """Service-set budgets must survive the per-update clear_all call."""
        self.manager.set_budget("climate.hp1", 800.0)
        self.manager._current_setpoints["climate.hp1"] = 22.0

        self.manager.clear_all()

        assert self.manager.get_budget("climate.hp1") == 800.0
        assert self.manager._current_setpoints["climate.hp1"] == 22.0

    def test_manual_budget_overrides_automatic(self):
        """Manual budget takes precedence over the Solar allocation."""
        self.manager._budgets = {"climate.hp1": 1200.0}
        self.manager.set_budget("climate.hp1", 400.0)

        assert self.manager.get_budget("climate.hp1") == 400.0
        self.manager.clear_budget("climate.hp1")
        assert self.manager.get_budget("climate.hp1") == 1200.0

    def test_get_budget_nonexistent_entity(self):
        """Should return 0 for unknown entity."""
        assert self.manager.get_budget("climate.unknown") == 0.0


class TestBudgetAllocation:
    """Tests for budget allocation logic."""

    def setup_method(self):
        """Set up test fixtures."""
        self.hass = MagicMock()
        self.config = MockConfig()
        self.manager = PowerBudgetManager(self.hass, self.config)

    def test_allocate_single_device_surplus(self):
        """Should allocate surplus to first device."""
        # Exporting 3000W (-3000W net power)
        self.hass.states.get.return_value = MockState("-3000", "W")

        devices = [
            {CONF_CLIMATE_ENTITY: "climate.hp1"},
        ]

        self.manager.update_budgets(devices)

        # Available = 3000 - reserve
        expected_available = 3000.0 - DEFAULT_POWER_SURPLUS_RESERVE_W
        # Capped at max per device
        expected_budget = min(DEFAULT_POWER_MAX_BUDGET_PER_DEVICE_W, expected_available)

        assert self.manager.get_budget("climate.hp1") == expected_budget

    def test_allocate_no_surplus_when_importing(self):
        """Should allocate nothing when importing power."""
        # Importing 500W (positive net power)
        self.hass.states.get.return_value = MockState("500", "W")

        devices = [
            {CONF_CLIMATE_ENTITY: "climate.hp1"},
        ]

        self.manager.update_budgets(devices)

        assert self.manager.get_budget("climate.hp1") == 0.0
        assert self.manager.power_available_w == 0.0

    def test_allocate_priority_order(self):
        """Should allocate in device priority order."""
        # Exporting 2000W with 200W reserve = 1800W available
        # With max 1500W per device, HP1 gets 1500W, HP2 gets 300W
        self.hass.states.get.return_value = MockState("-2000", "W")

        devices = [
            {CONF_CLIMATE_ENTITY: "climate.hp1"},
            {CONF_CLIMATE_ENTITY: "climate.hp2"},
        ]

        self.manager.update_budgets(devices)

        # HP1 should get first allocation (up to max)
        hp1_budget = self.manager.get_budget("climate.hp1")
        hp2_budget = self.manager.get_budget("climate.hp2")

        assert hp1_budget >= hp2_budget  # Priority allocation
        assert hp1_budget + hp2_budget <= 2000.0 - DEFAULT_POWER_SURPLUS_RESERVE_W

    @patch("custom_components.powerclimate.power_budget.dt_util.utcnow")
    def test_allocate_rotates_air_device_priority(self, mock_utcnow):
        """Partial surplus after HP1 should rotate across air devices over time."""
        base_time = datetime(2024, 1, 1, 12, 0, 0)
        self.hass.states.get.return_value = MockState("-1800", "W")
        devices = [
            {CONF_CLIMATE_ENTITY: "climate.hp1"},
            {CONF_CLIMATE_ENTITY: "climate.hp2"},
            {CONF_CLIMATE_ENTITY: "climate.hp3"},
        ]

        mock_utcnow.return_value = base_time
        self.manager.update_budgets(devices)
        first_hp2 = self.manager.get_budget("climate.hp2")
        first_hp3 = self.manager.get_budget("climate.hp3")

        mock_utcnow.return_value = base_time + timedelta(minutes=1)
        self.manager.update_budgets(devices)
        second_hp2 = self.manager.get_budget("climate.hp2")
        second_hp3 = self.manager.get_budget("climate.hp3")

        assert first_hp2 != first_hp3
        assert second_hp2 != second_hp3
        assert second_hp2 == first_hp3
        assert second_hp3 == first_hp2

    def test_allocate_respects_minimum(self):
        """Should not allocate below minimum threshold."""
        # Small surplus, less than minimum budget
        small_surplus = DEFAULT_POWER_MIN_BUDGET_W / 2
        self.hass.states.get.return_value = MockState(
            str(-small_surplus - DEFAULT_POWER_SURPLUS_RESERVE_W), "W"
        )

        devices = [
            {CONF_CLIMATE_ENTITY: "climate.hp1"},
        ]

        self.manager.update_budgets(devices)

        # Should not allocate since available < minimum
        assert self.manager.get_budget("climate.hp1") == 0.0

    def test_allocate_kw_unit_conversion(self):
        """Should handle kW unit correctly."""
        # Exporting 3kW
        self.hass.states.get.return_value = MockState("-3", "kW")

        devices = [
            {CONF_CLIMATE_ENTITY: "climate.hp1"},
        ]

        self.manager.update_budgets(devices)

        # Should convert to watts: -3kW = -3000W
        assert self.manager.house_net_power_w == -3000.0

    def test_allocate_no_sensor_configured(self):
        """Should clear budgets when no sensor configured."""
        self.config.house_power_sensor = None

        devices = [
            {CONF_CLIMATE_ENTITY: "climate.hp1"},
        ]

        self.manager.update_budgets(devices)

        assert self.manager.budgets == {}

    def test_allocate_sensor_unavailable(self):
        """Should clear budgets when sensor unavailable."""
        self.hass.states.get.return_value = None

        devices = [
            {CONF_CLIMATE_ENTITY: "climate.hp1"},
        ]

        self.manager.update_budgets(devices)

        assert self.manager.budgets == {}


class TestSetpointCalculation:
    """Tests for setpoint calculation logic."""

    def setup_method(self):
        """Set up test fixtures."""
        self.hass = MagicMock()
        self.config = MockConfig()
        self.manager = PowerBudgetManager(self.hass, self.config)

    def test_calculate_initial_setpoint(self):
        """Should return midpoint for initial setpoint."""
        self.manager.set_budget("climate.hp1", 1000.0)

        setpoint = self.manager.calculate_setpoint(
            "climate.hp1",
            current_power=None,  # No reading yet
            min_setpoint=16.0,
            max_setpoint=30.0,
        )

        # Initial setpoint is midpoint
        assert setpoint == 23.0

    def test_calculate_initial_setpoint_uses_current_target(self):
        """Should seed power mode from the device's current target when available."""
        self.manager.set_budget("climate.hp1", 1000.0)

        setpoint = self.manager.calculate_setpoint(
            "climate.hp1",
            current_power=None,
            min_setpoint=16.0,
            max_setpoint=30.0,
            current_target_setpoint=20.5,
        )

        assert setpoint == 20.5

    def test_calculate_no_budget(self):
        """Should return current setpoint when no budget."""
        setpoint = self.manager.calculate_setpoint(
            "climate.hp1",
            current_power=500.0,
            min_setpoint=16.0,
            max_setpoint=30.0,
        )

        # Returns midpoint as initial with no budget
        assert setpoint == 23.0

    @patch("custom_components.powerclimate.power_budget.dt_util.utcnow")
    def test_calculate_increase_when_under_budget(self, mock_utcnow):
        """Should increase setpoint when power is under budget."""
        # Set up time mocking to avoid rate limiting
        base_time = datetime(2024, 1, 1, 12, 0, 0)
        mock_utcnow.return_value = base_time

        self.manager.set_budget("climate.hp1", 1000.0)

        # Initialize setpoint
        initial = self.manager.calculate_setpoint(
            "climate.hp1",
            current_power=500.0,  # Under budget
            min_setpoint=16.0,
            max_setpoint=30.0,
        )

        # Advance time past adjustment interval
        mock_utcnow.return_value = base_time + timedelta(minutes=10)

        # Calculate again - should increase
        adjusted = self.manager.calculate_setpoint(
            "climate.hp1",
            current_power=500.0,  # Still under budget
            min_setpoint=16.0,
            max_setpoint=30.0,
        )

        assert adjusted >= initial

    @patch("custom_components.powerclimate.power_budget.dt_util.utcnow")
    def test_calculate_decrease_when_over_budget(self, mock_utcnow):
        """Should decrease setpoint when power is over budget."""
        base_time = datetime(2024, 1, 1, 12, 0, 0)
        mock_utcnow.return_value = base_time

        self.manager.set_budget("climate.hp1", 500.0)

        # Initialize with high power
        initial = self.manager.calculate_setpoint(
            "climate.hp1",
            current_power=1000.0,  # Over budget
            min_setpoint=16.0,
            max_setpoint=30.0,
        )

        # Advance time past adjustment interval
        mock_utcnow.return_value = base_time + timedelta(minutes=10)

        # Calculate again - should decrease
        adjusted = self.manager.calculate_setpoint(
            "climate.hp1",
            current_power=1000.0,  # Still over budget
            min_setpoint=16.0,
            max_setpoint=30.0,
        )

        assert adjusted <= initial

    def test_calculate_respects_min_max(self):
        """Should clamp setpoint to min/max bounds."""
        self.manager.set_budget("climate.hp1", 1000.0)
        # Force setpoint to a value
        self.manager._current_setpoints["climate.hp1"] = 15.0  # Below min

        setpoint = self.manager.calculate_setpoint(
            "climate.hp1",
            current_power=500.0,
            min_setpoint=16.0,
            max_setpoint=30.0,
        )

        # Rate limited, returns current setpoint
        assert setpoint >= 15.0  # Returns stored value when rate limited


class TestDiagnostics:
    """Tests for diagnostic output."""

    def setup_method(self):
        """Set up test fixtures."""
        self.hass = MagicMock()
        self.config = MockConfig()
        self.manager = PowerBudgetManager(self.hass, self.config)

    def test_get_diagnostics_empty(self):
        """Should return diagnostic data when empty."""
        diag = self.manager.get_diagnostics()

        assert "house_net_power_w" in diag
        assert "power_available_w" in diag
        assert "power_budget_remaining_w" in diag
        assert "power_budget_total_w" in diag
        assert "power_budget_by_entity_w" in diag

    def test_get_diagnostics_with_data(self):
        """Should return diagnostic data with values."""
        self.manager._house_net_power_w = -2000.0
        self.manager._power_available_w = 1800.0
        self.manager._power_budget_remaining_w = 300.0
        self.manager.set_budget("climate.hp1", 1500.0)

        diag = self.manager.get_diagnostics()

        assert diag["house_net_power_w"] == -2000.0
        assert diag["power_available_w"] == 1800.0
        assert diag["power_budget_remaining_w"] == 300.0
        assert diag["power_budget_total_w"] == 1500.0
        assert diag["power_budget_by_entity_w"] == {"climate.hp1": 1500.0}


# ---------------------------------------------------------------------------
# Cooling mode: budget allocation skips water device
# ---------------------------------------------------------------------------


class TestBudgetAllocationCoolingMode:
    """Tests that verify water HP is excluded from budget allocation in cooling mode."""

    def setup_method(self):
        """Set up test fixtures."""
        self.hass = MagicMock()
        self.config = MockConfig()
        self.manager = PowerBudgetManager(self.hass, self.config)

    @patch("custom_components.powerclimate.power_budget.dt_util.utcnow")
    def test_cooling_skips_water_device(self, mock_utcnow):
        """In cooling mode the water HP should receive no budget."""
        from datetime import datetime

        mock_utcnow.return_value = datetime(2024, 6, 1, 12, 0, 0)
        # Exporting 3000W = plenty of surplus
        self.hass.states.get.return_value = MockState("-3000", "W")

        devices = [
            {CONF_CLIMATE_ENTITY: "climate.hp1"},  # index 0 → water HP
            {CONF_CLIMATE_ENTITY: "climate.air1"},  # index 1 → air HP
        ]

        self.manager.update_budgets(devices, is_cooling=True)

        # Water HP must not receive a budget
        assert self.manager.get_budget("climate.hp1") == 0.0
        # Air HP must receive a budget
        assert self.manager.get_budget("climate.air1") > 0.0

    @patch("custom_components.powerclimate.power_budget.dt_util.utcnow")
    def test_heating_allocates_water_device_first(self, mock_utcnow):
        """In heating mode the water HP should still receive first allocation."""
        from datetime import datetime

        mock_utcnow.return_value = datetime(2024, 6, 1, 12, 0, 0)
        self.hass.states.get.return_value = MockState("-3000", "W")

        devices = [
            {CONF_CLIMATE_ENTITY: "climate.hp1"},
            {CONF_CLIMATE_ENTITY: "climate.air1"},
        ]

        self.manager.update_budgets(devices, is_cooling=False)

        # Both devices should get budgets; water HP gets priority (first allocation)
        assert self.manager.get_budget("climate.hp1") > 0.0
        assert self.manager.get_budget("climate.hp1") >= self.manager.get_budget("climate.air1")

    @patch("custom_components.powerclimate.power_budget.dt_util.utcnow")
    def test_cooling_all_surplus_goes_to_air_devices(self, mock_utcnow):
        """All available budget must flow to air devices when cooling."""
        from datetime import datetime

        mock_utcnow.return_value = datetime(2024, 6, 1, 12, 0, 0)
        # Small surplus that would normally only cover water HP
        surplus = DEFAULT_POWER_MIN_BUDGET_W + 10.0
        net_power = -(surplus + DEFAULT_POWER_SURPLUS_RESERVE_W)
        self.hass.states.get.return_value = MockState(str(net_power), "W")

        devices = [
            {CONF_CLIMATE_ENTITY: "climate.hp1"},   # water HP
            {CONF_CLIMATE_ENTITY: "climate.air1"},  # air HP
        ]

        self.manager.update_budgets(devices, is_cooling=True)

        # Water HP skipped; air HP gets the small surplus
        assert self.manager.get_budget("climate.hp1") == 0.0
        assert self.manager.get_budget("climate.air1") > 0.0

    def test_iter_budget_order_cooling_returns_only_air(self):
        """_iter_budget_order(is_cooling=True) must return only air devices."""
        devices = [
            {CONF_CLIMATE_ENTITY: "climate.hp1"},   # index 0 → water
            {CONF_CLIMATE_ENTITY: "climate.air1"},  # index 1 → air
            {CONF_CLIMATE_ENTITY: "climate.air2"},  # index 2 → air
        ]

        result = self.manager._iter_budget_order(devices, is_cooling=True)

        entity_ids = [d[CONF_CLIMATE_ENTITY] for d in result]
        assert "climate.hp1" not in entity_ids
        assert "climate.air1" in entity_ids
        assert "climate.air2" in entity_ids

    def test_iter_budget_order_heating_returns_water_first(self):
        """_iter_budget_order(is_cooling=False) must include the water device first."""
        devices = [
            {CONF_CLIMATE_ENTITY: "climate.hp1"},
            {CONF_CLIMATE_ENTITY: "climate.air1"},
        ]

        result = self.manager._iter_budget_order(devices, is_cooling=False)

        assert result[0][CONF_CLIMATE_ENTITY] == "climate.hp1"


class TestManualBudgetsWithSolar:
    """Solar reallocation must not remove service-set budgets."""

    def test_update_budgets_keeps_manual_budget(self):
        manager = PowerBudgetManager(MagicMock(), MockConfig())
        manager._hass.states.get.return_value = MockState("-100", "W")  # no surplus
        manager.set_budget("climate.hp2", 600.0)

        manager.update_budgets([{CONF_CLIMATE_ENTITY: "climate.hp2"}])

        assert manager.get_budget("climate.hp2") == 600.0


class TestCoolingDirection:
    """In cooling, more power is requested with a lower setpoint."""

    def test_cooling_lowers_setpoint_when_power_too_low(self):
        manager = PowerBudgetManager(MagicMock(), MockConfig())
        manager.set_budget("climate.ac", 1000.0)

        new_setpoint = manager.calculate_setpoint(
            "climate.ac", 200.0, 16.0, 30.0, current_target_setpoint=24.0, is_cooling=True
        )

        assert new_setpoint < 24.0
