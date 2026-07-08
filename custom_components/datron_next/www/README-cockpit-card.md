# DATRON Cockpit Card

Self-contained Lovelace card reproducing the DATRON Live Cockpit for
`datron_next` entities. Vanilla JS, no build step, no dependencies.

## Loading

The integration serves and auto-loads the card; no resource registration is
needed. Fallback options if auto-load is unavailable:

- Resource URL `/datron_next/datron-cockpit-card.js`, type JavaScript Module, or
- copy the file to `config/www/` and register `/local/datron-cockpit-card.js`.

## Configuration

A visual editor is provided (machine picker, title, remaining-time source,
camera and tool-browser toggles, extra-camera checklist). YAML equivalent:

```yaml
type: custom:datron-cockpit-card
prefix: datron_m8cube_1804685   # required: entity slug between "domain." and the suffix
title: M8Cube                   # optional header override
timer_source: machine           # machine (default) | estimated | both
show_camera: true               # default true
show_tools: true                # default true
extra_cameras:                  # optional additional cameras
  - camera.shop_cam
```

Entity ids are built as `${domain}.${prefix}_${suffix}`. To find the prefix,
take any Datron entity id and drop the domain and per-entity suffix
(`sensor.datron_m8cube_1804685_status` -> `datron_m8cube_1804685`).

## Panels

- Header: `Cockpit {type} {number}`, DATRON LIVE wordmark.
- Notification bar: click to expand history (newest first, severity-colored).
  Temporary/progress entries hidden by default (toggle); tool-load messages
  always filtered. Backed by the `get_notifications` service.
- Dialog: shows the open dialog and one button per machine-provided label,
  pressed via `confirm_dialog`.
- Program: name, preview image, elapsed/remaining. The panel body is a
  progress fill: while Running below 100 % the green area grows left-to-right
  with `job_progress` over a dark base; idle/finished shows fully green.
  `timer_source` selects the remaining time: `machine` (default,
  `job_remaining_time` with fallback), `estimated`
  (`estimated_remaining_time`), or `both` (machine plus an EST-labelled
  estimate below).
- Vacuum / compressed air / Microjet tiles; pressures rounded to 2 decimals;
  green when active/OK.
- Tool in spindle: spec line `⌀dia · R{r} · LOC {flute} · reach {shoulder} ·
  {n}FL` with EDP + description below. R only for corner-radius/bullnose
  tools; reach (shoulder/toric-cut length) only when it exceeds flute length.
  Click to open the full tool detail popup. When
  `sensor.${prefix}_program_tools_missing` reports missing program tools, a
  circled `!` badge appears on the tool icon (red if any tool is in neither
  magazine nor warehouse, else yellow); clicking it opens the browser's
  Program tab.
- Tool overview (blue bar) and the magazine/warehouse figures open the tool
  browser.
- Pause/Resume, greyed when unavailable.
- Camera: continuous MJPEG via `/api/camera_proxy_stream/...`. The stream
  element is persistent, so polling re-renders do not restart the video.

Missing entities are hidden or shown as a dash; the card does not throw at
render time. Renders are skipped entirely when none of the entities the card
reads have changed (HA pushes a new hass object on any state change in the
instance), so clicks are no longer eaten by mid-click DOM replacement.

## Cameras

The display list is the machine camera (when `show_camera`) followed by
`extra_cameras` entries that exist, de-duplicated, one shown at a time.
With two or more cameras a next button and position dots appear; the selected
index persists across re-renders. Unavailable cameras show a placeholder and
can still be cycled past.

## Tool browser

Tabs: Spindle (the currently loaded tool), Program (tools used by the current
program), Magazine, Warehouse. Search matches name, category, diameter, and
article number. Rows lead with the spec line and article number; categories,
geometry labels, and common German terms are translated to English. Lengths
render in mm, angles in degrees.

On the Program tab, rows are colored by availability from
`sensor.${prefix}_program_tools_missing` (matched by tool id, falling back to
article number): yellow accent/tint = in warehouse but not in the magazine,
red = in neither. A legend line appears under the tabs when any tool is
affected.

Clicking a row opens a detail popup mirroring the Datron Live tool page:
info rows plus grouped tool data (flute orange, toric cut blue, shank green,
length grey). The hero shows the machine's own tool thumbnail, proxied through
`/api/datron_next/tool_image` using the token from the tool's `imageUrl`; the
category icon is the instant placeholder and remains if the image fails. List
rows keep the lightweight category icons. Tool life/path percentages appear
only when the machine has maximums configured; uncalibrated counters are not
shown.

Data comes from the `get_tools` response service, fetched lazily and cached
per tab (the Spindle tab is refetched on each open since it changes often).

Program files are not browsable on Datron Live without the RemoteLink
license; the Program tab lists current-program tools only.
