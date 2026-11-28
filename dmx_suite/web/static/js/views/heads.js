// Heads page: aim moving heads with a drag pad (fine mode for small moves) and store where they
// point as named head points for this rig (v3.1), with a description, tags and a rough stage place.
// Focus mode steps through the heads one at a time for a point; the re-focus walk goes through
// every point, head by head, at load-in.
import { api, attempt, cmd, get, toast } from "../api.js";
import { $, el, svg } from "../dom.js";
import { t } from "../i18n.js";
import { onShow } from "../nav.js";
import { live, onCatalogue, onState, refreshCatalogue } from "../state.js";

let points = [];
// v7 exclusion zones: per head, in % of pan / tilt (pan left to right, tilt bottom to top as on the pad)
let zones = {}; // head id -> [zone]
let zoning = false; // Zones mode: drags draw, move and resize zones instead of aiming
let edit = null; // {head, zone (draft, %), old: name or null}
let focus = null; // {point, heads: [...], i, walk: [points...]}
let fine = false;
const NAME = /^[a-z0-9][a-z0-9_-]{0,39}$/;

function degrees(fx, axis, v) {
  const range = fx[axis + "_range"];
  return range ? ` ${Math.round(v * range)}°` : "";
}

function buildCatalogue(cat) {
  const heads = $("#heads");
  heads.replaceChildren();
  for (const fx of cat.fixtures.filter((x) => x.moves)) {
    const pt = el("div", { class: "pt" });
    const area = el("div", { class: "area", role: "slider", "aria-label": t("heads.pad_label", { id: fx.id }) }, pt);
    const status = el("span", { class: "muted" });
    const zsvg = svg("svg", { class: "zones", viewBox: "0 0 100 100", preserveAspectRatio: "none", "aria-hidden": "true" });
    area.append(zsvg);
    heads.append(el("div", { class: "pad", "data-pad": fx.id },
      el("div", { class: "head-row" }, el("b", { text: fx.id }), status,
        el("button", { onclick: () => cmd("position", { fixture: fx.id, release: true }) }, t("heads.release"))),
      area));
    zoneEvents(fx, area);
    let dragging = false, last = 0, start = null;
    const send = (ev, force = false) => {
      const now = performance.now();
      if (!force && now - last < 40) return; // at most 25 a second
      last = now;
      const r = area.getBoundingClientRect();
      let pan = (ev.clientX - r.left) / r.width, tilt = 1 - (ev.clientY - r.top) / r.height;
      if (fine && start) { // fine: a tenth of the movement from where the drag began
        pan = start.pan + (pan - start.x) / 10;
        tilt = start.tilt + (tilt - start.y) / 10;
      }
      cmd("position", { fixture: fx.id, pan: Math.min(1, Math.max(0, pan)), tilt: Math.min(1, Math.max(0, tilt)) });
    };
    area.addEventListener("pointerdown", (ev) => {
      if (zoning) return; // Zones mode: drawing, not aiming
      dragging = true;
      area.setPointerCapture(ev.pointerId);
      const r = area.getBoundingClientRect();
      const f = live.state.fixtures.find((x) => x.id === fx.id) || { pan: 0.5, tilt: 0.5 };
      start = { x: (ev.clientX - r.left) / r.width, y: 1 - (ev.clientY - r.top) / r.height, pan: f.pan, tilt: f.tilt };
      if (!fine) send(ev, true);
    });
    area.addEventListener("pointermove", (ev) => dragging && send(ev));
    area.addEventListener("pointerup", (ev) => { if (dragging) send(ev, true); dragging = false; });
  }
}

// ---------------------------------------------------------------- v7 exclusion zones

const pct = (v) => Math.round(Math.min(100, Math.max(0, v)) * 10) / 10;

function padPos(area, ev) { // pan / tilt in % under the pointer
  const r = area.getBoundingClientRect();
  return { pan: pct(((ev.clientX - r.left) / r.width) * 100), tilt: pct(100 - ((ev.clientY - r.top) / r.height) * 100) };
}

function box(z) { // {x0, x1, t0, t1} in %, for either shape
  if (z.shape === "rect") return { x0: z.pan[0], x1: z.pan[1], t0: z.tilt[0], t1: z.tilt[1] };
  return { x0: z.centre[0] - z.radius[0], x1: z.centre[0] + z.radius[0], t0: z.centre[1] - z.radius[1], t1: z.centre[1] + z.radius[1] };
}

function fromBox(shape, b, base = {}) {
  const x0 = pct(Math.min(b.x0, b.x1)), x1 = pct(Math.max(b.x0, b.x1)), t0 = pct(Math.min(b.t0, b.t1)), t1 = pct(Math.max(b.t0, b.t1));
  const out = { name: base.name, shape, ...(base.black ? { black: true } : {}) };
  if (shape === "rect") return { ...out, pan: [x0, Math.max(x1, x0 + 0.5)], tilt: [t0, Math.max(t1, t0 + 0.5)] };
  return { ...out, centre: [pct((x0 + x1) / 2), pct((t0 + t1) / 2)], radius: [Math.max(0.5, pct((x1 - x0) / 2)), Math.max(0.5, pct((t1 - t0) / 2))] };
}

function inside(z, p) {
  if (z.shape === "rect") return p.pan > z.pan[0] && p.pan < z.pan[1] && p.tilt > z.tilt[0] && p.tilt < z.tilt[1];
  return ((p.pan - z.centre[0]) / z.radius[0]) ** 2 + ((p.tilt - z.centre[1]) / z.radius[1]) ** 2 < 1;
}

function shapeEl(z, cls) {
  const b = box(z);
  const attrs = { class: cls, "data-zone": z.name || "" };
  const e = z.shape === "rect"
    ? svg("rect", { ...attrs, x: b.x0, y: 100 - b.t1, width: b.x1 - b.x0, height: b.t1 - b.t0 })
    : svg("ellipse", { ...attrs, cx: z.centre[0], cy: 100 - z.centre[1], rx: z.radius[0], ry: z.radius[1] });
  e.append(Object.assign(svg("title"), { textContent: z.name + (z.black ? ` · ${t("zones.black")}` : "") }));
  return e;
}

function drawZones() {
  for (const pad of document.querySelectorAll("#heads [data-pad]")) {
    const fid = pad.dataset.pad, g = pad.querySelector("svg.zones");
    const list = (zones[fid] || []).filter((z) => !(edit && edit.head === fid && z.name === edit.old));
    const kids = [
      svg("defs", {}, svg("pattern", { id: `hatch-${fid}`, width: 4, height: 4, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" },
        svg("line", { x1: 0, y1: 0, x2: 0, y2: 4, class: "hatch" }))),
      ...list.map((z) => shapeEl(z, "zone" + (z.black ? " black" : ""))),
    ];
    if (edit && edit.head === fid) {
      kids.push(shapeEl(edit.zone, "zone draft"));
      const b = box(edit.zone);
      kids.push(svg("rect", { class: "zone-handle", x: b.x1 - 3, y: 100 - b.t0 - 3, width: 6, height: 6 }));
    }
    g.replaceChildren(...kids);
    g.querySelectorAll(".zone:not(.draft)").forEach((e) => e.setAttribute("fill", `url(#hatch-${fid})`));
  }
}

function zoneEvents(fx, area) {
  let drag = null; // {mode: draw | move | size, from, start}
  area.addEventListener("pointerdown", (ev) => {
    if (!zoning) return;
    area.setPointerCapture(ev.pointerId);
    const p = padPos(area, ev);
    if (edit && edit.head === fx.id) {
      const b = box(edit.zone);
      if (Math.abs(p.pan - b.x1) < 4 && Math.abs(p.tilt - b.t0) < 8) { drag = { mode: "size", from: p, start: b }; return; }
      if (inside(edit.zone, p)) { drag = { mode: "move", from: p, start: b }; return; }
    }
    const hit = (zones[fx.id] || []).find((z) => inside(z, p));
    if (hit) { openEditor(fx.id, hit); drag = { mode: "move", from: p, start: box(hit) }; return; }
    openEditor(fx.id, null, fromBox($("#zone-shape").value, { x0: p.pan, x1: p.pan, t0: p.tilt, t1: p.tilt }));
    drag = { mode: "draw", from: p, start: null };
  });
  area.addEventListener("pointermove", (ev) => {
    if (!zoning || !drag || !edit) return;
    const p = padPos(area, ev), z = edit.zone, s = drag.start;
    let b;
    if (drag.mode === "draw") b = { x0: drag.from.pan, x1: p.pan, t0: drag.from.tilt, t1: p.tilt };
    else if (drag.mode === "move") {
      const dx = p.pan - drag.from.pan, dt = p.tilt - drag.from.tilt;
      b = { x0: s.x0 + dx, x1: s.x1 + dx, t0: s.t0 + dt, t1: s.t1 + dt };
    } else b = { x0: s.x0, x1: Math.max(s.x0 + 1, p.pan), t0: Math.min(s.t1 - 1, p.tilt), t1: s.t1 };
    edit.zone = fromBox(z.shape, b, z);
    showSize();
    drawZones();
  });
  area.addEventListener("pointerup", () => { drag = null; });
}

function openEditor(head, zone, draft = null) {
  const z = zone ? JSON.parse(JSON.stringify(zone)) : { ...draft, name: nextName(head) };
  edit = { head, zone: z, old: zone ? zone.name : null };
  $("#zone-editor").classList.remove("hidden");
  $("#zone-head").textContent = head;
  $("#zone-name").value = z.name;
  $("#zone-black").checked = !!z.black;
  $("#zone-delete").disabled = !zone;
  showSize();
  drawZones();
}

function nextName(head) {
  const names = new Set((zones[head] || []).map((z) => z.name));
  for (let n = 1; ; n++) if (!names.has(t("zones.default_name", { n }))) return t("zones.default_name", { n });
}

function showSize() {
  const b = box(edit.zone);
  $("#zone-size").textContent = t("zones.size", { pan: `${b.x0}-${b.x1}`, tilt: `${b.t0}-${b.t1}` });
}

function closeEditor() {
  edit = null;
  $("#zone-editor").classList.add("hidden");
  drawZones();
}

async function saveZone() {
  const name = $("#zone-name").value.trim();
  if (!name) return toast(t("zones.need_name"), true);
  const zone = { ...edit.zone, name };
  if ($("#zone-black").checked) zone.black = true; else delete zone.black;
  const r = await attempt(() => api("POST", "/api/store/zone", { action: "put", head: edit.head, zone, scope: $("#zone-scope").value,
    old_name: edit.old }), t("zones.saved", { name }));
  if (r) { closeEditor(); await loadZones(); }
}

async function deleteZone() {
  if (!edit?.old || !confirm(t("zones.confirm_delete", { name: edit.old }))) return;
  const r = await attempt(() => api("POST", "/api/store/zone", { action: "delete", head: edit.head, name: edit.old, scope: $("#zone-scope").value }),
    t("zones.deleted", { name: edit.old }));
  if (r) { closeEditor(); await loadZones(); }
}

async function loadZones() {
  zones = (await get("/api/zones")).zones || {};
  drawZones();
}

function setZoning(on) {
  zoning = on;
  $("#zones-mode").classList.toggle("on", on);
  $("#heads").classList.toggle("zoning", on);
  if (!on) closeEditor();
  else toast(t("zones.help"));
}

async function loadPoints() {
  const r = await get("/api/points");
  points = r.points;
  $("#point-problems").replaceChildren(...r.problems.map((p) => el("div", { class: "chip warn", text: p })));
  $("#point-list").replaceChildren(...points.map((p) => el("li", { "data-point": p.name },
    el("div", { class: "row wrap grow" },
      el("b", { text: p.name }), el("span", { class: "muted", text: p.description }),
      ...p.tags.map((tg) => el("span", { class: "chip", text: tg })),
      ...(p.stage && Object.keys(p.stage).length ? [el("span", { class: "chip", text: Object.values(p.stage).join(" · ") })] : []),
      ...(p.missing.length ? [el("span", { class: "chip warn", text: t("heads.missing", { heads: p.missing.join(", ") }) })] : [])),
    el("div", { class: "row wrap point-tools" },
      el("button", { onclick: () => aim(p) }, t("heads.go")),
      el("button", { onclick: () => editPoint(p) }, t("heads.edit_point")),
      el("button", { onclick: () => startFocus([p]) }, t("heads.focus")),
      el("button", { onclick: async () => {
        const to = prompt(t("heads.rename_to"), p.name);
        if (to && to !== p.name && NAME.test(to)) await attempt(() => api("POST", "/api/store/point", { action: "rename", name: p.name, new_name: to }), t("heads.saved", { name: to })).then(done);
      } }, t("heads.rename")),
      el("button", { class: "danger-text", onclick: async () => {
        if (confirm(t("heads.confirm_delete", { name: p.name }))) await attempt(() => api("POST", "/api/store/point", { action: "delete", name: p.name }), t("heads.deleted")).then(done);
      } }, "✕")))));
}

async function done(r) {
  if (r) {
    await refreshCatalogue();
    await loadPoints();
  }
  return r;
}

function aim(p) {
  for (const [fid, v] of Object.entries(p.heads)) cmd("position", { fixture: fid, pan: v.pan, tilt: v.tilt });
}

function editPoint(p) {
  $("#point-name").value = p.name;
  $("#point-desc").value = p.description;
  $("#point-tags").value = p.tags.join(", ");
  for (const k of ["x", "y", "z"]) $(`#point-${k}`).value = p.stage?.[k] || "";
  aim(p);
}

function form() {
  const stage = {};
  for (const k of ["x", "y", "z"]) if ($(`#point-${k}`).value) stage[k] = $(`#point-${k}`).value;
  return { description: $("#point-desc").value.trim(), tags: $("#point-tags").value.split(",").map((x) => x.trim()).filter(Boolean), stage };
}

async function store(heads) {
  const name = $("#point-name").value.trim();
  if (!NAME.test(name)) return toast(t("heads.need_name"), true);
  const held = live.state.fixtures.filter((f) => f.override && (!heads || heads.includes(f.id)));
  if (!held.length) return toast(t("heads.save_need"), true);
  const value = { ...form(), heads: Object.fromEntries(held.map((f) => [f.id, { pan: +f.pan.toFixed(5), tilt: +f.tilt.toFixed(5) }])) };
  return attempt(() => api("POST", "/api/store/point", { action: "store", name, value }), t("heads.saved", { name })).then(done);
}

// ---------------------------------------------------------------- focus mode and the re-focus walk

function startFocus(list) {
  const heads = (live.cat?.fixtures || []).filter((f) => f.moves).map((f) => f.id);
  if (!heads.length || !list.length) return;
  focus = { list, p: 0, heads, i: 0 };
  showFocus();
}

function showFocus() {
  const box = $("#focus");
  if (!focus) return box.classList.add("hidden");
  const p = focus.list[focus.p], fid = focus.heads[focus.i];
  box.classList.remove("hidden");
  editPoint(p);
  $("#point-name").value = p.name;
  for (const h of focus.heads) document.querySelector(`[data-pad="${CSS.escape(h)}"]`)?.classList.toggle("focus", h === fid);
  const v = p.heads[fid];
  if (v) cmd("position", { fixture: fid, pan: v.pan, tilt: v.tilt });
  box.replaceChildren(
    el("b", { text: t("heads.focus_on", { point: p.name, head: fid, n: focus.i + 1, of: focus.heads.length }) }),
    el("span", { class: "muted", text: p.description }),
    el("button", { class: "sel", onclick: async () => { if (await store([fid])) next(); } }, t("heads.focus_store")),
    el("button", { onclick: next }, t("heads.focus_skip")),
    el("button", { onclick: () => { focus = null; showFocus(); clearFocus(); } }, t("heads.focus_end")));
}

function clearFocus() {
  document.querySelectorAll(".pad.focus").forEach((x) => x.classList.remove("focus"));
}

function next() {
  if (!focus) return;
  focus.i += 1;
  if (focus.i >= focus.heads.length) {
    focus.i = 0;
    focus.p += 1;
    if (focus.p >= focus.list.length) {
      focus = null;
      clearFocus();
      toast(t("heads.focus_done"));
      return showFocus();
    }
    focus.list[focus.p] = points.find((x) => x.name === focus.list[focus.p].name) || focus.list[focus.p];
  }
  showFocus();
}

function render(s) {
  const cat = live.cat;
  const held = s.zones_held || {};
  for (const f of s.fixtures) {
    const pad = document.querySelector(`[data-pad="${CSS.escape(f.id)}"]`);
    if (pad && f.pan !== undefined) {
      const pt = $(".pt", pad);
      pt.style.left = f.pan * 100 + "%";
      pt.style.top = (1 - f.tilt) * 100 + "%";
      pt.style.background = f.colour;
      const fx = cat?.fixtures.find((x) => x.id === f.id) || {};
      $(".muted", pad).textContent = t(f.override ? "heads.held" : "heads.show") + degrees(fx, "pan", f.pan) + degrees(fx, "tilt", f.tilt)
        + (held[f.id] ? ` · ${t("zones.at_edge", { name: held[f.id] })}` : "");
      pad.classList.toggle("zone-held", !!held[f.id]);
    }
  }
}

export function init() {
  $("#point-store").onclick = () => store();
  $("#point-walk").onclick = () => startFocus([...points]);
  $("#fine").onclick = () => { fine = !fine; $("#fine").classList.toggle("sel", fine); };
  for (const [k, opts] of [["x", ["left", "centre", "right"]], ["y", ["front", "middle", "back"]], ["z", ["floor", "low", "mid", "high", "ceiling"]]]) {
    $(`#point-${k}`).replaceChildren(el("option", { value: "" }, t("heads.stage_" + k)), ...opts.map((o) => el("option", { value: o }, t("heads.place_" + o))));
  }
  onCatalogue((cat) => { buildCatalogue(cat); loadZones(); });
  onState(render);
  onShow("heads", () => { loadPoints(); loadZones(); });
  $("#zones-mode").onclick = () => setZoning(!zoning);
  $("#zone-save").onclick = saveZone;
  $("#zone-delete").onclick = deleteZone;
  $("#zone-cancel").onclick = closeEditor;
  $("#zone-shape").onchange = (e) => { if (edit && !edit.old) { edit.zone = fromBox(e.target.value, box(edit.zone), edit.zone); drawZones(); } };
}
