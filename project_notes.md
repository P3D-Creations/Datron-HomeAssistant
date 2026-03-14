# Project Notes — Datron NEXT Home Assistant Integration

## Machine Details
- **Machine:** Datron M8Cube CNC milling machine
- **Control System:** DATRON NEXT
- **Software Version:** 3.8x
- **API:** RESTful API with OpenAPI 3.0 spec (oas3.json)

## API Access Tiers
- **Basic** (current): Read access to operating data
- **Automation** (planned): Execute, pause, cancel programs; includes Basic

## Authentication
- Bearer token (JWT) via `Authorization: Bearer {token}` header
- Token created via `POST /api/v2/User/CreateToken` with username/password
- Token expiration: **Unknown** — currently using a static token; need to verify if refresh logic is needed

## API Versioning
- Using **V2** for all endpoints unless V1-only feature is needed
- Version specified in URL path: `/api/v2/...`

## Integration Architecture

### Polling Tiers
| Tier | Interval | Endpoints |
|------|----------|-----------|
| Fast (10s) | Machine status, execution durations, axis positions, compressed air, vacuum, spray system, notifications, feed override, status light |
| Medium (60s) | Tool in spindle, tools in changer, tools in warehouse, current program, workpiece info |
| Slow (3600s) | Machine number, machine type, software version, licenses, runtime hours |

### Entity Types
- **Sensors**: Machine status, program name, progress, times, axis positions, pressures, overrides, runtime
- **Binary Sensors**: Air input OK, vacuum active, tank empty flags, machine running
- **Buttons**: (Future) Start, pause, stop program
- **Image**: Workpiece image, preview image
- **Camera**: Live camera feed

## Excluded Features
- Tool Assist tools (not needed)
- Cartridge/dispensing info (machine doesn't have this variant)

## Key API Endpoints (Critical)

### Machine Status
- `GET /api/v2/Machine/MachineStatus` → `MachineExecutionState` enum

### Job Information  
- `GET /api/v2/Runtime/CurrentlyLoadedProgram` → program name, path
- `GET /api/v2/Runtime/ExecutionDurations` → elapsed, remaining, progress (0-1)

### Notifications
- `GET /api/v2/Runtime/Notifications` → last 100 messages (Error, Warning, Info, Temporary)

### Sensor Data
- `GET /api/v2/MachineComponents/AxisPositions` → X, Y, Z, A, B, C
- `GET /api/v2/MachineComponents/CompressedAir` → input/clamping pressure
- `GET /api/v2/MachineComponents/Vacuum` → digital + analog sensor, activated flag
- `GET /api/v2/MachineComponents/SpraySystem` → EKD + Microjet tank status
- `GET /api/v2/MachineComponents/FeedOverride` → cutting/positioning %
- `GET /api/v2/MachineComponents/StatusLight` → RGB values
- `GET /api/v2/MachineComponents/Runtime` → spindle/machine hours

### Tools
- `GET /api/v2/Tool/ToolInSpindle` → current tool details
- `GET /api/v2/Tool/ToolsInEmbeddedToolChanger` → magazine contents
- `GET /api/v2/Tool/ToolsInWarehouse` → warehouse contents

### Images
- `GET /api/v2/Workpiece/WorkpieceImage` → workpiece picture
- `GET /api/v2/Runtime/PreviewImage` → program preview URL

### Camera
- `GET /api/v2/Camera/CreateCameraImageUrl` → camera stream URL

## MachineExecutionState Values
- `Init` — Machine initializing
- `Preparing` — Preparing for execution
- `Idle` — Ready, no program running
- `Running` — Program actively executing
- `Pause` — Program paused
- `Manual` — Manual operation mode
- `Aborting` — Program being aborted
- `Aborted` — Program was aborted
- `Transient` — Transitional state
- `WaitingForUserInput` — Waiting on operator dialog

## Future Enhancements
- Custom Lovelace card for CNC machine display
- Support for additional CNC brands/machines
- Automation API tier: program control (start/pause/stop)
- Camera streaming integration
- Alert app integration
