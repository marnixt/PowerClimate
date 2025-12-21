DOMAIN = "powerclimate"
PLATFORMS = ["climate", "sensor"]
COORDINATOR = "coordinator"

DEFAULT_SCAN_INTERVAL = 60  # seconds

CONF_ENTRY_NAME = "entry_name"
DEFAULT_ENTRY_NAME = "PowerClimate"
MANUFACTURER = "MaxT"

DERIVATIVE_WINDOW_SECONDS = 900
DERIVATIVE_WATER_WINDOW_SECONDS = 900

# Minimum interval between set_temperature/set_hvac_mode calls per device
MIN_SET_CALL_INTERVAL_SECONDS = 20
SERVICE_CALL_TIMEOUT_SECONDS = 5


CONF_DEVICES = "devices"
CONF_ROOM_SENSORS = "room_sensor_entity_ids"
CONF_ROOM_SENSOR_VALUES = "room_sensor_values"
CONF_ROOM_TEMPERATURE_KEY = "room_temperature"
CONF_CLIMATE_ENTITY = "climate_entity_id"
CONF_ENERGY_SENSOR = "energy_sensor_entity_id"
CONF_WATER_SENSOR = "water_sensor_entity_id"
CONF_DEVICE_ID = "id"
CONF_DEVICE_NAME = "name"
CONF_COPY_SETPOINT_TO_POWERCLIMATE = "copy_setpoint_to_powerclimate"
CONF_ALLOW_ON_OFF_CONTROL = "allow_on_off_control"

# Setpoint offset configuration (replaces keep-on threshold)
# Floor = current_temp + lower_offset (lower is typically negative or zero)
# Ceiling = current_temp + upper_offset
CONF_LOWER_SETPOINT_OFFSET = "lower_setpoint_offset"
CONF_UPPER_SETPOINT_OFFSET = "upper_setpoint_offset"

# HP1 (water-based heat pump) defaults
DEFAULT_LOWER_SETPOINT_OFFSET_HP1 = 0.0
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
