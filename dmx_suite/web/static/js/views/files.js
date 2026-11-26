// Files page: preview or play scenes; put any file back from the backups.
import { api, attempt, cmd, get } from "../api.js";
import { $, el } from "../dom.js";
import { t } from "../i18n.js";
import { onShow } from "../nav.js";
import { live, refreshCatalogue } from "../state.js";

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
  onShow("files", () => { load(); loadHistory(); });
}
