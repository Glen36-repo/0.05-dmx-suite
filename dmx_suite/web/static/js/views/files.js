// Files page: preview or play scenes; put any file back from the backups.
import { api, attempt, cmd, get, toast } from "../api.js";
import { $, el } from "../dom.js";
import { t } from "../i18n.js";
import { onShow } from "../nav.js";
import { live, onState, refreshCatalogue } from "../state.js";

async function load() {
  $("#scenes").replaceChildren(...Object.entries(live.cat.scenes).map(([k, n]) => el("div", { class: "item" },
    el("span", { class: "name", text: `${n} (${k})` }),
    el("button", { onclick: () => attempt(() => api("POST", "/api/preview", { scene: k, seconds: 10 }), (r) => r.message) }, t("files.preview")),
    el("button", { onclick: () => cmd("scene", { scene: k }) }, t("files.play")))));
  const backups = await get("/api/backups");
  $("#backups").replaceChildren(...backups.map((b) => el("div", { class: "item" },
    el("span", { class: "name", text: `${b.id}  ${b.note}` }),
    ...b.files.map((f) => el("button", { onclick: async () => {
      if (!confirm(t("files.confirm_restore", { file: f, note: b.note }))) return;
      if (await attempt(() => api("POST", "/api/store/restore", { backup: b.id, file: f }), t("files.restored", { file: f }))) load();
    } }, t("files.restore", { file: f }))))));
}

// ---------------------------------------------------------------- the show file (.dms)

let info = null;
let pathAction = null; // "open" | "save_as" | "new" while typing a path (no file dialog: a browser)

async function loadProject() {
  info = await get("/api/project");
  const p = info.project;
  const now = $("#project-now");
  now.replaceChildren(p ? el("strong", { text: p.name }) : el("span", { text: t("project.folder") }),
    " ", el("code", { class: "muted", text: p ? p.path : info.folder }));
  if (p?.read_only) now.append(" ", el("span", { class: "chip warn", text: t("project.read_only") }));
  for (const id of ["#project-open", "#project-save-as", "#project-new"]) $(id).disabled = !info.local;
  drawSaveState(p);
  $("#project-recent").replaceChildren(...info.recent.map((r) => el("li", {},
    el("button", { class: "link", disabled: !info.local || r === p?.path, onclick: () => openFile(r) }, r))));
}

async function picked(mode, suggested) {
  const native = window.pywebview?.api?.pick; // the desktop window has real file dialogs
  if (native) return window.pywebview.api.pick(mode, suggested || "");
  return null;
}

function askPath(action) {
  pathAction = action;
  $("#project-path-row").classList.remove("hidden");
  $("#project-path").value = action === "open" ? "" : (info?.project?.path || "");
  $("#project-path").focus();
}

async function openFile(path) {
  const unsaved = await askUnsaved();
  if (unsaved === null) return;
  if (!unsaved.save && !unsaved.discard && !confirm(t("project.confirm_switch", { name: path.split(/[\\/]/).pop() }))) return;
  const r = await attempt(() => api("POST", "/api/project/open", { path, ...unsaved }));
  if (r?.restarting) restarting();
}

// ---------------------------------------------------------------- v7 Save, Auto-save / Manual save, "●"

const baseTitle = document.title;
let project = null; // the live state's project info

function drawSaveState(p) {
  project = p || null;
  const dirty = !!p?.dirty;
  const manual = p?.save_mode === "manual";
  $("#project-save").disabled = !p || !info?.local || (!dirty && !manual);
  $("#project-save").classList.toggle("primary", dirty);
  $("#save-state").textContent = !p ? t("project.folder_saves") : dirty ? t("project.unsaved") : manual ? t("project.all_saved") : "";
  const title = (dirty ? "● " : "") + (p ? `${p.name} - ` : "") + baseTitle;
  if (document.title !== title) {
    document.title = title;
    window.pywebview?.api?.set_title?.(title); // the desktop window's own title
  }
}

export async function saveFile() {
  if (!project) return toast(t("project.folder_saves"));
  const r = await attempt(() => api("POST", "/api/project/save", {}), t("project.saved_now", { name: project.name }));
  if (r) drawSaveState(r.project);
}

// before opening another file or starting a new one with unsaved changes: Save / Don't save / Cancel.
// Resolves {} (nothing unsaved), {save: true}, {discard: true} or null (cancel).
function askUnsaved() {
  if (!project?.dirty) return Promise.resolve({});
  const d = $("#unsaved-dialog");
  $("#unsaved-text").textContent = t("project.unsaved_ask", { name: project.name });
  return new Promise((done) => {
    const pick = (v) => { d.close(); done(v === "save" ? { save: true } : v === "discard" ? { discard: true } : null); };
    d.querySelectorAll("button").forEach((b) => (b.onclick = () => pick(b.value)));
    d.oncancel = () => pick("");
    d.showModal();
  });
}

function restarting() {
  toast(t("project.restarting"));
  document.body.classList.add("restarting");
  setTimeout(() => location.reload(), 4000);
}

async function run(action, path) {
  if (action === "open") return openFile(path);
  if (action === "new") {
    const unsaved = await askUnsaved();
    if (unsaved === null) return;
    const r = await attempt(() => api("POST", "/api/project/new", { path, ...unsaved }));
    if (r?.restarting) restarting();
    return;
  }
  let r = await api("POST", "/api/project/save_as", { path }).catch((e) => ({ error: e.message }));
  if (r.error && r.error.includes("already exists") && confirm(t("project.overwrite", { name: path }))) {
    r = await api("POST", "/api/project/save_as", { path, overwrite: true }).catch((e) => ({ error: e.message }));
  }
  if (r.error) return toast(r.error, true);
  toast(t(r.restart_to_use ? "project.saved_folder" : "project.saved", { name: r.saved }));
  loadProject();
}

async function choose(action) {
  const path = await picked(action === "open" ? "open" : "save", info?.project?.name || "show.dms");
  if (path) return run(action, path);
  if (!window.pywebview?.api?.pick) askPath(action);
}

async function upload(file) {
  if (!file || !confirm(t("project.confirm_switch", { name: file.name }))) return;
  const res = await fetch(`/api/project/upload?name=${encodeURIComponent(file.name)}`, {
    method: "POST",
    headers: { "Content-Type": "application/octet-stream", "X-DMX-Token": document.querySelector('meta[name="dmx-token"]').content },
    body: file,
  });
  const r = await res.json().catch(() => ({}));
  if (!res.ok) return toast(r.error || res.statusText, true);
  restarting();
}

// ---------------------------------------------------------------- undo / redo (every page)

async function loadHistory() {
  const h = await get("/api/undo");
  renderHistory(h);
}

function renderHistory(h) {
  $("#undo").disabled = !h.undo.length;
  $("#redo").disabled = !h.redo.length;
  const row = (c, done) => el("li", { class: done ? "" : "undone" },
    el("span", { class: "chip", text: t(c.who === "claude" ? "history.by_claude" : "history.by_you") }),
    el("span", { text: c.note }), el("span", { class: "muted", text: new Date(c.at * 1000).toLocaleTimeString("en-AU") }));
  $("#history").replaceChildren(...h.redo.slice().reverse().map((c) => row(c, false)), ...h.undo.map((c) => row(c, true)));
}

export async function undoRedo(redo = false) {
  const r = await attempt(() => api("POST", redo ? "/api/redo" : "/api/undo", {}),
    (x) => t(redo ? "history.redone" : "history.undone", { note: x.change.note }));
  if (!r) return;
  renderHistory(r);
  await refreshCatalogue();
  if ($("#page-files").classList.contains("on")) load();
}

export function init() {
  $("#project-save").onclick = saveFile;
  onState((s) => drawSaveState(s.project));
  document.addEventListener("keydown", (ev) => { // Ctrl+S anywhere (Layout saves the layout first, then the file)
    if (!(ev.ctrlKey || ev.metaKey) || ev.key.toLowerCase() !== "s" || ev.shiftKey || ev.altKey) return;
    if ($("#page-layout")?.classList.contains("on")) return; // layout.js: its own Ctrl+S, then "dmx:save-file"
    ev.preventDefault();
    saveFile();
  });
  window.addEventListener("dmx:save-file", () => { if (project?.dirty) saveFile(); });
  window.addEventListener("beforeunload", (ev) => { if (project?.dirty) ev.preventDefault(); });
  get("/api/settings").then((s) => { $("#save-mode").value = s.settings.save_mode || "auto"; }).catch(() => null);
  $("#save-mode").onchange = async (e) => {
    const r = await attempt(() => api("POST", "/api/settings", { save_mode: e.target.value }), t("project.save_mode_set"));
    if (r && e.target.value === "auto" && project?.dirty) saveFile(); // back to auto-save: write what's waiting
  };
  $("#project-open").onclick = () => choose("open");
  $("#project-save-as").onclick = () => choose("save_as");
  $("#project-new").onclick = () => choose("new");
  $("#project-upload").onchange = (e) => upload(e.target.files[0]);
  $("#project-path-go").onclick = () => {
    const path = $("#project-path").value.trim();
    if (!path) return;
    $("#project-path-row").classList.add("hidden");
    run(pathAction, path);
  };
  $("#project-path-cancel").onclick = () => $("#project-path-row").classList.add("hidden");
  $("#undo").onclick = () => undoRedo(false);
  $("#redo").onclick = () => undoRedo(true);
  // Ctrl+Z / Ctrl+Y (or Ctrl+Shift+Z) anywhere, except in a text box and on the Layout page,
  // which has its own undo for unsaved moves
  document.addEventListener("keydown", (ev) => {
    if (!(ev.ctrlKey || ev.metaKey) || ev.target.matches("input, select, textarea")) return;
    if ($("#page-layout").classList.contains("on")) return;
    const k = ev.key.toLowerCase();
    if (k === "z" && !ev.shiftKey) { ev.preventDefault(); undoRedo(false); }
    else if (k === "y" || (k === "z" && ev.shiftKey)) { ev.preventDefault(); undoRedo(true); }
  });
  onShow("files", () => { load(); loadHistory(); loadProject(); });
}
