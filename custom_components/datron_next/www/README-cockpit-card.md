# DATRON Cockpit Card

A self-contained Home Assistant Lovelace card that reproduces the **DATRON Live "Cockpit"**
web UI look for `datron_next` Datron Live entities. Vanilla JS, no build step, no external
dependencies.

## Installation

Pick **one** of the two ways to load the file, then register it as a Lovelace **resource**
of type **module**.

### Option A — served by the integration

If the `datron_next` integration registers its static path, the file is available at:

```
/datron_next/datron-cockpit-card.js
```

Add it as a resource (Settings -> Dashboards -> ... -> Resources):

- URL: `/datron_next/datron-cockpit-card.js`
- Type: **JavaScript Module**

### Option B — copy to `config/www/`

Copy `datron-cockpit-card.js` into your Home Assistant `config/www/` directory. It is then
served at:

```
/local/datron-cockpit-card.js
```

Add that URL as a resource of type **JavaScript Module**.

## Configuration

```yaml
type: custom:datron-cockpit-card
prefix: datron_m8cube_1804685    # REQUIRED — shared entity slug (part after "domain." and before the per-entity suffix)
title: M8Cube                    # optional — overrides the header title
show_camera: true                # optional — default true
```

The card builds every entity id as `${domain}.${prefix}_${suffix}` (for example
`sensor.datron_m8cube_1804685_status`, `button.datron_m8cube_1804685_pause_program`,
`camera.datron_m8cube_1804685_machine_camera`).

To find your `prefix`: open any Datron Live entity (e.g. the machine status sensor) and take
the entity id, drop the leading `sensor.` and the trailing `_status`. What remains is the
`prefix`.

## What it shows

- Header with `Cockpit {machine type} {number}`, a live status pill, refresh button and a
  DATRON LIVE wordmark.
- Latest notification bar.
- Open-dialog panel with one button per `right_buttons` label (Unlock door / Continue / Cancel).
  Each button calls `datron_next.confirm_dialog` with that label; the service auto-targets the
  open dialog.
- Program panel: name, preview image on a DATRON-green background, elapsed / remaining time and
  a job-progress bar.
- Vacuum, compressed-air, clamping and Microjet metric tiles (tinted green when active/OK).
- Live machine camera.
- Tool-in-spindle panel with tool image, number, description, diameter and magazine/warehouse
  chips.
- Pause / Resume action buttons (greyed out when unavailable; Resume highlights when paused).

Missing entities are hidden or shown as a dash — the card never throws at render time.
