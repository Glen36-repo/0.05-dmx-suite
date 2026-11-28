// Layout page: arrange the lights on the grid, and make groups from a selection.
import { ago, hue, universesOf } from "../addrmap.js";
import { api, attempt, cmd, get, toast } from "../api.js";
import { $, $$, el, remember } from "../dom.js";
import { LightGrid } from "../grid.js";
import { t } from "../i18n.js";
import { fillIcons } from "../icons.js";
import { onLeave, onShow } from "../nav.js";
import { addressMap } from "../patch.js";
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

function showCentre(c = grid.centreNow()) {
  for (const k of ["x", "y"]) {
    const inp = $(`#centre-${k}`);
    if (document.activeElement !== inp) inp.value = c[k];
    inp.classList.toggle("auto", !grid.centre);
  }
  $("#centre-reset").disabled = !grid.centre;
}

function updateSelection() {
  showProblems();
  showCentre();
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
    const mine = grid.layout, centre = grid.centre;
    grid.build(filteredCat(cat), mine);
    grid.saved = JSON.stringify(cat.layout);
    grid.centre = centre;
    grid.savedCentre = JSON.stringify(cat.centre || null);
    grid.drawCentre();
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
  grid = new LightGrid($("#layout-grid"), { edit: true, onChange: updateSelection, onView: syncView, onCentre: showCentre });
  // v8 stage centrelines: drag on the grid, type a value, or back to the middle of the lights
  const typed = () => grid.setCentre({ x: +$("#centre-x").value || 0, y: +$("#centre-y").value || 0 });
  $("#centre-x").onchange = typed;
  $("#centre-y").onchange = typed;
  $("#centre-reset").onclick = () => { grid.setCentre(null); toast(t("layout.centre_saved_auto")); };
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
    const r = await attempt(() => api("PUT", "/api/layout", { layout: grid.layout, centre: grid.centre }), t("layout.saved"));
    if (r) {
      grid.saved = JSON.stringify(grid.layout);
      grid.savedCentre = JSON.stringify(grid.centre);
      grid.history = [];
      grid.future = [];
      updateSelection(); // Save greys out straight away
      await refreshCatalogue();
      window.dispatchEvent(new CustomEvent("dmx:save-file")); // v7 Manual save: Ctrl+S saves the file too
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

  $("#lp-png").onclick = () => exportPng().catch((e) => toast(String(e), true));
  onShow("layout", () => {
    grid.fit();
    loadRouting();
    clearInterval(routingTimer);
    routingTimer = setInterval(() => (shown() ? loadRouting() : null), 1000);
  });
  onLeave("layout", () => {
    clearInterval(routingTimer);
    if (grid.dirty) toast(t("layout.unsaved_leave")); // kept, never discarded; Live isn't held up
  });

  onCatalogue(buildCatalogue);
  onState((s) => {
    grid.update(s.fixtures, s.haze);
    $$("#lp-fixtures [data-find]").forEach((b) => b.classList.toggle("sel", b.dataset.find === s.setup?.find));
  });
  onShow("layout", updateSelection);
  window.addEventListener("beforeunload", (ev) => { if (grid.dirty) ev.preventDefault(); });
}

// ---------------------------------------------------------------- v4: universes, status strip; v7: the narrow strip
// (universes, addresses, the address map and routing moved to Fixtures, the one place for them)

let uni = remember.get("layout.uni", "all"); // "all" or a universe number
let doc = null; // fixtures.yaml (types + patch rows), for the strip and the patch sheet
let routing = null;
let routingTimer = null;

const shown = () => $("#page-layout").classList.contains("on");

function universes() {
  return universesOf(doc, live.cat);
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
  renderStatus();
}

function filteredCat(cat) {
  return uni === "all" ? cat : { ...cat, fixtures: cat.fixtures.filter((f) => (f.universe ?? 0) === uni) };
}

// the narrow strip: name, type, find, test; tap a row to pick the light on the stage
function renderFixtures() {
  if (!doc) return;
  const findOn = live.state?.setup?.find;
  $("#lp-fixtures").replaceChildren(...rowsInView().map((f) => el("tr", { "data-id": f.id,
    onclick: (e) => { if (!e.target.closest("button")) pickFixture(f.id, e.shiftKey); } },
  el("td", { text: f.id }),
  el("td", { class: "muted", text: doc.types[f.type]?.name || f.type, title: doc.types[f.type]?.name || f.type }),
  el("td", { class: "tools" },
    el("button", { class: "mini" + (findOn === f.id ? " sel" : ""), "data-find": f.id, title: t("fixtures.find_tip"),
      onclick: () => cmd("find", { fixture: live.state?.setup?.find === f.id ? null : f.id }) }, t("fixtures.find")),
    el("button", { class: "mini", "data-test": f.id, title: t("layout.test_tip"), onclick: () => testFixture(f) }, t("layout.test"))))));
  markListSelection();
}

// Test: the v5 "find fixture" pattern (colour flash and a tilt nod) on that light's universe; again stops it
async function testFixture(f) {
  const st = await get("/api/test").catch(() => null);
  if (st?.test?.fixture === f.id) return api("POST", "/api/test/stop", { why: "stopped" }).catch(() => null);
  attempt(() => api("POST", "/api/test/run", { pattern: "find", fixture: f.id, universe: +f.universe || 0, timeout_s: 30 }),
    t("layout.testing", { id: f.id }));
}

function pickFixture(id, add) {
  if (grid.items[id]) grid.select([id], add);
  else { // not on the stage (haze machine) or another universe: highlight the list only
    lpSelected = new Set(add ? [...lpSelected, id] : [id]);
    markListSelection();
  }
}

let lpSelected = new Set();
function markListSelection() {
  const sel = new Set([...grid.selected, ...lpSelected]);
  $$("#lp-fixtures tr").forEach((tr) => tr.classList.toggle("sel", sel.has(tr.dataset.id)));
}

async function loadDoc() {
  doc = await get("/api/store/fixtures");
  doc.fixtures ||= [];
  renderUniTabs();
  renderFixtures();
}

// ---------------------------------------------------------------- status strip: the interface(s) carrying the universe in view

async function loadRouting() {
  try { routing = await get("/api/routing"); } catch { return; }
  renderStatus();
}

function renderStatus() {
  if (!routing) return;
  const us = uni === "all" ? universes() : [uni];
  const parts = us.map((u) => {
    const rows = routing.rows.filter((r) => r.universe === u);
    if (!rows.length) return t("layout.status_none", { u });
    return rows.map((r) => t("layout.status", { u, iface: r.interface, fps: r.fps ?? "-", frames: r.frames ?? r.packets ?? "-",
      errors: r.errors ?? "-", last: ago(r.last_frame_age_ms) })).join("  |  ");
  });
  $("#lp-status").textContent = parts.join("  |  ");
  $("#lp-status").classList.toggle("bad", us.some((u) => !routing.rows.some((r) => r.universe === u)));
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
