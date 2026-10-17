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

# Minimum delta for float comparison (prevents floating point issues)
FLOAT_COMPARISON_EPSILON = 0.01

# Temperature change threshold for detecting setpoint changes
TEMPERATURE_CHANGE_THRESHOLD = 0.01

# Setpoint comparison threshold (0.1°C precision)
SETPOINT_COMPARISON_THRESHOLD = 0.1


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
MODE_SUPPLY_ADVICE = "supply_advice"
MODE_OFF = "off"

# Preset modes of the climate entity
PRESET_NONE = "none"
PRESET_BOOST = "boost"
PRESET_AWAY = "away"
PRESET_MAIN_ONLY = "main_only"
PRESET_SUPPLY_ADVICE = "supply_advice"

# Sensor with an advised supply temperature from any source (heating curve,
# MPC, ...); enables the supply advice preset.
CONF_SUPPLY_ADVICE_SENSOR = "supply_advice_sensor_entity_id"

# Supply-temperature control (supply advice preset, water heat pump, heating).
# The water heat pump's setpoint is a room setpoint; a PI controller moves it
# within the device's heating offsets until the measured supply temperature
# matches the advised one.
CONF_SUPPLY_PI_KP = "supply_pi_kp"  # °C setpoint per °C supply error
CONF_SUPPLY_PI_TI_MINUTES = "supply_pi_ti_minutes"
# Below this water heat pump power the compressor is considered idle and the
# integral is frozen: the supply temperature then says nothing about output.
CONF_SUPPLY_PI_MIN_POWER_W = "supply_pi_min_power_w"
# Moving average of the measured supply temperature (time constant).
SUPPLY_FILTER_TAU_SECONDS = 120.0
# A reading this far above the average is a spike (e.g. a boiler making hot
# water through the same pipe); the controller holds its output meanwhile.
SUPPLY_SPIKE_KELVIN = 5.0
# A spike lasting longer than this is accepted as a real change.
SUPPLY_SPIKE_MAX_SECONDS = 600.0
# Only move the water heat pump's setpoint when it changes at least this much,
# so supply noise does not send a new setpoint every few seconds.
SUPPLY_SETPOINT_DEADBAND = 0.2

# Setpoint offset configuration
# Floor = current_temp + lower_offset (lower is typically negative or zero)
# Ceiling = current_temp + upper_offset

# Heating-specific offset keys
CONF_LOWER_SETPOINT_OFFSET_HEATING = "lower_setpoint_offset_heating"
CONF_UPPER_SETPOINT_OFFSET_HEATING = "upper_setpoint_offset_heating"

# Cooling-specific offset keys (air devices only)
CONF_LOWER_SETPOINT_OFFSET_COOLING = "lower_setpoint_offset_cooling"
CONF_UPPER_SETPOINT_OFFSET_COOLING = "upper_setpoint_offset_cooling"

# HP1 (water-based heat pump) heating defaults
DEFAULT_LOWER_SETPOINT_OFFSET_HP1 = -0.3
DEFAULT_UPPER_SETPOINT_OFFSET_HP1 = 1.5

# Assist heat pumps (HP2, HP3, etc.) heating defaults
DEFAULT_LOWER_SETPOINT_OFFSET_ASSIST = -4.0
DEFAULT_UPPER_SETPOINT_OFFSET_ASSIST = 4.0

# Assist heat pumps (HP2, HP3, etc.) cooling defaults
# Floor = current_temp - 4 (aggressive cooling)
# Ceiling = current_temp + 0 (do not cool below current temp on startup)
DEFAULT_LOWER_SETPOINT_OFFSET_COOLING = -4.0
DEFAULT_UPPER_SETPOINT_OFFSET_COOLING = 0.0

# Advanced options (stored in config_entry.options); defaults and ranges are
# in number_options.py.
# Absolute floor/ceiling for any heat pump setpoint
CONF_MIN_SETPOINT_OVERRIDE = "min_setpoint_override"
CONF_MAX_SETPOINT_OVERRIDE = "max_setpoint_override"
CONF_ASSIST_TIMER_SECONDS = "assist_timer_seconds"

# Preferred ETA thresholds in minutes
CONF_ASSIST_ON_ETA_THRESHOLD_MINUTES = "assist_on_eta_threshold_minutes"
CONF_ASSIST_OFF_ETA_THRESHOLD_MINUTES = "assist_off_eta_threshold_minutes"

# Anti-short-cycle protection for assist pumps (only applies when
# allow_on_off_control is enabled for an assist device)
CONF_ASSIST_MIN_ON_MINUTES = "assist_min_on_minutes"
CONF_ASSIST_MIN_OFF_MINUTES = "assist_min_off_minutes"
CONF_ASSIST_WATER_TEMP_THRESHOLD = "assist_water_temp_threshold"
CONF_ASSIST_STALL_TEMP_DELTA = "assist_stall_temp_delta"
CONF_MAXIMUM_OVERSHOOT = "maximum_overshoot"

SUMMARY_SIGNAL_TEMPLATE = "powerclimate_summary_update_{entry_id}"
