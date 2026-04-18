# Datron NEXT Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/P3D-Creations/datron-homeassistant.svg)](https://github.com/P3D-Creations/datron-homeassistant/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A custom Home Assistant integration for monitoring and controlling Datron CNC milling machines via the DATRON NEXT REST API.

## Overview

This integration connects Home Assistant to a Datron M8Cube (or compatible) CNC milling machine running DATRON NEXT control software (v3.8x+). It uses the machine's REST API to provide real-time monitoring and control capabilities.

## Features

### Monitoring (Basic API)
- **Machine Status** — Real-time execution state (Idle, Running, Pause, Error, etc.)
- **Job Monitoring** — Current program name, progress percentage, elapsed and remaining time
- **Sensor Data** — Axis positions (X/Y/Z/A/B/C), compressed air pressure, vacuum status, spray system status
- **Notifications** — Error, warning, and info messages from the machine
- **Feed Override** — Current cutting and positioning override percentages
- **Runtime Tracking** — Spindle and machine runtime hours
- **Status Light** — Current RGB status light color
- **Workpiece Image** — Image of the current workpiece setup
- **Tool Monitoring** — Tool in spindle, tools in embedded changer and warehouse

### Control (Automation API)
- **Execution buttons** — Start, Pause, Resume, Abort, and Move-to-Park. Each button disables itself in machine states where the command would be rejected (e.g. Resume only enabled when paused).
- **Program selection** — `Selected Program` dropdown lists all `.simpl` files found in the machine root and one level of subfolders. Paired with **Load Selected** and **Execute Selected** buttons.
- **Reload Program** — Re-issues `LoadProgram` on the currently loaded program (useful after editing on the controller).
- **Dialog interaction** — Two `Confirm Dialog` buttons (OK / Cancel) that press the first right- or left-side button on the currently open machine dialog.

### Services
- `datron_next.execute_program_async` / `load_program` — run or load a program by SimPL path.
- `datron_next.enumerate_folder_contents` / `get_program_file_info` — file-system queries (response-capable).
- `datron_next.confirm_dialog` — press a specific dialog button by label.
- `datron_next.activate_workpiece` — select a saved workpiece setup by name.
- `datron_next.execute_remote_link` — run a program from the machine's RemoteLink list.
- `datron_next.set_variable` / `get_variable` — read or write SimPL bool/number/string variables on the machine.

> **Licensing note:** Every feature in the "Control" section above (and every service except the connectivity ones) requires the **Automation API** license tier on your Datron NEXT control. Read-only monitoring only needs the Basic tier. A 403 from the machine usually means either (a) the license is insufficient *or* (b) the command is invalid in the current machine state (e.g. pressing Resume when not paused). The availability guards on the control buttons prevent most state-related 403s, but not all.

## Installation

### HACS (Recommended)
1. Open HACS in your Home Assistant instance
2. Click the three dots in the top right corner → **Custom repositories**
3. Add `https://github.com/P3D-Creations/datron-homeassistant` with category **Integration**
4. Click **Add**
5. Search for "Datron NEXT" in HACS and click **Download**
6. Restart Home Assistant
7. Go to Settings → Devices & Services → **Add Integration** → search "Datron NEXT"

### Manual
1. Copy the `custom_components/datron_next` folder to your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant
3. Add the integration via Settings → Devices & Services → Add Integration

## Configuration

You will need:
- **Host** — IP address or hostname of your Datron NEXT machine
- **Bearer Token** — API authentication token (obtained from the DATRON NEXT control)

## Polling Intervals

The integration uses tiered polling to balance responsiveness with API efficiency:

| Tier | Interval | Data |
|------|----------|------|
| Fast | 10 seconds | Machine status, job progress, axis positions, sensor data, notifications |
| Medium | 60 seconds | Tool information, program details |
| Slow | 1 hour | Machine info, software version, licenses |

## Development

Requires Home Assistant 2024.1.0 or later.

## License

MIT License — see [LICENSE](LICENSE) for details.
