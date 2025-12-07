# PowerClimate

Home Assistant custom integration to manage multiple heat-pump climate devices
and coordinate their setpoints using per-device temperature offsets.

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

- **Per-device copy-to-PowerClimate (optional):** Each heatpump now has an optional checkbox in the config flow (`Copy manual setpoint changes to PowerClimate thermostat`) which, when enabled, forwards manual setpoint changes from that heatpump to the PowerClimate climate entity via `climate.set_temperature` (default: off). This lets a single heatpump act as a co-master for setpoints while keeping the integration's steering logic intact.

## Quick Start

1. Install the `powerclimate` folder into `custom_components/`.
2. In Home Assistant, go to **Settings → Devices & Services → Add Integration
  → PowerClimate**.
3. Pick the room temperature sensor and provide the lower/upper setpoint
   offsets that define the minimal/run targets.
4. Configure your heat pumps:
  - **Water-based heat pump** (required): Climate entity, power sensor, water
    temperature sensor, offsets for HP1
  - **Assist pumps** (optional): Climate entity, power sensor, offsets per HP

## Control Algorithm

### Water-based heat pump (Primary Pump)
- PowerClimate owns the HVAC mode: HP1 is forced to HEAT when the virtual
  climate entity is on and turned off otherwise.
- The PowerClimate target temperature is clamped between the lower/upper
  offsets (and the global 16–30 °C limits) before being sent to HP1.
- HP1 water temperature is tracked and exposed via diagnostics but no longer
  gates assist activation.

### Assist pumps (HP2, HP3, ...)

- The user controls each assist pump's HVAC mode. When an assist is off,
  PowerClimate leaves it untouched.
- When an assist pump is on, PowerClimate compares the room temperature to
  the requested target:
  - **Minimal mode** (room ≥ target): setpoint = current temp + lower offset.
  - **Setpoint mode** (room < target): setpoint = requested target clamped
    between `current + lower offset` and `current + upper offset`.
- All temperatures are clamped between the global min/max before sending
  commands, ensuring thermostats stay in a safe operating window.

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

Sensors are added only for pumps that have a configured `climate_entity_id`.

| Sensor | Description |
|--------|-------------|
| Temperature Derivative | Room temperature change rate (°C/hour) |
| Water Derivative | Water temperature change rate (°C/hour) |
| Thermal Summary | Human-readable system state |
| HP1 Behavior | HVAC status, temps, water temperature when available |
| HP2 Behavior | HVAC status, temps, and assist mode (minimal/setpoint/off) |
| HP3 Behavior | Same as above when a third pump is configured |
| HP4 Behavior | Same logic as HP2 when a fourth pump is configured |
| HP5 Behavior | Same logic as HP2 when a fifth pump is configured |
| Total Power | Aggregated power from all configured pumps |

Derivatives use the slope between the oldest and newest sample within the
window (room: 15 minutes, water: 10 minutes), matching Home Assistant's
Derivative helper behavior.

Behavior sensors label each pump as `<first word> (hpX)` to match the Thermal Summary format.

## Heat Pump Tips

General setup guidance (always double-check your device manual):

- Assist pumps (HP2–HP5): enable the manufacturer’s “heat shift” / °C offset if available to stabilize minimal mode, then tune `lower_setpoint_offset` accordingly so assists idle gently when the room is satisfied.
- Water/hybrid pump (HP1): if hybrid, disable gas for space heating and cap CH/flow temperature around 45°C initially for better COP; adjust based on insulation and emitters.

## Next Steps

- Allow min/max clamp values to be configured from the UI
- Use energy sensors or COP data for economic decisions
- Add unit tests for the assist logic

## Assets

- **logo.png**: Recommended primary image for the integration (use a square PNG, `256×256`, transparent background). Place this file in the integration folder as `custom_components/powerclimate/logo.png` — HACS and many frontends use a `logo.png` or `logo.svg` as the canonical asset.
- **icon.png**: Legacy/fallback icon. Keep `icon.png` for compatibility with older setups and for any UI or tooling that expects that filename. It is not strictly required if `logo.png`/`logo.svg` exist, but keeping it avoids surprises.
- **logo.svg** (recommended): An SVG is preferred where possible because it scales cleanly and can be recolored. If you have an SVG source, include `logo.svg` alongside `logo.png`.

PowerShell quick commands to create or copy these assets locally and to a Home Assistant install on `Z:`:

```
Copy-Item -Path .\custom_components\powerclimate\icon.png -Destination .\custom_components\powerclimate\logo.png -Force
Copy-Item -Path .\custom_components\powerclimate\logo.png -Destination Z:\custom_components\powerclimate\logo.png -Force
```
## Changelog

- Feature: per-device copy-to-PowerClimate option added (see config flow). Implemented on branch `Co-master`.
- **What it does:** When enabled for a heatpump, manual temperature setpoint changes made on that heatpump are forwarded to the PowerClimate climate entity via a Home Assistant service call (`climate.set_temperature`). This allows an individual heatpump to act as a co-master for setpoints without changing the global steering logic.

