# PowerClimate

Home Assistant custom integration to manage multiple heat-pump climate devices
and coordinate their setpoints using per-device temperature offsets.

Not affiliated with Home Assistant.

## Features

- **Multi-heatpump orchestration**: One virtual thermostat controls HP1 and coordinates any number of assist heat pumps.
- **Per-device offsets + guardrails**: Lower/upper offsets per device, plus global min/max setpoint limits.
- **Manual assists (default) + optional auto on/off**: You decide when assists run, or let PowerClimate manage assist HVAC mode with timers and anti-short-cycle.
- **Power-aware control (optional)**: `Solar` preset can allocate per-device power budgets from a signed house net power sensor.
- **Diagnostics**: Thermal summary, per-HP behavior, derivatives, total power, and budget diagnostics.
- **Works with standard HA services**: Orchestrates existing `climate.*` entities via Home Assistant.

## Documentation

- Detailed documentation (EN): [custom_components/powerclimate/README.md](custom_components/powerclimate/README.md)
- Gedetailleerde documentatie (NL): [custom_components/powerclimate/README-NL.md](custom_components/powerclimate/README-NL.md)

## Installation

### Install with HACS (recommended)

1. HACS → **Integrations**.
2. Menu (⋮) → **Custom repositories**.
3. Add this repository URL and select category **Integration**.
4. Install **PowerClimate** and restart Home Assistant.

### Manual install

1. Copy `custom_components/powerclimate/` into your Home Assistant `config/custom_components/`.
2. Restart Home Assistant.

## Setup

1. Home Assistant → **Settings → Devices & Services → Add Integration → PowerClimate**.
2. Select one or more room temperature sensors (PowerClimate uses an average of available values).
3. Configure HP1 (water-based heat pump) and any assist heat pumps (HP2/HP3/…).

## Support

- Issues and feature requests: use the GitHub issue tracker linked in the integration manifest.

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
| HP2 Behavior | HVAC status, temps, and PowerClimate mode (off/minimal/setpoint/power/boost) |
| HP3 Behavior | Same as above when a third pump is configured |
| HP4 Behavior | Same logic as HP2 when a fourth pump is configured |
| HP5 Behavior | Same logic as HP2 when a fifth pump is configured |
| Total Power | Aggregated power from all configured pumps |
| Power Budget | Allocated budget totals + per-device budgets (when enabled) |

Derivatives use the slope between the oldest and newest sample within the
window (room: 15 minutes, water: 10 minutes), matching Home Assistant's
Derivative helper behavior.

Behavior sensors label each pump as `<first word> (hpX)` to match the Thermal Summary format.

## Heat Pump Tips

General setup guidance (always double-check your device manual):

- Assist pumps (HP2–HP5): enable the manufacturer’s “heat shift” / °C offset if available to stabilize minimal mode, then tune `lower_setpoint_offset` accordingly so assists idle gently when the room is satisfied.
- Water/hybrid pump (HP1): if hybrid, disable gas for space heating and cap CH/flow temperature around 45°C initially for better COP; adjust based on insulation and emitters.

## Next Steps

- Use Advanced options to tune assist thresholds (ETA in minutes) and anti-short-cycle
- Use energy sensors or COP data for economic decisions
- Add unit tests for the assist logic

## Assets

- **logo.png**: Recommended primary image for the integration (use a square PNG, `256×256`, transparent background). Place this file in the integration folder as `custom_components/powerclimate/logo.png` — HACS and many frontends use a `logo.png` or `logo.svg` as the canonical asset.
- **icon.png**: Legacy/fallback icon. Keep `icon.png` for compatibility with older setups and for any UI or tooling that expects that filename. It is not strictly required if `logo.png`/`logo.svg` exist, but keeping it avoids surprises.
- **logo.svg** (recommended): An SVG is preferred where possible because it scales cleanly and can be recolored. If you have an SVG source, include `logo.svg` alongside `logo.png`.

PowerShell quick command to create a logo from the existing icon:

```
Copy-Item -Path .\custom_components\powerclimate\icon.png -Destination .\custom_components\powerclimate\logo.png -Force
```

