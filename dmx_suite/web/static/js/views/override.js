// Override page (v3 "Busk"): play a panel of buttons and faders over the running show, or edit the panels.
// Buttons act on press and let go (latches toggle on press); faders send their value.
import { openWheel } from "../colourwheel.js";
import { api, attempt, cmd, get, toast } from "../api.js";
import { $, el } from "../dom.js";
import { t } from "../i18n.js";
import { onShow } from "../nav.js";
import { live, onCatalogue, onState, refreshCatalogue } from "../state.js";

const TYPES = ["colour", "flash", "solo", "effect", "go", "fader", "haze"];
let panelKey = null;
let file = null; // panels.yaml as data (editing)
let saved = "";
let colours = {};

function current() {
  const panels = live.cat.panels || {};
  if (panelKey && panels[panelKey]) return panelKey;
  const show = live.state?.now.show;
  return show && panels[show] ? show : panels.default ? "default" : Object.keys(panels)[0] || null;
}

// ---------------------------------------------------------------- playing

function renderPlay() {
  const panels = live.cat.panels || {};
  panelKey = current();
  const pick = $("#panel-pick");
  pick.replaceChildren(...Object.entries(panels).map(([k, p]) => el("option", { value: k, selected: k === panelKey }, p.name)));
  const box = $("#override");
  if (!panelKey) return box.replaceChildren(el("p", { class: "muted", text: t("override.no_panels") }));
  box.replaceChildren(...panels[panelKey].widgets.map((w) => {
    const send = (down, value) => cmd("override", { panel: panelKey, widget: w.id, down, value });
    if (w.type === "fader") {
      const inp = el("input", { type: "range", min: 0, max: 100, value: 50, "aria-label": w.label });
      let last = 0;
      inp.addEventListener("input", () => {
        const now = performance.now();
        if (now - last > 40) { last = now; send(true, inp.value / 100); }
      });
      inp.addEventListener("change", () => send(true, inp.value / 100));
      return el("div", { class: "pad-tile fader-tile", "data-widget": w.id }, el("span", { class: "label", text: w.label }), inp);
    }
    const b = el("button", { class: `pad-tile ${w.type}`, "data-widget": w.id }, el("span", { class: "label", text: w.label }),
      el("span", { class: "kind", text: t("override.type_" + w.type) + (w.mode === "flash" && w.type === "colour" ? " · " + t("override.held") : "") }));
    b.addEventListener("pointerdown", (e) => { e.preventDefault(); b.setPointerCapture(e.pointerId); send(true); });
    b.addEventListener("pointerup", () => send(false));
    b.addEventListener("pointercancel", () => send(false));
    return b;
  }));
}

function renderHeld(s) {
  const held = new Set(s.override?.held || []);
  for (const b of document.querySelectorAll("#override [data-widget]")) b.classList.toggle("on", held.has(`${panelKey}/${b.dataset.widget}`));
}

// ---------------------------------------------------------------- editing

async function openEditor() {
  $("#override-editor").dataset.ready = "";
  file = await get("/api/store/panels");
  file.panels ||= {};
  colours = (await get("/api/effects")).colours;
  saved = JSON.stringify(file);
  if (!panelKey || !file.panels[panelKey]) panelKey = Object.keys(file.panels)[0] || null;
  renderEditor();
  $("#override-editor").dataset.ready = "1"; // loaded: typing now won't be overwritten
}

function panel() {
  return panelKey ? file.panels[panelKey] : null;
}

function renderEditor() {
  const p = panel();
  $("#panel-key").value = panelKey || "";
  $("#panel-name").value = p?.name || "";
  $("#panel-fade").value = p?.release_fade_s ?? "";
  $("#panels-save").classList.toggle("sel", JSON.stringify(file) !== saved);
  $("#override-state").textContent = JSON.stringify(file) !== saved ? t("shows.unsaved") : "";
  if (!p) return $("#widgets-edit").replaceChildren(el("p", { class: "muted", text: t("override.no_panels") }));
  p.widgets ||= [];
  $("#widgets-edit").replaceChildren(...p.widgets.map((w, i) => el("li", {},
    el("span", { class: "chip", text: t("override.type_" + w.type) }),
    el("input", { value: w.label || "", placeholder: t("override.label"), oninput: (e) => { w.label = e.target.value; dirty(); } }),
    ...widgetFields(w),
    el("span", { class: "tools" },
      el("button", { disabled: i === 0, onclick: () => { p.widgets.splice(i - 1, 0, ...p.widgets.splice(i, 1)); renderEditor(); } }, "↑"),
      el("button", { disabled: i === p.widgets.length - 1, onclick: () => { p.widgets.splice(i + 1, 0, ...p.widgets.splice(i, 1)); renderEditor(); } }, "↓"),
      el("button", { class: "danger-text", onclick: () => { p.widgets.splice(i, 1); renderEditor(); } }, "✕")))));
}

function dirty() {
  $("#panels-save").classList.toggle("sel", JSON.stringify(file) !== saved);
  $("#override-state").textContent = JSON.stringify(file) !== saved ? t("shows.unsaved") : "";
}

function select(options, value, onChange, blank) {
  return el("select", { onchange: (e) => { onChange(e.target.value || undefined); renderEditor(); } },
    ...(blank ? [el("option", { value: "" }, blank)] : []),
    ...options.map(([v, label]) => el("option", { value: v, selected: v === value }, label)));
}

function widgetFields(w) {
  const fixtures = () => el("input", { list: "override-groups", value: (w.fixtures || []).join(", "), placeholder: t("override.fixtures"),
    onchange: (e) => { w.fixtures = e.target.value.split(",").map((x) => x.trim()).filter(Boolean); dirty(); } });
  const colourSel = () => {
    const custom = typeof w.colour === "string" && w.colour.startsWith("#") || (w.colour && typeof w.colour === "object");
    const opts = Object.keys(colours).map((c) => [c, c]);
    const sel = select(custom ? [["", t("override.custom_colour")], ...opts] : opts, custom ? "" : w.colour || "white", (v) => { if (v) w.colour = v; });
    const wheel = el("button", { type: "button", class: "sw wheel-btn", title: t("scenes.custom_colour"),
      style: custom && typeof w.colour === "string" ? `background:${w.colour}` : "",
      onclick: () => openWheel({ value: w.colour, fixtures: w.fixtures || [], names: colours,
        onPick: (c) => { w.colour = c; dirty(); renderEditor(); } }) }, "◐");
    return el("span", { class: "row" }, sel, wheel);
  };
  const scenes = Object.entries(live.cat.scenes).map(([k, n]) => [k, n]);
  switch (w.type) {
    case "colour":
      return [fixtures(), colourSel(), select([["latch", t("override.latch")], ["flash", t("override.held")]], w.mode || "latch", (v) => (w.mode = v))];
    case "flash":
      return [fixtures(), colourSel()];
    case "solo":
      return [fixtures()];
    case "effect":
      return [select(scenes, w.scene, (v) => (w.scene = v), t("scenes.choose"))];
    case "go": {
      const shows = Object.entries(live.cat.shows).map(([k, s]) => [`show:${k}`, s.name]);
      const sc = scenes.map(([k, n]) => [`scene:${k}`, "▸ " + n]);
      const now = w.scene ? `scene:${w.scene}` : w.show ? `show:${w.show}` : "";
      const out = [select([...shows, ...sc], now, (v) => {
        delete w.scene; delete w.show; delete w.set;
        if (v?.startsWith("scene:")) w.scene = v.slice(6);
        else if (v?.startsWith("show:")) w.show = v.slice(5);
      }, t("scenes.choose"))];
      if (w.show && live.cat.shows[w.show]) out.push(select(live.cat.shows[w.show].sets.map((s) => [s, s]), w.set, (v) => (v ? (w.set = v) : delete w.set), t("setlists.default_set")));
      return out;
    }
    case "fader":
      return [select([["grand", t("live.grand")], ["flash_level", t("live.flash_level")], ["speed", t("live.speed")],
        ...["head", "bar", "wash", "kick"].map((k) => [`sub:${k}`, t("live.sub_" + k)])], w.target, (v) => (w.target = v))];
    case "haze":
      return [select(["off", "manual", "pulse", "boost"].map((a) => [a, t("override.haze_" + a)]), w.action, (v) => (w.action = v))];
    default:
      return [];
  }
}

function newWidget(type) {
  const p = panel();
  const n = (p.widgets || []).filter((w) => w.type === type).length + 1;
  let id = `${type}${n}`;
  while (p.widgets.some((w) => w.id === id)) id += "x";
  const w = { id, type, label: `${t("override.type_" + type)} ${n}` };
  if (["colour", "flash", "solo"].includes(type)) w.fixtures = ["all"];
  if (type === "colour" || type === "flash") w.colour = Object.keys(colours)[0] || "white";
  if (type === "effect") w.scene = Object.keys(live.cat.scenes)[0];
  if (type === "go") w.show = Object.keys(live.cat.shows)[0];
  if (type === "fader") w.target = "grand";
  if (type === "haze") w.action = "boost";
  p.widgets.push(w);
  renderEditor();
}

export function init() {
  $("#panel-pick").onchange = (e) => { panelKey = e.target.value; renderPlay(); if (file) renderEditor(); };
  $("#override-release").onclick = () => cmd("release_all", { fade_s: 0.5 });
  $("#override-edit").onchange = async (e) => {
    $("#override-editor").classList.toggle("hidden", !e.target.checked);
    if (e.target.checked) await openEditor();
  };
  $("#widget-type").replaceChildren(...TYPES.map((x) => el("option", { value: x }, t("override.type_" + x))));
  $("#widget-add").onclick = () => (panel() ? newWidget($("#widget-type").value) : toast(t("override.make_panel_first"), true));
  $("#panel-new").onclick = () => {
    const key = ($("#panel-key").value || "").toLowerCase().replace(/[^a-z0-9_-]+/g, "_") || `panel${Object.keys(file.panels).length + 1}`;
    if (file.panels[key]) return toast(t("override.panel_exists", { key }), true);
    file.panels[key] = { name: $("#panel-name").value || key, widgets: [] };
    panelKey = key;
    renderEditor();
  };
  $("#panel-del").onclick = () => {
    if (!panelKey || !confirm(t("override.confirm_delete", { name: panel().name || panelKey }))) return;
    delete file.panels[panelKey];
    panelKey = Object.keys(file.panels)[0] || null;
    renderEditor();
  };
  $("#panel-name").oninput = (e) => { if (panel()) { panel().name = e.target.value; dirty(); } };
  $("#panel-fade").onchange = (e) => {
    if (!panel()) return;
    if (e.target.value === "") delete panel().release_fade_s;
    else panel().release_fade_s = +e.target.value;
    dirty();
  };
  $("#panels-save").onclick = async () => {
    if (await attempt(() => api("PUT", "/api/store/panels", { data: file }), t("override.saved"))) {
      saved = JSON.stringify(file);
      await refreshCatalogue();
      renderEditor();
    }
  };
  const list = el("datalist", { id: "override-groups" });
  document.body.append(list);
  onCatalogue((cat) => {
    list.replaceChildren(...["all", ...Object.keys(cat.groups), ...cat.fixtures.map((f) => f.id)].map((v) => el("option", { value: v })));
    renderPlay();
  });
  onState(renderHeld);
  onShow("override", renderPlay);
}
