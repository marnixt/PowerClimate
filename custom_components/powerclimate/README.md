# PowerClimate

Home Assistant custom integration to manage multiple heat-pump climate devices
and coordinate their setpoints using temperature offsets.

## Features

- **Multi-pump orchestration**: Configure the primary water-based heat pump
  and any number of assist pumps. PowerClimate controls HP1 directly while
  supervising assist setpoints whenever the user turns them on.

- **Manual assists**: Assist pumps stay under user HVAC control (HEAT/OFF).
  When they are on, the integration only adjusts their temperature to follow
  the configured offsets; when they are off, PowerClimate does nothing.

- **Per-device offsets**: Each pump exposes lower/upper setpoint offsets.
  These offsets clamp the requested room setpoint and define the "minimal"
  temperature target used when the room is already satisfied.

- **Absolute setpoint guardrails**: All commands are bounded between
  16 °C and 30 °C by default to keep thermostats within sane ranges.

- **Diagnostic sensors**: Built-in sensors expose room/water temperature
  derivatives (°C/hour), a thermal summary, simplified assist behavior, and
  total power consumption.

- **Event-driven reactions**: Subscribes to Home Assistant state changes for all configured heat pumps, so setpoints and stages update immediately when a thermostat changes temperature or HVAC mode.

- **Standard HA services**: No vendor-specific APIs—this integration
  orchestrates existing climate entities via Home Assistant services.

## Quick Start

1. Install the `powerclimate` folder into `custom_components/`.
2. In Home Assistant, go to **Settings → Devices & Services → Add Integration
  → PowerClimate**.
3. Pick the room temperature sensor and provide the lower/upper setpoint
   offsets that define the minimal/run targets.
4. Configure your heat pumps:
  - **Water-based heat pump** (required): Climate entity, power sensor, water
    temperature sensor, offsets for HP1
  - **Assist pumps** (optional): Climate entity, power sensor, offsets per HP,
    and optionally enable automatic on/off control

## Control Algorithm

### Water-based heat pump (Primary Pump)
- PowerClimate owns the HVAC mode: HP1 is forced to HEAT when the virtual
  climate entity is on and turned off otherwise.
- The PowerClimate target temperature is clamped between the lower/upper
  offsets (and the global 16–30 °C limits) before being sent to HP1.
- HP1 water temperature is tracked and exposed via diagnostics

### Assist pumps (HP2, HP3, ...)

#### Manual Control (default)
- By default, the user controls each assist pump's HVAC mode. When an assist 
  is off, PowerClimate leaves it untouched.
- When an assist pump is on, PowerClimate compares the room temperature to
  the requested target:
  - **Minimal mode** (room ≥ target): setpoint = current temp + lower offset.
  - **Setpoint mode** (room < target): setpoint = requested target clamped
    between `current + lower offset` and `current + upper offset`.

#### Automatic ON/OFF Control (optional)
- Enable **"Allow PowerClimate to turn device on and off"** for an assist pump 
  to let PowerClimate automatically manage its HVAC mode based on system needs.
- PowerClimate monitors conditions and uses **5-minute timers** to prevent rapid cycling:
  - **ON conditions** (mutually exclusive with OFF conditions):
    1. **ETA > 60 minutes (default)**: Room will take more than the configured threshold to reach target
    2. **Water ≥ 40°C**: Primary pump water temperature is 40°C or higher
    3. **Stalled below target**: Room derivative ≤ 0 AND room is > 0.5°C below target
  - **OFF conditions** (mutually exclusive with ON conditions):
    1. **ETA < 15 minutes (default)**: Room will reach target in less than the configured threshold
    2. **Stalled at target**: Room derivative ≤ 0 AND room is within 0.5°C of target
  - When any condition is met, its timer increments; the opposite timer resets
  - When neither ON nor OFF conditions are met, both timers reset to zero
  - Action is taken only after a condition remains true for 5 minutes (300 seconds, configurable)
- **Anti-short-cycle (assist ON/OFF control only)**
  - When enabled, PowerClimate will *block* turning an assist pump:
    - **OFF** until it has been ON for at least *Min ON time* (default 20 minutes)
    - **ON** until it has been OFF for at least *Min OFF time* (default 10 minutes)
  - This also applies when you manually toggle an assist pump (the integration will respect the protection window)
- Timer state is **in-memory only** and resets on Home Assistant restart
- All temperatures are clamped between the global min/max before sending
  commands, ensuring thermostats stay in a safe operating window.

**Configuration Ranges:**
- Lower setpoint offset: -5.0 to 0.0 °C
- Upper setpoint offset: 0.0 to 5.0 °C

## Advanced Configuration Options

Expert users can fine-tune PowerClimate behavior via **Options → Advanced options** in the Home Assistant UI. These settings are optional; if not configured, sensible defaults are used.

To access: **Settings → Devices & Services → Integrations → PowerClimate → Options → Advanced options**

| Option | Default | Range | Description |
|--------|---------|-------|-------------|
| Min Setpoint Override | 16.0 °C | 10–25 °C | Absolute minimum temperature sent to any pump |
| Max Setpoint Override | 30.0 °C | 20–35 °C | Absolute maximum temperature sent to any pump |
| Assist Timer Duration | 300 s | 60–900 s | Seconds a condition must remain true before action |
| ON: ETA Threshold | 60 min | 5–600 min | Turn assist ON if ETA exceeds this duration |
| OFF: ETA Threshold | 15 min | 1–120 min | Turn assist OFF if ETA drops below this |
| Anti-short-cycle: Min ON time | 20 min | 0–180 min | Block turning assist OFF until it has been ON for at least this long |
| Anti-short-cycle: Min OFF time | 10 min | 0–180 min | Block turning assist ON until it has been OFF for at least this long |
| Water Temperature Threshold | 40.0 °C | 30–55 °C | Turn assist ON when water reaches this temperature |
| Stall Temperature Delta | 0.5 °C | 0.1–2 °C | Temperature difference for stall detection |

**Notes:**
- Changes take effect immediately (no restart required)
- Existing entries without advanced options use defaults for backwards compatibility
- Timers are in-memory and reset on Home Assistant restart
- Advanced options are stored in `config_entry.options` and merged via `merged_entry_data()`

## Configuration Constants

All control parameters are defined in `const.py` and can be adjusted:

| Constant | Default | Description |
|----------|---------|-------------|
| `DEFAULT_MIN_SETPOINT` | 16.0 | Absolute minimum temperature that will ever be sent to a pump. |
| `DEFAULT_MAX_SETPOINT` | 30.0 | Absolute maximum temperature sent to any pump. |
| `DEFAULT_LOWER_SETPOINT_OFFSET_HP1` | 0.0 | HP1 minimal-mode offset relative to its own sensed temperature. |
| `DEFAULT_UPPER_SETPOINT_OFFSET_HP1` | 1.5 | HP1 ceiling offset relative to its sensed temperature. |
| `DEFAULT_LOWER_SETPOINT_OFFSET_ASSIST` | -4.0 | Assist minimal-mode offset (room satisfied). |
| `DEFAULT_UPPER_SETPOINT_OFFSET_ASSIST` | 4.0 | Assist ceiling offset when chasing the room setpoint. |

## Sensors

PowerClimate provides several diagnostic sensors to monitor system state. Text sensors 
use the `powerclimate_text_*` naming pattern for easy exclusion from recorder.

Sensors are added only for pumps that have a configured `climate_entity_id`.

| Sensor | Entity ID Pattern | Description |
|--------|-------------------|-------------|
| Temperature Derivative | `sensor.powerclimate_derivative_*` | Room temperature change rate (°C/hour) |
| Water Derivative | `sensor.powerclimate_water_derivative_*` | Water temperature change rate (°C/hour) |
| **Thermal Summary** | `sensor.powerclimate_text_thermal_summary_*` | Human-readable system state with all pump temps and ETAs |
| **Assist Summary** | `sensor.powerclimate_text_assist_summary_*` | Room state, trend, and per-pump timer/condition status |
| **HP1 Behavior** | `sensor.powerclimate_text_hp1_behavior_*` | HVAC status, temps, water temperature when available |
| **HP2 Behavior** | `sensor.powerclimate_text_hp2_behavior_*` | HVAC status, temps, assist mode, and timer info |
| **HP3 Behavior** | `sensor.powerclimate_text_hp3_behavior_*` | Same as HP2 when a third pump is configured |
| **HP4 Behavior** | `sensor.powerclimate_text_hp4_behavior_*` | Same as HP2 when a fourth pump is configured |
| **HP5 Behavior** | `sensor.powerclimate_text_hp5_behavior_*` | Same as HP2 when a fifth pump is configured |
| Total Power | `sensor.powerclimate_total_power_*` | Aggregated power consumption from all configured pumps |

**Text Sensor Details:**
- All text sensors (prefixed `powerclimate_text_*`) can be excluded from recorder:
  ```yaml
  recorder:
    exclude:
      entity_globs:
        - sensor.powerclimate_text_*
  ```
- Behavior sensors label each pump as `<first word> (hpX)` to match the Thermal Summary format
- Assist Summary shows:
  - Room state (temp, target, delta, trend, ETA)
  - Per-pump status with timer countdown (e.g., "Water≥40°C ON:3:45/5:00")
  - Condition labels reflect configured thresholds (e.g., ETA>60m / ETA<15m)
  - Anti-short-cycle blocking when applicable (e.g., "Blocked(min_off 420s)")
  - "Manual control" for pumps without automatic ON/OFF enabled

## Heat Pump Tips

General setup guidance (always double-check your device manual):

- Assist pumps (HP2–HP5): enable the manufacturer’s “heat shift” / °C offset if available to stabilize minimal mode, then tune `lower_setpoint_offset` accordingly so assists idle gently when the room is satisfied.
- Water/hybrid pump (HP1): if hybrid, disable gas for space heating and cap CH/flow temperature around 45°C initially for better COP; adjust based on insulation and emitters.

## Next Steps

- ✅ Min/max clamp values and assist timer/thresholds now configurable via Advanced Options
- Use energy sensors or COP data for economic decisions
- Add unit tests for the assist logic and advanced configuration
- Consider adding persistent timer state (currently in-memory only)

## Assets

- **logo.png**: Recommended primary image for the integration (use a square PNG, `256×256`, transparent background). Place this file in the integration folder as `custom_components/powerclimate/logo.png` — HACS and many frontends use a `logo.png` or `logo.svg` as the canonical asset.
- **icon.png**: Legacy/fallback icon. Keep `icon.png` for compatibility with older setups and for any UI or tooling that expects that filename. It is not strictly required if `logo.png`/`logo.svg` exist, but keeping it avoids surprises.
- **logo.svg** (recommended): An SVG is preferred where possible because it scales cleanly and can be recolored. If you have an SVG source, include `logo.svg` alongside `logo.png`.

PowerShell quick commands to create or copy these assets locally and to a Home Assistant install on `Z:`:

```
Copy-Item -Path .\custom_components\powerclimate\icon.png -Destination .\custom_components\powerclimate\logo.png -Force
Copy-Item -Path .\custom_components\powerclimate\logo.png -Destination Z:\custom_components\powerclimate\logo.png -Force
```
