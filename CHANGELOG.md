# Changelog

This file consolidates release notes and highlights useful for HACS and users.

## 0.8.0 — 2026-10-04

**Summary**
Dutch translation, diagnostics download, translated entity names and an options flow fix.

**Highlights**
- **Dutch translation** of the config flow, options and entity names.
- **Diagnostics download**: "Download diagnostics" now includes the configuration, effective settings, coordinator data, thermal model, climate state and assist timers.
- **Translated entity names**: entities use Home Assistant's entity naming, so names follow device renames and can be translated. Existing entity IDs do not change.

**Fixes**
- Editing an existing PowerClimate entry ("Configure" → "Edit setup") no longer fails with "Unknown error occurred".
- A non-numeric heat pump temperature no longer breaks the ETA in the heat pump status.

**Internal**
- Device commands, mode target calculation and summary building moved out of the climate entity into separately tested modules; `sensor.py` is split into a `sensors` package.
- Config and options flows are tested end to end.

**Compatibility**
- Target Home Assistant: 2024.11.0+

## 0.7.0 — 2026-10-04

**Summary**
Adds cooling (air conditioning) support for air-based heat pumps.

**Highlights**
- **Cool HVAC mode**: PowerClimate now exposes `HVACMode.COOL` alongside `OFF` and `HEAT`. Air-based heat pumps that support cooling can be driven in cooling mode.
- **Heating/cooling offset separation**: The per-device setpoint offsets are now split into `lower_setpoint_offset_heating`/`upper_setpoint_offset_heating` and `lower_setpoint_offset_cooling`/`upper_setpoint_offset_cooling`.
- **Cooling defaults**: Lower cooling offset default is −4 °C, upper cooling offset default is 0 °C.
- **Water HP excluded from cooling**: The water-based heat pump is automatically turned off when PowerClimate is in Cool mode.
- **Preset behaviour in Cool mode**: Boost maximises cooling; Away raises target to max setpoint (effectively disabling cooling); Solar and MPC are heating-only and remain unaffected.
- **Assist control for cooling**: The assist controller and condition checks are mode-aware; ETA, overshoot detection, and stall detection all invert correctly for cooling.

**Fixes**
- Saving the Advanced options no longer fails; the minimum/maximum setpoint and ON/OFF ETA thresholds are now validated.
- `set_power_budget` now takes effect: service budgets are kept separate from Solar budgets and are applied immediately. Invalid targets raise an error instead of being silently ignored, and negative budgets are rejected.
- With multiple assist heat pumps, every pump now runs its own ON/OFF timer (previously only the first one switched automatically).
- HVAC modes and setpoints are compared with the device's actual state, so manual changes on a device are corrected and failed service calls are retried.
- Mirror thermostat setpoint changes are no longer dropped while a refresh is pending.
- The thermal model learns once per poll interval instead of on every heat pump state change.
- Air-only setups: the first air heat pump now shows assist information instead of being treated as the water heat pump.
- Total Power sensor reports watts (kW sources are converted) with power device and state classes.
- Power mode steers in the right direction while cooling (a lower setpoint draws more power).
- Per-device power readings in kW are converted to W for power mode and the thermal model.
- Assist pumps are only recorded as switched on/off when the mode change succeeded.
- When a heat pump reports no temperature, its current setpoint is kept instead of dropping to the minimum.
- Experimental sensors can be cleared again in the options.
- Large diagnostic attributes of the climate entity are excluded from the recorder; the broken entity picture was removed.
- Timer and thermal model state now use Home Assistant's storage helper, are saved on unload and are removed when the entry is deleted.

**Breaking Changes**
- The legacy `lower_setpoint_offset` / `upper_setpoint_offset` keys and devices without a role are no longer read; reconfigure the devices if they predate the heating/cooling split.
- Assist timer and thermal model state move to new storage files and start fresh.

**Compatibility**
- Target Home Assistant: 2024.11.0+
- No external Python package requirements.

---

## 0.6.0 — 2026-02-01

**Summary**
Major refactoring release with improved code organization, persistent timer state, and better maintainability.

**Highlights**
- **Persistent timer state**: Assist pump timer states now survive Home Assistant restarts (stored in `.storage/powerclimate_timers_*.json`).
- **Refactored config flow**: ConfigFlow and OptionsFlow now share step handlers, reducing code duplication by ~50%.
- **Cleaned up codebase**: Removed unused `device_config.py`, simplified `models.py`, consolidated duplicate utility functions.
- **HACS metadata**: Added `homeassistant` minimum version requirement to `hacs.json`.

**Breaking Changes**
- None. This release is fully backward compatible.

**Compatibility**
- Target Home Assistant: 2024.1.0+
- No external Python package requirements.

---

## 0.5.2 — 2026-01-25

**Fixes**
- Minor bug fixes and stability improvements.

---

## 0.5.1 — 2026-01-20

**Fixes**
- Ensure HACS installs from the default branch (no release zip required).
- Align release metadata with `hacs.json` to prevent missing manifest errors.

---

## 0.5.0 — 2026-01-15

**Summary**
Initial public release of PowerClimate. This integration orchestrates multiple heat pumps (water- and air-based) around a shared hydronic system to provide a single combined climate entity and diagnostic sensors.

**Highlights**
- Adds a central `climate` entity representing the combined system.
- Diagnostic `sensor` entities for temperature derivatives, thermal summary, assist behavior, and aggregated power.
- Config flow for easy setup via the Home Assistant UI.
- Services: `powerclimate.set_power_budget` and `powerclimate.clear_power_budget` for per-device power budgeting.
- **Thermostat mirroring:** Select thermostats whose setpoint changes will be mirrored into PowerClimate.

**Compatibility**
- Target Home Assistant: 2024.1.0+
- No external Python package requirements.

---

For full details, see GitHub Releases and the commit history.
