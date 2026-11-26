// Scene builder: pick lights on the layout, add layers (a colour, position or gobo, and/or an
// effect from the registry), see it live, save it as a scene file.
//
// The scene is kept as the same data the file holds ({name, layers: [{fixtures, effect, ...}]}),
// so what's saved is exactly what was previewed. Settings at their default aren't written.
import { openWheel } from "../colourwheel.js";
import { isSteps, renderSteps, toggleSteps } from "../stepedit.js";
import { api, attempt, get, toast } from "../api.js";
import { $, el } from "../dom.js";
import { LightGrid } from "../grid.js";
import { t } from "../i18n.js";
import { onShow } from "../nav.js";
import { copyLook, layerFor, pasteLayers } from "../paste.js";
import { live, onCatalogue, onState, refreshCatalogue } from "../state.js";

const SPREAD_KEYS = ["mapping", "direction", "angle", "groups_of"];
const LAYER_KEYS = ["level", "blend"];

let grid;
let fx = null; // /api/effects: effect schemas, palette, blends
let key = null; // file name of the scene being edited (null = not saved yet)
let doc = { name: "", layers: [] };
let saved = "";
let current = -1; // layer being edited
let group = "all";
let previewTimer = null;
let namedInputs = [];

const dirty = () => JSON.stringify(doc) !== saved;
const effect = (name) => fx?.effects.find((e) => e.name === name);
const slug = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40) || "scene";

// ---------------------------------------------------------------- loading and saving

async function loadEffects() {
  fx = await get("/api/effects");
}

function setDoc(data, k) {
  doc = data;
  key = k;
  saved = JSON.stringify(doc);
  current = doc.layers.length ? 0 : -1;
  $("#scene-name").value = doc.name || "";
  doc.layers ||= [];
  $("#scene-steps").checked = isSteps(doc);
  $("#scene-length").value = doc.length_s ?? "";
  $("#scene-show-colour").replaceChildren(swatch(doc.show_colour, (c) => { toggleKey(doc, "show_colour", c); changed(); }));
  renderAll();
}

async function open(k) {
  if (dirty() && !confirm(t("scenes.discard"))) {
    $("#scene-pick").value = key || "";
    return;
  }
  if (!k) return setDoc({ name: t("scenes.untitled"), layers: [] }, null);
  const data = await get(`/api/store/scene/${encodeURIComponent(k)}`);
  if (data.error) return toast(data.error, true);
  setDoc(data, k);
}

async function save() {
  doc.name = $("#scene-name").value.trim() || t("scenes.untitled");
  let k = key;
  if (!k) {
    k = slug(doc.name);
    if (live.cat.scenes[k] && !confirm(t("scenes.overwrite", { key: k }))) return;
  }
  const r = await attempt(() => api("PUT", `/api/store/scene/${encodeURIComponent(k)}`, { data: doc }), t("scenes.saved", { name: doc.name }));
  if (!r) return;
  key = k;
  saved = JSON.stringify(doc);
  await refreshCatalogue();
  renderBar();
}

// ---------------------------------------------------------------- the bar along the top

function renderBar() {
  const pick = $("#scene-pick");
  const names = Object.entries(live.cat.scenes).sort((a, b) => a[1].localeCompare(b[1]));
  pick.replaceChildren(el("option", { value: "" }, t("scenes.new_scene")),
    ...names.map(([k, n]) => el("option", { value: k, selected: k === key }, `${n} (${k})`)));
  pick.value = key || "";
  $("#scene-dup").disabled = !key;
  $("#scene-del").disabled = !key;
  $("#scene-save").classList.toggle("sel", dirty());
  $("#scene-state").textContent = dirty() ? t("scenes.unsaved") : key ? t("scenes.saved_as", { key }) : "";
}

// ---------------------------------------------------------------- layers list

function describe(ly) {
  const what = ly.effect ? effect(ly.effect)?.label || ly.effect : [ly.colour && t("scenes.static_colour", { c: ly.colour }),
    ly.position && t("scenes.static_position", { p: ly.position }), ly.gobo && t("scenes.static_gobo", { g: ly.gobo })].filter(Boolean).join(", ");
  return `${(ly.fixtures || []).join(", ")}: ${what || t("scenes.nothing_set")}`;
}

function renderLayers(errLayer = null) {
  $("#layers").replaceChildren(...doc.layers.map((ly, i) => el("li", {
    class: [i === current ? "on" : "", ly.mute ? "muted-layer" : "", errLayer === i + 1 ? "error" : ""].join(" "),
  },
  el("button", { class: "link name", onclick: () => pick(i) }, describe(ly)),
  el("span", { class: "tools" },
    el("button", { title: t("scenes.up"), disabled: i === 0, onclick: () => move(i, -1) }, "↑"),
    el("button", { title: t("scenes.down"), disabled: i === doc.layers.length - 1, onclick: () => move(i, 1) }, "↓"),
    el("button", { title: t("scenes.mute"), class: ly.mute ? "sel" : "", onclick: () => { toggleKey(ly, "mute", !ly.mute); changed(); } }, "M"),
    el("button", { title: t("scenes.remove"), class: "danger-text", onclick: () => remove(i) }, "✕")))));
  $("#layer-title").classList.toggle("hidden", current < 0);
}

function pick(i) {
  current = i;
  const ly = doc.layers[i];
  grid.select(expand(ly.fixtures || []));
  const f = ly.fixtures || [];
  group = f.length === 1 && (f[0] === "all" || live.cat.groups[f[0]]) ? f[0] : null; // its group's tab, if it is one
  buildTabs(live.cat);
  renderAll();
}

function move(i, d) {
  const [ly] = doc.layers.splice(i, 1);
  doc.layers.splice(i + d, 0, ly);
  current = i + d;
  changed();
}

function remove(i) {
  doc.layers.splice(i, 1);
  current = Math.min(current, doc.layers.length - 1);
  changed();
}

// fixture ids and group names -> fixture ids
function expand(names) {
  const out = new Set();
  for (const n of names) {
    if (n === "all") live.cat.fixtures.forEach((f) => out.add(f.id));
    else if (live.cat.groups[n]) live.cat.groups[n].forEach((f) => out.add(f));
    else out.add(n);
  }
  return [...out];
}

// the selection, as a group name when it's exactly a group
function selectionNames() {
  const sel = [...grid.selected];
  const set = JSON.stringify([...sel].sort());
  for (const [g, ids] of Object.entries(live.cat.groups)) if (JSON.stringify([...ids].sort()) === set) return [g];
  const order = live.cat.fixtures.map((f) => f.id);
  return sel.sort((a, b) => order.indexOf(a) - order.indexOf(b));
}

// ---------------------------------------------------------------- the layer form

function toggleKey(obj, k, v, dflt) {
  if (v === undefined || v === null || v === "" || (dflt !== undefined && JSON.stringify(v) === JSON.stringify(dflt))) delete obj[k];
  else obj[k] = v;
}

const dark = (hex) => /^#[0-9a-f]{6}$/i.test(hex) && parseInt(hex.slice(1, 3), 16) + parseInt(hex.slice(3, 5), 16) + parseInt(hex.slice(5, 7), 16) < 60;

function swatch(value, onPick, allowNone = true, fixtures = []) {
  const box = el("div", { class: "swatches" });
  const draw = () => {
    box.replaceChildren(
      ...(allowNone ? [el("button", { class: "sw none" + (!value ? " sel" : ""), title: t("scenes.none"), onclick: () => { value = undefined; onPick(value); draw(); } }, "∅")] : []),
      el("button", { class: "sw dark" + (value === "off" ? " sel" : ""), title: t("scenes.off"), style: "background:#000", onclick: () => { value = "off"; onPick(value); draw(); } }, ""),
      ...Object.entries(fx.colours).filter(([n]) => n !== "off").map(([n, hex]) => el("button", {
        class: "sw" + (value === n ? " sel" : "") + (dark(hex) ? " dark" : ""), title: n, style: `background:${hex}`, onclick: () => { value = n; onPick(value); draw(); },
      })),
      el("button", { class: "sw wheel-btn" + (value && !fx.colours[value] && value !== "off" ? " sel" : ""), title: t("scenes.custom_colour"),
                     style: typeof value === "string" && value.startsWith("#") ? `background:${value}` : "",
                     onclick: () => openWheel({ value, fixtures, names: fx.colours, onPick: (c) => { value = c; onPick(value); draw(); } }) }, "◐"));
  };
  draw();
  return box;
}

function field(label, control, help) {
  return el("label", { class: "field", title: help || "" }, el("span", { text: label }), control);
}

function paramControl(prm, ly) {
  const v = ly[prm.key];
  const set = (val) => { toggleKey(ly, prm.key, val, prm.default); changed(); };
  switch (prm.kind) {
    case "number": case "angle": {
      const lo = prm.lo ?? 0, hi = prm.hi ?? (prm.kind === "angle" ? 359 : prm.key.endsWith("_s") ? 30 : 10);
      const step = hi - lo <= 2 ? 0.01 : hi - lo <= 40 ? 0.1 : 1;
      const out = el("input", { type: "number", class: "narrow", min: lo, max: prm.hi ?? undefined, step, value: v ?? prm.default ?? "" });
      const range = el("input", { type: "range", min: lo, max: hi, step, value: v ?? prm.default ?? lo });
      range.oninput = () => { out.value = range.value; set(+range.value); };
      out.onchange = () => { range.value = out.value; set(out.value === "" ? undefined : +out.value); };
      return el("span", { class: "slider" }, range, out);
    }
    case "int":
      return el("input", { type: "number", class: "narrow", min: prm.lo ?? 0, max: prm.hi ?? undefined, step: 1, value: v ?? prm.default ?? "",
                           onchange: (e) => set(e.target.value === "" ? undefined : Math.round(+e.target.value)) });
    case "bool":
      return el("input", { type: "checkbox", checked: v ?? prm.default ?? false, onchange: (e) => set(e.target.checked) });
    case "colour":
      return swatch(v ?? prm.default, (c) => set(c), false, ly.fixtures);
    case "colours": {
      const list = [...(v || ["white", "off"].slice(0, Math.max(prm.min_items || 1, 1)))];
      if (!v) set(list);
      const box = el("div", { class: "colour-list" });
      const draw = () => box.replaceChildren(...list.map((c, i) => el("div", { class: "row" },
        swatch(c, (nc) => { list[i] = nc; set([...list]); }, false, ly.fixtures),
        el("button", { class: "danger-text", disabled: list.length <= (prm.min_items || 1), onclick: () => { list.splice(i, 1); set([...list]); draw(); } }, "✕"))),
        el("button", { onclick: () => { list.push("white"); set([...list]); draw(); } }, t("scenes.add_colour")));
      draw();
      return box;
    }
    case "position":
      return el("select", { onchange: (e) => set(e.target.value || undefined) },
        el("option", { value: "" }, t("scenes.choose")), ...fx.positions.map((p) => el("option", { value: p, selected: v === p }, p)));
    case "range": {
      const [a, b] = v || prm.default || [0, 1];
      const lo = el("input", { type: "number", class: "narrow", min: 0, max: 1, step: 0.05, value: a });
      const hi = el("input", { type: "number", class: "narrow", min: 0, max: 1, step: 0.05, value: b });
      const send = () => set([+lo.value, +hi.value]);
      lo.onchange = send;
      hi.onchange = send;
      return el("span", { class: "slider" }, lo, el("span", { class: "muted", text: "–" }), hi);
    }
    case "choice":
      return el("select", { onchange: (e) => set(e.target.value) },
        ...prm.choices.map((c) => el("option", { value: c, selected: (v ?? prm.default) === c }, c.replaceAll("_", " "))));
    default:
      return el("input", { value: v ?? "", onchange: (e) => set(e.target.value || undefined) });
  }
}

function renderForm() {
  const form = $("#layer-form");
  if (current < 0) {
    form.replaceChildren(el("p", { class: "muted", text: t("scenes.no_layer") }));
    grid.setArrow(null);
    return;
  }
  const ly = doc.layers[current];
  const e = effect(ly.effect);
  const parts = [];
  parts.push(field(t("scenes.lights"), el("span", { class: "chips" },
    ...(ly.fixtures || []).map((n) => el("span", { class: "chip", text: n })),
    el("button", { onclick: () => {
      const names = selectionNames();
      if (!names.length) return toast(t("scenes.select_first"), true);
      ly.fixtures = names;
      changed();
    } }, t("scenes.use_selection")))));
  parts.push(field(t("scenes.effect"), el("select", { onchange: (ev) => {
    const old = effect(ly.effect);
    for (const prm of old?.params || []) if (prm.key !== "colour") delete ly[prm.key]; // the colour carries over
    toggleKey(ly, "effect", ev.target.value || undefined);
    changed();
  } }, el("option", { value: "" }, t("scenes.no_effect")),
  ...fx.effects.map((x) => el("option", { value: x.name, selected: ly.effect === x.name }, x.label)))));
  if (e) parts.push(el("p", { class: "muted", text: e.help }));

  // static settings (the effect's own colour wins when it has one)
  const own = new Set((e?.params || []).map((p) => p.key));
  if (!own.has("colour")) parts.push(field(t("scenes.colour"), swatch(ly.colour, (c) => { toggleKey(ly, "colour", c); changed(); }, true, ly.fixtures)));
  if (!e?.movement) {
    parts.push(field(t("scenes.position"), el("select", { onchange: (ev) => { toggleKey(ly, "position", ev.target.value || undefined); changed(); } },
      el("option", { value: "" }, t("scenes.none")), ...fx.positions.map((p) => el("option", { value: p, selected: ly.position === p }, p)))));
  }
  parts.push(field(t("scenes.gobo"), el("select", { onchange: (ev) => { toggleKey(ly, "gobo", ev.target.value || undefined); changed(); } },
    el("option", { value: "" }, t("scenes.none")), ...fx.gobos.map((g) => el("option", { value: g, selected: ly.gobo === g }, g)))));
  if (fx.intensity) {
    parts.push(field(t("scenes.intensity"), paramControl({ key: "intensity", kind: "number", lo: 0, hi: 1 }, ly)));
  }

  // the effect's settings, then how it runs across the lights
  if (e) {
    const main = e.params.filter((p) => !SPREAD_KEYS.includes(p.key));
    const spread = e.params.filter((p) => SPREAD_KEYS.includes(p.key));
    parts.push(el("h3", { text: t("scenes.effect_settings") }), ...main.map((p) => field(p.label, paramControl(p, ly), p.help)));
    if (spread.length) parts.push(el("h3", { text: t("scenes.across") }), ...spread.map((p) => field(p.label, paramControl(p, ly), p.help)));
  }
  parts.push(el("h3", { text: t("scenes.mixing") }),
    field(t("scenes.level"), paramControl({ key: "level", kind: "number", lo: 0, hi: 1, default: 1 }, ly), t("scenes.level_help")),
    field(t("scenes.blend"), el("select", { onchange: (ev) => { toggleKey(ly, "blend", ev.target.value, "replace"); changed(); } },
      ...fx.blends.map((b) => el("option", { value: b, selected: (ly.blend || "replace") === b }, t("scenes.blend_" + b)))), t("scenes.blend_help")));
  form.replaceChildren(...parts);

  // the arrow on the layout: which way it runs (spatial effects)
  const mapping = ly.mapping ?? e?.params.find((p) => p.key === "mapping")?.default;
  const dir = ly.direction ?? e?.params.find((p) => p.key === "direction")?.default;
  if (e?.name === "radial") grid.setArrow({ radial: ly.inward ? "in" : "out" });
  else if (mapping !== "spatial" || !dir) grid.setArrow(null);
  else if (dir === "centre_out" || dir === "out_centre") grid.setArrow({ radial: dir === "centre_out" ? "out" : "in" });
  else if (dir === "angle") grid.setArrow({ angle: ly.angle ?? 0 });
  else if (dir === "forward" || dir === "reverse") grid.setArrow({ angle: dir === "forward" ? 0 : 180 });
  else grid.setArrow(null);
}

function stepCtx() {
  const fixtures = (target) => expand([target]).map((id) => live.cat.fixtures.find((f) => f.id === id)).filter(Boolean);
  return {
    changed, swatch, fx, selectionNames, inputs: namedInputs, key: () => key,
    moves: (target) => fixtures(target).some((f) => f.moves),
    hasGobo: (target) => fixtures(target).some((f) => f.gobo),
    hasRole: (target, role) => fixtures(target).some((f) => (f.roles || []).includes(role)),
  };
}

function renderAll(errLayer = null) {
  if (!fx) return; // still loading the effects list (a tap this early does nothing)
  renderBar();
  renderLayers(errLayer);
  renderForm();
  renderSteps(doc, stepCtx());
  $("#layers-title").textContent = t(isSteps(doc) ? "steps.effects_on_top" : "scenes.layers");
}

// ---------------------------------------------------------------- checking and live preview

function changed() {
  renderAll();
  clearTimeout(previewTimer);
  previewTimer = setTimeout(check, 250);
}

async function check() {
  const data = { ...doc, name: $("#scene-name").value.trim() || doc.name };
  const errBox = $("#scene-error");
  if (!data.layers.length && !isSteps(data)) {
    errBox.classList.add("hidden");
    return;
  }
  const r = await api("POST", "/api/validate/scene", { data }).catch((e) => ({ ok: false, error: e.message }));
  if (!r.ok) {
    errBox.textContent = r.error;
    errBox.classList.remove("hidden");
    renderLayers(r.layer);
    return;
  }
  errBox.classList.add("hidden");
  $("#scene-preview-note").textContent = r.length_s ? t("scenes.length_is", { s: Math.round(r.length_s * 10) / 10 }) : "";
  if ($("#scene-preview").checked) {
    await attempt(() => api("POST", "/api/preview", { scene_data: data, seconds: 300 })); // the engine's longest preview
  }
}

function updateSelection() {
  const n = grid.selected.size;
  $("#scene-sel").textContent = n ? t("scenes.selected", { n, names: selectionNames().join(", ") }) : t("scenes.select_help");
}

function buildTabs(cat) {
  const names = ["all", ...Object.keys(cat.groups).sort()];
  if (group !== null && !names.includes(group)) group = "all";
  const ids = Object.keys(grid.layout);
  const count = (g) => (g === "all" ? ids.length : (cat.groups[g] || []).filter((id) => grid.layout[id]).length);
  const pick = (sel) => { group = null; buildTabs(live.cat); grid.select(sel); };
  $("#scene-group-tabs").replaceChildren(...names.map((g) => el("button", {
    role: "tab", class: g === group ? "on" : "", "aria-selected": g === group, "data-group": g,
    onclick: () => { group = g; buildTabs(live.cat); grid.select(g === "all" ? ids : cat.groups[g] || []); },
  }, g === "all" ? t("groups.all") : g, el("span", { class: "n", text: String(count(g)) }))),
  el("span", { class: "sep" }),
  el("button", { class: "quick", id: "pick-none", onclick: () => pick([]) }, t("scenes.pick_none")),
  el("button", { class: "quick", id: "pick-invert", onclick: () => pick(ids.filter((id) => !grid.selected.has(id))) }, t("scenes.pick_invert")));
}

// ---------------------------------------------------------------- copy / paste a look

const CLIP = "dmx-suite.look";
let clip = null;
try {
  clip = JSON.parse(localStorage.getItem(CLIP) || "null");
} catch {}

function copy() {
  // the layer being edited, else the one lighting the first selected light
  const src = current >= 0 ? doc.layers[current] : layerFor(doc.layers, [...grid.selected][0], expand);
  if (!src) return toast(t("scenes.nothing_to_copy"), true);
  clip = copyLook(src);
  try {
    localStorage.setItem(CLIP, JSON.stringify(clip));
  } catch {}
  toast(t("scenes.copied", { what: describe(src) }));
}

function paste() {
  if (!clip) return toast(t("scenes.nothing_copied"), true);
  const ids = [...grid.selected];
  if (!ids.length) return toast(t("scenes.select_first"), true);
  const layers = pasteLayers(clip, ids, selectionNames(), live.cat.fixtures, fx.effects);
  if (!layers.length) return toast(t("scenes.paste_none"), true);
  const at = current >= 0 ? current + 1 : doc.layers.length;
  doc.layers.splice(at, 0, ...layers);
  current = at + layers.length - 1;
  toast(t("scenes.pasted", { n: layers.length }));
  changed();
}

export function init() {
  grid = new LightGrid($("#scene-grid"), { select: true, onChange: updateSelection });
  $("#look-copy").onclick = copy;
  $("#look-paste").onclick = paste;
  document.addEventListener("keydown", (ev) => {
    if (!$("#page-scenes").classList.contains("on") || !(ev.ctrlKey || ev.metaKey) || ev.target.matches("input, select, textarea")) return;
    const k = ev.key.toLowerCase();
    if (k === "c") { ev.preventDefault(); copy(); }
    else if (k === "v") { ev.preventDefault(); paste(); }
  });
  $("#scene-pick").onchange = (e) => open(e.target.value);
  $("#scene-steps").onchange = (e) => { toggleSteps(doc, e.target.checked); changed(); };
  $("#scene-new").onclick = () => open("");
  $("#scene-save").onclick = save;
  $("#scene-dup").onclick = async () => {
    const to = slug(prompt(t("scenes.duplicate_prompt"), `${key}_copy`) || "");
    if (!to || to === "scene") return;
    if (await attempt(() => api("POST", `/api/store/scene/${key}/duplicate`, { to }), t("scenes.duplicated", { key: to }))) {
      await refreshCatalogue();
      key = null;
      saved = "";
      open(to);
    }
  };
  $("#scene-del").onclick = async () => {
    if (!confirm(t("scenes.confirm_delete", { name: doc.name }))) return;
    if (await attempt(() => api("DELETE", `/api/store/scene/${key}`), t("scenes.deleted", { name: doc.name }))) {
      saved = JSON.stringify(doc);
      await refreshCatalogue();
      open("");
    }
  };
  $("#scene-name").oninput = (e) => { doc.name = e.target.value; renderBar(); };
  $("#scene-length").onchange = (e) => { toggleKey(doc, "length_s", e.target.value === "" ? undefined : +e.target.value); changed(); };
  $("#layer-add").onclick = () => {
    const names = selectionNames();
    if (!names.length) return toast(t("scenes.select_first"), true);
    doc.layers.push({ fixtures: names, colour: "white" });
    current = doc.layers.length - 1;
    changed();
  };
  let keepAlive = null;
  $("#scene-preview").onchange = (e) => {
    clearInterval(keepAlive);
    if (e.target.checked) {
      check();
      keepAlive = setInterval(check, 240000); // a preview lasts 5 minutes: renew it while the box is ticked
    } else attempt(() => api("POST", "/api/control", { cmd: "preview_end" }));
  };
  onCatalogue((cat) => {
    grid.build(cat);
    buildTabs(cat);
    if (fx) renderBar();
  });
  onState((s) => grid.update(s.fixtures));
  onShow("scenes", async () => {
    get("/api/inputs").then((r) => { namedInputs = r.inputs; if (fx) renderAll(); }); // for step scenes; not needed to start
    if (!fx) {
      await loadEffects();
      setDoc({ name: t("scenes.untitled"), layers: [] }, null);
    } else {
      await loadEffects(); // the palette may have changed
      renderAll();
    }
    updateSelection();
  });
  window.addEventListener("beforeunload", (ev) => { if (fx && dirty()) ev.preventDefault(); });
}
