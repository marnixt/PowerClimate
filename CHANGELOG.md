# Changelog

This file consolidates release notes and highlights useful for HACS and users.

## 0.7.0 — (upcoming)

**Summary**
Adds cooling (air conditioning) support for air-based heat pumps.

**Highlights**
- **Cool HVAC mode**: PowerClimate now exposes `HVACMode.COOL` alongside `OFF` and `HEAT`. Air-based heat pumps that support cooling can be driven in cooling mode.
- **Heating/cooling offset separation**: The per-device setpoint offsets are now split into `lower_setpoint_offset_heating`/`upper_setpoint_offset_heating` and `lower_setpoint_offset_cooling`/`upper_setpoint_offset_cooling`. Existing config entries are read transparently via backward-compatible aliases.
- **Cooling defaults**: Lower cooling offset default is −4 °C, upper cooling offset default is 0 °C.
- **Water HP excluded from cooling**: The water-based heat pump is automatically turned off when PowerClimate is in Cool mode.
- **Preset behaviour in Cool mode**: Boost maximises cooling; Away raises target to max setpoint (effectively disabling cooling); Solar and MPC are heating-only and remain unaffected.
- **Assist control for cooling**: The assist controller and condition checks are mode-aware; ETA, overshoot detection, and stall detection all invert correctly for cooling.

**Breaking Changes**
- None. The renamed config keys fall back to the legacy `lower_setpoint_offset` / `upper_setpoint_offset` keys, so existing installations continue to work without any manual migration.

**Compatibility**
- Target Home Assistant: 2024.1.0+
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
