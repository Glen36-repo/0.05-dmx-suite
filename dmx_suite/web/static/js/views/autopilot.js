// Autopilot page (v3.4 "Ride page"): ride the auto show live. Autopilot, mood and hold along the top; Move FX,
// Flash FX, Colour FX and (v7) the palette bank across; drum FX and ride faders below; the
// haze controls stay alongside (separate: the auto show never touches haze). Big touch targets.
// "Learn" makes any control MIDI/OSC-learnable: tap it, then hit a pad or press a pedal.
import { api, attempt, cmd, get, toast } from "../api.js";
import { $, el } from "../dom.js";
import { LightGrid } from "../grid.js";
import { t } from "../i18n.js";
import { infoButton } from "../info.js";
import { go, onLeave, onShow } from "../nav.js";
import { picker } from "../picker.js";
import { review } from "./review.js";
import { live, onCatalogue, onState } from "../state.js";

let fx = null; // /api/fx
let grid = null;
let learning = false;
let excluding = false; // Exclude mode: a tap on a type leaves it out of the autopilot (or puts it back)
const HOLD_MS = 600; // v8: long-press (or right-click) a type opens its settings panel
let bank = ""; // fader tab: "" = everything, or move / colour / drum
const FADERS = ["speed", "fade", "fan", "size", "shift"];
const CLASSES = ["head", "wash", "pixel", "strobe", "effect"];

function act(action, params = {}, level) {
  if (learning) {
    learning = false;
    $("#ride-learn").classList.remove("sel");
    return attempt(() => api("POST", "/api/autopilot/learn", { action, params }), (r) => r.message);
  }
  return attempt(() => api("POST", "/api/autopilot/action", { action, ...params, ...(level !== undefined ? { level } : {}) }));
}

function fxTitle(item) {
  return `${item.label} · ${t("autopilot.busy", { n: Math.round(item.busy * 100) })}` + (item.excluded ? ` · ${t("autopilot.excluded_tip")}` : "")
    + ` · ${t("fxp.hold_tip")}`;
}

// v8: the priority badge (0-5) on a tile, its own touch target; a tap steps 1 -> 5 -> 1 (never to 0)
function badge(item, b, key) {
  const p = el("span", { class: "prio", role: "button", tabindex: 0, "data-prio": String(item.priority ?? 3),
                         "aria-label": t("fxp.badge_tip", { n: item.priority ?? 3 }), title: t("fxp.badge_tip", { n: item.priority ?? 3 }) },
    String(item.priority ?? 3));
  const step = async (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (live.state?.gig_lock) return toast(t("fxp.locked"), true);
    try {
      const r = await api("POST", "/api/autopilot/fx", { action: "priority", ...key });
      item.priority = r.priority;
      item.excluded = r.priority === 0;
      p.textContent = p.dataset.prio = String(r.priority);
      p.title = t("fxp.badge_tip", { n: r.priority });
      b.classList.toggle("excluded", item.excluded);
    } catch (err) { toast(err.message, true); }
  };
  for (const ev of ["pointerdown", "pointerup"]) p.addEventListener(ev, (e) => e.stopPropagation()); // no long-press, no play
  p.addEventListener("click", step);
  p.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") step(e); });
  const dot = el("span", { class: "ovr" + (item.overridden ? "" : " hidden"), title: t("fxp.changed") });
  b.append(dot, p);
  return b;
}

// a type button: tap plays it (or, in Exclude mode, leaves it out / puts it back); hold or right-click for its settings
function fxButton(item, onClick, b = null, toggle = toggleExcluded, key = { item: item.id }) {
  b = b || el("button", { class: "ride-fx" + (item.excluded ? " excluded" : ""), "data-fx": item.id, title: fxTitle(item) },
    el("span", { class: "lbl", text: item.label }));
  badge(item, b, key);
  let timer = null, held = false;
  const cancel = () => { clearTimeout(timer); timer = null; };
  b.addEventListener("pointerdown", (e) => {
    if (e.button > 0) return;
    held = false;
    cancel();
    timer = setTimeout(() => { held = true; timer = null; navigator.vibrate?.(15); openPanel(key); }, HOLD_MS);
  });
  for (const ev of ["pointerup", "pointerleave", "pointercancel"]) b.addEventListener(ev, cancel);
  b.addEventListener("contextmenu", (e) => { e.preventDefault(); if (!held) openPanel(key); }); // right-click; a long touch mustn't open the browser's menu
  b.addEventListener("click", (e) => {
    if (held) { held = false; e.preventDefault(); return; } // the long-press already did its job
    if (excluding && !learning) return toggle(item, b);
    onClick();
  });
  return b;
}

// ---------------------------------------------------------------- v8 FX settings panel

const num0 = (v) => (v === "" || v === null || v === undefined ? null : +v);

function paramInput(p) {
  const id = `fxp-p-${p.key}`;
  const has = p.value !== undefined && JSON.stringify(p.value) !== JSON.stringify(p.default);
  let inp;
  if (p.kind === "bool") {
    inp = el("select", { id }, el("option", { value: "" }, t("fxp.default", { v: p.default ? t("fxp.on") : t("fxp.off") })),
      el("option", { value: "true" }, t("fxp.on")), el("option", { value: "false" }, t("fxp.off")));
    inp.value = has ? String(!!p.value) : "";
  } else if (p.kind === "choice") {
    inp = el("select", { id }, el("option", { value: "" }, t("fxp.default", { v: p.default ?? "" })),
      ...(p.choices || []).map((c) => el("option", { value: c }, c)));
    inp.value = has ? p.value : "";
  } else if (["number", "int", "angle"].includes(p.kind)) {
    inp = el("input", { id, type: "number", step: p.kind === "int" ? 1 : "any", placeholder: p.default ?? "",
                        ...(p.lo !== undefined ? { min: p.lo } : {}), ...(p.hi !== undefined ? { max: p.hi } : {}) });
    inp.value = has ? p.value : "";
  } else {
    inp = el("input", { id, placeholder: p.default ?? "" });
    inp.value = has ? p.value : "";
  }
  inp.dataset.key = p.key;
  inp.dataset.kind = p.kind;
  return el("label", { class: "fxp-field", for: id, title: p.help || "" }, el("span", { text: p.label }), inp);
}

function readParams(d) {
  const out = {};
  for (const inp of d.querySelectorAll("[data-key]")) {
    const v = inp.value;
    if (v === "") continue;
    const k = inp.dataset.kind;
    out[inp.dataset.key] = k === "bool" ? v === "true" : ["number", "int", "angle"].includes(k) ? +v : v;
  }
  return out;
}

let panelKey = null;

async function openPanel(key) {
  let it;
  try { it = await api("POST", "/api/autopilot/fx", { action: "get", ...key }); } catch (err) { return toast(err.message, true); }
  panelKey = key;
  const d = $("#fx-panel");
  const locked = !!live.state?.gig_lock;
  const pal = !!key.palette;
  const dk = it.darkness === "follow" || it.darkness === "exempt" ? it.darkness : "reduced";
  const dkLabels = { follow: t("fxp.dark_follow"), exempt: t("fxp.dark_exempt"), reduced: t("fxp.dark_reduced") };
  const dkSel = el("select", { id: "fxp-dark" }, ...Object.entries(dkLabels).map(([v, label]) => el("option", { value: v }, label)));
  dkSel.value = dk;
  const dkVal = el("input", { id: "fxp-dark-val", type: "range", min: 0, max: 100, step: 5, value: dk === "reduced" ? Math.round(+it.darkness * 100) : 50,
                              "aria-label": t("fxp.dark_share") });
  const dkOut = el("span", { class: "muted", text: dkVal.value + " %" });
  dkVal.oninput = () => (dkOut.textContent = dkVal.value + " %");
  const showVal = () => { dkVal.closest("label").classList.toggle("hidden", dkSel.value !== "reduced"); };
  dkSel.onchange = showVal;
  const prio = el("select", { id: "fxp-prio" }, ...[0, 1, 2, 3, 4, 5].map((n) => el("option", { value: n }, n === 0 ? t("fxp.prio_0") : String(n))));
  prio.value = String(it.priority ?? 3);
  const moods = el("span", { class: "fxp-moods" }, ...MOODS.map((m) => el("label", { class: "check" },
    el("input", { type: "checkbox", "data-mood": m, checked: (it.moods || []).includes(m) || undefined }),
    el("span", { text: t("autopilot.mood_" + m) }))));
  const minS = el("input", { id: "fxp-min", type: "number", min: 2, max: 3600, step: 1, value: it.min_s ?? "", placeholder: t("fxp.any") });
  const maxS = el("input", { id: "fxp-max", type: "number", min: 2, max: 3600, step: 1, value: it.max_s ?? "", placeholder: t("fxp.any") });
  const name = it.variant ? el("input", { id: "fxp-name", value: it.label }) : null;
  const params = pal ? [] : (it.params || []).map(paramInput);
  const btn = (id, label, onclick, cls = "") => el("button", { type: "button", id, class: cls, onclick }, label);
  const save = async () => {
    const ov = {};
    const p = +prio.value;
    if (p !== 3) ov.priority = p;
    if (dkSel.value === "exempt") ov.darkness = "exempt";
    else if (dkSel.value === "reduced") ov.darkness = +dkVal.value / 100;
    if (!pal) {
      const ms = MOODS.filter((m) => moods.querySelector(`[data-mood=${m}]`).checked);
      if (!ms.length) return toast(t("fxp.need_mood"), true);
      if (ms.join() !== (it.default_moods || MOODS).join()) ov.moods = ms;
      if (num0(minS.value) !== null) ov.min_s = num0(minS.value);
      if (num0(maxS.value) !== null) ov.max_s = num0(maxS.value);
      const ps = readParams(d.querySelector(".fxp-params"));
      if (Object.keys(ps).length) ov.params = ps;
      if (name && name.value.trim()) ov.name = name.value.trim();
    }
    const r = await attempt(() => api("POST", "/api/autopilot/fx", { action: "save", ...key, overrides: ov }), t("fxp.saved", { name: it.label }));
    if (r) { d.close(); load(); }
  };
  const children = [
    el("h3", {}, name ? t("fxp.title_variant") : it.label, infoButton("autopilot.fx_settings")),
    name ? el("label", { class: "fxp-field" }, el("span", { text: t("fxp.name") }), name) : null,
    locked ? el("p", { class: "muted", text: t("fxp.locked") }) : null,
    el("h4", { text: t("fxp.darkness") }),
    el("div", { class: "fxp-row" }, el("label", { class: "fxp-field" }, el("span", { text: t("fxp.darkness_mode") }), dkSel),
      el("label", { class: "fxp-field" }, el("span", { text: t("fxp.dark_share") }), dkVal, dkOut)),
    params.length ? el("h4", { text: t("fxp.params") }) : null,
    params.length ? el("div", { class: "fxp-params fxp-row" }, ...params) : el("div", { class: "fxp-params" }),
    el("h4", { text: t("fxp.autopilot") }),
    el("div", { class: "fxp-row" }, el("label", { class: "fxp-field" }, el("span", { text: t("fxp.priority") }), prio),
      pal ? null : el("div", { class: "fxp-field" }, el("span", { text: t("fxp.moods") }), moods),
      pal ? null : el("label", { class: "fxp-field" }, el("span", { text: t("fxp.min_s") }), minS),
      pal ? null : el("label", { class: "fxp-field" }, el("span", { text: t("fxp.max_s") }), maxS)),
    el("div", { class: "row wrap fxp-buttons" },
      btn("fxp-save", t("fxp.save"), save, "primary"),
      btn("fxp-preview", t("fxp.preview"), () => attempt(() => api("POST", "/api/autopilot/fx", { action: "preview", ...key }), (r) => r.message)),
      btn("fxp-reset", t("fxp.reset"), async () => {
        if (await attempt(() => api("POST", "/api/autopilot/fx", { action: "reset", ...key }), t("fxp.reset_done", { name: it.label }))) { d.close(); load(); }
      }),
      pal ? null : btn("fxp-dup", t("fxp.duplicate"), async () => {
        const r = await attempt(() => api("POST", "/api/autopilot/fx", { action: "duplicate", ...key }), (x) => t("fxp.duplicated", { name: x.item.label }));
        if (r) { await load(); openPanel({ item: r.id }); }
      }),
      it.variant ? btn("fxp-delete", t("fxp.delete"), async () => {
        if (!confirm(t("fxp.delete_confirm", { name: it.label }))) return;
        if (await attempt(() => api("POST", "/api/autopilot/fx", { action: "delete", ...key }), t("fxp.deleted", { name: it.label }))) { d.close(); load(); }
      }, "danger-text") : null,
      btn("fxp-close", t("fxp.close"), () => d.close())),
  ].filter(Boolean);
  d.replaceChildren(...children);
  showVal();
  if (locked) { // gig lock: read-only, no Preview
    d.querySelectorAll("input, select").forEach((x) => (x.disabled = true));
    for (const id of ["fxp-save", "fxp-preview", "fxp-reset", "fxp-dup", "fxp-delete"]) { const b = d.querySelector("#" + id); if (b) b.disabled = true; }
  }
  if (!d.open) d.showModal();
}

function setBadge(b, n) {
  const p = b.querySelector(".prio");
  if (p) { p.textContent = p.dataset.prio = String(n); p.title = t("fxp.badge_tip", { n }); }
}

async function toggleExcluded(item, b) {
  const want = !item.excluded;
  item.excluded = want; // shown at once; put back if the laptop says no
  b.classList.toggle("excluded", want);
  b.title = fxTitle(item);
  try {
    await api("POST", "/api/autopilot/exclude", { item: item.id, excluded: want });
    const now = (await api("POST", "/api/autopilot/fx", { action: "get", item: item.id })).priority; // put back: its old priority
    item.priority = now;
    setBadge(b, now);
    toast(t(want ? "autopilot.excluded_toast" : "autopilot.included_toast", { name: item.label }));
  } catch (err) {
    item.excluded = !want;
    b.classList.toggle("excluded", !want);
    b.title = fxTitle(item);
    toast(err.message, true);
  }
}

// v7 palette bank: a tile per palette (swatches + mood tags); green = playing, red = left out of the autopilot
const MOODS = ["low", "mid", "high"];
function palTitle(p) {
  return p.name + (p.excluded ? ` · ${t("autopilot.excluded_tip")}` : "");
}
function palTile(key, p) {
  const tags = p.tags.filter((x) => MOODS.includes(x)).map((x) => t("autopilot.mood_" + x)).join(" · ");
  const b = el("button", { class: "ride-fx ride-pal-tile" + (p.excluded ? " excluded" : ""), "data-palette": key, title: palTitle(p) },
    el("span", { class: "pal-sw" }, ...p.swatches.map((c) => el("i", { style: `background:${c}` }))),
    el("span", { text: p.name }), el("span", { class: "tags", text: tags }));
  return fxButton(p, () => act("autopilot_palette", { palette: key }), b, (item, btn) => togglePalette(key, item, btn), { palette: key });
}
async function togglePalette(key, p, b) {
  const want = !p.excluded;
  p.excluded = want;
  b.classList.toggle("excluded", want);
  b.title = palTitle(p);
  try {
    await api("POST", "/api/autopilot/palette", { palette: key, excluded: want });
    const now = (await api("POST", "/api/autopilot/fx", { action: "get", palette: key })).priority;
    p.priority = now;
    setBadge(b, now);
    toast(t(want ? "autopilot.excluded_toast" : "autopilot.included_toast", { name: p.name }));
  } catch (err) {
    p.excluded = !want;
    b.classList.toggle("excluded", !want);
    b.title = palTitle(p);
    toast(err.message, true);
  }
}

function setExcluding(on) {
  excluding = on;
  $("#ride-exclude").classList.toggle("on", on);
  $("#ride-exclude").textContent = t(on ? "autopilot.exclude_done" : "autopilot.exclude");
  $("#page-autopilot").classList.toggle("excluding", on);
  if (on) toast(t("autopilot.exclude_help"));
}

function flashButton(item) {
  const b = el("button", { class: "ride-fx flash", "data-flash": item.id }, item.label);
  const down = (e) => {
    e.preventDefault();
    if (learning) return act("flash_fx", { fx: item.id });
    b.classList.add("on");
    api("POST", "/api/flashfx", { fx: item.id, down: true, colour: "show" }).catch((err) => toast(err.message, true));
  };
  const up = () => {
    if (!b.classList.contains("on")) return;
    b.classList.remove("on");
    api("POST", "/api/flashfx", { fx: item.id, down: false }).catch(() => {});
  };
  b.addEventListener("pointerdown", down);
  b.addEventListener("pointerup", up);
  b.addEventListener("pointerleave", up);
  return b;
}

async function load() {
  fx = await get("/api/fx");
  render();
  loadWhy();
  loadPresets();
  loadSettings();
}

async function loadPresets() {
  const pres = await get("/api/presets");
  $("#ride-presets").replaceChildren(...Object.entries(pres).map(([k, p]) => el("button", {
    class: "ride-pal", "data-preset": k, title: p.tags.join(", "),
    onclick: () => act("preset", { preset: k }) }, p.name)));
}

function render() {
  if (!fx) return;
  const ok = fx.items.filter((i) => i.available);
  const pick = live.state?.ride?.pick || fx.pick;
  const byBank = (b) => ok.filter((i) => i.bank === b);
  $("#ride-move").replaceChildren(
    el("button", { class: "ride-fx" + (!pick.move ? " sel" : ""), "data-fx": "", onclick: () => act("autopilot_fx", { bank: "move", item: "" }) }, t("autopilot.no_move")),
    ...byBank("move").map((i) => fxButton(i, () => act("autopilot_fx", { bank: "move", item: i.id }))));
  $("#ride-colour").replaceChildren(...byBank("colour").map((i) => fxButton(i, () => act("autopilot_fx", { bank: "colour", item: i.id }))));
  $("#ride-flash").replaceChildren(...byBank("flash").map(flashButton));
  $("#ride-drum").replaceChildren(
    el("button", { class: "ride-fx" + (!pick.drum ? " sel" : ""), "data-fx": "", onclick: () => act("autopilot_fx", { bank: "drum", item: "" }) }, t("autopilot.no_drum")),
    ...byBank("drum").map((i) => fxButton(i, () => act("autopilot_fx", { bank: "drum", item: i.id }))));
  $("#ride-palettes").replaceChildren(...Object.entries(fx.palettes).map(([k, p]) => palTile(k, p)));
  $("#ride-tabs").replaceChildren(...["", "move", "colour", "drum"].map((b) => el("button", {
    class: b === bank ? "on" : "", onclick: () => { bank = b; render(); } }, b ? t("autopilot.bank_" + b) : t("autopilot.all_banks"))));
  $("#ride-faders").replaceChildren(...FADERS.map((k) => {
    const src = bank ? pick.bank_feel?.[bank] || { speed: 1, fade: 0.5, fan: 0.5, size: 0.5, shift: 0 } : pick.feel;
    const v = k === "speed" ? (Math.log(src.speed) / Math.log(4) + 1) / 2 : src[k];
    const inp = el("input", { type: "range", min: 0, max: 1, step: 0.01, value: v, "aria-label": t("autopilot.fader_" + k) });
    let last = 0;
    inp.addEventListener("input", () => {
      const now = performance.now();
      if (now - last < 120) return;
      last = now;
      act("feel_" + k, bank ? { bank } : {}, +inp.value);
    });
    inp.addEventListener("pointerdown", (e) => { if (learning) { e.preventDefault(); act("feel_" + k, bank ? { bank } : {}); } });
    return el("label", { class: "ride-fader" }, el("span", { text: t("autopilot.fader_" + k) }), inp);
  }));
  renderLights();
  update(live.state);
}

function renderLights() {
  const rig = fx.rig;
  const rows = [];
  for (const c of CLASSES) for (const f of rig.classes[c] || []) rows.push([f, c]);
  for (const f of rig.excluded) rows.push([f, null]);
  $("#ride-lights").replaceChildren(...rows.map(([f, c]) => el("li", {},
    el("b", { text: f }),
    el("select", { "aria-label": t("a11y.light_class", { id: f }), onchange: (e) => saveClass(f, e.target.value) },
      ...CLASSES.map((x) => el("option", { value: x, selected: x === c || undefined }, t("autopilot.class_" + x))),
      el("option", { value: "exclude", selected: c === null || undefined }, t("autopilot.class_exclude"))))));
}

async function saveClass(fid, value) {
  const rig = fx.rig;
  const classes = {};
  const exclude = rig.excluded.filter((f) => f !== fid);
  if (value === "exclude") exclude.push(fid);
  else classes[fid] = value;
  const r = await attempt(() => api("POST", "/api/store/auto", { classes, exclude }), t("autopilot.lights_saved"));
  if (r) load();
}

async function loadWhy() {
  const r = await get("/api/autopilot?n=12");
  $("#ride-why").replaceChildren(...r.log.slice().reverse().map((d) => el("li", {
    title: t("autopilot.why_open"), onclick: () => { if (d.look.scene) return; review.jump = d.look; go("review"); } },
    el("span", { class: "muted", text: new Date(d.time * 1000).toLocaleTimeString("en-AU", { hour12: false }) }),
    el("b", { text: d.look.scene ? t("between.scene_look", { scene: live.cat?.scenes?.[d.look.scene] || d.look.scene })
      : [d.look.move, d.look.colour, d.look.drum].filter(Boolean).join(" + ") + " · " + d.look.palette }),
    el("span", { text: t("autopilot.why_line", { why: d.why, mood: t("autopilot.mood_" + d.mood), energy: Math.round(d.energy * 100) }) }))));
}

let lastDecision = null;

// ---------------------------------------------------------------- v7 layer timing: countdown and lock per layer
const LAYERS = ["move", "colour", "palette", "darkness"];

function layerChip(k) {
  return el("button", { class: "chip layer-chip", "data-layer": k, title: t("layers.lock_tip"),
    onclick: () => act("autopilot_lock", { layer: k }) },
  el("span", { text: t("layers." + k) }), el("b", { class: "layer-next" }));
}

function drawLayers(ap) {
  const box = $("#ap-layers");
  if (!box.children.length) box.replaceChildren(...LAYERS.map(layerChip));
  for (const k of LAYERS) {
    const l = ap.layers?.[k] || {};
    const b = box.querySelector(`[data-layer=${k}]`);
    b.classList.toggle("locked", !!l.locked);
    b.setAttribute("aria-pressed", l.locked ? "true" : "false");
    b.querySelector(".layer-next").textContent = l.locked ? t("layers.locked")
      : l.on ? t("layers.on_" + l.on) : l.next_s != null ? t("layers.in", { s: Math.round(l.next_s) }) : "";
  }
}

// ---------------------------------------------------------------- v7 settings panel (saved to the rig)
const SCHED = ["every_s", "every_looks", "song", "set"];
let apCfg = null;

function field(label, input) {
  return el("label", { class: "ap-field" }, el("span", { text: label }), input);
}
function num(value, min, max, step, aria) {
  return el("input", { type: "number", class: "num", min, max, step, value: value ?? "", "aria-label": aria });
}

function layerRow(k, lay) {
  const mode = "every_s" in lay ? "every_s" : "every_looks" in lay ? "every_looks" : lay.on;
  const sel = el("select", { "data-sched": k, "aria-label": t("layers.schedule", { layer: t("layers." + k) }) },
    ...SCHED.map((m) => el("option", { value: m, selected: m === mode || undefined }, t("layers.sched_" + m))));
  const val = num(lay.every_s ?? lay.every_looks ?? "", 0.1, 3600, 0.1, t("layers.value"));
  val.dataset.val = k;
  const spread = num(lay.spread ?? 25, 0, 50, 1, t("layers.spread"));
  spread.dataset.spread = k;
  const sync = () => { val.disabled = sel.value === "song" || sel.value === "set"; };
  sel.addEventListener("change", sync);
  sync();
  return el("div", { class: "row wrap ap-layer-row" }, el("b", { text: t("layers." + k) }), sel, val,
    field(t("layers.spread"), spread));
}

// v7 Between songs: the settings that were rig-YAML only, and a scene as the between-songs / walk look
let apDefaults = null;
let inputs = [];
function lookSelect(id, look) {
  const scenes = Object.entries(live.cat?.scenes || {}).filter(([k]) => !k.startsWith("preset:"));
  return el("select", { id, "aria-label": t("between." + id.replace("bt-", "")) },
    el("option", { value: "", selected: !look?.scene || undefined }, t("between.generated")),
    ...scenes.map(([k, name]) => el("option", { value: k, selected: look?.scene === k || undefined }, name)));
}
function betweenSection() {
  const b = apCfg.between;
  const opt = (v, cur) => el("option", { value: v, selected: v === cur || undefined }, t("between.start_" + v));
  const ignore = picker({
    items: inputs.map((i) => ({ id: i.id, label: i.name || i.id, group: i.device })),
    groups: [...new Map(inputs.map((i) => [i.device, { id: i.device, label: i.device_name || i.device }])).values()],
    value: b.ignore || [], label: t("between.ignore"), all: t("between.ignore_all") });
  ignore.id = "bt-ignore";
  return [
    el("h3", { text: t("between.title") }),
    el("label", { class: "chip" }, el("input", { type: "checkbox", id: "bt-on", checked: b.on || undefined }), el("span", { text: t("between.on") })),
    el("div", { class: "row wrap" },
      fieldId(t("between.gap_s"), num(b.gap_s, 1, 120, 0.5, t("between.gap_s")), "bt-gap"),
      fieldId(t("between.min_song_s"), num(b.min_song_s, 0, 600, 1, t("between.min_song_s")), "bt-min-song")),
    el("div", { class: "row wrap" },
      field(t("between.start"), el("select", { id: "bt-start" }, opt("first_hit", b.start), opt("count_in", b.start))),
      fieldId(t("between.count_in"), num(b.count_in, 2, 8, 1, t("between.count_in")), "bt-count")),
    el("div", { class: "row wrap" },
      fieldId(t("between.fade_in"), num(b.fade_in, 0, 30, 0.1, t("between.fade_in")), "bt-fade-in"),
      fieldId(t("between.fade_out"), num(b.fade_out, 0, 30, 0.1, t("between.fade_out")), "bt-fade-out"),
      el("span", { class: "muted", text: t("between.fade_help") })),
    el("div", { class: "row wrap" }, field(t("between.ignore"), ignore)),
    el("div", { class: "row wrap" },
      field(t("between.look"), lookSelect("bt-look", b.look)),
      field(t("between.walk_on"), lookSelect("bt-walk_on", apCfg.walk_on)),
      field(t("between.walk_off"), lookSelect("bt-walk_off", apCfg.walk_off))),
    el("p", { class: "muted", text: t("between.scene_help") }),
  ];
}
function fieldId(label, input, id) {
  input.id = id;
  return field(label, input);
}
function readBetween() {
  const v = (id) => $(id).value;
  const opt = (id) => (v(id) === "" ? null : +v(id));
  const look = (id, cur, def) => (v(id) ? { scene: v(id) } : cur?.scene ? def : undefined);
  const out = {
    between: { on: $("#bt-on").checked, gap_s: +v("#bt-gap"), min_song_s: +v("#bt-min-song"), start: v("#bt-start"),
      count_in: +v("#bt-count"), fade_in: opt("#bt-fade-in"), fade_out: opt("#bt-fade-out"), ignore: $("#bt-ignore").value },
  };
  const bl = look("#bt-look", apCfg.between.look, apDefaults.look);
  if (bl) out.between.look = bl;
  for (const k of ["walk_on", "walk_off"]) {
    const l = look(`#bt-${k}`, apCfg[k], apDefaults[k]);
    if (l) out[k] = l;
  }
  return out;
}

function renderSettings() {
  if (!apCfg) return;
  const timing = el("span", { class: "seg-row", id: "ap-timing" }, ...["together", "staggered"].map((m) => el("button", {
    type: "button", class: apCfg.timing === m ? "on" : "", "data-timing": m,
    onclick: (e) => { $("#ap-timing").querySelectorAll("button").forEach((b) => b.classList.toggle("on", b === e.currentTarget)); } },
  t("layers.timing_" + m))));
  const body = $("#ap-settings-body");
  body.replaceChildren(
    el("h3", { text: t("layers.title") }), el("div", { class: "row wrap" }, timing),
    el("p", { class: "muted", text: t("layers.help") }),
    ...LAYERS.map((k) => layerRow(k, apCfg.layers[k])),
    ...betweenSection(),
    el("div", { class: "row" }, el("button", { id: "ap-settings-save", class: "primary", onclick: saveSettings }, t("common.save"))));
}

function readLayers() {
  const out = {};
  for (const k of LAYERS) {
    const mode = $(`[data-sched=${k}]`).value;
    const v = +$(`[data-val=${k}]`).value;
    const lay = { spread: +$(`[data-spread=${k}]`).value || 0 };
    if (mode === "song" || mode === "set") lay.on = mode;
    else lay[mode] = v;
    out[k] = lay;
  }
  return out;
}

async function saveSettings() {
  const timing = $("#ap-timing button.on")?.dataset.timing || "together";
  const r = await attempt(() => api("POST", "/api/autopilot/settings", { changes: { timing, layers: readLayers(), ...readBetween() } }),
    t("apset.saved"));
  if (r) { apCfg = r.config; renderSettings(); }
}

async function loadSettings() {
  const [r, ins] = await Promise.all([get("/api/autopilot?n=1"), get("/api/inputs")]);
  apCfg = r.config;
  apDefaults = r.defaults;
  inputs = ins.inputs || [];
  renderSettings();
}

// v6 Darkness: the slider sends at most every 60 ms; the server eases it in over the look's fade
let dkLast = 0, dkTimer = null, dkHeld = false;
function sendDarkness(v) {
  clearTimeout(dkTimer);
  const go = () => { dkLast = performance.now(); api("POST", "/api/darkness", { value: v }).catch(() => null); };
  if (performance.now() - dkLast > 60) go(); else dkTimer = setTimeout(go, 60);
}

let dkEditing = false; // a marker or Time at Max being changed here: don't redraw it under the finger
let dkSentAt = 0; // and not from a live frame made before our change landed
let dkLastDk = null;
function drawDarkness(dk) {
  if (!dk) return;
  dkLastDk = dk;
  const auto = dk.mode === "auto";
  $("#ride-darkness").classList.toggle("auto", auto);
  if (!dkHeld) $("#dk-slider").value = auto ? dk.now : dk.darkness;
  $("#dk-val").textContent = `${Math.round(auto ? dk.now : dk.darkness)} %`;
  $("#dk-src").textContent = (auto ? t("darkness.auto_src", { marker: t("darkness." + (dk.marker || "min")), share: Math.round(dk.share_at_max ?? 0) })
    : t("darkness.src_" + dk.source)) + (dk.cc ? ` · ${dk.cc.describe}` : "");
  document.querySelectorAll("#dk-mode [data-dkmode]").forEach((b) => b.classList.toggle("on", b.dataset.dkmode === dk.mode));
  $("#dk-mark-min").style.left = dk.min + "%";
  $("#dk-mark-max").style.left = dk.max + "%";
  if (!dkEditing && performance.now() - dkSentAt > 1500) {
    $("#dk-min").value = dk.min;
    $("#dk-max").value = dk.max;
    $("#dk-tam").value = dk.time_at_max;
  }
  $("#dk-min-v").textContent = `${Math.round(+$("#dk-min").value)} %`;
  $("#dk-max-v").textContent = `${Math.round(+$("#dk-max").value)} %`;
  $("#dk-note").textContent = dk.dropped ? t("darkness.dropped") : "";
  document.querySelectorAll("#ride-darkness [data-dkset]").forEach((b) => {
    const v = dk.set_darkness[b.dataset.dkset];
    b.textContent = t("darkness.set_btn", { set: t("autopilot.mood_" + b.dataset.dkset), v: v === null ? t("darkness.none") : `${v} %` });
  });
}

// v7 Auto: markers and Time at Max go live (and hold until the next set change, like the slider)
function sendAuto(changes) {
  dkSentAt = performance.now();
  return api("POST", "/api/darkness", changes).then((dk) => { dkSentAt = performance.now(); drawDarkness(dk); })
    .catch((err) => toast(err.message, true));
}
function storeSetDarkness(set, value) {
  const auto = dkLastDk?.mode === "auto";
  const v = auto ? { mode: "auto", min: +$("#dk-min").value, max: +$("#dk-max").value, time_at_max: +$("#dk-tam").value }
    : value; // a plain number = that set's Manual value
  return attempt(() => api("POST", "/api/darkness/set", { set, value: v }));
}

function update(s) {
  if (!s || !fx || !$("#page-autopilot").classList.contains("on")) return;
  const ap = s.autopilot, pick = s.ride.pick;
  drawDarkness(ap.darkness);
  $("#ap-toggle").classList.toggle("on", ap.on);
  $("#ap-toggle").textContent = t(ap.on ? "autopilot.autopilot_on" : "autopilot.autopilot_off");
  $("#ap-hold").classList.toggle("on", ap.hold);
  document.querySelectorAll("#ride-moods [data-mood]").forEach((b) => b.classList.toggle("sel",
    b.dataset.mood === "auto" ? !ap.mood_manual : ap.mood_manual && ap.mood === b.dataset.mood));
  $("#ap-energy").style.width = Math.round(ap.energy * 100) + "%";
  $("#ap-energy").parentElement.setAttribute("aria-valuenow", Math.round(ap.energy * 100));
  $("#ap-between").classList.toggle("hidden", !(ap.on && ap.between));
  $("#ap-between").textContent = t("between.badge", { s: Math.round(ap.since_hit_s ?? 0) });
  $("#ap-state").textContent = [t("autopilot.mood_now", { mood: t("autopilot.mood_" + ap.mood) }),
    ap.paused ? t("autopilot.paused") : ap.between ? t("autopilot.between", { s: Math.round(ap.since_hit_s ?? 0) })
      : ap.next_change_s != null ? t("autopilot.next_in", { s: Math.round(ap.next_change_s) }) : "",
    t("autopilot.priority_" + s.priority.top)].filter(Boolean).join(" · ");
  const now = ap.pick || pick;
  // one green button per bank: the type running now ("No movement" / "No drum FX" when there's none)
  document.querySelectorAll("#ride-move [data-fx]").forEach((b) => b.classList.toggle("sel", b.dataset.fx === (now.move || "")));
  document.querySelectorAll("#ride-colour [data-fx]").forEach((b) => b.classList.toggle("sel", b.dataset.fx === now.colour));
  document.querySelectorAll("#ride-drum [data-fx]").forEach((b) => b.classList.toggle("sel", b.dataset.fx === (now.drum || "")));
  document.querySelectorAll("#ride-palettes [data-palette]").forEach((b) => b.classList.toggle("sel", b.dataset.palette === now.palette));
  drawLayers(ap);
  if (grid) grid.update(s.fixtures, s.haze);
  const lastT = ap.last?.time;
  if (lastT && lastT !== lastDecision) { lastDecision = lastT; loadWhy(); }
}

export function init() {
  $("#ap-toggle").onclick = () => act("autopilot", { state: "toggle" });
  $("#ap-hold").onclick = () => act("hold");
  $("#ap-next").onclick = () => act("look_next");
  $("#ap-prev").onclick = () => act("look_prev");
  $("#ride-walk-on").onclick = () => act("walk_on");
  $("#ride-walk-off").onclick = () => act("walk_off");
  $("#ride-save-preset").onclick = async () => {
    const id = (prompt(t("autopilot.preset_name")) || "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
    if (!id) return;
    if (await attempt(() => api("POST", "/api/store/preset", { id }), t("autopilot.preset_saved", { id }))) loadPresets();
  };
  $("#ride-capture").onclick = async () => {
    const id = (prompt(t("autopilot.capture_name")) || "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
    if (id) await attempt(() => api("POST", "/api/capture", { key: id }), t("autopilot.captured", { id }));
  };
  $("#ride-reroll").onclick = () => {
    const locks = [...document.querySelectorAll("[data-lock]")].filter((c) => c.checked).map((c) => c.dataset.lock);
    attempt(() => api("POST", "/api/autopilot/reroll", { locks }));
  };
  $("#ride-more").onclick = async () => {
    const r = await attempt(() => api("POST", "/api/autopilot/more", { n: 4 }));
    if (r) $("#ride-variations").replaceChildren(...r.picks.map((p, i) => el("button", {
      onclick: () => attempt(() => api("POST", "/api/autopilot/play", { pick: p })) }, t("autopilot.variation", { n: i + 1, palette: p.palette }))));
  };
  document.querySelectorAll("#ride-moods [data-mood]").forEach((b) => (b.onclick = () => act("mood", { mood: b.dataset.mood })));
  $("#ride-learn").onclick = () => {
    learning = !learning;
    $("#ride-learn").classList.toggle("sel", learning);
    if (learning) toast(t("autopilot.learn_help"));
  };
  const boost = $("#ride-boost");
  boost.addEventListener("pointerdown", (e) => { e.preventDefault(); boost.classList.add("on"); cmd("haze", { action: "boost" }); });
  const up = () => { if (boost.classList.contains("on")) { boost.classList.remove("on"); cmd("haze", { action: "release" }); } };
  boost.addEventListener("pointerup", up);
  boost.addEventListener("pointerleave", up);
  onCatalogue((cat) => {
    grid = grid || new LightGrid($("#ride-grid"));
    grid.build(cat);
  });
  onState(update);
  const dk = $("#dk-slider");
  dk.addEventListener("pointerdown", (e) => { if (learning) { e.preventDefault(); act("darkness", {}); return; } dkHeld = true; });
  dk.addEventListener("pointerup", () => { dkHeld = false; });
  dk.addEventListener("input", () => sendDarkness(+dk.value));
  document.querySelectorAll("#ride-darkness [data-dkset]").forEach((b) => (b.onclick = async () => {
    const r = await storeSetDarkness(b.dataset.dkset, +dk.value);
    if (r) toast(t(dkLastDk?.mode === "auto" ? "darkness.stored_auto" : "darkness.stored",
      { set: t("autopilot.mood_" + b.dataset.dkset), v: +dk.value }));
  }));
  document.querySelectorAll("#dk-mode [data-dkmode]").forEach((b) => (b.onclick = () => sendAuto({ mode: b.dataset.dkmode })));
  for (const [id, key] of [["#dk-min", "min"], ["#dk-max", "max"]]) {
    const inp = $(id);
    inp.addEventListener("pointerdown", () => { dkEditing = true; });
    inp.addEventListener("input", () => {
      dkEditing = true;
      const mn = +$("#dk-min").value, mx = +$("#dk-max").value;
      if (mn > mx) { if (key === "min") $("#dk-max").value = mn; else $("#dk-min").value = mx; } // markers can't cross
      $("#dk-min-v").textContent = `${$("#dk-min").value} %`;
      $("#dk-max-v").textContent = `${$("#dk-max").value} %`;
    });
    inp.addEventListener("change", async () => {
      await sendAuto({ min: +$("#dk-min").value, max: +$("#dk-max").value });
      dkEditing = false;
    });
  }
  $("#dk-tam").addEventListener("focus", () => { dkEditing = true; });
  $("#dk-tam").addEventListener("change", async () => { await sendAuto({ time_at_max: +$("#dk-tam").value }); dkEditing = false; });
  $("#ride-exclude").onclick = () => setExcluding(!excluding);
  onLeave("autopilot", () => { if (excluding) setExcluding(false); });
  onShow("autopilot", load);
}
