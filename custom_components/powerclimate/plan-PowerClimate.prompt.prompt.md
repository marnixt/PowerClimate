Plan for powerclimate Home Assistant integration

1. Gather integration requirements (Completed)
   - Confirm integration name: `powerclimate`.
   - Integration purpose: configure a list of heat-pump climate devices for heating control and energy-aware staging.
   - Device types: each device can be `Air-to-Water` or `Air-to-Air`.
   - Device-specific sensors:
     - `Air-to-Water`: include an extra water temperature sensor.
     - `Air-to-Air`: use the device's internal temperature sensor.
   - All devices: must have an energy sensor configured.
   - Global sensors: allow configuration of a `room temperature` sensor and a `house energy` sensor.
   - Behavior: enable the first climate device by default; depending on runtime criteria, enable the 2nd or 3rd device to meet heating demand most efficiently.
   - Exposed entity: integration exposes a single `climate` device the user can use to set the heating setpoint; the `climate` uses the configured room temperature sensor as its temperature source.

2. Scaffold custom component (Not started)
   - Create `custom_components/powerclimate` with:
     - `manifest.json` (basic metadata + requirements)
     - `__init__.py` (async setup/teardown)
     - `climate.py` (primary `ClimateEntity` exposing HVAC setpoint and modes)
     - `sensor.py` (energy sensors, water/internal temp sensors, house energy sensor)
     - `coordinator.py` (or integrate coordinator in `__init__.py`) providing `DataUpdateCoordinator` for polling/pushing device state
     - `translations` (for entity names/units)
     - `README.md` with usage and example `configuration.yaml` and config-flow notes

3. Implement core logic (Not started)
   - Implement a small device client (REST or MQTT) configurable per-user; support for polling (DataUpdateCoordinator) and optional push (MQTT/webhook).
   - Implement logic to decide when to enable 2nd/3rd devices based on: current room temperature, setpoint delta, device efficiencies (energy sensor), and `house energy` constraints.
   - Provide per-device config options: `type` (Air-to-Water|Air-to-Air), entity IDs for device energy sensor and internal/water temperature.
   - Ensure all async operations follow Home Assistant integration guidelines.

4. Add Config Flow (optional) (Not started)
   - Implement `config_flow.py` to allow UI-driven configuration of multiple devices and selection of room/house sensors.
   - Provide an `options_flow.py` to tune thresholds and staging criteria.

5. Tests and docs (Not started)
   - Add basic tests for coordinator updates, entity state mapping, and staging logic.
   - Expand `README.md` with configuration examples and troubleshooting.

Notes / Next steps
- User-provided details are recorded above; proceed to scaffold the integration files when ready.
- Ask whether the preferred communication method is `REST` (HTTP) or `MQTT`, and whether UI Config Flow is required now.
