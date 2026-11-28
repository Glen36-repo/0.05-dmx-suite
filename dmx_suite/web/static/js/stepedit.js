// Step scene editor (v4; v3.2 started it): three panes on the Scenes page - the step list on the left,
// the stage in the middle (select lights or, item 11, single pixels), the programmer on the right - with
// the scene's settings in a bar across the top.
//
// Tracking: a step only lists what changes. The programmer shows, for the selection, what's set in
// this step and what's tracked from an earlier one (POST /api/steps/view). Values go into a programmer
// buffer first; Record puts them into the step (merge / overwrite / as a new step / update only what
// the step already sets). Live sends the step (with the buffer) to the rig as you work; Blind doesn't.
// Undo / redo inside the editor; YAML side panel round-trips through the server; copy / paste a
// light's values or a whole step. Every change is checked (validate_scene) and problems are pinned to
// their step.
import { api, attempt, cmd, toast } from "./api.js";
import { $, el, remember } from "./dom.js";
import { t } from "./i18n.js";
import { infoButton } from "./info.js";
import { live } from "./state.js";

let currentStep = 0;
let ctxRef = null;
let docRef = null;
let prog = {}; // programmer buffer: {target: {attr: value}} - not in the step until Recorded
let tab = remember.get("steps.tab", "colour");
let liveMode = remember.get("steps.live", false);
let view = null; // /api/steps/view for the current step
let viewKey = "";
let picked = new Set(); // steps ticked for bulk timing
let loopRange = null; // [a, b] steps to loop (0-based), or null
let stepErr = null; // {step, target, error} from the last check
let stepProblems = []; // [{step, fixture, message}] head-limit notes
let past = [], future = []; // editor undo / redo (doc snapshots)
let lastSnap = "";
let yamlOpen = false;
let previewTimer = null;

const STEP_CLIP = "dmx-suite.step";
const VALUE_CLIP = "dmx-suite.values";
const num = (v) => (v === "" || v === undefined || v === null ? undefined : +v);
const BEAM = ["gobo", "colour_wheel", "strobe", "zoom", "focus", "frost", "prism", "speed"];

function setOrDrop(obj, k, v) {
  if (v === undefined || v === null || v === "" || Number.isNaN(v)) delete obj[k];
  else obj[k] = v;
}

export function isSteps(doc) {
  return doc.type === "steps";
}

export function toggleSteps(doc, on) {
  if (on) {
    doc.type = "steps";
    doc.steps ||= [{ name: t("steps.step_n", { n: 1 }), set: {} }];
    doc.step_s ??= 2;
  } else {
    for (const k of ["type", "steps", "step_s", "step_beats", "fade_s", "playback", "advance", "move", "dark_s"]) delete doc[k];
  }
  currentStep = 0;
  prog = {};
  past = [];
  future = [];
}

// ---------------------------------------------------------------- undo / redo (the editor's own)

function snapshot() {
  const s = JSON.stringify(docRef);
  if (s === lastSnap) return;
  if (lastSnap) past.push(lastSnap);
  if (past.length > 100) past.shift();
  future = [];
  lastSnap = s;
}

function restore(json) {
  const data = JSON.parse(json);
  for (const k of Object.keys(docRef)) delete docRef[k];
  Object.assign(docRef, data);
  lastSnap = json;
  currentStep = Math.min(currentStep, (docRef.steps || [1]).length - 1);
  ctxRef.changed(true);
}

export function undo() { if (past.length) { future.push(JSON.stringify(docRef)); restore(past.pop()); } }
export function redo() { if (future.length) { past.push(JSON.stringify(docRef)); restore(future.pop()); } }

function changed() {
  snapshot();
  ctxRef.changed();
  sendLive();
}

// ---------------------------------------------------------------- helpers

function field(label, control, cls = "") {
  return el("label", { class: "field " + cls }, el("span", { text: label }), control);
}

function numIn(value, onChange, opts = {}) {
  return el("input", { type: "number", class: "narrow", min: opts.min ?? 0, max: opts.max, step: opts.step || 0.1, value: value ?? "",
    placeholder: opts.placeholder || "", "data-k": opts.k || "", onchange: (e) => onChange(num(e.target.value)) });
}

function select(options, value, onChange, attrs = {}) {
  return el("select", { ...attrs, onchange: (e) => onChange(e.target.value) },
    ...options.map(([v, label]) => el("option", { value: v, selected: v === value || undefined }, label)));
}

function hexOf(c) {
  const fx = ctxRef.fx;
  if (!c) return null;
  if (typeof c === "string") return c.startsWith("#") ? c : c === "off" ? "#000000" : fx.colours[c] || null;
  if (typeof c === "object") {
    const v = (k) => Math.min(1, (c[k] || 0) + (c.white || 0));
    return "#" + [v("red"), v("green"), v("blue")].map((x) => Math.round(x * 255).toString(16).padStart(2, "0")).join("");
  }
  return null;
}

// the lights a target names (group, id, pixel selector)
function targetFixtures(target) {
  const [name] = String(target).split(":");
  const cat = live.cat;
  if (name === "all") return cat.fixtures.map((f) => f.id);
  if (cat.groups[name]) return cat.groups[name];
  return cat.fixtures.some((f) => f.id === name) ? [name] : [];
}

const fixtureOf = (id) => live.cat.fixtures.find((f) => f.id === id);
const selIds = () => [...new Set(ctxRef.selectionNames().flatMap(targetFixtures))];

// ---------------------------------------------------------------- live on the rig (or blind)

function stepData(i = currentStep) {
  // the scene with the programmer buffer laid over the step being edited
  const d = JSON.parse(JSON.stringify({ ...docRef, name: docRef.name || "preview" }));
  const st = d.steps[i];
  st.set ||= {};
  for (const [target, attrs] of Object.entries(prog)) st.set[target] = { ...(st.set[target] || {}), ...attrs };
  return d;
}

function sendLive() {
  if (!liveMode || !isSteps(docRef)) return;
  clearTimeout(previewTimer);
  previewTimer = setTimeout(() => {
    if (live.state?.gig_lock) return;
    api("POST", "/api/preview", { scene_data: stepData(), seconds: 300, step: currentStep }).catch(() => {});
  }, 120);
}

function play() {
  if (live.state?.gig_lock) return toast(t("wheel.preview_locked"), true);
  let d = stepData();
  let from = currentStep;
  if (loopRange) { // loop a range: the steps a..b, the first one carrying what earlier steps tracked
    const [a, b] = loopRange;
    const carried = {};
    for (const st of d.steps.slice(0, a + 1)) for (const [k, v] of Object.entries(st.set || {})) carried[k] = { ...(carried[k] || {}), ...v };
    d = { ...d, playback: "loop", steps: [{ ...d.steps[a], set: carried }, ...d.steps.slice(a + 1, b + 1)] };
    from = 0;
  }
  attempt(() => api("POST", "/api/preview", { scene_data: d, seconds: 300, play_from: from }), (r) => r.message);
}

function stop() { attempt(() => api("POST", "/api/control", { cmd: "preview_end" })); }

function go(i) {
  currentStep = Math.max(0, Math.min(docRef.steps.length - 1, i));
  ctxRef.changed(true);
  sendLive();
}

// ---------------------------------------------------------------- set vs tracked (server's view)

async function loadView() {
  const key = JSON.stringify([docRef.steps, currentStep]);
  if (key === viewKey) return;
  viewKey = key;
  try {
    view = await api("POST", "/api/steps/view", { scene: docRef, index: currentStep });
  } catch {
    view = null;
  }
  renderProgrammer();
}

// the value a light shows for an attribute at this step, and where it comes from
function shownValue(attr) {
  const ids = selIds();
  for (const target of Object.keys(prog)) if (prog[target][attr] !== undefined && ctxRef.selectionNames().includes(target)) {
    return { value: prog[target][attr], source: "programmer" };
  }
  for (const id of ids) {
    const e = view?.fixtures?.[id]?.[attr];
    if (e) return e;
  }
  return null;
}

// ---------------------------------------------------------------- the programmer

function put(attr, value) {
  const names = ctxRef.selectionNames();
  if (!names.length) return toast(t("scenes.select_first"), true);
  for (const n of names) {
    prog[n] ||= {};
    if (value === undefined) delete prog[n][attr];
    else prog[n][attr] = value;
    if (!Object.keys(prog[n]).length) delete prog[n];
  }
  renderProgrammer();
  sendLive();
}

// take an attribute out of this step for the selection: it tracks the step before again
function clearFromStep(attr) {
  const st = docRef.steps[currentStep];
  for (const n of ctxRef.selectionNames()) {
    if (st.set?.[n]) {
      delete st.set[n][attr];
      if (!Object.keys(st.set[n]).length) delete st.set[n];
    }
    if (prog[n]) delete prog[n][attr];
  }
  changed();
}

const RELEASE = { colour: "off", strobe: 0, zoom: 0, focus: 0, frost: 0, prism: 0, speed: 0.5 };

function record(mode) {
  const steps = docRef.steps;
  if (!Object.keys(prog).length) return toast(t("steps.prog_empty"), true);
  if (mode === "new") {
    steps.splice(currentStep + 1, 0, { name: t("steps.step_n", { n: steps.length + 1 }), set: JSON.parse(JSON.stringify(prog)) });
    currentStep += 1;
  } else {
    const st = steps[currentStep];
    st.set ||= {};
    if (mode === "overwrite") st.set = {};
    for (const [target, attrs] of Object.entries(prog)) {
      if (mode === "update") { // only what the step already sets
        if (!st.set[target]) continue;
        for (const [k, v] of Object.entries(attrs)) if (k in st.set[target]) st.set[target][k] = v;
      } else st.set[target] = { ...(st.set[target] || {}), ...JSON.parse(JSON.stringify(attrs)) };
    }
  }
  prog = {};
  toast(t("steps.recorded", { n: currentStep + 1 }));
  changed();
}

function marked(attr, control) {
  const s = shownValue(attr);
  const cls = !s ? "unset" : s.source === "programmer" ? "prog" : s.source === "set" ? "set" : "tracked";
  const note = !s ? t("steps.v_unset") : s.source === "programmer" ? t("steps.v_prog")
    : s.source === "set" ? t("steps.v_set") : t("steps.v_tracked", { n: s.from_step + 1 });
  return el("div", { class: `prog-row ${cls}`, "data-attr": attr },
    el("span", { class: "prog-src", text: note }), control,
    el("button", { class: "mini", title: t("steps.clear_tip"), onclick: () => clearFromStep(attr) }, t("steps.clear")),
    attr in RELEASE ? el("button", { class: "mini", title: t("steps.release_tip"), onclick: () => put(attr, RELEASE[attr]) }, t("steps.release")) : "");
}

function colourTab(ids) {
  const fx = ctxRef.fx;
  const cur = shownValue("colour")?.value;
  const emit = new Set(ids.flatMap((id) => fixtureOf(id)?.emitters || []));
  const faders = ["red", "green", "blue", "white", "amber", "uv"].filter((k) => emit.has(k)).map((k) => {
    const base = typeof cur === "object" && cur ? cur : {};
    return field(t("wheel." + k), el("input", { type: "range", min: 0, max: 1, step: 0.01, value: base[k] ?? 0, "data-fader": k,
      onchange: (e) => {
        const c = typeof cur === "object" && cur ? { ...cur } : {};
        c[k] = +e.target.value;
        put("colour", c);
      } }));
  });
  const pals = Object.entries(fx.palettes || {}).map(([k, p]) => el("div", { class: "pal-row" }, el("span", { class: "muted", text: p.name }),
    ...p.hex.map((h, i) => el("button", { class: "sw", style: `background:${h}`, title: p.colours[i], onclick: () => put("colour", p.colours[i]) }))));
  return [marked("colour", ctxRef.swatch(typeof cur === "string" ? cur : undefined, (c) => put("colour", c), true, ids)),
    el("div", { class: "row wrap" }, el("button", { class: "danger-text", "data-off": "1", onclick: () => put("colour", "off") }, t("steps.off"))),
    ...faders, el("details", { class: "scene-more" }, el("summary", { text: t("steps.palettes") }), ...pals)];
}

function positionTab(ids) {
  const heads = ids.filter((id) => fixtureOf(id)?.moves);
  if (!heads.length) return [el("p", { class: "muted", text: t("steps.no_movers") })];
  const lim = live.cat.head_limits?.[heads[0]] || { pan: [0, 1], tilt: [0, 1] };
  const cur = shownValue("position")?.value;
  const xy = typeof cur === "object" && cur ? cur : { pan: 0.5, tilt: 0.5 };
  const pad = el("div", { class: "xy-pad", title: t("steps.xy_tip") });
  const dot = el("span", { class: "xy-dot" });
  const box = el("span", { class: "xy-limits" });
  box.style.cssText = `left:${lim.pan[0] * 100}%;width:${(lim.pan[1] - lim.pan[0]) * 100}%;bottom:${lim.tilt[0] * 100}%;height:${(lim.tilt[1] - lim.tilt[0]) * 100}%`;
  dot.style.cssText = `left:${xy.pan * 100}%;bottom:${xy.tilt * 100}%`;
  pad.append(box, dot);
  const clampTo = (v, [a, b]) => Math.min(b, Math.max(a, v));
  const fromEv = (ev) => {
    const r = pad.getBoundingClientRect();
    return { pan: +clampTo((ev.clientX - r.left) / r.width, lim.pan).toFixed(3), tilt: +clampTo(1 - (ev.clientY - r.top) / r.height, lim.tilt).toFixed(3) };
  };
  pad.addEventListener("pointerdown", (ev) => { pad.setPointerCapture(ev.pointerId); put("position", fromEv(ev)); });
  pad.addEventListener("pointermove", (ev) => { if (pad.hasPointerCapture(ev.pointerId)) put("position", fromEv(ev)); });
  const fine = (k) => numIn(xy[k], (v) => v !== undefined && put("position", { ...xy, [k]: clampTo(v, lim[k]) }), { step: 0.001, max: 1, k });
  const points = (ctxRef.fx.positions || []).map((p) => el("button", { class: "mini" + (cur === p ? " sel" : ""), "data-point": p, onclick: () => put("position", p) }, p));
  return [marked("position", pad), el("div", { class: "row wrap" }, field(t("steps.pan"), fine("pan")), field(t("steps.tilt"), fine("tilt"))),
    el("div", { class: "row wrap point-buttons" }, ...points)];
}

function beamTab(ids) {
  const roles = new Set(ids.flatMap((id) => fixtureOf(id)?.roles || []));
  const out = [];
  if (roles.has("gobo")) {
    out.push(marked("gobo", select([["", t("steps.no_gobo")], ...(ctxRef.fx.gobos || []).map((g) => [g, g])],
      typeof shownValue("gobo")?.value === "string" ? shownValue("gobo").value : "", (v) => put("gobo", v || undefined))));
  }
  for (const k of BEAM.filter((k) => k !== "gobo" && roles.has(k === "speed" ? "pt_speed" : k))) {
    const v = shownValue(k)?.value;
    out.push(marked(k, field(t("steps.channel_" + k), el("input", { type: "range", min: 0, max: k === "colour_wheel" ? 255 : 1,
      step: k === "colour_wheel" ? 1 : 0.01, value: typeof v === "number" ? v : 0, "data-beam": k, onchange: (e) => put(k, +e.target.value) }))));
  }
  return out.length ? out : [el("p", { class: "muted", text: t("steps.no_beam") })];
}

function pixelsTab(ids) {
  const bars = ids.filter((id) => (fixtureOf(id)?.pixels || 1) > 1);
  if (!bars.length) return [el("p", { class: "muted", text: t("steps.no_pixels") })];
  const n = fixtureOf(bars[0]).pixels;
  const cur = shownValue("pixels")?.value;
  const cols = Array.isArray(cur) && cur.length === n ? [...cur] : Array(n).fill("off");
  let a = remember.get("steps.pxa", "red"), b = remember.get("steps.pxb", "blue");
  const row = el("div", { class: "px-row" }, ...cols.map((c, i) => {
    const sw = ctxRef.swatch(c, (v) => { cols[i] = v || "off"; put("pixels", [...cols]); }, false, bars);
    return el("div", { class: "px-cell", title: t("steps.pixel_n", { n: i + 1 }) }, el("span", { class: "muted", text: i + 1 }), sw.querySelector(".wheel-btn") || sw);
  }));
  const fill = () => put("pixels", Array(n).fill(a));
  const alternate = () => put("pixels", [...Array(n).keys()].map((i) => (i % 2 ? b : a)));
  const gradient = () => {
    const ha = hexOf(a) || "#ff0000", hb = hexOf(b) || "#0000ff";
    const pick = (h, i) => parseInt(h.slice(1 + i * 2, 3 + i * 2), 16);
    put("pixels", [...Array(n).keys()].map((i) => {
      const f = n > 1 ? i / (n - 1) : 0;
      return "#" + [0, 1, 2].map((k) => Math.round(pick(ha, k) * (1 - f) + pick(hb, k) * f).toString(16).padStart(2, "0")).join("");
    }));
  };
  return [marked("pixels", row),
    el("div", { class: "row wrap" }, el("span", { class: "muted", text: t("steps.px_a") }),
      ctxRef.swatch(a, (v) => { a = v || "red"; remember.set("steps.pxa", a); }, false, bars),
      el("span", { class: "muted", text: t("steps.px_b") }),
      ctxRef.swatch(b, (v) => { b = v || "blue"; remember.set("steps.pxb", b); }, false, bars)),
    el("div", { class: "row wrap" }, el("button", { "data-px": "fill", onclick: fill }, t("steps.px_fill")),
      el("button", { "data-px": "gradient", onclick: gradient }, t("steps.px_gradient")),
      el("button", { "data-px": "alternate", onclick: alternate }, t("steps.px_alternate")), infoButton("steps.pixels"))];
}

function renderProgrammer() {
  const box = $("#step-programmer");
  if (!box || !isSteps(docRef)) return;
  const ids = selIds();
  const fx = ids.map(fixtureOf).filter(Boolean);
  const tabs = [["colour", fx.some((f) => f.emitters?.length)], ["position", fx.some((f) => f.moves)],
    ["beam", fx.some((f) => BEAM.some((k) => (f.roles || []).includes(k === "speed" ? "pt_speed" : k)))],
    ["pixels", fx.some((f) => (f.pixels || 1) > 1)]].filter(([, ok]) => ok).map(([k]) => k);
  if (!tabs.includes(tab)) tab = tabs[0] || "colour";
  const body = !ids.length ? [el("p", { class: "muted", text: t("steps.select_lights") })]
    : tab === "position" ? positionTab(ids) : tab === "beam" ? beamTab(ids) : tab === "pixels" ? pixelsTab(ids) : colourTab(ids);
  const progN = Object.keys(prog).length;
  box.replaceChildren(
    el("div", { class: "tabs prog-tabs", role: "tablist" }, ...tabs.map((k) => el("button", { class: k === tab ? "on" : "", "data-tab": k,
      onclick: () => { tab = k; remember.set("steps.tab", k); renderProgrammer(); } }, t("steps.tab_" + k)))),
    el("div", { class: "prog-body" }, ...body),
    el("div", { class: "row wrap record-row" },
      el("button", { class: "primary", id: "rec-merge", disabled: !progN || undefined, title: t("steps.rec_merge_tip"), onclick: () => record("merge") }, t("steps.rec_merge")),
      el("button", { id: "rec-overwrite", disabled: !progN || undefined, title: t("steps.rec_overwrite_tip"), onclick: () => record("overwrite") }, t("steps.rec_overwrite")),
      el("button", { id: "rec-new", disabled: !progN || undefined, onclick: () => record("new") }, t("steps.rec_new")),
      el("button", { id: "rec-update", disabled: !progN || undefined, title: t("steps.rec_update_tip"), onclick: () => record("update") }, t("steps.rec_update")),
      infoButton("steps.record"),
      el("button", { class: "mini", id: "prog-clear", disabled: !progN || undefined, onclick: () => { prog = {}; renderProgrammer(); sendLive(); } }, t("steps.prog_clear")),
      el("span", { class: "muted", id: "prog-state", text: progN ? t("steps.prog_n", { n: progN }) : "" })),
    el("div", { class: "row wrap" },
      el("button", { class: "mini", onclick: copyValues, title: t("steps.copy_values_tip") }, t("steps.copy_values")),
      el("button", { class: "mini", onclick: pasteValues }, t("steps.paste_values")),
      el("button", { class: "mini", onclick: () => capture() }, t("steps.capture"))));
}

// ---------------------------------------------------------------- copy / paste

function copyValues() {
  const ids = selIds();
  if (!ids.length) return toast(t("scenes.select_first"), true);
  const vals = {};
  for (const [k, e] of Object.entries(view?.fixtures?.[ids[0]] || {})) if (!k.includes("@")) vals[k] = e.value;
  for (const target of ctxRef.selectionNames()) Object.assign(vals, prog[target] || {});
  try { localStorage.setItem(VALUE_CLIP, JSON.stringify(vals)); } catch {}
  toast(t("steps.values_copied", { n: Object.keys(vals).length }));
}

function pasteValues() {
  let vals = null;
  try { vals = JSON.parse(localStorage.getItem(VALUE_CLIP) || "null"); } catch {}
  if (!vals) return toast(t("scenes.nothing_copied"), true);
  for (const [k, v] of Object.entries(vals)) put(k, v);
}

function copyStep(i) {
  try { localStorage.setItem(STEP_CLIP, JSON.stringify(docRef.steps[i])); } catch {}
  toast(t("steps.step_copied", { n: i + 1 }));
}

function pasteStep() {
  let st = null;
  try { st = JSON.parse(localStorage.getItem(STEP_CLIP) || "null"); } catch {}
  if (!st) return toast(t("scenes.nothing_copied"), true);
  docRef.steps.splice(currentStep + 1, 0, st);
  currentStep += 1;
  changed();
}

async function capture() {
  const names = ctxRef.selectionNames();
  if (!names.length) return toast(t("scenes.select_first"), true);
  const r = await attempt(() => api("POST", "/api/steps/capture", { fixtures: names.map((n) => n.split(":")[0]) }));
  if (!r) return;
  for (const [target, attrs] of Object.entries(r.set)) prog[target] = { ...(prog[target] || {}), ...attrs };
  toast(t("steps.captured", { n: Object.keys(r.set).length }));
  renderProgrammer();
}

// ---------------------------------------------------------------- YAML side panel

async function renderYaml() {
  const box = $("#step-yaml");
  box.classList.toggle("hidden", !yamlOpen);
  if (!yamlOpen) return;
  const r = await api("POST", "/api/yaml/dump", { data: docRef }).catch(() => null);
  if (!r || box.contains(document.activeElement)) return;
  const ta = el("textarea", { class: "yaml-text", spellcheck: "false", rows: 18 });
  ta.value = r.text;
  const apply = el("button", { onclick: async () => {
    const got = await attempt(() => api("POST", "/api/yaml/load", { text: ta.value }));
    if (got) { restoreFrom(got.data); }
  } }, t("steps.yaml_apply"));
  box.replaceChildren(el("h3", { text: t("steps.yaml") }), ta, apply);
}

function restoreFrom(data) {
  snapshot();
  for (const k of Object.keys(docRef)) delete docRef[k];
  Object.assign(docRef, data);
  docRef.layers ||= []; // effects on top: none written is none
  if (!isSteps(docRef)) toggleSteps(docRef, true);
  ctxRef.changed();
}

// ---------------------------------------------------------------- the panes

function thumb(st) {
  const chips = Object.values(st.set || {}).map((a) => hexOf(a.colour)).filter(Boolean).slice(0, 6);
  return el("span", { class: "step-thumb" }, ...chips.map((h) => el("span", { class: "chip-c", style: `background:${h}` })));
}

function timing(st) {
  const bits = [];
  if (st.step_beats !== undefined) bits.push(t("steps.beats_n", { n: st.step_beats }));
  else if (st.step_s !== undefined) bits.push(`${st.step_s}s`);
  if (st.fade_s !== undefined) bits.push(t("steps.fade_short", { s: st.fade_s }));
  if (st.move) bits.push(t("steps.move_" + st.move));
  return bits.join(" · ");
}

function renderList() {
  const steps = docRef.steps;
  let dragFrom = null;
  const rows = steps.map((st, i) => {
    const bad = stepErr && stepErr.step === i;
    const warn = stepProblems.some((p) => p.step === i);
    const li = el("li", { class: [i === currentStep ? "on" : "", bad ? "error" : "", warn ? "warn" : "", loopRange && i >= loopRange[0] && i <= loopRange[1] ? "looped" : ""].join(" ").trim(),
      "data-step": i, draggable: "true", title: bad ? stepErr.error : warn ? stepProblems.filter((p) => p.step === i).map((p) => p.message).join("\n") : "" },
    el("input", { type: "checkbox", class: "step-pick", checked: picked.has(i) || undefined, title: t("steps.pick_tip"),
      onchange: (e) => { if (e.target.checked) picked.add(i); else picked.delete(i); renderList(); } }),
    el("button", { class: "link name", onclick: () => go(i) }, el("b", { text: `${i + 1}` }), ` ${st.name || ""}`),
    thumb(st), el("span", { class: "muted step-time", text: timing(st) }),
    el("span", { class: "tools" },
      el("button", { class: "mini", title: t("steps.insert_after"), onclick: () => { steps.splice(i + 1, 0, { name: t("steps.step_n", { n: steps.length + 1 }), set: {} }); currentStep = i + 1; changed(); } }, "+"),
      el("button", { class: "mini", title: t("steps.duplicate"), onclick: () => { steps.splice(i + 1, 0, JSON.parse(JSON.stringify(st))); currentStep = i + 1; changed(); } }, "⧉"),
      el("button", { class: "mini", title: t("steps.copy_step"), onclick: () => copyStep(i) }, "⎘"),
      el("button", { class: "mini danger-text", title: t("scenes.remove"), disabled: steps.length < 2 || undefined,
        onclick: () => { steps.splice(i, 1); currentStep = Math.max(0, Math.min(currentStep, steps.length - 1)); picked.clear(); changed(); } }, "✕")));
    li.addEventListener("dragstart", () => { dragFrom = i; });
    li.addEventListener("dragover", (e) => e.preventDefault());
    li.addEventListener("drop", (e) => {
      e.preventDefault();
      if (dragFrom === null || dragFrom === i) return;
      steps.splice(i, 0, ...steps.splice(dragFrom, 1));
      currentStep = i;
      picked.clear();
      changed();
    });
    return li;
  });
  const bulk = picked.size > 1 ? el("div", { class: "row wrap bulk" }, el("span", { class: "muted", text: t("steps.bulk", { n: picked.size }) }),
    numIn(undefined, (v) => { for (const i of picked) setOrDrop(steps[i], "step_s", v); changed(); }, { placeholder: t("steps.step_time"), k: "bulk-step" }),
    numIn(undefined, (v) => { for (const i of picked) setOrDrop(steps[i], "fade_s", v); changed(); }, { placeholder: t("steps.fade_time"), k: "bulk-fade" }),
    el("button", { class: "mini", onclick: () => { const ix = [...picked].sort((a, b) => a - b); loopRange = [ix[0], ix[ix.length - 1]]; renderList(); } }, t("steps.loop_range")),
    el("button", { class: "mini", onclick: () => { picked.clear(); loopRange = null; renderList(); } }, t("steps.unpick"))) : "";
  $("#steps-list-pane").replaceChildren(
    el("h2", {}, el("span", { text: t("steps.title") }), " ", infoButton("steps.list")),
    el("ol", { class: "steps-list" }, ...rows), bulk,
    el("div", { class: "row wrap" },
      el("button", { id: "step-add", onclick: () => { steps.push({ name: t("steps.step_n", { n: steps.length + 1 }), set: {} }); currentStep = steps.length - 1; changed(); } }, t("steps.add")),
      el("button", { class: "mini", onclick: pasteStep }, t("steps.paste_step"))));
}

function renderBar(ctx) {
  const d = docRef;
  const adv = typeof d.advance === "object" ? "input:" + d.advance.input : d.advance || "timer";
  const length = (d.steps || []).reduce((s, st) => s + (st.step_s ?? d.step_s ?? 2), 0);
  $("#steps-bar").replaceChildren(
    field(t("scenes.show_colour"), ctx.swatch(d.show_colour, (c) => { setOrDrop(d, "show_colour", c); changed(); }, true)),
    field(t("steps.step_time"), numIn(d.step_s, (v) => { setOrDrop(d, "step_s", v); changed(); }, { k: "step_s" })),
    field(t("steps.step_beats"), numIn(d.step_beats, (v) => { setOrDrop(d, "step_beats", v); changed(); }, { step: 1, placeholder: t("steps.beats_hint"), k: "step_beats" })),
    field(t("steps.fade_time"), numIn(d.fade_s, (v) => { setOrDrop(d, "fade_s", v); changed(); }, { k: "fade_s" })),
    field(t("steps.playback"), select(["loop", "once", "bounce"].map((p) => [p, t("steps.playback_" + p)]), d.playback || "loop",
      (v) => { setOrDrop(d, "playback", v === "loop" ? undefined : v); changed(); })),
    field(t("steps.advance"), select([["timer", t("steps.advance_timer")], ["manual", t("steps.advance_manual")],
      ...(ctx.inputs || []).map((i) => ["input:" + i.id, t("steps.advance_input", { name: i.name })])], adv, (v) => {
      setOrDrop(d, "advance", v === "timer" ? undefined : v.startsWith("input:") ? { input: v.slice(6) } : v);
      changed();
    })),
    field(t("steps.move"), select([["", t("steps.move_profile")], ["dark", t("steps.move_dark")], ["lit", t("steps.move_lit")]], d.move || "",
      (v) => { setOrDrop(d, "move", v || undefined); changed(); })),
    field(t("steps.dark_s"), numIn(d.dark_s, (v) => { setOrDrop(d, "dark_s", v); changed(); }, { max: 5, k: "dark_s" })),
    el("span", { class: "muted", id: "steps-length", text: t("steps.length", { s: Math.round(length * 10) / 10 }) }),
    infoButton("steps.bar"));
}

function renderTransport() {
  const st = docRef.steps[currentStep];
  return el("div", { class: "row wrap transport" },
    el("button", { class: "icon", title: t("steps.prev"), onclick: () => go(currentStep - 1) }, "◀"),
    el("button", { class: "icon", id: "step-play", title: t("steps.play"), onclick: play }, "▶"),
    el("button", { class: "icon", title: t("steps.stop"), onclick: stop }, "■"),
    el("button", { class: "icon", title: t("steps.next"), onclick: () => go(currentStep + 1) }, "▶|"),
    numIn(currentStep + 1, (v) => v && go(v - 1), { min: 1, max: docRef.steps.length, step: 1, k: "goto" }),
    docRef.step_beats !== undefined || st.step_beats !== undefined ? el("button", { onclick: () => cmd("tap") }, t("live.tap")) : "",
    el("label", { class: "check", title: t("steps.live_tip") }, el("input", { type: "checkbox", id: "steps-live", checked: liveMode || undefined,
      onchange: (e) => { liveMode = e.target.checked; remember.set("steps.live", liveMode); if (liveMode) sendLive(); else stop(); } }), t("steps.live")),
    infoButton("steps.live"),
    el("button", { class: "mini", title: "Ctrl+Z", disabled: !past.length || undefined, id: "steps-undo", onclick: undo }, t("layout.undo")),
    el("button", { class: "mini", title: "Ctrl+Shift+Z", disabled: !future.length || undefined, id: "steps-redo", onclick: redo }, t("layout.redo")),
    el("button", { class: "mini" + (yamlOpen ? " sel" : ""), id: "steps-yaml", onclick: () => { yamlOpen = !yamlOpen; renderYaml(); renderTransportOnly(); } }, t("steps.yaml")));
}

function renderTransportOnly() {
  const old = $("#steps-editor .transport");
  if (old) old.replaceWith(renderTransport());
}

export function renderSteps(doc, ctx) {
  docRef = doc;
  ctxRef = ctx;
  const on = isSteps(doc);
  $("#page-scenes .builder").classList.toggle("steps-mode", on);
  for (const id of ["#steps-editor", "#steps-list-pane", "#steps-bar"]) $(id).classList.toggle("hidden", !on);
  if (!on) return;
  if (!lastSnap) lastSnap = JSON.stringify(doc);
  currentStep = Math.min(currentStep, doc.steps.length - 1);
  renderBar(ctx);
  renderList();
  const st = doc.steps[currentStep];
  const stepForm = el("div", { class: "form step-form" },
    field(t("steps.name"), el("input", { value: st.name || "", "data-k": "name", onchange: (e) => { st.name = e.target.value; changed(); } })),
    field(t("steps.step_time_own"), numIn(st.step_s, (v) => { setOrDrop(st, "step_s", v); changed(); }, { placeholder: t("steps.default"), k: "own_step_s" })),
    field(t("steps.step_beats"), numIn(st.step_beats, (v) => { setOrDrop(st, "step_beats", v); changed(); }, { step: 1, placeholder: t("steps.default"), k: "own_step_beats" })),
    field(t("steps.fade_time_own"), numIn(st.fade_s, (v) => { setOrDrop(st, "fade_s", v); changed(); }, { placeholder: t("steps.default"), k: "own_fade_s" })),
    field(t("steps.move"), select([["", t("steps.move_scene")], ["dark", t("steps.move_dark")], ["lit", t("steps.move_lit")]], st.move || "",
      (v) => { setOrDrop(st, "move", v || undefined); changed(); })));
  const errNote = stepErr && stepErr.step === currentStep ? el("div", { class: "error", text: stepErr.error }) : "";
  const warns = stepProblems.filter((p) => p.step === currentStep).map((p) => el("div", { class: "warn-note", text: p.message }));
  $("#steps-editor").replaceChildren(
    renderTransport(),
    el("h3", {}, el("span", { text: t("steps.this_step", { n: currentStep + 1 }) + (st.name ? ` · ${st.name}` : "") }), " ", infoButton("steps.programmer")),
    errNote, ...warns,
    el("p", { class: "muted", text: t("steps.tracking_help") }),
    el("div", { id: "step-programmer", class: "programmer" }),
    el("details", { class: "scene-more" }, el("summary", { text: t("steps.step_timing") }), stepForm),
    el("div", { id: "step-yaml", class: "step-yaml hidden" }));
  renderProgrammer();
  loadView();
  if (yamlOpen) renderYaml();
}

// the scene builder's check: errors and head-limit problems pinned to their step
export function showStepCheck(r) {
  stepErr = r && !r.ok && r.step !== null && r.step !== undefined ? r : null;
  stepProblems = (r && r.problems) || [];
  if (docRef && isSteps(docRef)) { renderList(); }
}

export function selectionChanged() {
  if (docRef && isSteps(docRef)) renderProgrammer();
}

export function keyDown(ev) {
  if (!docRef || !isSteps(docRef)) return false;
  const mod = ev.ctrlKey || ev.metaKey, k = ev.key.toLowerCase();
  if (mod && k === "z" && !ev.shiftKey) { undo(); return true; }
  if (mod && (k === "y" || (k === "z" && ev.shiftKey))) { redo(); return true; }
  if (!mod && ev.key === "PageDown") { go(currentStep + 1); return true; }
  if (!mod && ev.key === "PageUp") { go(currentStep - 1); return true; }
  return false;
}

export const _test = { get prog() { return prog; }, get currentStep() { return currentStep; } };
