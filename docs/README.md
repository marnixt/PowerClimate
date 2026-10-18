# PowerClimate

[![HACS Integration](https://img.shields.io/badge/HACS-Integration-blue?logo=hacs)](https://github.com/hacs/integration)

Home Assistant custom integration that lets one virtual thermostat run several
heat pumps together and coordinates their setpoints with per-device
temperature offsets. Release notes are in the [CHANGELOG](../CHANGELOG.md).

![PowerClimate on the Home Assistant integrations page.](images/integration-page.png)

## Features

- **Multi-heat-pump orchestration**: one virtual thermostat drives an optional water-based heat pump and any number of air-based assist heat pumps.
- **Offsets and limits**: lower/upper offsets per device for heating and cooling, and global minimum/maximum setpoints.
- **Assists: manual or automatic on/off**: optional timers and anti-short-cycle protection.
- **Presets**: `none`, `boost`, `away`, `main only` and `supply advice`.
- **Thermostat mirroring**: setpoint changes on selected thermostats are copied to PowerClimate; their HVAC on/off state is ignored.
- **Diagnostics**: a mode sensor per heat pump, derivatives, total power and a diagnostics download.
- **Standard HA services**: PowerClimate controls existing `climate.*` entities through Home Assistant.

![The PowerClimate thermostat.](images/climate-more-info.png)

## Installation

### HACS (recommended)

1. In Home Assistant, open **HACS → Integrations → Custom repositories**.
2. Add the repository URL and set **Category** to **Integration**.
3. Search for **PowerClimate** and install it.
4. Restart Home Assistant.

Pre-releases (alpha and beta versions) are only offered when you enable them for PowerClimate in HACS.

### Manual

Copy the `custom_components/powerclimate/` folder into your Home Assistant `config/custom_components/` and restart Home Assistant.

## Configuration Flow

1. Go to **Settings → Devices & Services → Add Integration → PowerClimate**.
2. Give the hub a name and pick one or more room temperature sensors; PowerClimate uses the average of the available values.
3. Optionally select thermostats to mirror. Only numeric setpoint changes are mirrored; HVAC mode changes of those thermostats are ignored.
4. Select the heat pumps: one optional water-based heat pump (0 or 1) and zero or more air-based assist heat pumps. The first mirrored thermostat is preselected as water heat pump.

   ![Selecting the water and air heat pumps.](images/config-select-devices.png)

5. Configure each heat pump on its own page:
   - **Water heat pump**: power sensor, water (supply) temperature sensor, heating offsets, and whether PowerClimate may turn it on and off.
   - **Air heat pumps**: power sensor, heating and cooling offsets, and whether PowerClimate may turn it on and off.

   ![Configuring an air heat pump.](images/config-air-device.png)

Offsets are relative to the temperature the heat pump itself measures. The
lower heating offset ranges from −10 to 0 °C and the upper from 0 to 10 °C (the
same for cooling). Set the lower heating offset so that the heat pump almost,
but not completely, stops.

Later changes go through the hub's **Configure** button: **Edit setup** (name,
room sensors, mirrored thermostats and devices), **Advanced options** and
**Experimental**.

![The options menu.](images/options-menu.png)

## Control Algorithm

### HVAC modes

| Mode | Behaviour |
|------|-----------|
| **off** | PowerClimate sends no setpoints. The water heat pump is turned off if it has on/off control enabled; assists are left as they are. |
| **heat** | The water heat pump (if configured) and the air assists heat the room to the target. |
| **cool** | The air assists cool the room to the target. The water heat pump is turned off (if allowed), because it cannot cool. |

### Water-based heat pump (optional)

- PowerClimate sets the water heat pump's setpoint while it is heating: the room target, clamped between *device temperature + lower offset* and *device temperature + upper offset* and the global minimum/maximum setpoints.
- With **Allow PowerClimate to turn device on and off** enabled, PowerClimate also switches it:
  - on as soon as there is any heating demand (room below target), well before the assists;
  - off after a sustained overshoot: when the room stays above target + `Maximum overshoot` for the assist timer duration;
  - off when PowerClimate is turned off or set to cool.
- Without that option PowerClimate never changes its HVAC mode; you keep control.
- The water temperature is tracked when a water sensor is configured. PowerClimate also keeps a moving average of it (about two minutes) and ignores readings more than 5 K above that average for up to 10 minutes; the assist conditions and the supply advice control use this smoothed value. The climate attributes show the measured value as `water_temperature` and the smoothed value as `water_temperature_filtered`, with `water_spike` while a spike is ignored; both are filled whenever the sensor reports, also while PowerClimate is off.

### Air-based assist heat pumps (0..n)

#### Manual control (default)

- You control each assist's HVAC mode. When an assist is off, PowerClimate leaves it untouched.
- When an assist is on, PowerClimate compares the room temperature to the target:
  - **Minimal mode** (room at or above target): setpoint = device temperature + lower offset.
  - **Setpoint mode** (room below target): setpoint = target, clamped between *device temperature + lower offset* and *device temperature + upper offset*.

#### Automatic on/off control (optional)

- Enable **Allow PowerClimate to turn device on and off** for an assist to let PowerClimate manage its HVAC mode.
- PowerClimate checks conditions and uses timers (5 minutes by default) against rapid cycling:
  - **On conditions**:
    1. **ETA above the on-threshold** (60 minutes by default): the room needs longer than that to reach the target.
    2. **Water at or above the water threshold** (40 °C by default): the water heat pump runs hot. This uses the smoothed water temperature, so a short spike (such as a boiler making hot water through the same pipe) does not turn assists on.
    3. **Stalled below target**: room derivative ≤ 0 and the room is more than the stall delta (0.5 °C) below target.
  - **Off conditions**:
    1. **ETA below the off-threshold** (15 minutes by default).
    2. **Stalled at target**: room derivative ≤ 0 and the room is within the stall delta of the target.
  - While a condition holds, its timer runs and the opposite timer resets; when neither holds, both reset.
  - PowerClimate acts only when a condition held for the full timer duration.
- **Anti-short-cycle**: PowerClimate does not turn an assist
  - off until it has been on for the *minimum on time* (20 minutes by default);
  - on until it has been off for the *minimum off time* (10 minutes by default).

  This also applies after you switch an assist by hand.
- Timer states are stored and survive Home Assistant restarts.
- All setpoints are clamped between the global minimum and maximum before they are sent.

## Preset Behavior

| Preset | 💧 Water heat pump | 🌬️ Air heat pump(s) |
|--------|-------------------|---------------------|
| **none** | Normal operation (follows the room target within its offsets) | Setpoint tracking when on; untouched when off, unless on/off control is enabled |
| **boost** | Device temperature + upper offset | Turned on (with on/off control) and set to device temperature + upper offset; in cool mode + lower offset |
| **away** | Minimal mode; the room target drops to the minimum setpoint | Turned off (with on/off control), otherwise minimal; in cool mode the room target rises to the maximum setpoint |
| **main only** | As in `none` | Only the main heat pump runs, as in `none`; the others are turned off (with on/off control) and never turned on, otherwise left untouched |
| **supply advice** | Steers the supply temperature towards the advice of the supply advice sensor by moving the room setpoint within the device's heating offsets (see below); without advice it falls back to normal setpoint logic | Normal assist logic based on room demand |

- **Main only** runs PowerClimate with one heat pump: the water heat pump, or the first air heat pump when there is none. With a water heat pump as main, main only does not cool.
- **Supply advice** appears once a supply advice sensor is configured under **Configure → Experimental**; see [Advice sources](#advice-sources).
- Switching from **away** to `none`, `main only` or `supply advice` restores the previous target.

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

The tuning lives under **Configure → Experimental → Supply temperature control**.
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

## Advanced Options

Fine-tune PowerClimate under **Settings → Devices & Services → PowerClimate → Configure → Advanced options**. All fields are optional; empty fields use the defaults. Changes take effect immediately.

![The advanced options.](images/options-advanced.png)

| Option | Default | Range | Description |
|--------|---------|-------|-------------|
| Minimum temperature | 16.0 °C | 10–25 °C | Absolute minimum setpoint sent to any heat pump |
| Maximum temperature | 30.0 °C | 20–35 °C | Absolute maximum setpoint sent to any heat pump |
| Maximum overshoot | 0.5 °C | 0–5 °C | Room overshoot above target after which a water heat pump with on/off control may be turned off |
| Assist timer duration | 300 s | 60–900 s | How long a condition must hold before PowerClimate acts |
| Turn-on ETA threshold | 60 min | 5–600 min | Turn an assist on when the ETA exceeds this |
| Turn-off ETA threshold | 15 min | 1–120 min | Turn an assist off when the ETA drops below this |
| Minimum ON time | 20 min | 0–180 min | Anti-short-cycle: keep an assist on at least this long |
| Minimum OFF time | 10 min | 0–180 min | Anti-short-cycle: keep an assist off at least this long |
| Water temperature threshold | 40 °C | 30–55 °C | Turn an assist on when the water reaches this temperature |
| Stall temperature difference | 0.5 °C | 0.1–2 °C | Temperature difference for stall detection |

The minimum must be below the maximum, and the off-threshold below the on-threshold.

## Experimental Options

Under **Configure → Experimental**:

- **Supply advice sensor**: a sensor with an advised supply temperature. When set, the `supply advice` preset is available.
- **Supply temperature control** (supply advice preset, heating):

| Option | Default | Range | Description |
|--------|---------|-------|-------------|
| Proportional gain | 0.15 | 0.01–1.0 | Setpoint change in °C per °C supply error |
| Integral time | 45 min | 5–240 min | Time in which the integral adds one proportional step; longer is calmer |
| Minimum compressor power | 200 W | 0–2000 W | Below this water heat pump power the integral is frozen |

## Device Offset Defaults

New devices start with these offsets (defined in `const.py`):

| Constant | Default | Description |
|----------|---------|-------------|
| `DEFAULT_LOWER_SETPOINT_OFFSET_HP1` | -0.3 | Water heat pump: minimal-mode offset. |
| `DEFAULT_UPPER_SETPOINT_OFFSET_HP1` | 1.5 | Water heat pump: ceiling offset. |
| `DEFAULT_LOWER_SETPOINT_OFFSET_ASSIST` | -4.0 | Air heat pump, heating: minimal-mode offset (room satisfied). |
| `DEFAULT_UPPER_SETPOINT_OFFSET_ASSIST` | 4.0 | Air heat pump, heating: ceiling offset when chasing the room target. |
| `DEFAULT_LOWER_SETPOINT_OFFSET_COOLING` | -4.0 | Air heat pump, cooling: most aggressive cooling. |
| `DEFAULT_UPPER_SETPOINT_OFFSET_COOLING` | 0.0 | Air heat pump, cooling: least cooling (minimal). |

## Sensors

Each hub is a device. Entity IDs follow the device name, for example
`sensor.powerclimate_temperature_derivative`. The climate entity carries the
full system state (room, ETA, per-pump status, assist timers, supply control)
as attributes.

| Entity | Description |
|--------|-------------|
| **HPx Mode** | Per heat pump: the mode PowerClimate runs it in (`off`, `minimal`, `setpoint`, `boost`, `supply_advice`), with its status as attributes: temperatures, derivatives, ETA, power and, for assists, the active condition, timers and what blocks a switch |
| Temperature Derivative | Room temperature change (°C/h) |
| Water Derivative | Supply water temperature change (°C/h) |
| Total Power | Sum of the configured power sensors |
| Target Temperature | PowerClimate's room target, for integrations that only accept a sensor (not a diagnostic entity) |
| Supply Correction | Setpoint correction of the supply-temperature control, with its state as attributes |

![The entities of a PowerClimate hub.](images/device-entities.png)

A mode sensor is created for every configured heat pump. Derivatives use the
slope between the oldest and newest sample within a 15-minute window, like
Home Assistant's Derivative helper.

**Download diagnostics** on the hub's device page includes the configuration,
the effective settings, the coordinator data, the climate state and the assist
timers.

## Heat Pump Tips

General setup guidance (always check your device manual):

- Air heat pumps: enable the manufacturer's "heat shift" / °C offset if available to stabilize minimal mode, then tune the lower offset so assists idle gently when the room is satisfied.
- Water/hybrid heat pump: if hybrid, disable gas for space heating and cap the flow temperature around 45 °C initially for a better COP; adjust for your insulation and emitters.
