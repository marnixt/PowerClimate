# PowerClimate

[![HACS Integration](https://img.shields.io/badge/HACS-Integration-blue?logo=hacs)](https://github.com/hacs/integration)

**Install via HACS (recommended):**
Home Assistant custom integration to manage multiple heat-pump climate devices
and coordinate their setpoints using temperature offsets.

## Audit Log

- 0.2 — First public version
- 0.3-beta — Improved config flow and optional water heat pump
- 0.4.0-beta — Modularized core logic, assist control, solar power budgets, and formatting utilities
- 0.5-beta — Separated mirror thermostats
- 0.6.0 — Persistent timer state, refactored config flow, cleaned up codebase

## Features

- **Multi-heatpump orchestration**: One virtual thermostat coordinates an optional water-based device and any number of air-based assist heat pumps.
- **Offsets + guardrails**: Lower/upper offsets per device and global min/max setpoints.
- **Assists: manual or automatic ON/OFF**: Optional timers + anti-short-cycle protections.
- **Power-aware `Solar` preset (optional)**: Allocate per-device power budgets from a signed house net power sensor.
- **Diagnostics**: Thermal summary, per-HP behavior, derivatives, total power, and budget diagnostics.
- **Thermostat mirroring**: Mirror setpoint changes only from selected thermostats into PowerClimate; thermostat HVAC on/off is ignored.
- **Standard HA services**: Orchestrates existing `climate.*` entities via Home Assistant.

## Quick Start

### Install

#### HACS (recommended)

1. In Home Assistant, open **HACS → Integrations → Custom repositories**.
2. Add the repository URL and set **Category** to **Integration**.
3. Search for **PowerClimate** and install it.
4. Restart Home Assistant.

#### Manual

1. Install the `powerclimate` folder into `custom_components/`.
2. In Home Assistant, go to **Settings → Devices & Services → Add Integration
  → PowerClimate**.
3. Pick the room temperature sensor and optionally select thermostats to mirror.
4. Configure your heat pumps (the first mirrored thermostat is preselected for the water heat pump):
  - **Water-based heat pump** (optional): Climate entity, optional power sensor, optional water
    temperature sensor, and offsets
  - **Air-based assist pumps** (optional, 0..n): Climate entity, optional power sensor, offsets per device,
    and optionally enable automatic on/off control

## Configuration Flow

The setup flow is role-based: you may configure one optional water-based heat
pump (0 or 1) and zero or more air-based assist heat pumps. Before selecting
devices, you can optionally choose thermostats whose setpoint changes should be
mirrored into PowerClimate. Only numeric temperature changes are mirrored; thermostat HVAC mode changes are ignored. The UI presents a device selection page and then
separate configuration pages per device where you choose device role (`water` or
`air`) and advanced options.

## Control Algorithm

### Water-based heat pump (optional)
- If configured, PowerClimate owns the HVAC mode: the water-based device is forced to HEAT while the virtual
  climate entity is on and explicitly switched to OFF when PowerClimate is turned off.
- The PowerClimate target temperature is clamped between the lower/upper offsets (and the global 16–30 °C limits)
  before being sent to the water-based device.
- Water temperature is tracked and exposed via diagnostics when a water sensor is configured.

### Air-based assist heat pumps (0..n)

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
- Timer state is **persistent** and survives Home Assistant restarts (stored in `.storage/powerclimate_timers_*.json`)
- All temperatures are clamped between the global min/max before sending
  commands, ensuring thermostats stay in a safe operating window.

## Preset Behavior

PowerClimate presets control how heat pumps operate in different scenarios:

| Preset | 💧 Water Heat Pump | 🌬️ Air Heat Pump(s) |
|--------|-------------------|---------------------|
| **none** | Normal operation (HEAT mode, follows setpoint) | Setpoint-tracking if ON, untouched if OFF |
| **boost** | Boost mode (current + upper offset) | Boost mode (current + upper offset) |
| **Away** | Minimal mode (let temp drop to 16°C) | OFF (if allow_on_off enabled), otherwise minimal |
| **Solar** | Power-budgeted setpoint (uses surplus energy) | Power-budgeted setpoint (priority after water HP) |

**Note:** Solar preset requires a configured house net power sensor. Budget allocation prioritizes the water-based device first; any remaining air-device budget rotates across assists to avoid starving the same device every cycle.
Away preset turns off air heat pumps only when `allow_on_off_control` is enabled for that device.
Mirrored thermostat HVAC mode changes are not propagated; only temperature setpoint changes are mirrored.

**Configuration Ranges:**
- Lower setpoint offset: -5.0–0.0 °C
- Upper setpoint offset: 0.0–5.0 °C

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

## Experimental Options

Some features are intentionally marked experimental and live under **Options → Experimental**.

To access: **Settings → Devices & Services → Integrations → PowerClimate → Options → Experimental**

- **House net power sensor (signed)**: Configure a sensor that reports net active power in W (negative = export/surplus). This is required to enable/select the `Solar` preset.

**Notes:**
- Changes take effect immediately (no restart required)
- Existing entries without advanced options use defaults for backwards compatibility
- Timer states are persisted to disk and survive Home Assistant restarts
- Advanced options are stored in `config_entry.options` and merged via `merged_entry_data()`

## Configuration Constants

All control parameters are defined in `const.py` and can be adjusted:

| Constant | Default | Description |
|----------|---------|-------------|
| `DEFAULT_MIN_SETPOINT` | 16.0 | Absolute minimum temperature that will ever be sent to a pump. |
| `DEFAULT_MAX_SETPOINT` | 30.0 | Absolute maximum temperature sent to any pump. |
| `DEFAULT_LOWER_SETPOINT_OFFSET_HP1` | -0.3 | HP1 minimal-mode offset relative to its own sensed temperature. |
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
| **HP2+ Behavior** | `sensor.powerclimate_text_hp*_behavior_*` | HVAC status, temps, and PowerClimate mode for each configured assist pump |
| Total Power | `sensor.powerclimate_total_power_*` | Aggregated power consumption from all configured pumps |
| Power Budget | `sensor.powerclimate_power_budget_*` | Total + per-device budgets (used by `Solar` preset) |

**Text Sensor Details:**
- All text sensors (prefixed `powerclimate_text_*`) can be excluded from recorder:
  ```yaml
  recorder:
    exclude:
      entity_globs:
        - sensor.powerclimate_text_*
  ```
- Behavior sensors label each pump as `<first word> (hpX)` to match the Thermal Summary format
- Behavior sensors are created for every configured pump, not only the first five
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
- ✅ Persistent timer state now survives Home Assistant restarts
- Use energy sensors or COP data for economic decisions
- Add unit tests for the assist logic and advanced configuration
