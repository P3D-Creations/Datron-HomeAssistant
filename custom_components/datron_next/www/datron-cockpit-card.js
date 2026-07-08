/**
 * DATRON Cockpit Card
 * A self-contained Home Assistant Lovelace card that reproduces the
 * DATRON Live "Cockpit" web UI look for the `datron_next` integration.
 *
 * No build step, no external dependencies. Loaded by HA as an ES module.
 */

const CARD_VERSION = "1.2.0";

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

// ---- Datron i18n maps (translate machine-native terms to English) --------

// Tool category (tool.category) -> human label
const CATEGORY_LABELS = {
  MillingEndFlat: "Flat Endmill",
  MillingEndBall: "Ball Endmill",
  MillingEndBullnose: "Corner Radius Endmill",
  MillingRadius: "External Radius Endmill",
  MillingFace: "Face Mill",
  MillingThread: "Thread Mill",
  MillingChamfer: "Chamfer Mill",
  MillingSlot: "T-Slot Mill",
  MillingDovetail: "Dovetail Mill",
  MillingLollipop: "Lollipop Mill",
  Drill: "Drill",
  Reamer: "Reamer",
  CounterSink: "Countersink",
  Graver: "Engraving Tool",
  Unspecified: "Special Tool",
};

// Geometry attribute -> human label
const GEOMETRY_LABELS = {
  Diameter: "Diameter",
  FluteLength: "Flute length",
  NumberOfFlutes: "Flute number",
  ShoulderDiameter: "Toric cut diameter",
  ShoulderLength: "Toric cut length",
  ShaftDiameter: "Shaft diameter",
  BodyLength: "Unclamping length",
  ReferenceBodyLength: "Reference body length",
  OverallLength: "Total length",
  CornerRadius: "Corner radius",
  FluteAngle: "Cutting angle",
  TaperAngle: "Cone angle",
  TipAngle: "Point angle",
  TipDiameter: "Point diameter",
  ThreadPitch: "Thread pitch",
  ThreadAngle: "Thread angle",
};

// Geometry attributes whose value is an angle (radians -> degrees)
const ANGLE_ATTRS = ["FluteAngle", "TaperAngle", "TipAngle", "ThreadAngle"];

// German -> English whole-word replacements (sorted longest-first so more
// specific terms win before their substrings).
const GERMAN_TERMS = [
  ["Einschneider", "Single-flute"],
  ["Zweischneider", "Two-flute"],
  ["Dreischneider", "Three-flute"],
  ["Mehrschneider", "Multi-flute"],
  ["Kugelfräser", "Ball nose mill"],
  ["Torusfräser", "Toroidal mill"],
  ["Schaftfräser", "End mill"],
  ["Planfräser", "Face mill"],
  ["Gravierstichel", "Engraving graver"],
  ["Bohrer", "Drill"],
  ["Reibahle", "Reamer"],
  ["Fasenfräser", "Chamfer mill"],
  ["Fase", "Chamfer"],
  ["Senker", "Countersink"],
  ["Gewindefräser", "Thread mill"],
  ["gewuchtet", "balanced"],
  ["poliert", "polished"],
  ["Planschneide", "flat face"],
  ["beschichtet", "coated"],
  ["unbeschichtet", "uncoated"],
  ["Schneide", "cutting edge"],
  ["für", "for"],
  ["mit", "with"],
  ["ohne", "without"],
].sort((a, b) => b[0].length - a[0].length);

class DatronCockpitCard extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._config = null;
    this._built = false;
    // Tool browser overlay state
    this._ovEl = null;
    this._ovOpen = false;
    this._ovTab = "magazine";
    this._ovSearch = "";
    this._toolCache = {}; // storage -> tools array (successful fetch)
    this._toolStatus = {}; // storage -> "loading" | "error" | "ok"
    this._ovDetailTool = null; // tool object shown in the detail popup, or null
    this._camSrc = null; // last MJPEG stream src applied to the persistent <img>
    // Notification history dropdown state
    this._notifOpen = false;
    this._notifHideProgress = true; // hide "Temporary" progress spam by default
    this._notifCache = null; // notifications array (successful fetch)
    this._notifStatus = "idle"; // "idle" | "loading" | "error" | "ok"
    this._onKeyDown = this._onKeyDown.bind(this);
    this.attachShadow({ mode: "open" });
  }

  static getConfigElement() {
    return document.createElement("datron-cockpit-card-editor");
  }

  static getStubConfig(hass) {
    let prefix = null;
    if (hass && hass.states) {
      for (const id in hass.states) {
        const m = /^sensor\.(.+)_machine_number$/.exec(id);
        if (m) {
          prefix = m[1];
          break;
        }
      }
    }
    if (!prefix) prefix = "datron_m8cube_1804685";
    return { prefix: prefix, show_camera: true };
  }

  setConfig(config) {
    if (!config || !config.prefix) {
      throw new Error(
        'datron-cockpit-card: "prefix" is required (the shared entity slug, e.g. datron_m8cube_1804685).'
      );
    }
    this._config = Object.assign(
      { show_camera: true, show_tools: true, title: null },
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

  // Resolve the HA device_id for this machine (used by response services).
  _deviceId() {
    const prefix = this._config && this._config.prefix;
    if (!prefix) return undefined;
    const ent =
      (this._hass &&
        this._hass.entities &&
        this._hass.entities["sensor." + prefix + "_status"]) ||
      {};
    return ent.device_id;
  }

  // Round a pressure/numeric state to 2 decimals; "--" when non-numeric.
  _fmtPressure(v) {
    const n = this._num(v);
    return n === null ? "--" : n.toFixed(2);
  }

  // ---- i18n / geometry helpers ----------------------------------------

  _trim(s) {
    if (typeof s !== "string") s = String(s);
    return s.indexOf(".") !== -1 ? s.replace(/0+$/, "").replace(/\.$/, "") : s;
  }

  // Convert a length in METERS to a trimmed mm string, or null.
  _mmVal(raw, dec) {
    const n = Number(raw);
    if (!isFinite(n)) return null;
    return this._trim((n * 1000).toFixed(dec == null ? 2 : dec));
  }

  // Prettify an unknown camelCase term: strip a leading "Milling", space caps.
  _prettify(s) {
    return String(s == null ? "" : s)
      .replace(/^Milling/, "")
      .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
      .replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2")
      .trim();
  }

  _translateCategory(cat) {
    if (cat == null || cat === "") return "";
    if (CATEGORY_LABELS[cat]) return CATEGORY_LABELS[cat];
    return this._prettify(cat);
  }

  // Whole-word German -> English replacement (handles umlauts via \p{L}).
  _translateTerms(str) {
    if (str == null) return "";
    let out = String(str);
    for (let i = 0; i < GERMAN_TERMS.length; i++) {
      const term = GERMAN_TERMS[i][0];
      const rep = GERMAN_TERMS[i][1];
      try {
        const esc = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        const re = new RegExp("(?<![\\p{L}])" + esc + "(?![\\p{L}])", "giu");
        out = out.replace(re, rep);
      } catch (e) {
        // Fallback: simple case-insensitive replace if lookbehind unsupported.
        try {
          out = out.split(new RegExp(term, "gi")).join(rep);
        } catch (e2) {
          /* leave as-is */
        }
      }
    }
    return out;
  }

  // Build {attribute: value} from a tool's nominalGeometry array.
  _geomMap(t) {
    const map = {};
    const ng = t && Array.isArray(t.nominalGeometry) ? t.nominalGeometry : [];
    for (let i = 0; i < ng.length; i++) {
      const e = ng[i];
      if (e && e.attribute != null) map[e.attribute] = e.value;
    }
    return map;
  }

  // Format a geometry attribute value with its unit; null when unusable.
  _fmtAttrValue(attr, raw) {
    if (raw === null || raw === undefined || raw === "") return null;
    const n = Number(raw);
    if (!isFinite(n)) return null;
    if (attr === "NumberOfFlutes") return String(Math.round(n));
    if (ANGLE_ATTRS.indexOf(attr) !== -1) {
      return this._trim(((n * 180) / Math.PI).toFixed(1)) + "°";
    }
    return this._trim((n * 1000).toFixed(3)) + " mm";
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
    this._updateCamera();
  }

  _buildShell() {
    this.shadowRoot.innerHTML =
      "<style>" +
      this._css() +
      "</style>" +
      '<div class="card"><div id="content"></div>' +
      '<div id="camera-host"></div>' +
      '<div id="overlay" class="ov-root" style="display:none"></div>' +
      "</div>";
    this._ovEl = this.shadowRoot.getElementById("overlay");
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
    // Delegated input handling (overlay search)
    this.shadowRoot.addEventListener("input", (ev) => {
      const t = ev.target;
      if (t && t.dataset && t.dataset.action === "ov-search") {
        this._ovSearch = t.value || "";
        this._renderOverlayList();
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
    } else if (action === "notif-toggle") {
      this._notifOpen = !this._notifOpen;
      if (this._notifOpen) {
        this._fetchNotifications();
      } else {
        this._update();
      }
    } else if (action === "notif-hideprogress") {
      this._notifHideProgress = !this._notifHideProgress;
      this._update();
    } else if (action === "open-tools") {
      this._openOverlay(arg || "magazine");
    } else if (action === "ov-tab") {
      this._openTab(arg);
    } else if (action === "ov-tool") {
      const p = (arg || "").split(":");
      this._openToolDetail(p[0], parseInt(p[1], 10));
    } else if (action === "ov-back") {
      this._backToList();
    } else if (action === "ov-close") {
      this._closeOverlay();
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
    const open = this._notifOpen;
    return (
      '<div class="notif-wrap">' +
      '<div class="panel notif tap" data-action="notif-toggle">' +
      '<span class="notif-msg">' +
      this._esc(msg) +
      "</span>" +
      '<span class="notif-chev' +
      (open ? " open" : "") +
      '">' +
      this._svgChevron() +
      "</span>" +
      "</div>" +
      (open ? this._renderNotifDropdown() : "") +
      "</div>"
    );
  }

  _notifType(n) {
    if (!n || typeof n !== "object") return "Info";
    const t = n.type || n.severity || n.level || "Info";
    return String(t);
  }

  _notifColor(type) {
    const t = String(type || "").toLowerCase();
    if (t === "error") return SEV_ERROR;
    if (t === "warning" || t === "warn") return SEV_WARN;
    if (t === "temporary") return "#8a8a8a";
    return SEV_INFO;
  }

  _notifMsg(n) {
    if (n == null) return "";
    if (typeof n === "string") return n;
    return n.message || n.text || n.caption || n.title || "";
  }

  _renderNotifDropdown() {
    const status = this._notifStatus;
    if (status === "loading") {
      return '<div class="notif-drop"><div class="notif-msg2">Loading notifications…</div></div>';
    }
    if (status === "error") {
      return '<div class="notif-drop"><div class="notif-msg2">Couldn\'t load notifications</div></div>';
    }
    const all = Array.isArray(this._notifCache) ? this._notifCache : [];
    const hide = this._notifHideProgress;
    let list = all;
    if (hide) {
      list = all.filter(
        (n) => this._notifType(n).toLowerCase() !== "temporary"
      );
    }
    const capped = list.slice(0, 60);

    const head =
      '<div class="notif-drophead">' +
      '<span class="notif-count">' +
      capped.length +
      (capped.length === 1 ? " entry" : " entries") +
      (list.length > capped.length ? " (of " + list.length + ")" : "") +
      "</span>" +
      '<span class="notif-spacer2"></span>' +
      '<button class="notif-progbtn" data-action="notif-hideprogress">' +
      (hide ? "Show progress" : "Hide progress") +
      "</button>" +
      "</div>";

    let body;
    if (!all.length) {
      body = '<div class="notif-msg2">No notifications</div>';
    } else if (!capped.length) {
      body = '<div class="notif-msg2">No notifications (progress hidden)</div>';
    } else {
      let rows = "";
      for (let i = 0; i < capped.length; i++) {
        const n = capped[i];
        const type = this._notifType(n);
        const isTemp = type.toLowerCase() === "temporary";
        rows +=
          '<div class="notif-item' +
          (isTemp ? " temp" : "") +
          '">' +
          '<span class="notif-dot" style="background:' +
          this._notifColor(type) +
          '" title="' +
          this._esc(type) +
          '"></span>' +
          '<span class="notif-itxt">' +
          this._esc(this._notifMsg(n)) +
          "</span>" +
          "</div>";
      }
      body = '<div class="notif-items">' + rows + "</div>";
    }

    return '<div class="notif-drop">' + head + body + "</div>";
  }

  async _fetchNotifications() {
    this._notifStatus = "loading";
    this._update();
    let list = null;
    let ok = false;
    try {
      const deviceId = this._deviceId();
      const res = await this._hass.callService(
        "datron_next",
        "get_notifications",
        deviceId ? { device_id: deviceId } : {},
        undefined,
        false,
        true
      );
      if (res && res.response) {
        list = res.response.notifications || [];
        ok = true;
      }
    } catch (e) {
      ok = false;
    }
    if (ok) {
      this._notifCache = list;
      this._notifStatus = "ok";
    } else {
      this._notifStatus = "error";
    }
    this._update();
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
    const value = this._fmtPressure(vacS.state);
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
    const value = this._fmtPressure(airS.state);
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
    const desc = this._translateTerms(a.description || s.state);

    const mag = this._state("sensor", "tools_in_magazine");
    const wh = this._state("sensor", "tools_in_warehouse");
    const tappable = this._config.show_tools !== false;

    let figs = "";
    if (this._valid(mag))
      figs +=
        '<span class="tfig' +
        (tappable ? " tap" : "") +
        '"' +
        (tappable ? ' data-action="open-tools" data-arg="magazine"' : "") +
        '><span class="tfig-n">' +
        this._esc(mag) +
        '</span><span class="tfig-l">Magazine</span></span>';
    if (this._valid(wh))
      figs +=
        '<span class="tfig' +
        (tappable ? " tap" : "") +
        '"' +
        (tappable ? ' data-action="open-tools" data-arg="warehouse"' : "") +
        '><span class="tfig-n">' +
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
    const useTools = this._config.show_tools !== false;
    const id = this._eid("image", "tool_in_spindle_image");
    const actionAttr = useTools
      ? 'data-action="open-tools" data-arg="magazine"'
      : 'data-action="more-info" data-arg="' + this._esc(id) + '"';
    return (
      '<div class="panel overview" ' +
      actionAttr +
      ">" +
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
  //
  // The camera lives in a PERSISTENT host outside #content so the MJPEG
  // stream <img> survives every hass update. Rebuilding it would restart the
  // stream and stutter the video, so we build the <img> once and only touch
  // its .src when (entity id, access_token) actually changes.

  _updateCamera() {
    const host = this.shadowRoot.getElementById("camera-host");
    if (!host) return;

    const hide = () => {
      if (host.innerHTML) host.innerHTML = "";
      this._camSrc = null;
    };

    if (!this._config.show_camera) return hide();

    const camId = "camera." + this._config.prefix + "_machine_camera";
    const s = this._st(camId);
    const token = s && s.attributes ? s.attributes.access_token : null;
    if (!s || !this._valid(token)) return hide();

    const src =
      "/api/camera_proxy_stream/" +
      encodeURIComponent(camId) +
      "?token=" +
      encodeURIComponent(token);

    let img = host.querySelector(".cam-img");
    if (!img) {
      host.innerHTML =
        '<div class="panel camera">' +
        '<img class="cam-img" alt="Machine camera" data-action="more-info" data-arg="' +
        this._esc(camId) +
        '"/>' +
        "</div>";
      img = host.querySelector(".cam-img");
      this._camSrc = null;
    }
    if (img && src !== this._camSrc) {
      img.src = src;
      this._camSrc = src;
    }
  }

  // ---- tool browser overlay --------------------------------------------

  _openOverlay(tab) {
    if (!this._ovEl) return;
    this._ovOpen = true;
    this._ovSearch = "";
    this._ovDetailTool = null;
    this._ovEl.style.display = "block";
    document.addEventListener("keydown", this._onKeyDown, true);
    this._openTab(tab || "magazine");
  }

  _closeOverlay() {
    this._ovOpen = false;
    this._ovDetailTool = null;
    if (this._ovEl) {
      this._ovEl.style.display = "none";
      this._ovEl.innerHTML = "";
    }
    document.removeEventListener("keydown", this._onKeyDown, true);
  }

  _onKeyDown(ev) {
    if (this._ovOpen && ev.key === "Escape") {
      ev.stopPropagation();
      // Esc from the detail popup returns to the list; from the list, closes.
      if (this._ovDetailTool) this._backToList();
      else this._closeOverlay();
    }
  }

  _openTab(storage) {
    if (!this._ovEl) return;
    this._ovTab = storage;
    this._ovDetailTool = null;
    this._renderOverlayShell();
    if (this._toolStatus[storage] === "ok") {
      this._renderOverlayList();
    } else {
      this._fetchTools(storage);
    }
  }

  async _fetchTools(storage) {
    this._toolStatus[storage] = "loading";
    this._renderOverlayList();
    let tools = [];
    let ok = false;
    try {
      const deviceId = this._deviceId();
      const data = { storage: storage };
      if (deviceId) data.device_id = deviceId;
      const res = await this._hass.callService(
        "datron_next",
        "get_tools",
        data,
        undefined,
        false,
        true
      );
      if (res && res.response) {
        tools = res.response.tools || [];
        ok = true;
      }
    } catch (e) {
      ok = false;
    }
    if (ok) {
      this._toolCache[storage] = tools;
      this._toolStatus[storage] = "ok";
    } else {
      this._toolStatus[storage] = "error";
    }
    if (this._ovOpen && this._ovTab === storage) this._renderOverlayList();
  }

  _renderOverlayShell() {
    if (!this._ovEl) return;
    const tabs = [
      ["magazine", "Magazine"],
      ["warehouse", "Warehouse"],
      ["program", "Program"],
    ];
    let tabHtml = "";
    for (let i = 0; i < tabs.length; i++) {
      const key = tabs[i][0];
      tabHtml +=
        '<button class="ov-tab' +
        (this._ovTab === key ? " active" : "") +
        '" data-action="ov-tab" data-arg="' +
        key +
        '">' +
        tabs[i][1] +
        "</button>";
    }
    this._ovEl.innerHTML =
      '<div class="ov-backdrop" data-action="ov-close"></div>' +
      '<div class="ov-panel" role="dialog" aria-label="Tools">' +
      '<div class="ov-head">' +
      '<span class="ov-title">Tools</span>' +
      '<span class="ov-count" id="ov-count"></span>' +
      '<span class="ov-spacer"></span>' +
      '<button class="ov-x" data-action="ov-close" aria-label="Close">' +
      this._svgClose() +
      "</button>" +
      "</div>" +
      '<div class="ov-tabs">' +
      tabHtml +
      "</div>" +
      '<div class="ov-searchwrap">' +
      '<input class="ov-search" type="text" data-action="ov-search"' +
      ' placeholder="Search name, category, ⌀, article…"' +
      ' value="' +
      this._esc(this._ovSearch) +
      '"/>' +
      "</div>" +
      '<div class="ov-list" id="ov-list"></div>' +
      "</div>";
  }

  _renderOverlayList() {
    if (!this._ovEl) return;
    const list = this._ovEl.querySelector("#ov-list");
    const countEl = this._ovEl.querySelector("#ov-count");
    if (!list) return;
    const storage = this._ovTab;
    const status = this._toolStatus[storage];

    if (status === "loading") {
      if (countEl) countEl.textContent = "";
      list.innerHTML = '<div class="ov-msg">Loading tools…</div>';
      return;
    }
    if (status === "error") {
      if (countEl) countEl.textContent = "";
      list.innerHTML = '<div class="ov-msg">Couldn\'t load tools</div>';
      return;
    }

    const all = this._toolCache[storage] || [];
    const q = (this._ovSearch || "").trim().toLowerCase();
    const tools = q ? all.filter((t) => this._toolMatches(t, q)) : all;

    if (countEl) {
      const n = tools.length;
      countEl.textContent = n + (n === 1 ? " tool" : " tools");
    }

    if (!all.length) {
      list.innerHTML =
        '<div class="ov-msg">' +
        (storage === "program" ? "No program tools" : "No tools") +
        "</div>";
      return;
    }
    if (!tools.length) {
      list.innerHTML = '<div class="ov-msg">No matching tools</div>';
      return;
    }

    let rows = "";
    for (let i = 0; i < tools.length; i++) {
      const idx = all.indexOf(tools[i]);
      rows += this._toolRow(tools[i], idx, storage);
    }
    list.innerHTML = rows;
  }

  _toolMatches(t, q) {
    const fields = [
      t.toolNumber,
      t.name,
      this._translateTerms(t.name),
      t.category,
      this._translateCategory(t.category),
      t.articleNumber,
      t.description,
      t.vendor,
    ];
    const gm = this._geomMap(t);
    if (gm.Diameter != null) {
      const d = this._mmVal(gm.Diameter, 2);
      if (d !== null) fields.push(d);
    }
    for (let i = 0; i < fields.length; i++) {
      const v = fields[i];
      if (v !== null && v !== undefined && String(v).toLowerCase().indexOf(q) !== -1)
        return true;
    }
    return false;
  }

  // Spec-first row: characteristics up top, translated name + article below.
  _toolRow(t, idx, storage) {
    const cat = this._valid(t.category) ? t.category : "";
    const gm = this._geomMap(t);

    const pieces = [];
    if (gm.Diameter != null) {
      const d = this._mmVal(gm.Diameter, 2);
      if (d !== null) pieces.push("⌀" + d);
    }
    if (gm.NumberOfFlutes != null) {
      const n = Number(gm.NumberOfFlutes);
      if (isFinite(n)) pieces.push(Math.round(n) + " FL");
    }
    if (gm.FluteLength != null) {
      const f = this._mmVal(gm.FluteLength, 2);
      if (f !== null) pieces.push("FL " + f);
    }
    if (gm.BodyLength != null) {
      const b = this._mmVal(gm.BodyLength, 2);
      if (b !== null) pieces.push("reach " + b);
    }
    const catLabel = this._translateCategory(cat);
    if (catLabel) pieces.push(catLabel);
    const spec = pieces.join(" · ") || catLabel || "Tool";

    const name = this._valid(t.name)
      ? this._translateTerms(t.name)
      : "Unnamed tool";
    const art = this._valid(t.articleNumber) ? t.articleNumber : "";

    return (
      '<div class="ov-row" data-action="ov-tool" data-arg="' +
      this._esc(storage + ":" + idx) +
      '">' +
      '<span class="ov-ic">' +
      this._toolIcon(cat) +
      "</span>" +
      '<span class="ov-main">' +
      '<span class="ov-spec">' +
      this._esc(spec) +
      "</span>" +
      '<span class="ov-line2">' +
      '<span class="ov-nm">' +
      this._esc(name) +
      "</span>" +
      (art ? '<span class="ov-art">' + this._esc(art) + "</span>" : "") +
      "</span>" +
      "</span>" +
      '<span class="ov-chev">' +
      this._svgChevronRight() +
      "</span>" +
      "</div>"
    );
  }

  // ---- tool detail popup -----------------------------------------------

  _openToolDetail(storage, index) {
    const arr = this._toolCache[storage] || [];
    const t = arr[index];
    if (!t) return;
    this._ovDetailTool = t;
    this._renderDetail(t);
  }

  _backToList() {
    this._ovDetailTool = null;
    this._renderOverlayShell();
    this._renderOverlayList();
  }

  _dRow(attr, val) {
    const label = GEOMETRY_LABELS[attr] || this._prettify(attr);
    return (
      '<div class="det-drow"><span class="det-dlabel">' +
      this._esc(label) +
      '</span><span class="det-dval">' +
      this._esc(val) +
      "</span></div>"
    );
  }

  _detailGroupsHtml(t, gm) {
    const groups = [
      ["fluteGroup", "#f7931e"],
      ["toricCutGroup", "#0064a0"],
      ["shankGroup", "#8bc53f"],
      ["toolLengthGroup", "#8a8a8a"],
    ];
    const used = {};
    let html = "";
    for (let g = 0; g < groups.length; g++) {
      const key = groups[g][0];
      const color = groups[g][1];
      const attrs = Array.isArray(t[key]) ? t[key] : [];
      let rows = "";
      for (let i = 0; i < attrs.length; i++) {
        const attr = attrs[i];
        if (!(attr in gm)) continue;
        const val = this._fmtAttrValue(attr, gm[attr]);
        if (val === null) continue;
        used[attr] = true;
        rows += this._dRow(attr, val);
      }
      if (rows) {
        html +=
          '<div class="det-group" style="border-left-color:' +
          color +
          '">' +
          rows +
          "</div>";
      }
    }
    // Any nominalGeometry attributes not covered by a group.
    let extra = "";
    for (const attr in gm) {
      if (used[attr]) continue;
      const val = this._fmtAttrValue(attr, gm[attr]);
      if (val === null) continue;
      extra += this._dRow(attr, val);
    }
    if (extra) {
      html += '<div class="det-group ungrouped">' + extra + "</div>";
    }
    return html;
  }

  _detailLifeHtml(t) {
    const maxLife = this._num(t.maxToolLife);
    const life = this._num(t.currentTotalLife);
    const maxPath = this._num(t.maxToolPath);
    const path = this._num(t.currentTotalPath);
    let badges = "";
    if (maxLife !== null && maxLife > 0) {
      const p = Math.round(((life || 0) / maxLife) * 100);
      badges += '<span class="det-life">' + p + "% life</span>";
    }
    if (maxPath !== null && maxPath > 0) {
      const p = Math.round(((path || 0) / maxPath) * 100);
      badges += '<span class="det-life">' + p + "% path</span>";
    }
    return badges;
  }

  _detailInfoRow(icon, text) {
    if (!this._valid(text)) return "";
    return (
      '<div class="det-inforow"><span class="det-infoic">' +
      icon +
      '</span><span class="det-infotext">' +
      this._esc(text) +
      "</span></div>"
    );
  }

  _renderDetail(t) {
    if (!this._ovEl) return;
    const cat = this._valid(t.category) ? t.category : "";
    const name = this._valid(t.name)
      ? this._translateTerms(t.name)
      : "Unnamed tool";
    const art = this._valid(t.articleNumber) ? t.articleNumber : "";
    const desc = this._valid(t.description)
      ? this._translateTerms(t.description)
      : "";
    const comment = this._valid(t.comment) ? t.comment : "";
    const vendor = this._valid(t.vendor) ? t.vendor : "";
    const catLabel = this._translateCategory(cat);
    const gm = this._geomMap(t);

    const lifeHtml = this._detailLifeHtml(t);
    const groupsHtml = this._detailGroupsHtml(t, gm);

    let info = "";
    info += this._detailInfoRow(this._svgInfo(), desc);
    info += this._detailInfoRow(this._svgComment(), comment);
    info += this._detailInfoRow(this._svgFactory(), vendor);
    info += this._detailInfoRow(this._svgTag(), art);

    this._ovEl.innerHTML =
      '<div class="ov-backdrop" data-action="ov-close"></div>' +
      '<div class="ov-panel det-panel" role="dialog" aria-label="Tool detail">' +
      '<div class="ov-head det-head">' +
      '<button class="ov-backbtn" data-action="ov-back" aria-label="Back">' +
      this._svgChevronLeft() +
      "</button>" +
      '<span class="det-title">' +
      this._esc(name) +
      "</span>" +
      '<span class="ov-spacer"></span>' +
      (art ? '<span class="det-art-h">' + this._esc(art) + "</span>" : "") +
      '<button class="ov-x" data-action="ov-close" aria-label="Close">' +
      this._svgClose() +
      "</button>" +
      "</div>" +
      '<div class="det-body">' +
      '<div class="det-hero">' +
      '<span class="det-ic">' +
      this._toolIcon(cat) +
      "</span>" +
      '<div class="det-herometa">' +
      (catLabel ? '<div class="det-cat">' + this._esc(catLabel) + "</div>" : "") +
      (lifeHtml ? '<div class="det-lives">' + lifeHtml + "</div>" : "") +
      "</div>" +
      "</div>" +
      (info ? '<div class="det-info">' + info + "</div>" : "") +
      (groupsHtml
        ? '<div class="det-section-title">Tool data</div>' +
          '<div class="det-groups">' +
          groupsHtml +
          "</div>"
        : "") +
      "</div>" +
      "</div>";
  }

  _toolIcon(category) {
    const c = (category || "").toLowerCase();
    if (c.indexOf("drill") !== -1) return this._svgTDrill();
    if (c.indexOf("ball") !== -1) return this._svgTBall();
    if (c.indexOf("face") !== -1) return this._svgTFace();
    if (c.indexOf("flat") !== -1) return this._svgTFlat();
    if (c.indexOf("graver") !== -1) return this._svgTGraver();
    if (c.indexOf("reamer") !== -1) return this._svgTReamer();
    if (c.indexOf("thread") !== -1) return this._svgTThread();
    return this._svgTEnd();
  }

  // ---- inline SVG line icons -------------------------------------------

  _svgChevron() {
    return '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>';
  }
  _svgChevronRight() {
    return '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg>';
  }
  _svgChevronLeft() {
    return '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 6l-6 6 6 6"/></svg>';
  }
  _svgInfo() {
    return '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 8h.01"/></svg>';
  }
  _svgComment() {
    return '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 5h16v11H8l-4 4V5z"/></svg>';
  }
  _svgFactory() {
    return '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 20h18"/><path d="M4 20V10l5 3V10l5 3V6l6 3v11"/></svg>';
  }
  _svgTag() {
    return '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12l8-8h8v8l-8 8-8-8z"/><circle cx="15" cy="9" r="1.4" fill="currentColor" stroke="none"/></svg>';
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
  _svgClose() {
    return '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 6l12 12"/><path d="M18 6l-12 12"/></svg>';
  }
  // Tool category icons (22x22)
  _svgTEnd() {
    return '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3h6v5H9z"/><path d="M10 8v9l2 3 2-3V8"/></svg>';
  }
  _svgTFlat() {
    return '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3h6v5H9z"/><path d="M10 8v11h4V8"/></svg>';
  }
  _svgTBall() {
    return '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3h6v5H9z"/><path d="M10 8v8"/><path d="M14 8v8"/><path d="M10 16a2 2 0 0 0 4 0"/></svg>';
  }
  _svgTFace() {
    return '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 3h4v4h-4z"/><path d="M7 7h10l-2 12H9L7 7z"/></svg>';
  }
  _svgTDrill() {
    return '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3h6v5H9z"/><path d="M10 8v9l2 3 2-3V8"/><path d="M10 11l4-2"/><path d="M10 14l4-2"/></svg>';
  }
  _svgTGraver() {
    return '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3h6v5H9z"/><path d="M10 8h4l-2 12z"/></svg>';
  }
  _svgTReamer() {
    return '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3h6v5H9z"/><path d="M11 8v11h2V8"/><path d="M9 11l6 0"/><path d="M9 15l6 0"/></svg>';
  }
  _svgTThread() {
    return '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3h6v5H9z"/><path d="M10 8v10l2 2 2-2V8"/><path d="M10 11l4 1"/><path d="M10 14l4 1"/><path d="M10 17l4 1"/></svg>';
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
      .notif-wrap { display:flex; flex-direction:column; }
      .notif { display:flex; align-items:center; gap:12px; }
      .notif.tap { cursor:pointer; transition:background .12s; }
      .notif.tap:hover { background:#565656; }
      .notif-msg {
        flex:1; min-width:0; font-size:14px; font-weight:400; color:#ececec;
        overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
      }
      .notif-chev {
        color:#bdbdbd; display:inline-flex; flex-shrink:0;
        transition:transform .18s ease;
      }
      .notif-chev.open { transform:rotate(180deg); }
      .notif-drop {
        margin-top:4px; background:#3a3a3a; border:1px solid #454545;
        border-radius:3px; overflow:hidden;
      }
      .notif-drophead {
        display:flex; align-items:center; gap:8px;
        padding:8px 12px; border-bottom:1px solid #4a4a4a;
      }
      .notif-count { font-size:12px; color:#b5b5b5; font-variant-numeric:tabular-nums; }
      .notif-spacer2 { flex:1; }
      .notif-progbtn {
        cursor:pointer; background:#4a4a4a; color:#dcdcdc; border:1px solid #565656;
        border-radius:3px; padding:5px 10px; font-size:12px; letter-spacing:.3px;
        transition:background .12s, color .12s;
      }
      .notif-progbtn:hover { background:#565656; color:#fff; }
      .notif-items { max-height:280px; overflow-y:auto; }
      .notif-item {
        display:flex; align-items:flex-start; gap:10px;
        padding:8px 12px; border-bottom:1px solid #333;
      }
      .notif-item:last-child { border-bottom:none; }
      .notif-item.temp { opacity:.5; }
      .notif-dot {
        width:9px; height:9px; border-radius:50%; margin-top:5px; flex-shrink:0;
      }
      .notif-itxt { font-size:13px; color:#e2e2e2; line-height:1.35; word-break:break-word; }
      .notif-item.temp .notif-itxt { color:#b5b5b5; }
      .notif-msg2 { padding:16px 12px; text-align:center; color:#9a9a9a; font-size:13px; }

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
      .tfig.tap { cursor:pointer; border-radius:3px; padding:2px 6px; transition:background .12s; }
      .tfig.tap:hover { background:rgba(255,255,255,.08); }
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

      /* Camera (persistent host, MJPEG stream) */
      #camera-host:not(:empty) { margin-top:8px; }
      .camera { padding:0; overflow:hidden; }
      .cam-img { width:100%; display:block; cursor:pointer; background:#111; }

      /* Tool browser overlay */
      .ov-root { position:absolute; inset:0; z-index:20; }
      .ov-backdrop {
        position:fixed; inset:0; background:rgba(0,0,0,.55);
        backdrop-filter:blur(1px);
      }
      .ov-panel {
        position:fixed; top:50%; left:50%; transform:translate(-50%,-50%);
        width:min(560px, calc(100vw - 24px)); max-height:82vh;
        display:flex; flex-direction:column;
        background:#2e2e2e; border:1px solid #454545; border-radius:6px;
        box-shadow:0 12px 40px rgba(0,0,0,.5);
        color:#ececec; overflow:hidden;
        font-family:-apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      }
      .ov-head { display:flex; align-items:center; gap:10px; padding:12px 14px 8px; }
      .ov-title { font-size:17px; font-weight:400; color:#fff; }
      .ov-count { font-size:12px; color:#b5b5b5; font-variant-numeric:tabular-nums; }
      .ov-spacer { flex:1; }
      .ov-x {
        display:inline-flex; align-items:center; justify-content:center;
        width:30px; height:30px; padding:0; cursor:pointer;
        background:transparent; border:none; color:#cfcfcf; border-radius:4px;
        transition:background .12s, color .12s;
      }
      .ov-x:hover { background:#3a3a3a; color:#fff; }
      .ov-tabs { display:flex; gap:6px; padding:0 14px 10px; flex-wrap:wrap; }
      .ov-tab {
        cursor:pointer; background:#3a3a3a; color:#cfcfcf; border:1px solid #4a4a4a;
        border-radius:3px; padding:7px 14px; font-size:13px; letter-spacing:.3px;
        transition:background .12s, color .12s, border-color .12s;
      }
      .ov-tab:hover { background:#444; color:#fff; }
      .ov-tab.active { background:${GREEN}; border-color:${GREEN}; color:#232323; font-weight:600; }
      .ov-searchwrap { padding:0 14px 10px; }
      .ov-search {
        width:100%; box-sizing:border-box; background:#3a3a3a; color:#ececec;
        border:1px solid #4a4a4a; border-radius:3px; padding:9px 11px;
        font-size:14px; outline:none; transition:border-color .12s;
      }
      .ov-search:focus { border-color:${GREEN}; }
      .ov-search::placeholder { color:#8f8f8f; }
      .ov-list {
        max-height:60vh; overflow-y:auto; padding:0 8px 10px;
        display:flex; flex-direction:column; gap:2px;
      }
      .ov-msg { padding:22px 8px; text-align:center; color:#9a9a9a; font-size:14px; }
      .ov-row {
        display:flex; align-items:center; gap:12px; cursor:pointer;
        padding:9px 8px; border-radius:4px;
      }
      .ov-row:hover { background:#363636; }
      .ov-ic {
        display:inline-flex; align-items:center; justify-content:center;
        flex-shrink:0; width:34px; height:34px; border-radius:4px;
        background:#3a3a3a; color:${GREEN};
      }
      .ov-main { display:flex; flex-direction:column; min-width:0; flex:1; gap:2px; }
      .ov-spec {
        font-size:13.5px; font-weight:500; color:#fff; letter-spacing:.2px;
        overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
      }
      .ov-line2 { display:flex; align-items:baseline; gap:8px; min-width:0; }
      .ov-nm {
        font-size:12.5px; font-weight:400; color:#bdbdbd; min-width:0;
        overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
      }
      .ov-art {
        font-size:11px; color:#8f8f8f; flex-shrink:0; font-variant-numeric:tabular-nums;
      }
      .ov-chev { display:inline-flex; color:#6f6f6f; flex-shrink:0; }

      /* Tool detail popup */
      .det-panel { }
      .det-head { padding-left:6px; }
      .ov-backbtn {
        display:inline-flex; align-items:center; justify-content:center;
        width:30px; height:30px; padding:0; cursor:pointer;
        background:transparent; border:none; color:#cfcfcf; border-radius:4px;
        transition:background .12s, color .12s; flex-shrink:0;
      }
      .ov-backbtn:hover { background:#3a3a3a; color:#fff; }
      .det-title {
        font-size:16px; font-weight:400; color:#fff; min-width:0;
        overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
      }
      .det-art-h { font-size:12px; color:#b5b5b5; font-variant-numeric:tabular-nums; flex-shrink:0; }
      .det-body { overflow-y:auto; padding:4px 16px 16px; max-height:66vh; }
      .det-hero {
        display:flex; align-items:center; gap:16px; padding:10px 0 14px;
      }
      .det-ic {
        display:inline-flex; align-items:center; justify-content:center;
        width:72px; height:72px; border-radius:8px; flex-shrink:0;
        background:#3a3a3a; color:${GREEN};
      }
      .det-ic svg { width:52px; height:52px; }
      .det-herometa { display:flex; flex-direction:column; gap:8px; min-width:0; }
      .det-cat { font-size:15px; font-weight:500; color:#ececec; }
      .det-lives { display:flex; flex-wrap:wrap; gap:6px; }
      .det-life {
        font-size:12px; color:#232323; background:${GREEN};
        border-radius:10px; padding:3px 10px; font-weight:600;
        font-variant-numeric:tabular-nums;
      }
      .det-info { display:flex; flex-direction:column; gap:2px; padding:4px 0 6px; }
      .det-inforow { display:flex; align-items:flex-start; gap:10px; padding:6px 0; }
      .det-infoic { display:inline-flex; color:#8f8f8f; flex-shrink:0; margin-top:1px; }
      .det-infotext { font-size:13px; color:#dcdcdc; line-height:1.4; word-break:break-word; }
      .det-section-title {
        font-size:12px; text-transform:uppercase; letter-spacing:.6px;
        color:#8f8f8f; margin:12px 0 8px;
      }
      .det-groups { display:flex; flex-direction:column; gap:8px; }
      .det-group {
        border-left:3px solid #8a8a8a; background:#363636; border-radius:0 4px 4px 0;
        padding:4px 12px;
      }
      .det-group.ungrouped { border-left-color:#5a5a5a; }
      .det-drow {
        display:flex; align-items:baseline; justify-content:space-between; gap:12px;
        padding:6px 0; border-bottom:1px solid #414141;
      }
      .det-drow:last-child { border-bottom:none; }
      .det-dlabel { font-size:13px; color:#bdbdbd; }
      .det-dval { font-size:13px; color:#fff; font-variant-numeric:tabular-nums; text-align:right; white-space:nowrap; }

      @media (max-width:460px) {
        .hcockpit { font-size:18px; }
        .prog-time .tval, .bar-value { font-size:20px; }
        .tfigs { gap:12px; }
      }
    `;
  }
}

// ---- Visual configuration editor ---------------------------------------

class DatronCockpitCardEditor extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._config = {};
    this._built = false;
    this.attachShadow({ mode: "open" });
  }

  setConfig(config) {
    this._config = Object.assign({}, config || {});
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _machines() {
    const out = [];
    const states = (this._hass && this._hass.states) || null;
    if (!states) return out;
    for (const id in states) {
      const m = /^sensor\.(.+)_machine_number$/.exec(id);
      if (!m) continue;
      const prefix = m[1];
      let label = null;
      const typeS = states["sensor." + prefix + "_machine_type"];
      const statusS = states["sensor." + prefix + "_status"];
      if (typeS && typeS.attributes && typeS.attributes.friendly_name)
        label = typeS.attributes.friendly_name;
      else if (statusS && statusS.attributes && statusS.attributes.friendly_name)
        label = statusS.attributes.friendly_name;
      else if (states[id] && states[id].state) label = states[id].state;
      // Trim the per-entity suffix so the picker reads like the device name,
      // e.g. "Datron M8Cube (1804685) Machine Type" -> "Datron M8Cube (1804685)".
      if (label)
        label = label.replace(/\s+(Machine Type|Status|Machine Number)$/i, "").trim();
      out.push({ prefix: prefix, label: label || prefix });
    }
    out.sort((a, b) => a.label.localeCompare(b.label));
    return out;
  }

  _render() {
    if (!this.shadowRoot) return;
    if (!this._built) {
      this._buildForm();
      this._built = true;
    }
    this._populateMachines();
    this._syncValues();
  }

  _buildForm() {
    this.shadowRoot.innerHTML =
      "<style>" +
      this._css() +
      "</style>" +
      '<div class="ed">' +
      '<label class="row"><span class="lbl">Machine</span>' +
      '<select id="ed-prefix" class="ctl"></select></label>' +
      '<label class="row"><span class="lbl">Title</span>' +
      '<input id="ed-title" class="ctl" type="text" placeholder="Optional header title"/></label>' +
      '<label class="row cb"><input id="ed-camera" type="checkbox"/>' +
      '<span class="lbl">Show camera</span></label>' +
      '<label class="row cb"><input id="ed-tools" type="checkbox"/>' +
      '<span class="lbl">Show tool browser</span></label>' +
      "</div>";
    const onChange = () => this._emit();
    const pref = this.shadowRoot.getElementById("ed-prefix");
    const title = this.shadowRoot.getElementById("ed-title");
    const cam = this.shadowRoot.getElementById("ed-camera");
    const tools = this.shadowRoot.getElementById("ed-tools");
    if (pref) pref.addEventListener("change", onChange);
    if (title) title.addEventListener("input", onChange);
    if (cam) cam.addEventListener("change", onChange);
    if (tools) tools.addEventListener("change", onChange);
  }

  _populateMachines() {
    const sel = this.shadowRoot.getElementById("ed-prefix");
    if (!sel) return;
    const machines = this._machines();
    const current = this._config.prefix || "";
    let hasCurrent = false;
    let html = "";
    for (let i = 0; i < machines.length; i++) {
      if (machines[i].prefix === current) hasCurrent = true;
      html +=
        '<option value="' +
        this._esc(machines[i].prefix) +
        '">' +
        this._esc(machines[i].label) +
        "</option>";
    }
    // Keep the configured prefix selectable even if not discoverable yet.
    if (current && !hasCurrent) {
      html =
        '<option value="' +
        this._esc(current) +
        '">' +
        this._esc(current) +
        "</option>" +
        html;
    }
    if (!machines.length && !current) {
      html = '<option value="">No machines found</option>';
    }
    sel.innerHTML = html;
    if (current) sel.value = current;
  }

  _syncValues() {
    const cfg = this._config || {};
    const active = this.shadowRoot.activeElement;
    const title = this.shadowRoot.getElementById("ed-title");
    const cam = this.shadowRoot.getElementById("ed-camera");
    const tools = this.shadowRoot.getElementById("ed-tools");
    const pref = this.shadowRoot.getElementById("ed-prefix");
    if (pref && pref !== active && cfg.prefix) pref.value = cfg.prefix;
    if (title && title !== active) title.value = cfg.title || "";
    if (cam && cam !== active) cam.checked = cfg.show_camera !== false;
    if (tools && tools !== active) tools.checked = cfg.show_tools !== false;
  }

  _emit() {
    const cfg = Object.assign({}, this._config);
    const pref = this.shadowRoot.getElementById("ed-prefix");
    const title = this.shadowRoot.getElementById("ed-title");
    const cam = this.shadowRoot.getElementById("ed-camera");
    const tools = this.shadowRoot.getElementById("ed-tools");
    if (pref && pref.value) cfg.prefix = pref.value;
    const tv = title ? (title.value || "").trim() : "";
    if (tv) cfg.title = tv;
    else delete cfg.title;
    cfg.show_camera = cam ? cam.checked : true;
    cfg.show_tools = tools ? tools.checked : true;
    this._config = cfg;
    this.dispatchEvent(
      new CustomEvent("config-changed", {
        detail: { config: cfg },
        bubbles: true,
        composed: true,
      })
    );
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

  _css() {
    return `
      :host { display:block; }
      .ed { display:flex; flex-direction:column; gap:14px; padding:4px 2px; }
      .row { display:flex; flex-direction:column; gap:6px; }
      .row.cb { flex-direction:row; align-items:center; gap:10px; }
      .lbl { font-size:13px; color:var(--secondary-text-color,#8a8a8a); font-weight:500; }
      .row.cb .lbl { color:var(--primary-text-color,#212121); font-weight:400; font-size:14px; }
      .ctl {
        width:100%; box-sizing:border-box; padding:9px 10px; font-size:14px;
        border-radius:4px; border:1px solid var(--divider-color,#c7c7c7);
        background:var(--card-background-color,#fff);
        color:var(--primary-text-color,#212121); outline:none;
      }
      .ctl:focus { border-color:${GREEN}; }
      input[type=checkbox] { width:18px; height:18px; accent-color:${GREEN}; cursor:pointer; }
    `;
  }
}

if (!customElements.get("datron-cockpit-card-editor")) {
  customElements.define("datron-cockpit-card-editor", DatronCockpitCardEditor);
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
