// Layout page: arrange the lights on the grid, and make groups from a selection.
import { api, attempt, get, toast } from "../api.js";
import { $, $$, el, remember } from "../dom.js";
import { watchFrames } from "../frames.js";
import { LightGrid } from "../grid.js";
import { t } from "../i18n.js";
import { fillIcons } from "../icons.js";
import { onLeave, onShow } from "../nav.js";
import { addressMap, clashes as clashPatch, footprintOf } from "../patch.js";
import { live, onCatalogue, onState, refreshCatalogue } from "../state.js";

let grid;
let group = "all"; // the group tab showing

// a button's tooltip: its name and its shortcut
const tip = (b) => [b.dataset.tip ? t(b.dataset.tip) : b.textContent.trim(), b.dataset.key ? `(${b.dataset.key})` : ""].filter(Boolean).join(" ");

function showProblems() {
  const ps = grid.problems();
  $("#layout-problems").replaceChildren(...ps.map((p) => el("li", { class: p.kind },
    el("button", { class: "link", onclick: () => grid.select([p.a, p.b]) },
      t(p.kind === "overlap" ? "layout.problem_overlap" : "layout.problem_close", { a: p.a, b: p.b })))));
  $("#layout-problems-head").classList.toggle("hidden", !ps.length);
}

function updateSelection() {
  showProblems();
  lpSelected = new Set();
  markListSelection();
  $("#layout-dirty").classList.toggle("hidden", !grid.dirty);
  const n = grid.selected.size;
  const ids = [...grid.selected];
  $("#layout-sel").textContent = n
    ? t("layout.selected", { n, names: ids.slice(0, 8).join(", ") + (n > 8 ? " …" : "") })
    : t("layout.select_help");
  $("#layout-save").classList.toggle("sel", grid.dirty);
  $("#layout-save").disabled = !grid.dirty;
  $("#layout-undo").disabled = !grid.history.length;
  $("#layout-redo").disabled = !grid.future.length;
  $("#layout-reset").disabled = !grid.dirty;
  // arrange tools: disabled (not hidden) when the selection can't use them, and the tooltip says why
  const px = grid.pixelIds().length;
  const need = { align: n < 2 ? "layout.need_two" : null, distribute: n < 3 ? "layout.need_three" : null,
                 shape: n < 2 ? "layout.need_two" : null, rotate: n < 1 ? "layout.need_one" : null,
                 pixels: px < 1 ? "layout.need_pixels" : null };
  for (const g of $$("#arrange .ar-group")) {
    const why = need[g.dataset.group];
    g.querySelectorAll("button:not(.info)").forEach((b) => { // the ⓘ always works
      b.disabled = !!why;
      b.title = tip(b) + (why ? ` - ${t(why)}` : "");
    });
  }
  if (n === 1) $("#ar-angle").value = grid.layout[ids[0]]?.rot ?? 0;
  $("#group-new").disabled = !n;
  $("#group-set").disabled = !n || group === "all";
  $("#group-rename").disabled = group === "all";
  $("#group-delete").disabled = group === "all";
}

function buildTabs(cat) {
  const names = ["all", ...Object.keys(cat.groups).sort()];
  if (!names.includes(group)) group = "all";
  $("#group-tabs").replaceChildren(...names.map((g) =>
    el("button", { role: "tab", "aria-selected": g === group, class: g === group ? "on" : "", "data-group": g,
                   onclick: () => pickGroup(g) }, g === "all" ? t("groups.all") : g)));
}

function pickGroup(g) {
  group = g;
  buildTabs(live.cat);
  const members = g === "all" ? Object.keys(grid.layout) : live.cat.groups[g] || [];
  grid.select(members);
}

async function editGroup(body, message) {
  const r = await attempt(() => api("POST", "/api/store/group", body), message);
  if (r) {
    await refreshCatalogue();
    if (body.action === "delete") pickGroup("all");
    else pickGroup(body.new_name || body.name);
  }
}

// the stage for the universe in view; an unsaved arrangement is kept
function buildGrid(cat, notify = false) {
  if (grid.layout && grid.dirty) {
    if (notify) toast(t("layout.kept_unsaved")); // someone else changed the files: keep this screen's edits
    const mine = grid.layout;
    grid.build(filteredCat(cat), mine);
    grid.saved = JSON.stringify(cat.layout);
  } else grid.build(filteredCat(cat));
}

function buildCatalogue(cat) {
  renderUniTabs();
  buildGrid(cat, true);
  buildTabs(cat);
  updateSelection();
  loadDoc();
}

export function init() {
  const syncView = () => {
    $("#zoom").value = Math.max(50, Math.min(400, grid.zoom));
    $("#layout-fit").classList.toggle("primary", !grid.fitted); // zoomed by hand: Fit brings it all back
  };
  grid = new LightGrid($("#layout-grid"), { edit: true, onChange: updateSelection, onView: syncView });
  $("#zoom").oninput = (e) => grid.setZoom(+e.target.value);
  $("#layout-fit").onclick = () => grid.fitView();
  // Space + drag pans the stage
  document.addEventListener("keydown", (ev) => {
    if (ev.code === "Space" && $("#page-layout").classList.contains("on") && !ev.target.matches("input, select, textarea, button")) {
      ev.preventDefault();
      document.body.classList.add("space-held");
    }
  });
  document.addEventListener("keyup", (ev) => { if (ev.code === "Space") document.body.classList.remove("space-held"); });
  $("#show-names").onchange = (e) => grid.setNames(e.target.checked);
  $("#show-beams").onchange = (e) => grid.setBeams(e.target.checked);
  $$("[data-tool]").forEach((b) => (b.onclick = () => {
    grid.tool = b.dataset.tool;
    $$("[data-tool]").forEach((x) => x.classList.toggle("sel", x === b));
  }));
  fillIcons($("#page-layout"));
  $$("#page-layout [data-tip], #page-layout [data-key]").forEach((b) => (b.title = tip(b)));
  const step = () => Math.max(1, +$("#ar-step").value || 45);
  $$("[data-align]").forEach((b) => (b.onclick = () => grid.align(b.dataset.align)));
  $$("[data-distribute]").forEach((b) => (b.onclick = () => grid.distribute(b.dataset.distribute)));
  $$("[data-make]").forEach((b) => (b.onclick = () => grid.make(b.dataset.make, { spacing: +$("#ar-spacing").value || 0, cols: +$("#ar-cols").value || 0 })));
  $$("[data-rotate]").forEach((b) => (b.onclick = () => grid.rotate(+b.dataset.rotate * step())));
  $$("[data-flip]").forEach((b) => (b.onclick = () => grid.flip(b.dataset.flip)));
  $$("[data-shape]").forEach((b) => (b.onclick = () => grid.setShape(b.dataset.shape, +$("#ar-pcols").value || 0)));
  $("[data-reverse]").onclick = () => grid.toggleReverse();
  $("#ar-angle").onchange = (e) => grid.setAngle(+e.target.value || 0);
  $("#layout-undo").onclick = () => grid.undo();
  $("#layout-redo").onclick = () => grid.redo();
  $("#layout-reset").onclick = () => { if (grid.dirty && confirm(t("layout.revert_confirm"))) grid.revert(); };
  $("#layout-save").onclick = saveLayout;
  async function saveLayout() {
    if (!grid.dirty) return;
    const r = await attempt(() => api("PUT", "/api/layout", { layout: grid.layout }), t("layout.saved"));
    if (r) {
      grid.saved = JSON.stringify(grid.layout);
      grid.history = [];
      grid.future = [];
      updateSelection(); // Save greys out straight away
      await refreshCatalogue();
    }
  }
  document.addEventListener("keydown", (ev) => {
    if (!$("#page-layout").classList.contains("on") || ev.target.matches("input, select, textarea")) return;
    const mod = ev.ctrlKey || ev.metaKey, k = ev.key.toLowerCase();
    if (mod && k === "z" && !ev.shiftKey) { ev.preventDefault(); grid.undo(); }
    if (mod && (k === "y" || (k === "z" && ev.shiftKey))) { ev.preventDefault(); grid.redo(); }
    if (mod && k === "s") { ev.preventDefault(); saveLayout(); }
    if (ev.altKey && !mod) {
      const edge = { arrowleft: "left", arrowright: "right", arrowup: "top", arrowdown: "bottom" }[k];
      if (edge) { ev.preventDefault(); grid.align(edge); }
    }
    if (!mod && !ev.altKey && k === "r") grid.rotate((ev.shiftKey ? -1 : 1) * step());
    if (!mod && !ev.altKey && (k === "h" || k === "v")) grid.flip(k);
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "a") { ev.preventDefault(); grid.select(Object.keys(grid.layout)); }
    if (ev.key === "Escape") grid.select([]);
    if (ev.key === "0" && !ev.ctrlKey && !ev.metaKey) grid.fitView();
  });

  $("#group-new").onclick = () => {
    const name = $("#group-name").value.trim();
    if (!name) return toast(t("groups.need_name"), true);
    if (live.cat.groups[name]) return toast(t("groups.exists", { name }), true);
    editGroup({ action: "set", name, fixtures: [...grid.selected] }, t("groups.made", { name }));
  };
  $("#group-set").onclick = () => editGroup({ action: "set", name: group, fixtures: [...grid.selected] }, t("groups.updated", { name: group }));
  $("#group-rename").onclick = () => {
    const to = $("#group-name").value.trim();
    if (!to) return toast(t("groups.need_new_name"), true);
    editGroup({ action: "rename", name: group, new_name: to }, t("groups.renamed", { name: group, to }));
  };
  $("#group-delete").onclick = () => {
    if (confirm(t("groups.confirm_delete", { name: group }))) editGroup({ action: "delete", name: group }, t("groups.deleted", { name: group }));
  };

  $$("#lp-views [data-view]").forEach((b) => (b.onclick = () => setView(b.dataset.view)));
  $("#lp-out").onchange = (e) => { outChoice = e.target.value; remember.set("layout.out", outChoice); watch(); };
  $("#lp-patch-save").onclick = savePatch;
  $("#lp-patch-revert").onclick = () => { doc.fixtures = JSON.parse(docSaved); renderFixtures(); renderAddresses(); };
  $("#lp-print").onclick = () => { renderAddresses(); window.print(); };
  $("#lp-png").onclick = () => exportPng().catch((e) => toast(String(e), true));
  onShow("layout", () => {
    setView(view);
    loadRouting();
    clearInterval(routingTimer);
    routingTimer = setInterval(() => (shown() ? loadRouting() : null), 1000);
  });
  onLeave("layout", () => {
    clearInterval(routingTimer); stopFeeds.forEach((s) => s()); stopFeeds = [];
    if (grid.dirty) toast(t("layout.unsaved_leave")); // kept, never discarded; Live isn't held up
  });

  onCatalogue(buildCatalogue);
  onState((s) => grid.update(s.fixtures, s.haze));
  onShow("layout", updateSelection);
  window.addEventListener("beforeunload", (ev) => { if (grid.dirty) ev.preventDefault(); });
}

// ---------------------------------------------------------------- v4: universes, patch list, routing, address map

let uni = remember.get("layout.uni", "all"); // "all" or a universe number
let view = remember.get("layout.view", "stage");
let doc = null; // fixtures.yaml (types + patch rows)
let docSaved = "";
let routing = null;
let routingTimer = null;
let stopFeeds = [];
const values = {}; // universe -> Uint8Array (what the chosen interface sent)
let outChoice = remember.get("layout.out", "");

const hue = (id) => [...id].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);
const shown = () => $("#page-layout").classList.contains("on");

function universes() {
  const set = new Set((live.cat?.fixtures || []).map((f) => f.universe ?? 0));
  for (const f of doc?.fixtures || []) set.add(+f.universe || 0);
  return [...set].sort((a, b) => a - b);
}

function rowsInView() {
  return (doc?.fixtures || []).filter((f) => uni === "all" || (+f.universe || 0) === uni);
}

function renderUniTabs() {
  const tabs = ["all", ...universes()];
  if (!tabs.includes(uni)) uni = "all";
  $("#lp-uni").replaceChildren(...tabs.map((u) => el("button", { role: "tab", class: u === uni ? "on" : "", "data-uni": String(u),
    "aria-selected": u === uni, onclick: () => setUni(u) }, u === "all" ? t("layout.uni_all") : `U${u}`)));
}

function setUni(u) {
  uni = u;
  remember.set("layout.uni", u);
  renderUniTabs();
  buildGrid(live.cat);
  renderFixtures();
  renderRouting();
  renderAddresses();
}

function filteredCat(cat) {
  return uni === "all" ? cat : { ...cat, fixtures: cat.fixtures.filter((f) => (f.universe ?? 0) === uni) };
}

// interfaces carrying each universe, from the routing table: "U0" -> ["Simulator", "Left bars"]
function carriers(u) {
  return (routing?.rows || []).filter((r) => r.universe === u).map((r) => r.interface);
}

// a rebuilt list keeps the field being typed in (and honours a pending "Change" from Fixtures)
let pendingAddr = null;
function focusRowField(id, idx, select) {
  const tr = document.querySelector(`#lp-fixtures tr[data-id="${CSS.escape(id)}"]`);
  const inp = tr?.querySelectorAll("input")[idx];
  if (!inp) return false;
  inp.focus();
  if (select) { inp.scrollIntoView({ block: "center" }); inp.select(); }
  return true;
}

function renderFixtures() {
  const act = document.activeElement;
  const keep = act?.closest?.("#lp-fixtures tr") ? [act.closest("tr").dataset.id, [...act.closest("tr").querySelectorAll("input")].indexOf(act)] : null;
  renderFixtureRows();
  if (pendingAddr && focusRowField(pendingAddr, 1, true)) { pickFixture(pendingAddr); pendingAddr = null; }
  else if (keep) focusRowField(keep[0], keep[1], false);
}

function renderFixtureRows() {
  if (!doc) return;
  const bad = clashPatch(doc.fixtures, doc.types);
  const sel = grid ? grid.selected : new Set();
  $("#lp-fixtures").replaceChildren(...rowsInView().map((f) => {
    const n = footprintOf(doc.types, f.type);
    const tr = el("tr", { class: [bad.has(f.id) ? "error" : "", sel.has(f.id) ? "sel" : ""].join(" ").trim(), "data-id": f.id,
      onclick: (e) => { if (!e.target.matches("input")) pickFixture(f.id, e.shiftKey); } },
    el("td", { text: f.id }),
    el("td", { text: doc.types[f.type]?.name || f.type, title: doc.types[f.type]?.name || f.type }),
    el("td", { text: n }),
    el("td", {}, el("input", { type: "number", class: "num", min: 0, max: 15, value: f.universe ?? 0,
      "aria-label": t("layout.aria_universe", { id: f.id }),
      oninput: (e) => { f.universe = +e.target.value || 0; patchChanged(); } })),
    el("td", {}, el("input", { type: "number", class: "num", min: 1, max: 512, value: f.address ?? "",
      "aria-label": t("layout.aria_address", { id: f.id }),
      oninput: (e) => { f.address = +e.target.value || 0; patchChanged(); } })),
    el("td", { class: "muted", text: f.address ? `${f.address}-${f.address + n - 1}` : "" }),
    el("td", { class: "muted", text: (f.groups || []).join(", ") }),
    el("td", { class: "muted", text: carriers(+f.universe || 0).join(", ") || "-" }));
    return tr;
  }));
  $("#lp-clash").textContent = bad.size ? t("layout.clash", { ids: [...bad].join(", ") }) : "";
  $("#lp-clash").classList.toggle("hidden", !bad.size);
  const dirtyPatch = JSON.stringify(doc.fixtures) !== docSaved;
  $("#lp-patch-save").disabled = !dirtyPatch || bad.size > 0;
  $("#lp-patch-revert").disabled = !dirtyPatch;
}

function patchChanged() {
  // keep focus in the field being typed in: only refresh what depends on the numbers
  const bad = clashPatch(doc.fixtures, doc.types);
  $$("#lp-fixtures tr").forEach((tr) => {
    const f = doc.fixtures.find((x) => x.id === tr.dataset.id);
    tr.classList.toggle("error", bad.has(tr.dataset.id));
    const n = footprintOf(doc.types, f.type);
    tr.children[5].textContent = f.address ? `${f.address}-${f.address + n - 1}` : "";
  });
  $("#lp-clash").textContent = bad.size ? t("layout.clash", { ids: [...bad].join(", ") }) : "";
  $("#lp-clash").classList.toggle("hidden", !bad.size);
  const dirtyPatch = JSON.stringify(doc.fixtures) !== docSaved;
  $("#lp-patch-save").disabled = !dirtyPatch || bad.size > 0;
  $("#lp-patch-revert").disabled = !dirtyPatch;
  renderAddresses();
}

// Fixtures › Patch sends address changes here (one place to edit addresses): open Layout with that
// light picked and its address field ready to type in
export function editAddress(id) {
  if (uni !== "all" && !rowsInView().some((f) => f.id === id)) setUni("all");
  pendingAddr = id;  // taken by the next render if the rows aren't there yet
  if (focusRowField(id, 1, true)) { pickFixture(id); pendingAddr = null; }
}

function pickFixture(id, add) {
  if (grid.items[id]) grid.select([id], add);
  else { // not on the stage (haze machine) or another universe: highlight the list and the address map only
    lpSelected = new Set(add ? [...lpSelected, id] : [id]);
    markListSelection();
  }
}

let lpSelected = new Set();
function markListSelection() {
  const sel = new Set([...grid.selected, ...lpSelected]);
  $$("#lp-fixtures tr").forEach((tr) => tr.classList.toggle("sel", sel.has(tr.dataset.id)));
  $$("#addr-maps .ac").forEach((c) => c.classList.toggle("hl", (c.dataset.ids || "").split(",").some((x) => sel.has(x))));
}

async function loadDoc() {
  doc = await get("/api/store/fixtures");
  doc.fixtures ||= [];
  docSaved = JSON.stringify(doc.fixtures);
  renderUniTabs();
  renderFixtures();
  renderAddresses();
}

async function savePatch() {
  const r = await attempt(() => api("PUT", "/api/store/patch", { fixtures: doc.fixtures }), t("layout.patch_saved"));
  if (r) { await refreshCatalogue(); await loadDoc(); }
}

// ---------------------------------------------------------------- routing table + status strip

async function loadRouting() {
  try { routing = await get("/api/routing"); } catch { return; }
  renderRouting();
}

const ago = (ms) => (ms === null || ms === undefined ? t("layout.never") : t("layout.ms_ago", { n: ms }));

// v5: USB DMX (Open) rows: driver (VCP / D2XX), break method, measured vs target; amber when out of range
function timingCell(r) {
  const tm = r.timing;
  if (!tm) return el("td", { text: "" });
  const m = tm.measured, g = tm.target, ck = r.checks;
  const driver = t(`timing.${ck?.driver_type || (tm.backend === "d2xx" ? "d2xx" : "vcp")}`);
  const text = t("timing.short", { driver, method: tm.method_name, brk: m.break_us ?? "-", tbrk: g.break_us, mab: m.mab_us ?? "-", tmab: g.mab_us });
  const warn = tm.warnings.length || (ck && ck.result !== "pass");
  return el("td", { class: warn ? "amber" : "", text, title: [...tm.warnings, ...(ck?.problems || []), tm.note].join("\n") });
}

function renderRouting() {
  if (!routing) return;
  $("#lp-routing").replaceChildren(...routing.rows.map((r) => el("tr", { class: uni !== "all" && r.universe === uni ? "on" : "" },
    el("td", { text: r.universe ?? "?" }),
    el("td", { text: r.interface + (r.port ? ` (${r.port})` : r.mac ? ` (${r.mac})` : ""), title: r.detail || "" }),
    el("td", {}, el("span", { class: `st-dot ${r.state}` }), r.state),
    el("td", { text: r.fps ?? "-" }), el("td", { text: r.frames ?? r.packets ?? "-" }), el("td", { text: r.errors ?? "-" }),
    el("td", { text: ago(r.last_frame_age_ms) }), timingCell(r))));
  $("#lp-routing-problems").replaceChildren(...routing.problems.map((p) => el("li", { text: p })));
  // status strip: the interface(s) carrying the universe in view
  const us = uni === "all" ? universes() : [uni];
  const parts = us.map((u) => {
    const rows = routing.rows.filter((r) => r.universe === u);
    if (!rows.length) return t("layout.status_none", { u });
    return rows.map((r) => t("layout.status", { u, iface: r.interface, fps: r.fps ?? "-", frames: r.frames ?? r.packets ?? "-",
      errors: r.errors ?? "-", last: ago(r.last_frame_age_ms) })).join("  |  ");
  });
  $("#lp-status").textContent = parts.join("  |  ");
  $("#lp-status").classList.toggle("bad", us.some((u) => !routing.rows.some((r) => r.universe === u)));
  // where address-map values come from
  const opts = [["", "auto"], ...routing.rows.filter((r) => r.output !== null && r.output !== undefined && (uni === "all" || r.universe === uni))
    .map((r) => [String(r.output), r.interface]), ["engine", t("layout.addr_engine")]];
  const seen = new Set();
  $("#lp-out").replaceChildren(...opts.filter(([v]) => !seen.has(v) && seen.add(v)).map(([v, label]) =>
    el("option", { value: v, selected: v === outChoice }, v === "" ? (carriers(us[0])[0] || label) : label)));
  renderFixtures();
}

// ---------------------------------------------------------------- address map (32 x 16 per universe)

function renderAddresses() {
  if (!doc) return;
  const us = uni === "all" ? universes() : [uni];
  $("#addr-maps").replaceChildren(...us.map((u) => {
    const { cells } = addressMap(doc.fixtures, doc.types, u);
    const grid32 = el("div", { class: "addr-map", "data-u": u });
    for (let c = 1; c <= 512; c++) {
      const ids = cells[c - 1];
      const cell = el("div", { class: "ac" + (ids.length ? " used" : "") + (ids.length > 1 ? " clash" : ""), "data-ch": c,
        "data-ids": ids.join(",") }, el("span", { class: "n", text: c }), el("span", { class: "v" }));
      if (ids.length) {
        const f = doc.fixtures.find((x) => x.id === ids[0]);
        const n = footprintOf(doc.types, f.type);
        cell.style.setProperty("--h", hue(ids[0]));
        const name = live.cat?.fixtures.find((x) => x.id === ids[0])?.channels?.[c - f.address];
        cell.title = `${ids.join(" + ")} · ch ${c}` + (name ? ` · ${name}` : "") + ` (${f.address}-${f.address + n - 1})`;
        if (c === f.address) { cell.classList.add("start"); cell.append(el("span", { class: "lbl", text: ids[0] })); }
      }
      grid32.append(cell);
    }
    return el("div", {}, el("h3", { text: t("layout.addr_title", { u }) }), el("div", { class: "addr-note", "data-note": u }), grid32);
  }));
  markListSelection();
  paintValues();
  watch();
}

function paintValues() {
  for (const box of $$("#addr-maps .addr-map")) {
    const u = +box.dataset.u, v = values[u];
    box.querySelectorAll(".ac").forEach((cell, i) => {
      const x = v ? v[i] : null;
      cell.querySelector(".v").textContent = x === null || x === undefined || !v ? "" : x || "";
      cell.style.setProperty("--v", x ? x / 255 : 0);
    });
  }
}

function watch() {
  stopFeeds.forEach((s) => s());
  stopFeeds = [];
  if (!shown() || view !== "addresses") return;
  const us = uni === "all" ? universes() : [uni];
  stopFeeds = us.map((u) => watchFrames(u, outChoice, (f) => {
    values[u] = f.values; // null when the interface sent nothing: shown blank, never guessed
    const note = $(`#addr-maps [data-note="${u}"]`);
    if (note) {
      note.textContent = f.no_frames ? t("layout.addr_no_frames", { source: f.source, u }) : f.stats?.all_zero ? t("layout.addr_all_zero", { source: f.source }) : f.source;
      note.classList.toggle("bad", !!(f.no_frames || f.stats?.all_zero));
    }
    paintValues();
  }));
}

function setView(v) {
  view = v;
  remember.set("layout.view", v);
  $$("#lp-views [data-view]").forEach((b) => b.classList.toggle("on", b.dataset.view === v));
  $("#lp-stage").classList.toggle("hidden", v !== "stage");
  $("#lp-addresses").classList.toggle("hidden", v !== "addresses");
  if (v === "stage") grid.fit();
  watch();
}

// ---------------------------------------------------------------- patch sheet: PNG

function inlineStyles(src, dst) {
  const cs = getComputedStyle(src);
  for (const k of ["fill", "stroke", "stroke-width", "font-size", "font-weight", "font-family", "opacity", "display", "paint-order"]) {
    dst.style.setProperty(k, cs.getPropertyValue(k));
  }
  [...src.children].forEach((c, i) => dst.children[i] && inlineStyles(c, dst.children[i]));
}

async function exportPng() {
  const svgEl = $("#layout-grid svg");
  const W = 1600, cellW = W / 32, cellH = 26;
  const us = uni === "all" ? universes() : [uni];
  const box = svgEl.getBoundingClientRect();
  const stageH = Math.round(W * (box.height / Math.max(1, box.width)));
  const canvas = document.createElement("canvas");
  canvas.width = W;
  canvas.height = 40 + stageH + us.length * (16 * cellH + 34) + 20;
  const g = canvas.getContext("2d");
  g.fillStyle = "#fff"; g.fillRect(0, 0, canvas.width, canvas.height);
  g.fillStyle = "#000"; g.font = "bold 20px sans-serif";
  g.fillText(t("layout.sheet_title", { rig: live.cat?.rig_name || "" }) + `  ${new Date().toLocaleDateString("en-AU")}`, 10, 26);
  const clone = svgEl.cloneNode(true);
  inlineStyles(svgEl, clone);
  clone.querySelector(".gridlines")?.remove();
  clone.setAttribute("width", W); clone.setAttribute("height", stageH);
  const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(clone)], { type: "image/svg+xml" }));
  const img = new Image();
  await new Promise((ok, bad) => { img.onload = ok; img.onerror = bad; img.src = url; });
  g.fillStyle = "#111"; g.fillRect(0, 40, W, stageH);
  g.drawImage(img, 0, 40, W, stageH);
  URL.revokeObjectURL(url);
  let y = 40 + stageH + 30;
  for (const u of us) {
    g.fillStyle = "#000"; g.font = "bold 16px sans-serif"; g.fillText(t("layout.addr_title", { u }), 10, y - 8);
    const { cells } = addressMap(doc.fixtures, doc.types, u);
    for (let c = 0; c < 512; c++) {
      const x = (c % 32) * cellW, yy = y + Math.floor(c / 32) * cellH, ids = cells[c];
      g.fillStyle = ids.length > 1 ? "#f08080" : ids.length ? `hsl(${hue(ids[0])} 60% 85%)` : "#fff";
      g.fillRect(x, yy, cellW, cellH);
      g.strokeStyle = "#bbb"; g.strokeRect(x, yy, cellW, cellH);
      g.fillStyle = "#555"; g.font = "9px sans-serif"; g.fillText(String(c + 1), x + 2, yy + 9);
      const f = ids.length ? doc.fixtures.find((q) => q.id === ids[0]) : null;
      if (f && f.address === c + 1) { g.fillStyle = "#000"; g.font = "bold 10px sans-serif"; g.fillText(ids[0], x + 2, yy + 21); }
    }
    y += 16 * cellH + 34;
  }
  const a = el("a", { download: `patch-sheet-${live.cat?.rig_name || "rig"}${uni === "all" ? "" : "-U" + uni}.png` });
  a.href = canvas.toDataURL("image/png");
  document.body.append(a);
  a.click();
  a.remove();
}
