# Datron Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/P3D-Creations/datron-homeassistant.svg)](https://github.com/P3D-Creations/datron-homeassistant/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Home Assistant custom integration for Datron CNC milling machines (M8Cube and
compatible, DATRON NEXT control v3.8x+). Supports two connection types and
ships a Lovelace card that reproduces the DATRON Live Cockpit.

## Connection types

### Datron NEXT (Automation API)
Bearer-token connection to the NEXT REST API (`http://<host>/api/v2`).
Full monitoring plus execution control, program selection, SimPL variables,
and filesystem enumeration. Control features require the Automation API
license tier on the machine; a 403 means either a missing license or a
command invalid in the current machine state.

### Datron Live (Cockpit web UI backend)
Username/password connection to the machine's built-in web UI backend
(`https://<host>/api`, self-signed certificate). The integration logs in,
captures the JWT, and re-authenticates automatically on expiry. No token
handling required.

Live provides: machine status, job progress/elapsed/remaining, compressed air
and vacuum pressures, spray system, status light, feed override, runtime
hours, notifications, open dialog (with its actual buttons), current program,
program preview image, tool in spindle, tools in magazine/warehouse/program,
and an MJPEG camera.

Not available on Live (entities omitted automatically): axis positions,
workpiece data, SimPL program browsing/variables, software version. Program
file listing and remote start require the RemoteLink license.

## Entities

One device per config entry. Highlights:

- `sensor.*_status` — execution state (Idle/Running/Pause/...)
- `sensor.*_job_progress`, `_job_elapsed_time`, `_job_remaining_time`,
  `_estimated_remaining_time` (regression-corrected), `_cycle_history`
- `sensor.*_compressed_air_input_pressure`, `_clamping_device_pressure`,
  `_vacuum_pressure` (bar; HA converts per locale)
- `sensor.*_open_dialog` — caption; attributes carry id, text, severity,
  button labels
- `sensor.*_tool_in_spindle` — attributes include diameter, flute length,
  shoulder (reach), corner radius, flute count, article number
- `binary_sensor.*_machine_running`, `_machine_error` (Error notification,
  Error dialog, or empty coolant tank)
- `button.*_pause_program`, `_resume_program`, `_dialog_button_1..4`
  (labels and actions mirror the machine's open dialog), `_refresh_data`
- `camera.*_machine_camera` — MJPEG stream (Live) or snapshot polling (NEXT)
- `image.*_program_preview_image`, `_tool_in_spindle_image`

## Services

| Service | Description |
|---|---|
| `datron_next.confirm_dialog` | Press a dialog button by label |
| `datron_next.get_tools` | Tool list (magazine/warehouse/program/spindle); response |
| `datron_next.get_notifications` | Notification history; response |
| `datron_next.diagnostics` | User claims + machine licenses; response |
| `datron_next.execute_program_async` / `load_program` | Run/load by SimPL path (NEXT) |
| `datron_next.enumerate_folder_contents` / `get_program_file_info` | Filesystem queries (NEXT) |
| `datron_next.set_variable` / `get_variable` | SimPL variables (NEXT) |
| `datron_next.activate_workpiece` / `execute_remote_link` | NEXT / license-gated |

## Cockpit card

The integration serves and auto-loads a Lovelace card — no resource setup.
Add a card and search for "DATRON Cockpit Card", or use YAML:

```yaml
type: custom:datron-cockpit-card
prefix: datron_m8cube_1804685   # entity slug before the per-entity suffix
title: M8Cube                   # optional
show_camera: true               # optional
show_tools: true                # optional
extra_cameras:                  # optional, cycled one at a time
  - camera.shop_overhead
```

A visual editor covers all options, including a machine picker for
multi-machine installs. The card includes the notification history dropdown,
dialog buttons mirroring the machine, a tool browser (magazine/warehouse/
program tools with search and per-tool detail), and the camera stream.
See [custom_components/datron_next/www/README-cockpit-card.md](custom_components/datron_next/www/README-cockpit-card.md).

## Installation

HACS: add `https://github.com/P3D-Creations/datron-homeassistant` as a custom
repository (Integration), download, restart, then add the integration under
Settings > Devices & Services.

Manual: copy `custom_components/datron_next` into `config/custom_components/`
and restart.

## Polling

| Tier | Interval | Data |
|---|---|---|
| Fast | 4 s | Status, job timing, pressures, spray, status light, notifications, dialog |
| Axis | 10 s (backoff) | Axis positions (NEXT only) |
| Medium | 6 s | Current program, tool in spindle, tool lists (Live caches large lists) |
| Slow | 600 s | Machine info, licenses, program enumeration (NEXT) |

## License

MIT — see [LICENSE](LICENSE).
