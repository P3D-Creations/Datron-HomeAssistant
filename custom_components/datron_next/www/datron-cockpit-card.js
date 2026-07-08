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
  "color:#232323;background:#8bc53f;font-weight:700;border-radius:3px 0 0 3px;padding:2px 6px;",
  "color:#8bc53f;background:#232323;border-radius:0 3px 3px 0;padding:2px 6px;"
);

const GREEN = "#8bc53f";
const BLUE = "#0064a0";
const SEV_INFO = "#0064a0";
const SEV_WARN = "#f7931e";
const SEV_ERROR = "#c80000";

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
    html += this._renderVacuum();
    html += this._renderCompressedAir();
    html += this._renderMicrojet();
    html += this._renderToolStrip();
    html += this._renderToolOverview();
    html += this._renderActions();
    html += this._renderCamera();
    c.innerHTML = html;
  }

  // -- Header ------------------------------------------------------------

  _renderHeader() {
    const mType = this._state("sensor", "machine_type");
    const mNum = this._state("sensor", "machine_number");
    let label = "Cockpit";
    const parts = [];
    if (this._config.title) parts.push(this._config.title);
    else if (this._valid(mType)) parts.push(mType);
    if (this._valid(mNum)) parts.push(mNum);
    if (parts.length) label += " " + parts.join(" ");

    return (
      '<div class="header">' +
      '<span class="hcockpit">' +
      this._esc(label) +
      "</span>" +
      '<span class="wordmark"><b>DATRON</b>&#8202;<i>LIVE</i></span>' +
      "</div>" +
      '<div class="hrule"></div>'
    );
  }

  // -- Notification bar --------------------------------------------------

  _renderNotification() {
    const s = this._st(this._eid("sensor", "latest_notification"));
    if (!s) return "";
    const msg = this._valid(s.state) ? s.state : "No notifications";
    return (
      '<div class="panel notif">' +
      '<span class="notif-msg">' +
      this._esc(msg) +
      "</span>" +
      '<span class="notif-chev">' +
      this._svgChevron() +
      "</span>" +
      "</div>"
    );
  }

  // -- Dialog bar --------------------------------------------------------

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
    const severity = (a.severity || "Info").toString();
    const sevClass = "sev-" + severity.toLowerCase();

    // Combine left then right buttons; one real button per label.
    let buttons = [];
    if (Array.isArray(a.left_buttons)) buttons = buttons.concat(a.left_buttons);
    if (Array.isArray(a.right_buttons)) buttons = buttons.concat(a.right_buttons);

    let btnHtml = "";
    for (let i = 0; i < buttons.length; i++) {
      const label = buttons[i];
      if (!this._valid(label)) continue;
      btnHtml +=
        '<button class="dbtn" data-action="dialog" data-arg="' +
        this._esc(label) +
        '">' +
        this._esc(label) +
        "</button>";
    }

    return (
      '<div class="panel dialog open ' +
      sevClass +
      '">' +
      '<div class="dcaption">' +
      this._esc(caption) +
      "</div>" +
      (this._valid(text)
        ? '<div class="dtext">' + this._esc(text) + "</div>"
        : "") +
      (btnHtml ? '<div class="dbtns">' + btnHtml + "</div>" : "") +
      "</div>"
    );
  }

  // -- Program panel -----------------------------------------------------

  _renderProgram() {
    const s = this._st(this._eid("sensor", "current_program"));
    const name = s && this._valid(s.state) ? s.state : "No program loaded";
    const elapsed = this._state("sensor", "job_elapsed_time");
    let remaining = this._state("sensor", "job_remaining_time");
    if (!this._valid(remaining))
      remaining = this._state("sensor", "estimated_remaining_time");
    const progress = this._num(this._state("sensor", "job_progress"));
    const preview = this._entityPicture("image", "program_preview_image");

    let previewHtml = "";
    if (preview) {
      previewHtml =
        '<img class="prog-preview" src="' +
        this._esc(preview) +
        '" alt="Program preview" data-action="more-info" data-arg="' +
        this._esc(this._eid("image", "program_preview_image")) +
        '"/>';
    }

    let barHtml = "";
    if (progress != null) {
      const pct = Math.max(0, Math.min(100, progress));
      barHtml = '<div class="prog-underline" style="width:' + pct + '%"></div>';
    }

    return (
      '<div class="panel program">' +
      '<div class="prog-title">' +
      this._esc(name) +
      "</div>" +
      '<div class="prog-inner">' +
      previewHtml +
      '<div class="prog-time left">' +
      '<span class="ti">' +
      this._svgStopwatch() +
      "</span>" +
      '<span class="tval">' +
      this._esc(this._valid(elapsed) ? elapsed : "00:00:00") +
      "</span>" +
      "</div>" +
      '<div class="prog-time right">' +
      '<span class="tval">' +
      this._esc(this._valid(remaining) ? remaining : "--:--:--") +
      "</span>" +
      "</div>" +
      barHtml +
      "</div>" +
      "</div>"
    );
  }

  // -- Media / consumable bars ------------------------------------------

  _renderVacuum() {
    const vacS = this._st(this._eid("sensor", "vacuum_pressure"));
    if (!vacS) return "";
    const active = this._isOn("binary_sensor", "vacuum_active");
    const unit =
      vacS.attributes && vacS.attributes.unit_of_measurement
        ? vacS.attributes.unit_of_measurement
        : "";
    const value = this._valid(vacS.state) ? vacS.state : "--";
    return this._valueBar(
      "Vacuum",
      value,
      unit,
      this._svgVacuum(),
      active
    );
  }

  _renderCompressedAir() {
    const airS = this._st(this._eid("sensor", "compressed_air_input_pressure"));
    if (!airS) return "";
    const unit =
      airS.attributes && airS.attributes.unit_of_measurement
        ? airS.attributes.unit_of_measurement
        : "";
    const value = this._valid(airS.state) ? airS.state : "--";
    return this._valueBar(
      "Compressed air",
      value,
      unit,
      this._svgGauge(),
      true
    );
  }

  _renderMicrojet() {
    const mjEmptyS = this._st(this._eid("binary_sensor", "microjet_tank1_empty"));
    if (!mjEmptyS) return "";
    const empty = mjEmptyS.state === "on";
    return (
      '<div class="panel bar' +
      (empty ? "" : " ok") +
      '">' +
      '<span class="bar-label">Microjet</span>' +
      '<span class="bar-spacer"></span>' +
      '<span class="bar-icon">' +
      this._svgSpray() +
      "</span>" +
      "</div>"
    );
  }

  _valueBar(label, value, unit, iconSvg, ok) {
    return (
      '<div class="panel bar' +
      (ok ? " ok" : "") +
      '">' +
      '<span class="bar-label">' +
      this._esc(label) +
      "</span>" +
      '<span class="bar-spacer"></span>' +
      '<span class="bar-value">' +
      this._esc(value) +
      (this._valid(unit)
        ? '<span class="bar-unit">' + this._esc(unit) + "</span>"
        : "") +
      "</span>" +
      '<span class="bar-icon">' +
      iconSvg +
      "</span>" +
      "</div>"
    );
  }

  // -- Tool strip --------------------------------------------------------

  _renderToolStrip() {
    const s = this._st(this._eid("sensor", "tool_in_spindle"));
    if (!s) return "";
    const a = s.attributes || {};
    const toolNo = a.tool_number;
    const desc = a.description || s.state;

    const mag = this._state("sensor", "tools_in_magazine");
    const wh = this._state("sensor", "tools_in_warehouse");

    let figs = "";
    if (this._valid(mag))
      figs +=
        '<span class="tfig"><span class="tfig-n">' +
        this._esc(mag) +
        '</span><span class="tfig-l">Magazine</span></span>';
    if (this._valid(wh))
      figs +=
        '<span class="tfig"><span class="tfig-n">' +
        this._esc(wh) +
        '</span><span class="tfig-l">Warehouse</span></span>';

    return (
      '<div class="panel toolstrip">' +
      '<span class="ts-icon">' +
      this._svgEndmill() +
      "</span>" +
      '<span class="ts-info">' +
      (this._valid(toolNo)
        ? '<span class="ts-no">T' + this._esc(toolNo) + "</span>"
        : "") +
      '<span class="ts-name">' +
      this._esc(this._valid(desc) ? desc : "No tool") +
      "</span>" +
      "</span>" +
      '<span class="bar-spacer"></span>' +
      (figs ? '<span class="tfigs">' + figs + "</span>" : "") +
      "</div>"
    );
  }

  _renderToolOverview() {
    const s = this._st(this._eid("sensor", "tool_in_spindle"));
    if (!s) return "";
    const id = this._eid("image", "tool_in_spindle_image");
    return (
      '<div class="panel overview" data-action="more-info" data-arg="' +
      this._esc(id) +
      '">' +
      '<span class="ov-icon">' +
      this._svgEndmill() +
      "</span>" +
      '<span class="ov-label">Tool overview</span>' +
      "</div>"
    );
  }

  // -- Pause / Resume ----------------------------------------------------

  _renderActions() {
    const paused = this._state("sensor", "status") === "Pause";
    const suffix = paused ? "resume_program" : "pause_program";
    const btnS = this._st(this._eid("button", suffix));
    if (!btnS) return "";
    const dis = btnS.state === "unavailable";
    const icon = paused ? this._svgPlay() : this._svgPause();
    const text = paused ? "Resume program" : "Pause program";
    const action = paused ? "resume" : "pause";
    return (
      '<div class="panel actionbar' +
      (dis ? " disabled" : "") +
      '" data-action="' +
      action +
      '">' +
      '<span class="ab-icon">' +
      icon +
      "</span>" +
      '<span class="ab-label">' +
      text +
      "</span>" +
      "</div>"
    );
  }

  // -- Camera ------------------------------------------------------------

  _renderCamera() {
    if (!this._config.show_camera) return "";
    const pic = this._entityPicture("camera", "machine_camera");
    if (!pic) return "";
    return (
      '<div class="panel camera">' +
      '<img class="cam-img" src="' +
      this._esc(pic) +
      '" alt="Machine camera" data-action="more-info" data-arg="' +
      this._esc(this._eid("camera", "machine_camera")) +
      '"/>' +
      "</div>"
    );
  }

  // ---- inline SVG line icons -------------------------------------------

  _svgChevron() {
    return '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>';
  }
  _svgStopwatch() {
    return '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 2h6"/><path d="M12 2v2"/><circle cx="12" cy="13" r="8"/><path d="M12 13V9"/><path d="M18.5 6.5l1.5-1.5"/></svg>';
  }
  _svgVacuum() {
    return '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7h18"/><path d="M5 7v12"/><path d="M9 7v12"/><path d="M13 7v12"/><path d="M17 7v12"/></svg>';
  }
  _svgGauge() {
    return '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 18a8 8 0 1 1 16 0"/><path d="M12 18l4-5"/><circle cx="12" cy="18" r="1.2" fill="currentColor" stroke="none"/></svg>';
  }
  _svgSpray() {
    return '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 8h5v4h-5z"/><path d="M10 10H6l-2-2m2 2 2 2m-4 0 2-2"/><path d="M15 10h2"/><path d="M19 7v6"/><path d="M12 12v9"/></svg>';
  }
  _svgEndmill() {
    return '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3h6v6H9z"/><path d="M10 9v8l2 3 2-3V9"/></svg>';
  }
  _svgPause() {
    return '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 5v14"/><path d="M16 5v14"/></svg>';
  }
  _svgPlay() {
    return '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 5l12 7-12 7V5z"/></svg>';
  }

  // ---- styles ----------------------------------------------------------

  _css() {
    return `
      :host { display:block; }
      .card {
        max-width: 600px;
        margin: 0 auto;
        background: #2e2e2e;
        border-radius: 3px;
        padding: 8px;
        color: #ececec;
        font-family: -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
        font-weight: 400;
        box-sizing: border-box;
        -webkit-font-smoothing: antialiased;
      }
      #content { display:flex; flex-direction:column; gap:8px; }

      /* Header */
      .header {
        display:flex; align-items:baseline; justify-content:space-between;
        gap:12px; padding:6px 4px 0;
      }
      .hcockpit {
        font-size:20px; font-weight:300; letter-spacing:.3px;
        color:#ececec; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
      }
      .wordmark {
        font-size:14px; letter-spacing:1px; color:#ececec;
        white-space:nowrap; flex-shrink:0;
      }
      .wordmark b { font-weight:600; color:#fff; font-style:normal; }
      .wordmark i { font-weight:300; color:#dcdcdc; font-style:normal; }
      .hrule {
        height:2px; margin:2px 4px 2px;
        background:linear-gradient(90deg, #29b6c8, rgba(41,182,200,0));
      }

      /* Generic panel */
      .panel {
        background:#4a4a4a; border-radius:3px; padding:12px 14px;
        color:#ececec; box-sizing:border-box;
      }
      .panel.ok { background:${GREEN}; color:#fff; }

      /* Notification */
      .notif { display:flex; align-items:center; gap:12px; }
      .notif-msg {
        flex:1; min-width:0; font-size:14px; font-weight:400; color:#ececec;
        overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
      }
      .notif-chev { color:#bdbdbd; display:inline-flex; flex-shrink:0; }

      /* Dialog */
      .dialog.closed { color:#9a9a9a; font-size:14px; font-weight:400; }
      .dialog.open { border-left:4px solid #6a6a6a; }
      .dialog.sev-info { border-left-color:${SEV_INFO}; }
      .dialog.sev-warning { border-left-color:${SEV_WARN}; }
      .dialog.sev-error { border-left-color:${SEV_ERROR}; }
      .dcaption { font-size:15px; font-weight:600; color:#fff; }
      .dialog.sev-info .dcaption { color:#5fb4e0; }
      .dialog.sev-warning .dcaption { color:${SEV_WARN}; }
      .dialog.sev-error .dcaption { color:#ff6a6a; }
      .dtext { font-size:14px; font-weight:400; color:#e2e2e2; margin-top:4px; }
      .dbtns { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:8px; margin-top:12px; }
      .dbtn {
        cursor:pointer; background:#5a5a5a; color:#fff; border:1px solid #6c6c6c;
        border-radius:3px; padding:9px 16px; font-size:14px; font-weight:400;
        letter-spacing:.3px; transition:background .12s;
      }
      .dbtn:hover { background:#666; }
      .dbtn:active { background:${GREEN}; border-color:${GREEN}; }

      /* Program */
      .program { padding:12px 14px; }
      .prog-title {
        font-size:16px; font-weight:300; letter-spacing:.3px; color:#ececec;
        margin-bottom:10px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
      }
      .prog-inner {
        position:relative; height:170px; border-radius:3px;
        background:${GREEN}; overflow:hidden;
      }
      .prog-preview {
        position:absolute; top:10px; right:12px; bottom:34px;
        max-width:55%; max-height:calc(100% - 44px);
        object-fit:contain; cursor:pointer;
      }
      .prog-time { position:absolute; bottom:12px; display:flex; align-items:center; gap:8px; color:#fff; }
      .prog-time.left { left:14px; }
      .prog-time.right { right:14px; }
      .prog-time .ti { display:inline-flex; color:#fff; }
      .prog-time .tval {
        font-size:22px; font-weight:300; color:#fff;
        font-variant-numeric:tabular-nums; letter-spacing:.5px;
      }
      .prog-underline {
        position:absolute; left:0; bottom:0; height:2px;
        background:rgba(255,255,255,.85); transition:width .4s ease;
      }

      /* Value / consumable bars */
      .bar { display:flex; align-items:center; gap:12px; }
      .bar-label { font-size:14px; font-weight:400; letter-spacing:.4px; }
      .bar-spacer { flex:1; }
      .bar-value {
        font-size:22px; font-weight:300; color:#fff;
        font-variant-numeric:tabular-nums; white-space:nowrap;
      }
      .bar.ok .bar-value { color:#fff; }
      .panel.bar:not(.ok) .bar-value { color:#ececec; }
      .bar-unit { font-size:14px; font-weight:400; margin-left:5px; opacity:.85; }
      .bar-icon { display:inline-flex; color:#fff; flex-shrink:0; }
      .panel.bar:not(.ok) .bar-icon { color:#dcdcdc; }

      /* Tool strip */
      .toolstrip { display:flex; align-items:center; gap:12px; }
      .ts-icon { display:inline-flex; color:#dcdcdc; flex-shrink:0; }
      .ts-info { display:flex; align-items:baseline; gap:8px; min-width:0; }
      .ts-no { font-size:15px; font-weight:600; color:#fff; flex-shrink:0; }
      .ts-name {
        font-size:14px; font-weight:300; color:#dcdcdc;
        overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
      }
      .tfigs { display:flex; gap:18px; flex-shrink:0; }
      .tfig { display:flex; flex-direction:column; align-items:center; line-height:1.1; }
      .tfig-n { font-size:18px; font-weight:300; color:#fff; }
      .tfig-l { font-size:10px; font-weight:400; letter-spacing:.5px; text-transform:uppercase; color:#b5b5b5; }

      /* Tool overview (blue) */
      .overview {
        background:${BLUE}; color:#fff; cursor:pointer;
        display:flex; align-items:center; justify-content:center; gap:10px;
        letter-spacing:.5px; transition:filter .12s;
      }
      .overview:hover { filter:brightness(1.1); }
      .ov-icon { display:inline-flex; color:#fff; }
      .ov-label { font-size:15px; font-weight:400; }

      /* Action bar (pause / resume) */
      .actionbar {
        display:flex; align-items:center; justify-content:center; gap:10px;
        cursor:pointer; letter-spacing:.4px; transition:background .12s;
      }
      .actionbar:hover { background:#565656; }
      .ab-icon { display:inline-flex; color:#fff; }
      .ab-label { font-size:15px; font-weight:400; color:#fff; }
      .actionbar.disabled {
        opacity:.4; cursor:not-allowed; pointer-events:none;
      }

      /* Camera */
      .camera { padding:0; overflow:hidden; }
      .cam-img { width:100%; display:block; cursor:pointer; background:#111; }

      @media (max-width:460px) {
        .hcockpit { font-size:18px; }
        .prog-time .tval, .bar-value { font-size:20px; }
        .tfigs { gap:12px; }
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
