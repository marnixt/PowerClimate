# Changelog

This file consolidates release notes and highlights useful for HACS and users.

## 0.5.1 — 2026-01-20

**Fixes**
- Ensure HACS installs from the default branch (no release zip required).
- Align release metadata with `hacs.json` to prevent missing manifest errors.

---

## v1.0.0 — 2026-01-01

**Summary**
Initial public release of PowerClimate. This integration orchestrates multiple heat pumps (water- and air-based) around a shared hydronic system to provide a single combined climate entity and diagnostic sensors.

**Highlights**
- Adds a central `climate` entity representing the combined system.
- Diagnostic `sensor` entities for temperature derivatives, thermal summary, assist behavior, and aggregated power.
- Config flow for easy setup via the Home Assistant UI.
- Services: `powerclimate.set_power_budget` and `powerclimate.clear_power_budget` for per-device power budgeting.

**Compatibility**
- Target Home Assistant: 2024.11.0
- No external Python package requirements.

---

## 0.5.0 (`0.5-beta` release notes)

**Highlights**
- **Thermostat mirroring:** Select thermostats whose setpoint changes will be mirrored into PowerClimate, keeping PowerClimate synced with manual changes.
- **Improved configuration flow:** The setup and options flow allow selecting thermostats to mirror, with the first mirrored thermostat preselected for the water heat pump if desired.
- **Refactored device logic:** Internal logic for device configuration and setpoint mirroring has been streamlined, removing legacy options and simplifying the codebase.
- **Updated documentation:** English and Dutch documentation updated to reflect new mirroring feature and improved setup instructions.

**Other changes**
- Minor bug fixes and code cleanups.
- Updated translation strings for improved clarity.

---

For full details, see GitHub Releases and the commit history.
