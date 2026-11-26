// Fixtures page: the patch (where each light sits), fixture types (channel maps, wheel and gobo
// slots, Open Fixture Library import/export) and the rig settings. Saves go through the store
// (checked, backed up, undoable) and apply live.
import { api, attempt, cmd, get, toast } from "../api.js";
import { $, $$, el } from "../dom.js";
import { t } from "../i18n.js";
import { onShow } from "../nav.js";
import { live, onCatalogue, refreshCatalogue } from "../state.js";

const KINDS = ["head", "bar", "wash", "kick", "haze"];
const SUBS = ["", "head", "bar", "wash", "kick"];
const ROLES = ["dimmer", "dimmer_fine", "red", "green", "blue", "white", "amber", "uv", "pan", "pan_fine", "tilt", "tilt_fine",
  "pt_speed", "colour_wheel", "gobo", "strobe", "zoom", "zoom_fine", "focus", "focus_fine", "frost", "prism", "haze", "fixed"];
const INVERTIBLE = ["pan", "tilt", "zoom", "focus", "frost", "pt_speed"];
const DRIVERS = ["node", "usb_dmx_open", "usb_dmx_pro", "artnet", "sacn", "log", "null"];

let doc = null; // fixtures.yaml as data
let saved = "";
let tab = "patch";
let typeKey = null;
let rigName = null;
let rig = null;
let rigSaved = "";
let testFixture = null;

// ---------------------------------------------------------------- helpers

const footprint = (type) => (doc.types[type]?.channels || []).length;

function clashes(rows) {
  const out = new Set();
  const used = new Map();
  for (const f of rows) {
    const n = footprint(f.type);
    const u = +f.universe || 0;
    if (!n || !f.address) continue;
    if (f.address < 1 || f.address + n - 1 > 512) out.add(f.id);
    for (let c = f.address; c < f.address + n; c++) {
      const k = `${u}:${c}`;
      if (used.has(k)) { out.add(f.id); out.add(used.get(k)); }
      else used.set(k, f.id);
    }
  }
  return out;
}

// next free addresses, in patch order, for the rows that need one (or all)
export function autoPatch(rows, types, all = false) {
  const size = (r) => (types[r.type]?.channels || []).length;
  const taken = new Map(); // universe -> list of [start, end]
  const fits = (u, a, n) => a >= 1 && a + n - 1 <= 512 && !(taken.get(u) || []).some(([s, e]) => a <= e && a + n - 1 >= s);
  const place = (u, a, n) => { if (!taken.has(u)) taken.set(u, []); taken.get(u).push([a, a + n - 1]); };
  const keep = all ? [] : rows.filter((r) => r.address && fits(+r.universe || 0, r.address, size(r)));
  for (const r of keep) place(+r.universe || 0, r.address, size(r));
  for (const r of rows) {
    if (keep.includes(r)) continue;
    const n = size(r);
    let u = +r.universe || 0;
    let a = 1;
    while (!fits(u, a, n)) {
      a += 1;
      if (a + n - 1 > 512) { u += 1; a = 1; }
      if (u > 15) break;
    }
    r.universe = u;
    r.address = a;
    place(u, a, n);
  }
  return rows;
}

function dirty() {
  const d = JSON.stringify(doc) !== saved;
  $("#fx-state").textContent = d ? t("shows.unsaved") : "";
  return d;
}

function num(value, oninput, attrs = {}) {
  return el("input", { type: "number", value: value ?? "", class: "num", ...attrs, oninput: (e) => oninput(e.target.value === "" ? undefined : +e.target.value) });
}

function select(options, value, onChange) {
  return el("select", { onchange: (e) => onChange(e.target.value) },
    ...options.map((o) => (Array.isArray(o) ? o : [o, o])).map(([v, label]) => el("option", { value: v, selected: v === value }, label)));
}

// ---------------------------------------------------------------- patch

function renderPatch() {
  const rows = doc.fixtures;
  const bad = clashes(rows);
  const typeNames = Object.entries(doc.types).map(([k, ty]) => [k, ty.name || k]);
  $("#fx-patch").replaceChildren(...rows.map((f, i) => el("tr", { class: bad.has(f.id) ? "error" : "" },
    el("td", {}, el("input", { value: f.id, class: "narrow", oninput: (e) => { f.id = e.target.value.trim(); dirty(); } })),
    el("td", {}, select(typeNames, f.type, (v) => { f.type = v; renderPatch(); })),
    el("td", {}, num(f.universe ?? 0, (v) => { f.universe = v ?? 0; renderPatch(); }, { min: 0, max: 15 })),
    el("td", {}, num(f.address, (v) => { f.address = v; renderPatch(); }, { min: 1, max: 512 })),
    el("td", { class: "muted", text: f.address ? `${f.address}-${f.address + footprint(f.type) - 1}` : "" }),
    el("td", {}, el("input", { value: (f.groups || []).join(", "), placeholder: t("fixtures.groups_placeholder"),
      oninput: (e) => { const g = e.target.value.split(",").map((x) => x.trim()).filter(Boolean); if (g.length) f.groups = g; else delete f.groups; dirty(); } })),
    el("td", {}, select(SUBS.map((s) => [s, s || t("fixtures.sub_kind")]), f.sub || "", (v) => { if (v) f.sub = v; else delete f.sub; dirty(); })),
    el("td", { class: "tools" },
      el("button", { title: t("fixtures.find_tip"), class: live.state?.setup.find === f.id ? "sel" : "", onclick: () => cmd("find", { fixture: live.state?.setup.find === f.id ? null : f.id }) }, t("fixtures.find")),
      el("button", { class: "danger-text", title: t("fixtures.remove_tip"), onclick: () => removeFixture(f, i) }, "✕")))));
  $("#fx-clash").textContent = bad.size ? t("fixtures.clash", { ids: [...bad].join(", ") }) : "";
  $("#fx-patch-save").disabled = bad.size > 0;
  dirty();
}

async function removeFixture(f, i) {
  if (!saved.includes(`"id":"${f.id}"`)) { // not saved yet: just drop the row
    doc.fixtures.splice(i, 1);
    return renderPatch();
  }
  if (!confirm(t("fixtures.confirm_remove", { id: f.id }))) return;
  if (await attempt(() => api("POST", "/api/store/fixture/remove", { id: f.id }), t("fixtures.removed", { id: f.id }))) await load();
}

function addFixtures() {
  const type = $("#fx-add-type").value;
  const n = Math.max(1, Math.min(64, +$("#fx-add-count").value || 1));
  const base = ($("#fx-add-id").value.trim() || type).toLowerCase().replace(/[^a-z0-9_]+/g, "_");
  const ids = new Set(doc.fixtures.map((f) => f.id));
  const fresh = [];
  for (let k = 1; fresh.length < n; k++) {
    const id = n === 1 && !ids.has(base) ? base : `${base}_${k}`;
    if (!ids.has(id)) { ids.add(id); fresh.push({ id, type, universe: 0, address: 0 }); }
  }
  doc.fixtures.push(...fresh);
  autoPatch(doc.fixtures, doc.types, false);
  renderPatch();
}

async function savePatch() {
  if (await attempt(() => api("PUT", "/api/store/patch", { fixtures: doc.fixtures }), t("fixtures.patch_saved"))) {
    saved = JSON.stringify(doc);
    await refreshCatalogue();
    renderPatch();
  }
}

// ---------------------------------------------------------------- types

function renderTypes() {
  const keys = Object.keys(doc.types);
  if (!typeKey || !doc.types[typeKey]) typeKey = keys[0] || null;
  $("#fx-type-pick").replaceChildren(...keys.map((k) => el("option", { value: k, selected: k === typeKey }, `${doc.types[k].name || k} (${k})`)));
  const ty = doc.types[typeKey];
  const box = $("#fx-type");
  if (!ty) return box.replaceChildren(el("p", { class: "muted", text: t("fixtures.no_types") }));
  ty.channels ||= [];
  const chan = (c) => (typeof c === "string" ? { role: c } : c);
  const set = (i, k, v) => {
    const c = { ...chan(ty.channels[i]) };
    if (v === undefined || v === "" || v === false || (k === "default" && v === 0)) delete c[k];
    else c[k] = v;
    ty.channels[i] = Object.keys(c).length === 1 ? c.role : c;
    renderTypes();
  };
  const field = (label, control) => el("label", { class: "field" }, el("span", { text: label }), control);
  const usedBy = doc.fixtures.filter((f) => f.type === typeKey);
  testFixture = usedBy.some((f) => f.id === testFixture) ? testFixture : usedBy[0]?.id || null;
  box.replaceChildren(
    el("div", { class: "form" },
      field(t("fixtures.type_name"), el("input", { value: ty.name || "", oninput: (e) => { ty.name = e.target.value; dirty(); } })),
      field(t("fixtures.kind"), select(KINDS, ty.kind, (v) => { ty.kind = v; renderTypes(); })),
      field(t("fixtures.colour_mix"), select([["auto", t("fixtures.mix_auto")], ["off", t("fixtures.mix_off")]], ty.colour_mix || "auto", (v) => { ty.colour_mix = v; renderTypes(); })),
      field(t("fixtures.sub"), select(SUBS.map((s) => [s, s || t("fixtures.sub_kind")]), ty.sub || "", (v) => { if (v) ty.sub = v; else delete ty.sub; dirty(); })),
      field(t("fixtures.colour_only"), el("input", { type: "checkbox", checked: !!ty.colour_only, onchange: (e) => { if (e.target.checked) ty.colour_only = true; else delete ty.colour_only; dirty(); } })),
      field(t("fixtures.verified"), el("input", { type: "checkbox", checked: !!ty.verified, onchange: (e) => { ty.verified = e.target.checked; dirty(); } })),
      field(t("fixtures.pan_range"), num(ty.pan_range, (v) => { if (v === undefined) delete ty.pan_range; else ty.pan_range = v; dirty(); }, { step: 1 })),
      field(t("fixtures.tilt_range"), num(ty.tilt_range, (v) => { if (v === undefined) delete ty.tilt_range; else ty.tilt_range = v; dirty(); }, { step: 1 }))),
    el("h3", { text: t("fixtures.channels", { n: ty.channels.length }) }),
    el("div", { class: "row wrap" }, el("span", { class: "muted", text: t("fixtures.test_on") }),
      select([["", "-"], ...usedBy.map((f) => [f.id, f.id])], testFixture || "", (v) => { testFixture = v || null; renderTypes(); })),
    el("table", { class: "grid-table" },
      el("thead", {}, el("tr", {}, ...["#", t("fixtures.role"), t("fixtures.default"), t("fixtures.pixel"), t("fixtures.invert"), t("fixtures.test"), ""].map((h) => el("th", { text: h })))),
      el("tbody", {}, ...ty.channels.map((raw, i) => {
        const c = chan(raw);
        return el("tr", {},
          el("td", { class: "muted", text: i + 1 }),
          el("td", {}, select(ROLES, c.role, (v) => set(i, "role", v))),
          el("td", {}, num(c.default, (v) => set(i, "default", v), { min: 0, max: 255 })),
          el("td", {}, ["red", "green", "blue", "white", "amber", "uv"].includes(c.role) ? num(c.pixel === undefined ? undefined : c.pixel + 1, (v) => set(i, "pixel", v === undefined ? undefined : v - 1), { min: 1 }) : ""),
          el("td", {}, INVERTIBLE.includes(c.role) ? el("input", { type: "checkbox", checked: !!c.invert, onchange: (e) => set(i, "invert", e.target.checked) }) : ""),
          el("td", {}, testFixture ? testSlider(i) : ""),
          el("td", { class: "tools" },
            el("button", { disabled: i === 0, onclick: () => { ty.channels.splice(i - 1, 0, ...ty.channels.splice(i, 1)); renderTypes(); } }, "↑"),
            el("button", { class: "danger-text", onclick: () => { ty.channels.splice(i, 1); renderTypes(); } }, "✕")));
      }))),
    el("div", { class: "row wrap" }, el("button", { onclick: () => { ty.channels.push("dimmer"); renderTypes(); } }, t("fixtures.add_channel"))),
    slotTable(ty, "wheel", t("fixtures.wheel"), true),
    slotTable(ty, "gobos", t("fixtures.gobos"), false));
  dirty();
}

function testSlider(i) {
  const f = doc.fixtures.find((x) => x.id === testFixture);
  const inp = el("input", { type: "range", min: 0, max: 255, value: 0, class: "mini", "aria-label": t("fixtures.test") });
  const send = (v) => cmd("chan", { channel: f.address + i, value: v, universe: +f.universe || 0 });
  inp.addEventListener("input", () => send(+inp.value));
  inp.addEventListener("dblclick", () => { inp.value = 0; send(null); });
  return inp;
}

function slotTable(ty, key, title, colours) {
  const slots = ty[key] || {};
  const rows = Object.entries(slots).map(([name, v]) => {
    const value = typeof v === "object" ? v.value : v;
    const colour = typeof v === "object" ? v.colour : undefined;
    const write = (n, val, col) => {
      const next = {};
      for (const [k, x] of Object.entries(ty[key] || {})) {
        if (k !== name) next[k] = x;
        else if (n) next[n] = colours && col ? { value: val, colour: col } : val;
      }
      if (Object.keys(next).length) ty[key] = next; else delete ty[key];
      renderTypes();
    };
    return el("tr", {},
      el("td", {}, el("input", { value: name, class: "narrow", onchange: (e) => write(e.target.value.trim().toLowerCase().replace(/[^a-z0-9_]+/g, "_"), value, colour) })),
      el("td", {}, num(value, (val) => write(name, val ?? 0, colour), { min: 0, max: 255 })),
      colours ? el("td", {}, el("input", { type: "color", value: colour || "#ffffff", onchange: (e) => write(name, value, e.target.value) })) : el("td"),
      el("td", {}, el("button", { class: "danger-text", onclick: () => write(null) }, "✕")));
  });
  return el("div", {},
    el("h3", { text: title }),
    el("table", { class: "grid-table" }, el("tbody", {}, ...rows)),
    el("button", { onclick: () => {
      ty[key] = { ...(ty[key] || {}) };
      let n = 1;
      while (ty[key][`slot${n}`] !== undefined) n++;
      ty[key][`slot${n}`] = colours ? { value: 0, colour: "#ffffff" } : 0;
      renderTypes();
    } }, t("fixtures.add_slot")));
}

async function saveType() {
  const key = typeKey;
  if (await attempt(() => api("PUT", `/api/store/fixtures/types/${encodeURIComponent(key)}`, { value: doc.types[key] }), t("fixtures.type_saved", { key }))) {
    const fresh = await get("/api/store/fixtures");
    doc.types[key] = fresh.types[key];
    saved = JSON.stringify({ ...JSON.parse(saved), types: { ...JSON.parse(saved).types, [key]: fresh.types[key] } });
    await refreshCatalogue();
    renderTypes();
  }
}

function newType() {
  const key = (prompt(t("fixtures.type_key_prompt")) || "").trim().toLowerCase().replace(/[^a-z0-9_-]+/g, "_");
  if (!key) return;
  if (doc.types[key]) return toast(t("fixtures.type_exists", { key }), true);
  doc.types[key] = { name: key, kind: "wash", colour_mix: "auto", verified: false, channels: ["dimmer", "red", "green", "blue"] };
  typeKey = key;
  renderTypes();
}

async function deleteType() {
  if (!typeKey || !confirm(t("fixtures.confirm_delete_type", { key: typeKey }))) return;
  if (doc.fixtures.some((f) => f.type === typeKey)) return toast(t("fixtures.type_in_use", { key: typeKey }), true);
  if (!JSON.parse(saved).types[typeKey]) { delete doc.types[typeKey]; typeKey = null; return renderTypes(); }
  if (await attempt(() => api("DELETE", `/api/store/fixtures/types/${encodeURIComponent(typeKey)}`), t("fixtures.type_deleted", { key: typeKey }))) await load();
}

async function importOfl(file) {
  if (!file) return;
  const text = await file.text();
  let r = await attempt(() => api("POST", "/api/ofl/import", { json: text }));
  if (!r) return;
  if (!r.entry) {
    const mode = prompt(t("fixtures.pick_mode", { modes: r.modes.join(", ") }), r.modes[0]);
    if (!mode) return;
    r = await attempt(() => api("POST", "/api/ofl/import", { json: text, mode }));
    if (!r?.entry) return;
  }
  const [key, entry] = Object.entries(r.entry)[0];
  let k = key;
  while (doc.types[k]) k += "_2";
  doc.types[k] = entry;
  typeKey = k;
  renderTypes();
  toast(r.warnings?.length ? t("fixtures.imported_warn", { key: k, n: r.warnings.length }) : t("fixtures.imported", { key: k }));
}

// ---------------------------------------------------------------- rig settings

async function loadRig(name) {
  rigName = name || live.cat.rig_name;
  rig = await get(`/api/store/rig/${encodeURIComponent(rigName)}`);
  rigSaved = JSON.stringify(rig);
  renderRig();
}

function renderRig() {
  if (!rig) return;
  $("#fx-rig-pick").replaceChildren(...(live.cat.rigs || [rigName]).map((r) => el("option", { value: r, selected: r === rigName }, r + (r === live.cat.rig_name ? ` (${t("fixtures.running")})` : ""))));
  $("#fx-rig-use").disabled = rigName === live.cat.rig_name;
  const pct = (obj, k, dflt = 100) => num(obj[k] ?? dflt, (v) => { if (v === undefined) delete obj[k]; else obj[k] = v; rigDirty(); }, { min: 0, max: 100 });
  const secs = (obj, k, dflt) => num(obj[k] ?? dflt, (v) => { if (v === undefined) delete obj[k]; else obj[k] = v; rigDirty(); }, { min: 0, step: 0.1 });
  const field = (label, control) => el("label", { class: "field" }, el("span", { text: label }), control);
  const ids = doc ? doc.fixtures.map((f) => f.id) : [];
  const inRig = new Set(rig.fixtures && !rig.fixtures.includes("all") ? rig.fixtures : ids);
  const heads = doc ? doc.fixtures.filter((f) => (doc.types[f.type]?.channels || []).some((c) => (c.role || c) === "pan") && !doc.types[f.type]?.colour_only) : [];
  rig.haze ||= {};
  rig.tempo ||= {};
  rig.osc ||= {};
  rig.sub_masters ||= {};
  rig.head_limits ||= {};
  const profile = typeof rig.profile === "string" ? rig.profile : "custom";
  $("#fx-rig").replaceChildren(
    el("div", { class: "form" },
      field(t("fixtures.profile"), profile === "custom" ? el("span", { class: "muted", text: t("fixtures.profile_custom") })
        : select([["0.05_band", t("fixtures.profile_band")], ["generic", t("fixtures.profile_generic")]], profile, (v) => { rig.profile = v; rigDirty(); })),
      field(t("fixtures.grand"), pct(rig, "grand_master")),
      field(t("fixtures.flash_level"), pct(rig, "flash_level")),
      ...["head", "bar", "wash", "kick"].map((k) => field(t("live.sub_" + k), pct(rig.sub_masters, k))),
      field(t("fixtures.fade_s"), secs(rig, "fade_s", 0.3)),
      field(t("fixtures.change_fade_s"), secs(rig, "change_fade_s", 0))),
    el("h3", { text: t("fixtures.in_rig") }),
    el("div", { class: "row wrap" }, ...ids.map((id) => el("label", { class: "check" },
      el("input", { type: "checkbox", checked: inRig.has(id), onchange: (e) => {
        if (e.target.checked) inRig.add(id); else inRig.delete(id);
        rig.fixtures = ids.filter((x) => inRig.has(x));
        if (rig.fixtures.length === ids.length) rig.fixtures = ["all"];
        rigDirty();
      } }), el("span", { text: id })))),
    el("h3", { text: t("fixtures.head_limits") }),
    el("table", { class: "grid-table" }, el("tbody", {}, ...heads.map((f) => {
      const lim = rig.head_limits[f.id] || {};
      const edge = (axis, end) => num((lim[axis] || [0, 100])[end], (v) => {
        const cur = rig.head_limits[f.id] || {};
        const pair = [...(cur[axis] || [0, 100])];
        pair[end] = v ?? (end ? 100 : 0);
        rig.head_limits[f.id] = { ...cur, [axis]: pair };
        rigDirty();
      }, { min: 0, max: 100 });
      return el("tr", {}, el("td", { text: f.id }), el("td", { class: "muted", text: t("fixtures.pan") }), el("td", {}, edge("pan", 0)), el("td", {}, edge("pan", 1)),
        el("td", { class: "muted", text: t("fixtures.tilt") }), el("td", {}, edge("tilt", 0)), el("td", {}, edge("tilt", 1)));
    }))),
    el("h3", { text: t("fixtures.haze") }),
    el("div", { class: "form" },
      field(t("fixtures.haze_enabled"), el("input", { type: "checkbox", checked: rig.haze.enabled !== false, onchange: (e) => { rig.haze.enabled = e.target.checked; rigDirty(); } })),
      field(t("fixtures.haze_mode"), select(["off", "manual", "pulse"], rig.haze.default_mode === false ? "off" : rig.haze.default_mode || "off", (v) => { rig.haze.default_mode = v; rigDirty(); })),
      field(t("fixtures.haze_level"), pct(rig.haze, "level", 60)),
      field(t("fixtures.haze_boost"), pct(rig.haze, "boost_level", 100))),
    el("h3", { text: t("fixtures.tempo") }),
    el("div", { class: "form" },
      field(t("fixtures.tempo_source"), select(["tap", "kick", "midi_clock"].map((s) => [s, t("tempo." + s)]), rig.tempo.source || "tap", (v) => { rig.tempo.source = v; rigDirty(); })),
      field(t("fixtures.kick_note"), num(rig.tempo.kick_note ?? 36, (v) => { rig.tempo.kick_note = v ?? 36; rigDirty(); }, { min: 0, max: 127 })),
      field(t("fixtures.tempo_timeout"), secs(rig.tempo, "timeout_s", 30))),
    el("h3", { text: t("fixtures.outputs") }),
    el("p", { class: "muted", text: t("fixtures.outputs_help") }),
    el("table", { class: "grid-table" }, el("tbody", {}, ...(rig.outputs || []).map((o, i) => el("tr", {},
      el("td", {}, select(DRIVERS, o.driver, (v) => { o.driver = v; rigDirty(); })),
      el("td", {}, el("input", { value: Object.entries(o).filter(([k]) => k !== "driver").map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`).join(" "),
        placeholder: t("fixtures.output_settings"), class: "wide",
        onchange: (e) => {
          const next = { driver: o.driver };
          for (const part of e.target.value.split(/\s+/).filter(Boolean)) {
            const [k, ...rest] = part.split("=");
            const v = rest.join("=");
            try { next[k] = JSON.parse(v); } catch { next[k] = v; }
          }
          rig.outputs[i] = next;
          rigDirty();
        } })),
      el("td", {}, el("button", { class: "danger-text", onclick: () => { rig.outputs.splice(i, 1); renderRig(); rigDirty(); } }, "✕")))))),
    el("button", { onclick: () => { (rig.outputs ||= []).push({ driver: "log" }); renderRig(); rigDirty(); } }, t("fixtures.add_output")),
    el("h3", { text: t("fixtures.inputs") }),
    el("div", { class: "form" },
      field(t("fixtures.midi_inputs"), el("input", { value: (rig.midi_inputs || []).join(", "), placeholder: t("fixtures.midi_inputs_placeholder"),
        onchange: (e) => { const v = e.target.value.split(",").map((x) => x.trim()).filter(Boolean); if (v.length) rig.midi_inputs = v; else delete rig.midi_inputs; rigDirty(); } })),
      field(t("fixtures.osc_port"), num(rig.osc.port, (v) => { if (v === undefined) delete rig.osc.port; else rig.osc.port = v; rigDirty(); }, { min: 1, max: 65535 }))));
  rigDirty();
}

function rigDirty() {
  const d = rig && JSON.stringify(rig) !== rigSaved;
  $("#fx-rig-state").textContent = d ? t("shows.unsaved") : "";
}

function clean(obj) {
  for (const k of ["haze", "tempo", "osc", "sub_masters", "head_limits"]) if (obj[k] && !Object.keys(obj[k]).length) delete obj[k];
  return obj;
}

async function saveRig() {
  const r = await attempt(() => api("PUT", `/api/store/rig/${encodeURIComponent(rigName)}`, { data: clean(structuredClone(rig)) }),
    (x) => [t("fixtures.rig_saved", { name: rigName }), ...(x.notes || [])].join(" · "));
  if (r) { await refreshCatalogue(); await loadRig(rigName); }
}

// ---------------------------------------------------------------- page

async function load() {
  doc = await get("/api/store/fixtures");
  doc.types ||= {};
  doc.fixtures ||= [];
  saved = JSON.stringify(doc);
  $("#fx-add-type").replaceChildren(...Object.entries(doc.types).map(([k, ty]) => el("option", { value: k }, ty.name || k)));
  renderPatch();
  renderTypes();
  await loadRig(rigName);
  document.body.dataset.fixturesReady = "1";
}

function showTab(name) {
  tab = name;
  $$("#fx-tabs [data-tab]").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  for (const p of ["patch", "types", "rig"]) $(`#fx-tab-${p}`).classList.toggle("hidden", p !== name);
}

export function init() {
  $$("#fx-tabs [data-tab]").forEach((b) => (b.onclick = () => showTab(b.dataset.tab)));
  $("#fx-add").onclick = addFixtures;
  $("#fx-auto").onclick = () => { autoPatch(doc.fixtures, doc.types, true); renderPatch(); };
  $("#fx-patch-save").onclick = savePatch;
  $("#fx-type-pick").onchange = (e) => { typeKey = e.target.value; renderTypes(); };
  $("#fx-type-new").onclick = newType;
  $("#fx-type-save").onclick = saveType;
  $("#fx-type-del").onclick = deleteType;
  $("#fx-ofl").onchange = (e) => { importOfl(e.target.files[0]); e.target.value = ""; };
  $("#fx-ofl-export").onclick = () => typeKey && (location.href = `/api/ofl/export/${encodeURIComponent(typeKey)}`);
  $("#fx-rig-pick").onchange = (e) => loadRig(e.target.value);
  $("#fx-rig-save").onclick = saveRig;
  $("#fx-rig-use").onclick = async () => {
    const r = await attempt(() => api("POST", "/api/control", { cmd: "rig", name: rigName }), t("fixtures.rig_running", { name: rigName }));
    if (r) { await refreshCatalogue(); renderRig(); }
  };
  onCatalogue(() => { if (doc && tab === "rig") renderRig(); });
  onShow("fixtures", () => { document.body.dataset.fixturesReady = ""; load(); showTab(tab); });
}
