# PowerClimate — Initial Release (v1.0.0)

Release date: 2026-01-01

## Summary
Initial public release of PowerClimate. This integration orchestrates multiple heat pumps (water- and air-based) around a shared hydronic system to provide a single combined climate entity and diagnostic sensors.

## Highlights
- Adds a central `climate` entity representing the combined system.
- Diagnostic `sensor` entities for temperature derivatives, thermal summary, assist behavior, and aggregated power.
- Config flow for easy setup via the Home Assistant UI.
- Services: `powerclimate.set_power_budget` and `powerclimate.clear_power_budget` for per-device power budgeting.

## Compatibility
- Target Home Assistant: 2024.11.0
- No external Python package requirements.

## Where to get help
Report issues at: https://github.com/marnixt/PowerClimate/issues
