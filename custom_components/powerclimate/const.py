DOMAIN = "powerclimate"
PLATFORMS = ["climate", "sensor"]
COORDINATOR = "coordinator"

DEFAULT_SCAN_INTERVAL = 60  # seconds

CONF_ENTRY_NAME = "entry_name"
DEFAULT_ENTRY_NAME = "PowerClimate"
MANUFACTURER = "MaxT"

# Temperature derivative calculation windows
DERIVATIVE_WINDOW_SECONDS = 900  # 15 minutes for room temperature
DERIVATIVE_WATER_WINDOW_SECONDS = 900  # 15 minutes for water temperature

# Minimum interval between set_temperature/set_hvac_mode calls per device
MIN_SET_CALL_INTERVAL_SECONDS = 20
SERVICE_CALL_TIMEOUT_SECONDS = 5

# Default target temperature for new integrations
DEFAULT_TARGET_TEMPERATURE = 21.0

# ETA threshold met duration in minutes
ETA_THRESHOLD_MET_DURATION_MINUTES = 5.0

# Minimum delta for float comparison (prevents floating point issues)
FLOAT_COMPARISON_EPSILON = 0.01

# Temperature change threshold for detecting setpoint changes
TEMPERATURE_CHANGE_THRESHOLD = 0.01

# Setpoint comparison threshold (0.1°C precision)
SETPOINT_COMPARISON_THRESHOLD = 0.1

# Outlier detection threshold multiplier for derivative calculation
OUTLIER_THRESHOLD_MULTIPLIER = 3.0

# Default MAD threshold when MAD is zero
DEFAULT_MAD_THRESHOLD = 0.5

# Timer minimum value for condition checking
TIMER_MIN_DELTA_SECONDS = 0.0


CONF_DEVICES = "devices"
CONF_ROOM_SENSORS = "room_sensor_entity_ids"
CONF_ROOM_SENSOR_VALUES = "room_sensor_values"
CONF_ROOM_TEMPERATURE_KEY = "room_temperature"
CONF_MIRROR_CLIMATE_ENTITIES = "mirror_climate_entity_ids"
CONF_CLIMATE_ENTITY = "climate_entity_id"
CONF_ENERGY_SENSOR = "energy_sensor_entity_id"
CONF_WATER_SENSOR = "water_sensor_entity_id"
CONF_DEVICE_ID = "id"
CONF_DEVICE_NAME = "name"
CONF_DEVICE_ROLE = "device_role"
CONF_ALLOW_ON_OFF_CONTROL = "allow_on_off_control"

# Device role values
DEVICE_ROLE_WATER = "water"
DEVICE_ROLE_AIR = "air"

# Heat pump operating modes
MODE_BOOST = "boost"
MODE_SETPOINT = "setpoint"
MODE_MINIMAL = "minimal"
MODE_POWER = "power"
MODE_OFF = "off"

# Power mode configuration
# Interval between setpoint adjustments in power mode (prevents oscillation)
DEFAULT_POWER_MODE_ADJUSTMENT_INTERVAL_SECONDS = 90.0
# Deadband as fraction of target power (no adjustment if within this range)
DEFAULT_POWER_MODE_DEADBAND_PERCENT = 0.15
# Setpoint step size per adjustment
DEFAULT_POWER_MODE_STEP_SIZE = 0.3

# Power preset (orchestrator-level) configuration
# House net active power sensor (negative when exporting/surplus).
CONF_HOUSE_POWER_SENSOR = "house_power_sensor_entity_id"
# Keep some headroom to avoid oscillation due to household noise.
DEFAULT_POWER_SURPLUS_RESERVE_W = 300.0
# Update interval for recomputing per-HP budgets from the house power sensor.
DEFAULT_POWER_BUDGET_UPDATE_INTERVAL_SECONDS = 30.0
# Do not allocate tiny budgets that only cause churn.
DEFAULT_POWER_MIN_BUDGET_W = 200.0
# Cap per-device budget so we don't slam a single HP.
DEFAULT_POWER_MAX_BUDGET_PER_DEVICE_W = 1200.0

# Setpoint offset configuration (replaces keep-on threshold)
# Floor = current_temp + lower_offset (lower is typically negative or zero)
# Ceiling = current_temp + upper_offset
CONF_LOWER_SETPOINT_OFFSET = "lower_setpoint_offset"
CONF_UPPER_SETPOINT_OFFSET = "upper_setpoint_offset"

# HP1 (water-based heat pump) defaults
DEFAULT_LOWER_SETPOINT_OFFSET_HP1 = -0.3
DEFAULT_UPPER_SETPOINT_OFFSET_HP1 = 1.5

# Assist heat pumps (HP2, HP3, etc.) defaults
DEFAULT_LOWER_SETPOINT_OFFSET_ASSIST = -4.0
DEFAULT_UPPER_SETPOINT_OFFSET_ASSIST = 4.0

# Absolute floor/ceiling for any heat pump setpoint
DEFAULT_MIN_SETPOINT = 16.0
DEFAULT_MAX_SETPOINT = 30.0

# Expert/Advanced configuration keys (stored in config_entry.options)
CONF_MIN_SETPOINT_OVERRIDE = "min_setpoint_override"
CONF_MAX_SETPOINT_OVERRIDE = "max_setpoint_override"
CONF_ASSIST_TIMER_SECONDS = "assist_timer_seconds"
# Legacy (kept for backwards compatibility; UI now uses minutes)

# Preferred ETA thresholds in minutes
CONF_ASSIST_ON_ETA_THRESHOLD_MINUTES = "assist_on_eta_threshold_minutes"
CONF_ASSIST_OFF_ETA_THRESHOLD_MINUTES = "assist_off_eta_threshold_minutes"

# Anti-short-cycle protection for assist pumps (only applies when
# allow_on_off_control is enabled for an assist device)
CONF_ASSIST_MIN_ON_MINUTES = "assist_min_on_minutes"
CONF_ASSIST_MIN_OFF_MINUTES = "assist_min_off_minutes"
CONF_ASSIST_WATER_TEMP_THRESHOLD = "assist_water_temp_threshold"
CONF_ASSIST_STALL_TEMP_DELTA = "assist_stall_temp_delta"

# Expert defaults (used when options not set)
DEFAULT_ASSIST_TIMER_SECONDS = 300.0

DEFAULT_ASSIST_ON_ETA_THRESHOLD_MINUTES = 60.0
DEFAULT_ASSIST_OFF_ETA_THRESHOLD_MINUTES = 15.0

DEFAULT_ASSIST_MIN_ON_MINUTES = 20.0
DEFAULT_ASSIST_MIN_OFF_MINUTES = 10.0
DEFAULT_ASSIST_WATER_TEMP_THRESHOLD = 40.0
DEFAULT_ASSIST_STALL_TEMP_DELTA = 0.5

# Sensor polling intervals
SENSOR_POLL_INTERVAL_SECONDS = 30  # Thermal summary and HP2/HP3 behavior

SUMMARY_SIGNAL_TEMPLATE = "powerclimate_summary_update_{entry_id}"
