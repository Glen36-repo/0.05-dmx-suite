// Layout page: arrange the lights on the grid, and make groups from a selection.
import { api, attempt, toast } from "../api.js";
import { $, $$, el } from "../dom.js";
import { LightGrid } from "../grid.js";
import { t } from "../i18n.js";
import { onShow } from "../nav.js";
import { live, onCatalogue, onState, refreshCatalogue } from "../state.js";

let grid;
let group = "all"; // the group tab showing

function updateSelection() {
  const n = grid.selected.size;
  const ids = [...grid.selected];
  $("#layout-sel").textContent = n
    ? t("layout.selected", { n, names: ids.slice(0, 8).join(", ") + (n > 8 ? " …" : "") })
    : t("layout.select_help");
  $("#layout-save").classList.toggle("sel", grid.dirty);
  $("#layout-save").disabled = !grid.dirty;
  $("#layout-undo").disabled = !grid.history.length;
  $$("#arrange-tools button, [data-make], [data-rotate], [data-shape]").forEach((b) => (b.disabled = !n));
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

function buildCatalogue(cat) {
  if (grid && grid.dirty) {
    toast(t("layout.kept_unsaved")); // someone else changed the files: keep this screen's edits
    const mine = grid.layout;
    grid.build(cat, mine);
    grid.saved = JSON.stringify(cat.layout);
  } else grid.build(cat);
  buildTabs(cat);
  updateSelection();
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
  $$("[data-align]").forEach((b) => (b.onclick = () => grid.align(b.dataset.align)));
  $$("[data-distribute]").forEach((b) => (b.onclick = () => grid.distribute(b.dataset.distribute) || toast(t("layout.distribute_help"))));
  $$("[data-make]").forEach((b) => (b.onclick = () => grid.make(b.dataset.make)));
  $$("[data-rotate]").forEach((b) => (b.onclick = () => grid.rotate(+b.dataset.rotate)));
  $$("[data-shape]").forEach((b) => (b.onclick = () => grid.setShape(b.dataset.shape) || toast(t("layout.shape_help"))));
  $("#layout-undo").onclick = () => grid.undo();
  $("#layout-reset").onclick = () => { grid.build(live.cat); updateSelection(); };
  $("#layout-save").onclick = async () => {
    const r = await attempt(() => api("PUT", "/api/layout", { layout: grid.layout }), t("layout.saved"));
    if (r) {
      grid.saved = JSON.stringify(grid.layout);
      grid.history = [];
      updateSelection(); // Save greys out straight away
      await refreshCatalogue();
    }
  };
  document.addEventListener("keydown", (ev) => {
    if (!$("#page-layout").classList.contains("on") || ev.target.matches("input, select, textarea")) return;
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "z") { ev.preventDefault(); grid.undo(); }
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

  onCatalogue(buildCatalogue);
  onState((s) => grid.update(s.fixtures, s.haze));
  onShow("layout", updateSelection);
  window.addEventListener("beforeunload", (ev) => { if (grid.dirty) ev.preventDefault(); });
}
