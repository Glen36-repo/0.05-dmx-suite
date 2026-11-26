// Talking to the engine: reads, writes (with the access token), control commands, messages.
import { $ } from "./dom.js";
import { t } from "./i18n.js";

const TOKEN = document.querySelector('meta[name="dmx-token"]').content;

export async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json", "X-DMX-Token": TOKEN },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

export const get = (path) => fetch(path).then((r) => r.json());

export async function cmd(name, args = {}) {
  try {
    const r = await api("POST", "/api/control", { cmd: name, ...args });
    if (r.bpm) toast(t("live.bpm", { bpm: Math.round(r.bpm) }));
    return r;
  } catch (e) {
    toast(e.message, true);
  }
}

// Run a write; show the error rather than throwing.
export async function attempt(fn, okMessage) {
  try {
    const r = await fn();
    if (okMessage) toast(typeof okMessage === "function" ? okMessage(r) : okMessage);
    return r;
  } catch (e) {
    toast(e.message, true);
    return undefined;
  }
}

let toastTimer;
export function toast(msg, err = false) {
  const box = $("#toast");
  box.textContent = msg;
  box.className = "toast" + (err ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => box.classList.add("hidden"), err ? 6000 : 2500);
}
