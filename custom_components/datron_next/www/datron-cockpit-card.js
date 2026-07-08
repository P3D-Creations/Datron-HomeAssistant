/**
 * DATRON Cockpit Card
 * A self-contained Home Assistant Lovelace card that reproduces the
 * DATRON Live "Cockpit" web UI look for the `datron_next` integration.
 *
 * No build step, no external dependencies. Loaded by HA as an ES module.
 */

const CARD_VERSION = "1.1.0";

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
    // Tool browser overlay state
    this._ovEl = null;
    this._ovOpen = false;
    this._ovTab = "magazine";
    this._ovSearch = "";
    this._toolCache = {}; // storage -> tools array (successful fetch)
    this._toolStatus = {}; // storage -> "loading" | "error" | "ok"
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
      '<div class="card"><div id="content"></div>' +
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
    } else if (action === "open-tools") {
      this._openOverlay(arg || "magazine");
    } else if (action === "ov-tab") {
      this._openTab(arg);
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

  // ---- tool browser overlay --------------------------------------------

  _openOverlay(tab) {
    if (!this._ovEl) return;
    this._ovOpen = true;
    this._ovSearch = "";
    this._ovEl.style.display = "block";
    document.addEventListener("keydown", this._onKeyDown, true);
    this._openTab(tab || "magazine");
  }

  _closeOverlay() {
    this._ovOpen = false;
    if (this._ovEl) {
      this._ovEl.style.display = "none";
      this._ovEl.innerHTML = "";
    }
    document.removeEventListener("keydown", this._onKeyDown, true);
  }

  _onKeyDown(ev) {
    if (this._ovOpen && ev.key === "Escape") {
      ev.stopPropagation();
      this._closeOverlay();
    }
  }

  _openTab(storage) {
    if (!this._ovEl) return;
    this._ovTab = storage;
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
      const prefix = this._config.prefix;
      const deviceId = (
        (this._hass &&
          this._hass.entities &&
          this._hass.entities["sensor." + prefix + "_status"]) ||
        {}
      ).device_id;
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
      ' placeholder="Search tool, name, category, article…"' +
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
      rows += this._toolRow(tools[i]);
    }
    list.innerHTML = rows;
  }

  _toolMatches(t, q) {
    const fields = [
      t.toolNumber,
      t.name,
      t.category,
      t.articleNumber,
      t.description,
      t.vendor,
    ];
    for (let i = 0; i < fields.length; i++) {
      const v = fields[i];
      if (v !== null && v !== undefined && String(v).toLowerCase().indexOf(q) !== -1)
        return true;
    }
    return false;
  }

  _toolRow(t) {
    const num = t.toolNumber !== null && t.toolNumber !== undefined ? t.toolNumber : "?";
    const name = this._valid(t.name) ? t.name : "Unnamed tool";
    const cat = this._valid(t.category) ? t.category : "";
    const desc = this._valid(t.description) ? t.description : "";
    const meta = [cat, desc].filter((x) => x).join(" · ");

    let wear = "";
    const life = this._num(t.currentTotalLife);
    const maxLife = this._num(t.maxToolLife);
    const path = this._num(t.currentTotalPath);
    const maxPath = this._num(t.maxToolPath);
    if (maxLife !== null && maxLife > 0 && life !== null) {
      const pct = Math.round((life / maxLife) * 100);
      wear = '<span class="ov-pct">' + pct + "%</span>";
      if (maxPath !== null && maxPath > 0 && path !== null) {
        const pp = Math.round((path / maxPath) * 100);
        wear += '<span class="ov-sub">' + pp + "% path</span>";
      } else {
        wear += '<span class="ov-sub">life</span>';
      }
    } else if (life !== null) {
      wear =
        '<span class="ov-pct">' +
        Math.round(life) +
        '</span><span class="ov-sub">min</span>';
    }

    return (
      '<div class="ov-row">' +
      '<span class="ov-ic">' +
      this._toolIcon(cat) +
      "</span>" +
      '<span class="ov-main">' +
      '<span class="ov-line1"><span class="ov-tno">T' +
      this._esc(num) +
      '</span><span class="ov-nm">' +
      this._esc(name) +
      "</span></span>" +
      (meta ? '<span class="ov-meta">' + this._esc(meta) + "</span>" : "") +
      "</span>" +
      (wear ? '<span class="ov-wear">' + wear + "</span>" : "") +
      "</div>"
    );
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

      /* Camera */
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
        display:flex; align-items:center; gap:12px;
        padding:9px 8px; border-radius:4px;
      }
      .ov-row:hover { background:#363636; }
      .ov-ic {
        display:inline-flex; align-items:center; justify-content:center;
        flex-shrink:0; width:34px; height:34px; border-radius:4px;
        background:#3a3a3a; color:${GREEN};
      }
      .ov-main { display:flex; flex-direction:column; min-width:0; flex:1; gap:2px; }
      .ov-line1 { display:flex; align-items:baseline; gap:8px; min-width:0; }
      .ov-tno { font-size:14px; font-weight:700; color:#fff; flex-shrink:0; font-variant-numeric:tabular-nums; }
      .ov-nm {
        font-size:14px; font-weight:400; color:#e6e6e6;
        overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
      }
      .ov-meta {
        font-size:12px; color:#9a9a9a;
        overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
      }
      .ov-wear {
        display:flex; flex-direction:column; align-items:flex-end; flex-shrink:0;
        line-height:1.1; text-align:right;
      }
      .ov-pct { font-size:16px; font-weight:300; color:#fff; font-variant-numeric:tabular-nums; }
      .ov-sub { font-size:10px; letter-spacing:.4px; text-transform:uppercase; color:#9a9a9a; }

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
