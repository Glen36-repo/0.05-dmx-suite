// Files page: preview or play scenes; put any file back from the backups.
import { api, attempt, cmd, get } from "../api.js";
import { $, el } from "../dom.js";
import { t } from "../i18n.js";
import { onShow } from "../nav.js";
import { live } from "../state.js";

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

export function init() {
  onShow("files", load);
}
