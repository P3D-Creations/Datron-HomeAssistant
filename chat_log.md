# Chat Log — Datron NEXT Home Assistant Integration

## Session 1 — 2026-03-14

### Initial Setup & Requirements Gathering

**Goal:** Create a Home Assistant custom integration for Datron M8Cube CNC machine with DATRON NEXT v3.8x control.

**Decisions Made:**
- Use API V2 for all endpoints
- Three-tier polling strategy: Fast (10s), Medium (60s), Slow (1hr)
- Initial implementation covers critical endpoints only (machine status, job info, sensors, notifications, workpiece image)
- Nice-to-have features (camera, tool warehouse, preview image) deferred to later
- Excluded: Tool Assist, Cartridge/dispensing features
- Bearer token used for auth; expiration behavior TBD

**Artifacts Created:**
- Repository initialized with git
- `.gitignore`, `README.md`, `LICENSE`, `project_notes.md`, `chat_log.md`
- `custom_components/datron_next/` — Full HA integration framework:
  - `manifest.json` — Integration metadata
  - `const.py` — Constants and domain config
  - `api.py` — API client with all endpoint methods
  - `coordinator.py` — Three data update coordinators (fast/medium/slow)
  - `config_flow.py` — UI-based configuration flow
  - `__init__.py` — Integration setup and teardown
  - `sensor.py` — Sensor entities (status, job, axes, pressures, overrides, runtime, notifications)
  - `binary_sensor.py` — Binary sensors (machine running, air/vacuum/tank status)
  - `button.py` — Control buttons (start/pause/stop — prepared for Automation API)
  - `image.py` — Workpiece and preview image entities
  - `strings.json` & `translations/en.json` — UI strings

**API Endpoints Mapped:**
- 6 Machine endpoints, 7 MachineComponents endpoints, 4 Runtime endpoints
- 11 Tool endpoints, 2 Workpiece endpoints, 1 Camera, 4 Image, 1 Dialog, 2 User

**Open Questions:**
- Does the bearer token expire? Need to test and potentially implement refresh logic.
- Automation API tier availability — need to inquire with Datron about upgrade.
