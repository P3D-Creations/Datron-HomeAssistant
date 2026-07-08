/**
 * DATRON Cockpit Card
 * A self-contained Home Assistant Lovelace card that reproduces the
 * DATRON Live "Cockpit" web UI look for the `datron_next` integration.
 *
 * No build step, no external dependencies. Loaded by HA as an ES module.
 */

const CARD_VERSION = "1.0.0";

console.info(
  "%c DATRON-COCKPIT-CARD %c v" + CARD_VERSION + " ",
  "color:#232323;background:#93c01f;font-weight:700;border-radius:3px 0 0 3px;padding:2px 6px;",
  "color:#93c01f;background:#232323;border-radius:0 3px 3px 0;padding:2px 6px;"
);

const ACCENT = "#93c01f";

class DatronCockpitCard extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._config = null;
    this._built = false;
    this.attachShadow({ mode: "open" });
  }

  static getStubConfig() {
    return { prefix: "datron_m8cube_1804685" };
  }

  setConfig(config) {
    if (!config || !config.prefix) {
      throw new Error(
        'datron-cockpit-card: "prefix" is required (the shared entity slug, e.g. datron_m8cube_1804685).'
      );
    }
    this._config = Object.assign(
      { show_camera: true, title: null },
      config
    );
    this._built = false;
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._config) return;
    this._render();
  }

  getCardSize() {
    return 14;
  }

  // ---- helpers ---------------------------------------------------------

  _eid(domain, suffix) {
    return domain + "." + this._config.prefix + "_" + suffix;
  }

  _st(entityId) {
    if (!this._hass || !this._hass.states) return null;
    return this._hass.states[entityId] || null;
  }

  // state string for a domain.suffix; returns null if entity missing
  _state(domain, suffix) {
    const s = this._st(this._eid(domain, suffix));
    return s ? s.state : null;
  }

  _attr(domain, suffix, attr) {
    const s = this._st(this._eid(domain, suffix));
    if (!s || !s.attributes) return undefined;
    return s.attributes[attr];
  }

  _isOn(domain, suffix) {
    const v = this._state(domain, suffix);
    return v === "on" || v === "true" || v === "Running";
  }

  _num(v) {
    if (v === null || v === undefined) return null;
    const n = parseFloat(v);
    return isNaN(n) ? null : n;
  }

  _valid(v) {
    return (
      v !== null &&
      v !== undefined &&
      v !== "" &&
      v !== "unknown" &&
      v !== "unavailable" &&
      v !== "None" &&
      v !== "none"
    );
  }

  _entityPicture(domain, suffix) {
    const s = this._st(this._eid(domain, suffix));
    if (!s || !s.attributes) return null;
    return s.attributes.entity_picture || null;
  }

  _esc(str) {
    if (str === null || str === undefined) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  _callService(domain, service, data, target) {
    if (!this._hass) return;
    this._hass.callService(domain, service, data || {}, target || {});
  }

  _pressButton(suffix) {
    const id = this._eid("button", suffix);
    const s = this._st(id);
    if (!s || s.state === "unavailable") return;
    this._callService("button", "press", {}, { entity_id: id });
  }

  _moreInfo(entityId) {
    const ev = new Event("hass-more-info", { bubbles: true, composed: true });
    ev.detail = { entityId: entityId };
    this.dispatchEvent(ev);
  }

  // ---- rendering -------------------------------------------------------

  _render() {
    if (!this._hass || !this._config) return;
    if (!this._built) {
      this._buildShell();
      this._built = true;
    }
    this._update();
  }

  _buildShell() {
    this.shadowRoot.innerHTML =
      "<style>" +
      this._css() +
      "</style>" +
      '<div class="card"><div id="content"></div></div>';
    // Delegated click handling
    this.shadowRoot.addEventListener("click", (ev) => {
      const t = ev.composedPath ? ev.composedPath()[0] : ev.target;
      let el = t;
      while (el && el !== this.shadowRoot) {
        if (el.dataset && el.dataset.action) {
          this._onAction(el.dataset.action, el.dataset.arg);
          return;
        }
        el = el.parentNode;
      }
    });
  }

  _onAction(action, arg) {
    if (action === "pause") {
      this._pressButton("pause_program");
    } else if (action === "resume") {
      this._pressButton("resume_program");
    } else if (action === "refresh") {
      this._pressButton("refresh_data");
    } else if (action === "dialog") {
      this._callService("datron_next", "confirm_dialog", { button: arg });
    } else if (action === "more-info") {
      this._moreInfo(arg);
    }
  }

  _update() {
    const c = this.shadowRoot.getElementById("content");
    if (!c) return;
    let html = "";
    html += this._renderHeader();
    html += this._renderNotification();
    html += this._renderDialog();
    html += this._renderProgram();
    html += this._renderMedia();
    html += this._renderCamera();
    html += this._renderTool();
    html += this._renderActions();
    c.innerHTML = html;
  }

  _renderHeader() {
    const mType = this._state("sensor", "machine_type");
    const mNum = this._state("sensor", "machine_number");
    let label = "Cockpit";
    const parts = [];
    if (this._config.title) parts.push(this._config.title);
    else if (this._valid(mType)) parts.push(mType);
    if (this._valid(mNum)) parts.push(mNum);
    if (parts.length) label += "  " + parts.join(" ");

    // status accent color
    const hex = this._state("sensor", "status_light_hex_color");
    const status = this._state("sensor", "status");
    let dot = ACCENT;
    if (this._valid(hex) && /^#?[0-9a-fA-F]{6}$/.test(hex)) {
      dot = hex.charAt(0) === "#" ? hex : "#" + hex;
    }

    return (
      '<div class="header">' +
      '<div class="hleft">' +
      '<span class="hcockpit">' +
      this._esc(label) +
      "</span>" +
      (this._valid(status)
        ? '<span class="statuspill"><span class="dot" style="background:' +
          this._esc(dot) +
          '"></span>' +
          this._esc(status) +
          "</span>"
        : "") +
      "</div>" +
      '<div class="hright">' +
      '<button class="iconbtn" title="Refresh" data-action="refresh">' +
      this._svgRefresh() +
      "</button>" +
      '<span class="wordmark"><b>DATRON</b> LIVE</span>' +
      "</div>" +
      "</div>" +
      '<div class="hrule"></div>'
    );
  }

  _renderNotification() {
    const s = this._st(this._eid("sensor", "latest_notification"));
    if (!s) return "";
    const msg = this._valid(s.state) ? s.state : "No notifications";
    const type = s.attributes ? s.attributes.type : null;
    const count =
      s.attributes && s.attributes.total_count != null
        ? s.attributes.total_count
        : null;
    return (
      '<div class="panel notif">' +
      '<span class="bell">' +
      this._svgBell() +
      "</span>" +
      '<span class="notif-msg">' +
      this._esc(msg) +
      "</span>" +
      (this._valid(type)
        ? '<span class="tag">' + this._esc(type) + "</span>"
        : "") +
      (count != null
        ? '<span class="count">' + this._esc(count) + "</span>"
        : "") +
      "</div>"
    );
  }

  _renderDialog() {
    const s = this._st(this._eid("sensor", "open_dialog"));
    if (!s) return "";
    const a = s.attributes || {};
    const isOpen =
      a.is_open === true ||
      a.is_open === "true" ||
      (this._valid(s.state) && s.state !== "none");
    if (!isOpen) {
      return (
        '<div class="panel dialog closed">' +
        '<span class="dlabel">No dialog open</span>' +
        "</div>"
      );
    }
    const caption = this._valid(s.state) ? s.state : a.caption || "Dialog";
    const text = a.text || "";
    const details = a.details || "";
    const severity = (a.severity || "Info").toString();
    const sevClass = "sev-" + severity.toLowerCase();
    let buttons = a.right_buttons;
    if (!Array.isArray(buttons)) buttons = [];

    let btnHtml = "";
    for (let i = 0; i < buttons.length; i++) {
      const label = buttons[i];
      const primary = i === 0 ? " primary" : "";
      btnHtml +=
        '<button class="dbtn' +
        primary +
        '" data-action="dialog" data-arg="' +
        this._esc(label) +
        '">' +
        this._esc(label) +
        "</button>";
    }

    return (
      '<div class="panel dialog open ' +
      sevClass +
      '">' +
      '<div class="drow"><span class="sevbadge">' +
      this._esc(severity) +
      '</span><span class="dcaption">' +
      this._esc(caption) +
      "</span></div>" +
      (this._valid(text)
        ? '<div class="dtext">' + this._esc(text) + "</div>"
        : "") +
      (this._valid(details)
        ? '<div class="ddetails">' + this._esc(details) + "</div>"
        : "") +
      (btnHtml ? '<div class="dbtns">' + btnHtml + "</div>" : "") +
      "</div>"
    );
  }

  _renderProgram() {
    const s = this._st(this._eid("sensor", "current_program"));
    const running = this._isOn("binary_sensor", "machine_running");
    const name = s && this._valid(s.state) ? s.state : "No program loaded";
    const elapsed = this._state("sensor", "job_elapsed_time");
    let remaining = this._state("sensor", "job_remaining_time");
    if (!this._valid(remaining))
      remaining = this._state("sensor", "estimated_remaining_time");
    const progress = this._num(this._state("sensor", "job_progress"));
    const preview = this._entityPicture("image", "program_preview_image");

    let bar = "";
    if (progress != null) {
      const pct = Math.max(0, Math.min(100, progress));
      bar =
        '<div class="progress"><div class="progfill" style="width:' +
        pct +
        '%"></div></div>' +
        '<div class="progtxt">' +
        pct.toFixed(0) +
        "%</div>";
    }

    let previewHtml;
    if (preview) {
      previewHtml =
        '<img class="preview-img" src="' +
        this._esc(preview) +
        '" alt="Program preview" data-action="more-info" data-arg="' +
        this._esc(this._eid("image", "program_preview_image")) +
        '"/>';
    } else {
      previewHtml = '<div class="preview-empty">' + this._svgPart() + "</div>";
    }

    return (
      '<div class="panel program' +
      (running ? " active" : "") +
      '">' +
      '<div class="prog-title">' +
      this._esc(name) +
      "</div>" +
      '<div class="preview">' +
      previewHtml +
      "</div>" +
      '<div class="timerow">' +
      '<div class="timer"><span class="ticon">' +
      this._svgStopwatch() +
      '</span><span class="tval">' +
      this._esc(this._valid(elapsed) ? elapsed : "00:00:00") +
      "</span></div>" +
      '<div class="timer right"><span class="tlabel">remaining</span><span class="tval big">' +
      this._esc(this._valid(remaining) ? remaining : "--:--:--") +
      "</span></div>" +
      "</div>" +
      (bar ? '<div class="progwrap">' + bar + "</div>" : "") +
      "</div>"
    );
  }

  _renderMedia() {
    // Vacuum, compressed air, microjet, in a responsive grid
    let cells = "";

    // Vacuum
    const vacS = this._st(this._eid("sensor", "vacuum_pressure"));
    if (vacS) {
      const active = this._isOn("binary_sensor", "vacuum_active");
      const unit =
        vacS.attributes && vacS.attributes.unit_of_measurement
          ? vacS.attributes.unit_of_measurement
          : "";
      cells += this._metricCell(
        "Vacuum",
        this._valid(vacS.state) ? vacS.state : "--",
        unit,
        active
      );
    }

    // Compressed air
    const airS = this._st(this._eid("sensor", "compressed_air_input_pressure"));
    if (airS) {
      const ok = this._isOn("binary_sensor", "compressed_air_monitor");
      const unit =
        airS.attributes && airS.attributes.unit_of_measurement
          ? airS.attributes.unit_of_measurement
          : "";
      cells += this._metricCell(
        "Compressed air",
        this._valid(airS.state) ? airS.state : "--",
        unit,
        ok || this._valid(airS.state)
      );
    }

    // Clamping device pressure (optional bonus metric)
    const clampS = this._st(this._eid("sensor", "clamping_device_pressure"));
    if (clampS && this._valid(clampS.state)) {
      const unit =
        clampS.attributes && clampS.attributes.unit_of_measurement
          ? clampS.attributes.unit_of_measurement
          : "";
      cells += this._metricCell("Clamping", clampS.state, unit, true);
    }

    // Microjet
    const mjEmptyS = this._st(this._eid("binary_sensor", "microjet_tank1_empty"));
    if (mjEmptyS) {
      const empty = mjEmptyS.state === "on";
      cells +=
        '<div class="mcell' +
        (empty ? " bad" : " ok") +
        '">' +
        '<div class="mlabel">Microjet</div>' +
        '<div class="mspray">' +
        this._svgSpray() +
        "</div>" +
        '<div class="mstate">' +
        (empty ? "Tank empty" : "OK") +
        "</div>" +
        "</div>";
    }

    if (!cells) return "";
    return '<div class="metrics">' + cells + "</div>";
  }

  _metricCell(label, value, unit, active) {
    return (
      '<div class="mcell' +
      (active ? " ok" : "") +
      '">' +
      '<div class="mlabel">' +
      this._esc(label) +
      "</div>" +
      '<div class="mvalue">' +
      this._esc(value) +
      (this._valid(unit) ? '<span class="munit">' + this._esc(unit) + "</span>" : "") +
      "</div>" +
      "</div>"
    );
  }

  _renderCamera() {
    if (!this._config.show_camera) return "";
    const pic = this._entityPicture("camera", "machine_camera");
    if (!pic) return "";
    return (
      '<div class="panel camera">' +
      '<div class="camlabel">Machine camera</div>' +
      '<img class="cam-img" src="' +
      this._esc(pic) +
      '" alt="Machine camera" data-action="more-info" data-arg="' +
      this._esc(this._eid("camera", "machine_camera")) +
      '"/>' +
      "</div>"
    );
  }

  _renderTool() {
    const s = this._st(this._eid("sensor", "tool_in_spindle"));
    if (!s) return "";
    const a = s.attributes || {};
    const img = this._entityPicture("image", "tool_in_spindle_image");
    const toolNo = a.tool_number;
    const desc = a.description || s.state;
    const dia = a.diameter_mm;
    const life = a.current_life_minutes;

    const mag = this._state("sensor", "tools_in_magazine");
    const wh = this._state("sensor", "tools_in_warehouse");

    let chips = "";
    if (this._valid(mag))
      chips +=
        '<span class="chip">Magazine <b>' + this._esc(mag) + "</b></span>";
    if (this._valid(wh))
      chips +=
        '<span class="chip">Warehouse <b>' + this._esc(wh) + "</b></span>";

    let imgHtml;
    if (img) {
      imgHtml =
        '<img class="tool-img" src="' +
        this._esc(img) +
        '" alt="Tool"/>';
    } else {
      imgHtml = '<div class="tool-img empty">' + this._svgTool() + "</div>";
    }

    const meta = [];
    if (this._valid(dia)) meta.push("&#8960; " + this._esc(dia) + " mm");
    if (this._valid(life)) meta.push(this._esc(life) + " min life");

    return (
      '<div class="panel tool">' +
      '<div class="tool-head">Tool in spindle</div>' +
      '<div class="tool-body">' +
      imgHtml +
      '<div class="tool-info">' +
      (this._valid(toolNo)
        ? '<span class="tool-no">T' + this._esc(toolNo) + "</span>"
        : "") +
      '<span class="tool-name">' +
      this._esc(this._valid(desc) ? desc : "No tool") +
      "</span>" +
      (meta.length
        ? '<span class="tool-meta">' + meta.join(" &middot; ") + "</span>"
        : "") +
      "</div>" +
      "</div>" +
      (chips ? '<div class="chips">' + chips + "</div>" : "") +
      "</div>"
    );
  }

  _renderActions() {
    const pauseS = this._st(this._eid("button", "pause_program"));
    const resumeS = this._st(this._eid("button", "resume_program"));
    const paused = this._state("sensor", "status") === "Pause";

    let btns = "";
    if (pauseS) {
      const dis = pauseS.state === "unavailable";
      btns +=
        '<button class="action pause' +
        (dis ? " disabled" : "") +
        '" data-action="pause"' +
        (dis ? " disabled" : "") +
        ">" +
        this._svgPause() +
        "<span>Pause</span></button>";
    }
    if (resumeS) {
      const dis = resumeS.state === "unavailable";
      btns +=
        '<button class="action resume' +
        (dis ? " disabled" : "") +
        (paused ? " highlight" : "") +
        '" data-action="resume"' +
        (dis ? " disabled" : "") +
        ">" +
        this._svgPlay() +
        "<span>Resume</span></button>";
    }
    if (!btns) return "";
    return '<div class="actions">' + btns + "</div>";
  }

  // ---- inline SVG icons ------------------------------------------------

  _svgRefresh() {
    return '<svg viewBox="0 0 24 24" width="18" height="18"><path fill="currentColor" d="M17.65 6.35A7.95 7.95 0 0 0 12 4a8 8 0 1 0 7.73 10h-2.08A6 6 0 1 1 12 6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg>';
  }
  _svgBell() {
    return '<svg viewBox="0 0 24 24" width="18" height="18"><path fill="currentColor" d="M12 22a2.1 2.1 0 0 0 2.09-2H9.91A2.1 2.1 0 0 0 12 22zm6-6v-5c0-3.07-1.64-5.64-4.5-6.32V4a1.5 1.5 0 0 0-3 0v.68C7.63 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z"/></svg>';
  }
  _svgStopwatch() {
    return '<svg viewBox="0 0 24 24" width="20" height="20"><path fill="currentColor" d="M15 1H9v2h6V1zm-4 13h2V8h-2v6zm8.03-6.61l1.42-1.42a11 11 0 0 0-1.42-1.41l-1.41 1.42A9 9 0 1 0 12 20a9 9 0 0 0 7.03-14.61zM12 20a7 7 0 1 1 0-14 7 7 0 0 1 0 14z"/></svg>';
  }
  _svgSpray() {
    return '<svg viewBox="0 0 24 24" width="26" height="26"><path fill="currentColor" d="M9 3v2h2V3H9zm4 1v2h2V4h-2zM7 6v2h2V6H7zm6 0v2h2V6h-2zM9 8v2h2V8H9zm2 3H9v9a1 1 0 0 0 1 1 1 1 0 0 0 1-1v-9zm4-1h-2v2h2v-2zM7 12v2h2v-2H7zm8 2h-2v2h2v-2zM9 15v2h2v-2H9z"/></svg>';
  }
  _svgTool() {
    return '<svg viewBox="0 0 24 24" width="34" height="34"><path fill="currentColor" d="M9 3 8 6h8l-1-3H9zm-1 5 1 9a3 3 0 0 0 6 0l1-9H8zm4 12.5a1 1 0 1 1 0-2 1 1 0 0 1 0 2z"/></svg>';
  }
  _svgPart() {
    return '<svg viewBox="0 0 24 24" width="48" height="48"><path fill="currentColor" opacity="0.5" d="M12 2 2 7v10l10 5 10-5V7L12 2zm0 2.2 6.9 3.45L12 11.1 5.1 7.65 12 4.2zM4 9.3l7 3.5v7.4l-7-3.5V9.3zm16 0v7.4l-7 3.5v-7.4l7-3.5z"/></svg>';
  }
  _svgPause() {
    return '<svg viewBox="0 0 24 24" width="22" height="22"><path fill="currentColor" d="M6 5h4v14H6V5zm8 0h4v14h-4V5z"/></svg>';
  }
  _svgPlay() {
    return '<svg viewBox="0 0 24 24" width="22" height="22"><path fill="currentColor" d="M8 5v14l11-7L8 5z"/></svg>';
  }

  // ---- styles ----------------------------------------------------------

  _css() {
    return `
      :host { display:block; }
      .card {
        max-width: 640px;
        margin: 0 auto;
        background: #232323;
        border-radius: 16px;
        padding: 14px;
        color: #f0f0f0;
        font-family: -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
        font-weight: 300;
        box-sizing: border-box;
        -webkit-font-smoothing: antialiased;
      }
      #content { display:flex; flex-direction:column; gap:12px; }

      /* Header */
      .header { display:flex; align-items:center; justify-content:space-between; gap:8px; }
      .hleft { display:flex; align-items:center; gap:10px; min-width:0; flex-wrap:wrap; }
      .hcockpit { font-size:18px; font-weight:300; letter-spacing:.3px; white-space:nowrap; }
      .statuspill {
        display:inline-flex; align-items:center; gap:6px;
        background:#3a3a3a; border-radius:999px; padding:3px 10px;
        font-size:12px; color:#ddd;
      }
      .statuspill .dot { width:9px; height:9px; border-radius:50%; box-shadow:0 0 6px currentColor; }
      .hright { display:flex; align-items:center; gap:10px; flex-shrink:0; }
      .wordmark { font-size:13px; letter-spacing:1px; color:#e8e8e8; white-space:nowrap; }
      .wordmark b { font-weight:800; color:#fff; }
      .iconbtn {
        background:transparent; border:none; color:#9a9a9a; cursor:pointer;
        padding:4px; border-radius:8px; display:inline-flex; transition:color .15s, background .15s;
      }
      .iconbtn:hover { color:${ACCENT}; background:#333; }
      .hrule { height:2px; background:linear-gradient(90deg, ${ACCENT}, rgba(147,192,31,0)); border-radius:2px; margin-top:-4px; }

      /* Panels */
      .panel {
        background:#3a3a3a; border-radius:14px; padding:14px 16px;
        box-shadow: inset 0 1px 0 rgba(255,255,255,.03);
      }
      .panel.active, .mcell.ok {
        background:linear-gradient(145deg, rgba(147,192,31,.22), rgba(147,192,31,.08));
        box-shadow: inset 0 0 0 1px rgba(147,192,31,.35);
      }

      /* Notification */
      .notif { display:flex; align-items:center; gap:10px; }
      .notif .bell { color:${ACCENT}; display:inline-flex; flex-shrink:0; }
      .notif-msg { flex:1; font-size:14px; color:#eaeaea; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
      .notif .tag { font-size:11px; background:#2b2b2b; color:#bdbdbd; padding:2px 8px; border-radius:999px; }
      .notif .count {
        min-width:20px; text-align:center; font-size:11px; font-weight:600;
        background:${ACCENT}; color:#232323; padding:2px 7px; border-radius:999px;
      }

      /* Dialog */
      .dialog.closed { text-align:center; color:#8a8a8a; font-size:14px; }
      .dialog .drow { display:flex; align-items:center; gap:10px; margin-bottom:6px; }
      .dcaption { font-size:16px; color:#fff; }
      .sevbadge {
        font-size:10px; text-transform:uppercase; letter-spacing:.5px;
        padding:2px 8px; border-radius:999px; font-weight:600;
        background:#4a4a4a; color:#ddd;
      }
      .sev-warning .sevbadge { background:#c8901f; color:#231b00; }
      .sev-error .sevbadge { background:#c0392b; color:#fff; }
      .sev-info .sevbadge { background:${ACCENT}; color:#232323; }
      .sev-warning { box-shadow: inset 0 0 0 1px rgba(200,144,31,.5); }
      .sev-error { box-shadow: inset 0 0 0 1px rgba(192,57,43,.55); }
      .dtext { font-size:14px; color:#e2e2e2; }
      .ddetails { font-size:12px; color:#a9a9a9; margin-top:2px; }
      .dbtns { display:flex; flex-wrap:wrap; gap:8px; margin-top:12px; }
      .dbtn {
        flex:1 1 auto; min-width:110px; cursor:pointer;
        background:#2c2c2c; color:#eee; border:1px solid #555;
        border-radius:10px; padding:10px 14px; font-size:14px; font-weight:400;
        transition:background .15s, border-color .15s, transform .05s;
      }
      .dbtn:hover { background:#333; border-color:#777; }
      .dbtn:active { transform:translateY(1px); }
      .dbtn.primary { background:${ACCENT}; color:#232323; border-color:${ACCENT}; font-weight:600; }
      .dbtn.primary:hover { background:#a5d426; }

      /* Program */
      .program .prog-title { font-size:17px; color:#fff; margin-bottom:10px; }
      .preview {
        border-radius:12px; overflow:hidden;
        background:linear-gradient(160deg, ${ACCENT}, #7ba417);
        display:flex; align-items:center; justify-content:center;
        min-height:150px; padding:10px;
      }
      .preview-img { max-width:100%; max-height:240px; object-fit:contain; cursor:pointer; border-radius:8px; }
      .preview-empty { color:rgba(35,35,35,.7); display:flex; }
      .timerow { display:flex; align-items:flex-end; justify-content:space-between; margin-top:12px; gap:12px; }
      .timer { display:flex; align-items:center; gap:8px; color:#dcdcdc; }
      .timer.right { flex-direction:column; align-items:flex-end; gap:0; }
      .ticon { color:${ACCENT}; display:inline-flex; }
      .tlabel { font-size:11px; color:#9a9a9a; text-transform:uppercase; letter-spacing:.5px; }
      .tval { font-family:"SFMono-Regular", ui-monospace, "Consolas", monospace; font-size:18px; color:#f2f2f2; }
      .tval.big { font-size:26px; font-weight:500; color:#fff; }
      .progwrap { display:flex; align-items:center; gap:10px; margin-top:12px; }
      .progress { flex:1; height:8px; background:#2a2a2a; border-radius:999px; overflow:hidden; }
      .progfill { height:100%; background:linear-gradient(90deg, ${ACCENT}, #b6e63a); border-radius:999px; transition:width .4s ease; }
      .progtxt { font-size:12px; color:#cfcfcf; font-variant-numeric:tabular-nums; min-width:34px; text-align:right; }

      /* Metrics grid */
      .metrics { display:grid; grid-template-columns:repeat(auto-fit, minmax(140px, 1fr)); gap:12px; }
      .mcell {
        background:#3a3a3a; border-radius:14px; padding:14px;
        display:flex; flex-direction:column; align-items:center; gap:6px; text-align:center;
      }
      .mcell.bad { box-shadow: inset 0 0 0 1px rgba(192,57,43,.5); }
      .mlabel { font-size:12px; color:#b5b5b5; text-transform:uppercase; letter-spacing:.5px; }
      .mvalue { font-size:30px; font-weight:400; color:#fff; line-height:1; }
      .munit { font-size:14px; color:#cfcfcf; margin-left:4px; font-weight:300; }
      .mspray { color:${ACCENT}; }
      .mcell.bad .mspray { color:#e06657; }
      .mstate { font-size:13px; color:#e0e0e0; }

      /* Camera */
      .camera .camlabel, .tool .tool-head {
        font-size:12px; color:#b5b5b5; text-transform:uppercase; letter-spacing:.5px; margin-bottom:8px;
      }
      .cam-img { width:100%; border-radius:10px; display:block; cursor:pointer; background:#111; }

      /* Tool */
      .tool-body { display:flex; align-items:center; gap:14px; }
      .tool-img {
        width:64px; height:64px; border-radius:12px; object-fit:contain;
        background:#2b2b2b; flex-shrink:0;
      }
      .tool-img.empty { display:flex; align-items:center; justify-content:center; color:#777; }
      .tool-info { display:flex; flex-direction:column; gap:2px; min-width:0; }
      .tool-no { font-size:13px; color:${ACCENT}; font-weight:600; }
      .tool-name { font-size:15px; color:#fff; overflow:hidden; text-overflow:ellipsis; }
      .tool-meta { font-size:12px; color:#a9a9a9; }
      .chips { display:flex; flex-wrap:wrap; gap:8px; margin-top:12px; }
      .chip { font-size:12px; background:#2c2c2c; color:#c9c9c9; padding:5px 10px; border-radius:999px; }
      .chip b { color:#fff; font-weight:600; margin-left:2px; }

      /* Actions */
      .actions { display:flex; gap:12px; margin-top:2px; }
      .action {
        flex:1; cursor:pointer; border:none; border-radius:14px;
        padding:16px; font-size:16px; font-weight:500;
        display:flex; align-items:center; justify-content:center; gap:8px;
        transition:filter .15s, transform .05s, background .15s;
      }
      .action:active { transform:translateY(1px); }
      .action.pause { background:#4a4a4a; color:#fff; }
      .action.pause:hover { filter:brightness(1.15); }
      .action.resume { background:#3a3a3a; color:#cfcfcf; box-shadow:inset 0 0 0 1px #555; }
      .action.resume.highlight { background:${ACCENT}; color:#232323; box-shadow:none; }
      .action.resume.highlight:hover { background:#a5d426; }
      .action.disabled { opacity:.4; cursor:not-allowed; pointer-events:none; }

      @media (max-width:460px) {
        .card { padding:10px; }
        .hcockpit { font-size:16px; }
        .tval.big { font-size:22px; }
        .mvalue { font-size:26px; }
      }
    `;
  }
}

if (!customElements.get("datron-cockpit-card")) {
  customElements.define("datron-cockpit-card", DatronCockpitCard);
}

window.customCards = window.customCards || [];
window.customCards.push({
  type: "datron-cockpit-card",
  name: "DATRON Cockpit Card",
  description: "DATRON Live cockpit-style machine card",
  preview: false,
});
