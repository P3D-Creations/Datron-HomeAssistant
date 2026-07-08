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

A **visual editor** is available: when you add the card from the dashboard UI it opens a small
form where you pick the **machine** (auto-discovered from your Datron Live entities), set an
optional **title**, and toggle **Show camera** and **Show tool browser**. You can still edit the
YAML directly:

```yaml
type: custom:datron-cockpit-card
prefix: datron_m8cube_1804685    # REQUIRED — shared entity slug (part after "domain." and before the per-entity suffix)
title: M8Cube                    # optional — overrides the header title
show_camera: true                # optional — default true
show_tools: true                 # optional — default true; enables the tool browser overlay
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
  Pressure values are rounded to 2 decimals.
- Live machine camera as a **continuous MJPEG stream** (`/api/camera_proxy_stream/...`). The
  `<img>` lives in a persistent host outside the per-update content, so the video does not
  restart / stutter on each poll — its `src` is only touched when the entity or access token
  changes.
- Tool-in-spindle panel with tool image, number, description, diameter and magazine/warehouse
  chips.
- Pause / Resume action buttons (greyed out when unavailable; Resume highlights when paused).

Missing entities are hidden or shown as a dash — the card never throws at render time.

## Notifications

The **notification bar** at the top is a working dropdown. Clicking it toggles an expanded
history list (chevron rotates when open). History is fetched lazily via the
`datron_next.get_notifications` response service and refreshed on each open. Rows are shown
newest-first with a severity dot coloured by `type` (Error red, Warning orange, Info blue,
Temporary grey). `Temporary` progress entries are de-emphasised and **hidden by default**;
a **Hide/Show progress** toggle filters them, and the list is capped at 60 rows in a scroll
container. If the response service is unavailable it shows "Couldn't load notifications".

## Tool browser

When `show_tools` is true (the default), the blue **Tool overview** bar and the Magazine /
Warehouse count figures open a **tool browser overlay**. The overlay has **Magazine ·
Warehouse · Program** tabs, a search box (matches name / category / diameter / article
number), and a scrollable list. Data is fetched lazily via the `datron_next.get_tools`
response service and cached per tab for the session. Set `show_tools: false` to keep the old
behavior where the bar opens the tool image's more-info dialog instead.

Each **row leads with the tool's characteristics**, not its (often auto-assigned) number:
a spec line built from the nominal geometry — `⌀diameter · N FL · FL length · reach ·
category` (each piece omitted when absent) — with the translated name and muted article
number below, plus a category icon. Categories, geometry labels and common German name /
description terms are translated to English (Datron's own i18n). Lengths render in **mm**,
angles in **degrees**.

**Click any row** to open a **tool detail popup** that mirrors the Datron Live tool page:
header (translated name + article number), a large category icon, info rows
(description / comment / vendor / article number), and a **Tool data** section that renders
the geometry grouped exactly like the real page with left-accent colours — flute group
(orange), toric-cut group (blue), shank group (green), tool-length group (grey), plus any
remaining attributes. Tool-life / path percentages are shown **only** when `maxToolLife` /
`maxToolPath` are positive; when the machine's tool-life feature is uncalibrated (both null,
the common case here) no runtime is shown. Close with ×, the backdrop, or Esc (Esc from the
detail returns to the list).

> **Note:** program **files** are *not* browsable on Datron Live (RemoteLink is unlicensed).
> The **Program** tab shows only the **tools used by the current program**, not a file browser.
