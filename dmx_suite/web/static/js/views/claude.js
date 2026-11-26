// Setup page: Connect to Claude. Adds the 0.05 tools to Claude Desktop and Claude Code on this
// laptop (or takes them out), with a once-per-laptop checklist and each Claude app's state.
// Nothing is written until Connect. Claude's edits are checked like yours and gig lock stops them.
import { api, attempt, get, toast } from "../api.js";
import { $, el } from "../dom.js";
import { t } from "../i18n.js";
import { onShow } from "../nav.js";

let status = null;
let busy = false;

const ago = (s) => (s < 90 ? t("claude.secs", { n: Math.round(s) }) : s < 5400 ? t("claude.mins", { n: Math.round(s / 60) }) : t("claude.hours", { n: Math.round(s / 3600) }));

function steps(s) {
  const found = s.targets.filter((x) => x.installed);
  const connected = found.length > 0 && found.every((x) => x.registered === "current");
  return [
    [t("claude.step_app"), s.program_ok],
    [t("claude.step_install"), found.length > 0],
    [t("claude.step_connect"), connected],
    [t("claude.step_restart"), s.last_seen != null],
  ];
}

function lines(s) {
  const out = [];
  if (!s.program_ok) out.push([t("claude.no_program", { path: s.program }), "warn"]);
  if (!s.targets.some((x) => x.installed)) out.push([t("claude.none_found"), "warn"]);
  for (const x of s.targets) {
    if (x.error) out.push([t("claude.target_error", { app: x.label, path: x.config, error: x.error }), "warn"]);
    else if (!x.installed) continue;
    else if (x.registered === "current") out.push([t("claude.target_ok", { app: x.label }), "ok"]);
    else if (x.registered === "other") out.push([t("claude.target_other", { app: x.label, shows: x.entry_shows || x.entry_command || "?" }), "warn"]);
    else out.push([t("claude.target_no", { app: x.label }), "muted"]);
  }
  const now = Date.now() / 1000;
  out.push([s.last_seen != null
    ? t("claude.seen", { ago: ago(now - s.last_seen), call: s.last_call || t("claude.checking_in") })
    : t("claude.never_seen"), s.last_seen != null && now - s.last_seen < 75 ? "ok" : "muted"]);
  return out;
}

function render() {
  const s = status;
  const box = $("#claude-connect");
  if (!s) return box.replaceChildren(el("p", { class: "muted", text: t("claude.checking") }));
  const found = s.targets.filter((x) => x.installed);
  const allCurrent = found.length > 0 && found.every((x) => x.registered === "current");
  const canConnect = s.program_ok && found.length > 0 && !found.some((x) => x.error) && !allCurrent;
  const canDisconnect = s.targets.some((x) => x.registered !== "no" && !x.error);
  box.replaceChildren(
    el("p", { class: "muted", text: t("claude.help") }),
    el("p", {}, el("b", { text: t("claude.setup_title") })),
    el("ol", { class: "claude-steps" }, ...steps(s).map(([text, done]) => el("li", { class: done ? "done" : "" }, (done ? "✓ " : "") + text))),
    ...lines(s).map(([text, tone]) => el("p", { class: "claude-line " + tone, text })),
    el("p", {}, el("b", { text: t("claude.show_title") }), " ", el("code", { text: s.shows })),
    el("div", { class: "row wrap" },
      el("button", { id: "claude-connect-btn", class: canConnect ? "sel" : "", disabled: !canConnect || busy || undefined,
        onclick: () => run("connect") }, t(found.some((x) => x.registered !== "no") ? "claude.update" : "claude.connect")),
      el("button", { id: "claude-disconnect-btn", disabled: !canDisconnect || busy || undefined, onclick: () => run("disconnect") }, t("claude.disconnect")),
      el("button", { onclick: () => load(true) }, t("claude.recheck"))),
    el("p", { class: "muted", text: t("claude.after") }));
}

async function run(what) {
  busy = true;
  render();
  const r = await attempt(() => api("POST", "/api/claude/" + what, {}));
  busy = false;
  if (r) {
    status = r.status;
    toast(r.changed.length ? t(what === "connect" ? "claude.connected" : "claude.disconnected") : t("claude.nothing"));
  }
  render();
}

async function load(fresh = false) {
  try {
    status = await get("/api/claude" + (fresh ? "?fresh=1" : ""));
  } catch {
    status = null;
  }
  render();
}

export function openClaude() {
  document.querySelector("#menu [data-page=setup]")?.click();
  setTimeout(() => $("#claude-connect")?.previousElementSibling?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
}

export function init() {
  onShow("setup", () => load(true));
}
