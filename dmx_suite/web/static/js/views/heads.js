// Heads page: aim moving heads with a drag pad (fine mode for small moves) and store where they
// point as named head points for this rig (v3.1), with a description, tags and a rough stage place.
// Focus mode steps through the heads one at a time for a point; the re-focus walk goes through
// every point, head by head, at load-in.
import { api, attempt, cmd, get, toast } from "../api.js";
import { $, el } from "../dom.js";
import { t } from "../i18n.js";
import { onShow } from "../nav.js";
import { live, onCatalogue, onState, refreshCatalogue } from "../state.js";

let points = [];
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
    heads.append(el("div", { class: "pad", "data-pad": fx.id },
      el("div", { class: "head-row" }, el("b", { text: fx.id }), status,
        el("button", { onclick: () => cmd("position", { fixture: fx.id, release: true }) }, t("heads.release"))),
      area));
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

async function loadPoints() {
  const r = await get("/api/points");
  points = r.points;
  $("#point-problems").replaceChildren(...r.problems.map((p) => el("div", { class: "chip warn", text: p })));
  $("#point-list").replaceChildren(...points.map((p) => el("li", { "data-point": p.name },
    el("div", { class: "row wrap" },
      el("b", { text: p.name }), el("span", { class: "muted", text: p.description }),
      ...p.tags.map((tg) => el("span", { class: "chip", text: tg })),
      ...(p.stage && Object.keys(p.stage).length ? [el("span", { class: "chip", text: Object.values(p.stage).join(" · ") })] : []),
      ...(p.missing.length ? [el("span", { class: "chip warn", text: t("heads.missing", { heads: p.missing.join(", ") }) })] : [])),
    el("div", { class: "row wrap" },
      el("button", { onclick: () => aim(p) }, t("heads.go")),
      el("button", { onclick: () => edit(p) }, t("heads.edit_point")),
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

function edit(p) {
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
  edit(p);
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
  for (const f of s.fixtures) {
    const pad = document.querySelector(`[data-pad="${CSS.escape(f.id)}"]`);
    if (pad && f.pan !== undefined) {
      const pt = $(".pt", pad);
      pt.style.left = f.pan * 100 + "%";
      pt.style.top = (1 - f.tilt) * 100 + "%";
      pt.style.background = f.colour;
      const fx = cat?.fixtures.find((x) => x.id === f.id) || {};
      $(".muted", pad).textContent = t(f.override ? "heads.held" : "heads.show") + degrees(fx, "pan", f.pan) + degrees(fx, "tilt", f.tilt);
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
  onCatalogue(buildCatalogue);
  onState(render);
  onShow("heads", loadPoints);
}
