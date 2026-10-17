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
- **Diagnostics**: Per-HP mode, derivatives and total power.
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
| **none** | Normal operation (HEAT mode, follows setpoint). If `Allow PowerClimate to turn device on and off` is enabled for the water device, sustained overshoot above `Maximum overshoot` can turn it OFF after the configured timer duration; it turns back ON as soon as there is any demand (room below target) | Setpoint-tracking if ON, untouched if OFF |
| **boost** | Boost mode (current + upper offset) | Boost mode (current + upper offset) |
| **Away** | Minimal mode (let temp drop to 16°C) | OFF (if allow_on_off enabled), otherwise minimal |
| **Main only** | Same as `none` | Only the main heat pump runs, as in `none`; the others are turned OFF (if allow_on_off enabled) and never turned on, otherwise left untouched |
| **Supply advice** | Steers the supply temperature towards the advice of the configured supply advice sensor by moving the room setpoint within the device's heating offsets (see below); falls back to normal setpoint logic without advice | Normal assist logic based on room demand |

The Supply advice preset requires a configured experimental sensor that exposes an advised supply (flow) temperature; see [Advice sources](#advice-sources).
Away preset turns off air heat pumps only when `allow_on_off_control` is enabled for that device.
Main only runs PowerClimate with one heat pump: the water heat pump, or the first air heat pump when there is no water heat pump. With a water heat pump as main, Main only does not cool, because water heat pumps cannot cool.
Mirrored thermostat HVAC mode changes are not propagated; only temperature setpoint changes are mirrored.
When `Allow PowerClimate to turn device on and off` is enabled on the water device, PowerClimate may switch it OFF after a sustained overshoot above `Maximum overshoot`. It turns the water device back ON only when the regular `ON: ETA threshold` condition is met again.

### Supply Advice Control Logic

Many water heat pumps are controlled through a room thermostat: the setpoint of
their climate entity is a **room** setpoint, and the heat pump picks the supply
temperature itself. An advised supply temperature (for example 35 °C) can
therefore not be sent as a setpoint. Instead, PowerClimate steers the room
setpoint so that the **measured** supply temperature follows the advice.

- **Error**: advised supply temperature − measured supply temperature (the
  water temperature sensor of the water device).
- **PI controller**: correction = Kp · error + integral. The water device's
  setpoint becomes *device temperature + correction*.
- **Limits**: the correction stays within the water device's lower/upper
  heating offsets (default −0.3 / +1.5 °C) and the global min/max setpoint.
- **Bumpless start**: entering the preset (or a restart) starts from the
  device's current setpoint, so it does not jump.
- **Anti-windup**: the integral does not grow while the correction is at a
  limit in the direction of the error.
- **Compressor idle**: below the minimum compressor power the integral is
  frozen (the supply temperature then says nothing about the heat delivered);
  the proportional part keeps responding.
- **Overshoot**: when the room is above target + `Maximum overshoot`, the
  correction goes to the lower offset. The water overshoot shutoff still
  applies independently.
- **No advice**: if the advice sensor is `unknown`/`unavailable` (some advice
  sources report this when no heat is needed) or there is no supply reading,
  the normal setpoint logic applies and the controller keeps its state.
- **Smoothed supply**: the controller uses a moving average of the supply
  temperature (about two minutes), so sensor noise does not reach the setpoint.
- **Spikes**: a reading more than 5 K above that average (for example a boiler
  making hot water through the same pipe) holds the last correction until the
  spike is over; a jump that lasts longer than 10 minutes counts as real.
- **Deadband**: the setpoint only moves when it changes by at least 0.2 °C.
- **Assist pumps** keep following room demand; they never receive the advice.
- The controller restarts on every preset or HVAC mode change.

The tuning lives under **Options → Experimental → Supply temperature control**.
The **Supply Correction** sensor shows the correction, with the advice, the
measured supply temperature, the error and the P and I parts as attributes, so
you can graph the controller while tuning.

**Avoid a feedback loop.** If the advice source calculates its advice from the
thermostat's room setpoint, it sees the setpoint PowerClimate itself moves: a
higher setpoint raises the advice, which raises the setpoint further. Point
the advice source's room setpoint at PowerClimate's **Target Temperature** sensor
instead, which always holds the room target you set.

**Other controllers.** If something else acts on the same advice (for example
a compressor sound-level or power limiter driven by the same supply error),
the two corrections add up. Keep PowerClimate the slower of the two (a longer
integral time) and watch the number of compressor starts.

### Advice sources

PowerClimate does not calculate the advice itself; any sensor with an advised
supply temperature in °C works:

- an integration that calculates an advised supply temperature, such as an MPC
  or heat-curve integration for your heat pump;
- a simple **heating curve** as a template sensor. Create it under
  **Settings → Devices & Services → Helpers → Create helper → Template → Template
  sensor**, with unit `°C` and device class *Temperature*. This example gives
  50 °C at −10 °C outside and 30 °C at 15 °C outside, linear in between and
  limited to that range:

  ```jinja
  {{ [[50 - 0.8 * (states('sensor.outdoor_temperature') | float + 10), 50] | min, 30] | max | round(1) }}
  ```

  Set its availability to `{{ has_value('sensor.outdoor_temperature') }}`, so
  the preset falls back to normal setpoint logic when the outdoor sensor is
  missing. Use an outdoor sensor that is not warmed by a running outdoor unit.

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
| Maximum Overshoot | 0.5 °C | 0–5 °C | If room temperature exceeds target by more than this amount, an auto-controllable water device may be turned OFF after the timer duration |

## Experimental Options

Some features are intentionally marked experimental and live under **Options → Experimental**.

To access: **Settings → Devices & Services → Integrations → PowerClimate → Options → Experimental**

- **Supply advice sensor**: Configure a sensor that exposes an advised supply temperature. When set, PowerClimate enables the `Supply advice` preset.
- **Supply temperature control** (Supply advice preset, heating):

| Option | Default | Range | Description |
|--------|---------|-------|-------------|
| Proportional gain | 0.15 | 0.01–1.0 | Setpoint change in °C per °C supply error |
| Integral time | 45 min | 5–240 min | Time in which the integral adds one proportional step; longer is calmer |
| Minimum compressor power | 200 W | 0–2000 W | Below this water heat pump power the integral is frozen |

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

PowerClimate provides several diagnostic sensors to monitor system state. The
climate entity carries the full system state (room, ETA, per-pump status,
assist timers, supply control) as attributes.

Sensors are added only for pumps that have a configured `climate_entity_id`.

| Sensor | Entity ID Pattern | Description |
|--------|-------------------|-------------|
| Temperature Derivative | `sensor.powerclimate_derivative_*` | Room temperature change rate (°C/hour) |
| Water Derivative | `sensor.powerclimate_water_derivative_*` | Water temperature change rate (°C/hour) |
| **HPx Mode** | `sensor.powerclimate_text_hp*_behavior_*` | Mode PowerClimate runs the pump in (`off`, `minimal`, `setpoint`, `boost`, `supply_advice`), with the pump's status as attributes |
| Total Power | `sensor.powerclimate_total_power_*` | Aggregated power consumption from all configured pumps |
| Target Temperature | `sensor.powerclimate_target_temperature_*` | PowerClimate's room target, for integrations that only accept a sensor (not a diagnostic entity) |
| Supply Correction | `sensor.powerclimate_supply_correction_*` | Setpoint correction of the supply-temperature controller (Supply advice preset), with its state as attributes |

The HPx Mode attributes include temperatures, derivatives, ETA, power and, for
assist pumps, the assist condition, timers and what blocks a switch.
A mode sensor is created for every configured pump, not only the first five.

## Heat Pump Tips

General setup guidance (always double-check your device manual):

- Assist pumps (HP2–HP5): enable the manufacturer’s “heat shift” / °C offset if available to stabilize minimal mode, then tune `lower_setpoint_offset` accordingly so assists idle gently when the room is satisfied.
- Water/hybrid pump (HP1): if hybrid, disable gas for space heating and cap CH/flow temperature around 45°C initially for better COP; adjust based on insulation and emitters.

## Next Steps

- ✅ Min/max clamp values and assist timer/thresholds now configurable via Advanced Options
- ✅ Persistent timer state now survives Home Assistant restarts
- Use energy sensors or COP data for economic decisions
- Add unit tests for the assist logic and advanced configuration
