// Always on screen: what's playing, MASTER, blackout, gig lock, the status strip and alerts.
import { api, attempt, cmd } from "../api.js";
import { $, el } from "../dom.js";
import { t } from "../i18n.js";
import { openClaude } from "./claude.js";
import { live, onConnection, onState } from "../state.js";

let lastNewBanner = null;
let audio;

function beep() {
  try {
    audio = audio || new AudioContext();
    const o = audio.createOscillator();
    const g = audio.createGain();
    o.frequency.value = 880;
    g.gain.value = 0.2;
    o.connect(g).connect(audio.destination);
    o.start();
    o.stop(audio.currentTime + 0.35);
  } catch {}
}

let lastBeat = null;

function renderTempo(tp) {
  const box = $("#tempo");
  if (!tp) return box.classList.add("hidden");
  box.classList.remove("hidden");
  const speed = tp.speed !== 1 ? ` ×${tp.speed.toFixed(2)}` : "";
  $("#tempo-text").textContent = tp.bpm
    ? t("top.tempo", { bpm: Math.round(tp.bpm), source: t("tempo." + tp.source) }) + speed
    : t(tp.lost ? "top.tempo_lost" : "top.tempo_timers") + speed;
  if (tp.bpm && tp.beat !== lastBeat) { // pulse on each beat
    box.classList.remove("pulse");
    void box.offsetWidth;
    box.classList.add("pulse");
  }
  lastBeat = tp.beat;
}

function render(s) {
  $("#now").textContent = s.describe;
  renderTempo(s.tempo);
  const gated = !s.profile || s.profile.master_gate;
  $("#master").classList.toggle("hidden", !gated); // no MASTER on/off under the generic profile
  $("#master").classList.toggle("on", s.master);
  $("#master").setAttribute("aria-pressed", s.master);
  $("#blackout").classList.toggle("on", s.blackout);
  $("#blackout").setAttribute("aria-pressed", s.blackout);
  const lock = $("#giglock");
  lock.classList.toggle("on", s.gig_lock);
  lock.textContent = t(s.gig_lock ? "top.giglock_on" : "top.giglock");

  // status strip: engine, outputs, MIDI, Claude, screens, then every node/receiver
  const nodes = s.nodes.filter((n) => n.mac);
  const short = (d) => (d.kind === "output" || d.kind === "midi" ? d.detail.split(" · ")[0] : d.detail);
  $("#health").replaceChildren(
    ...s.devices.map((d) =>
      el("div", { class: "tile" + (d.kind === "claude" ? " link" : ""), title: `${d.name}: ${d.detail}`, "data-key": `${d.kind}:${d.name}`,
        onclick: d.kind === "claude" ? openClaude : undefined },
        el("span", { class: `dot ${d.state}${d.active ? " active" : ""}`, "aria-label": d.state }),
        el("span", { text: d.name }),
        el("span", { class: "muted", text: d.state === "ok" && d.kind !== "claude" ? short(d) : d.detail }))),
    ...nodes.map((n, i) =>
      el("div", { class: "tile" + (i === 0 ? " sep" : ""), title: n.mac, "data-key": `node:${n.name || n.mac}` },
        el("span", { class: "dot " + n.state, "aria-label": n.state }), el("span", { text: n.name || n.mac }),
        el("span", { class: "muted", text: n.rssi != null ? `${n.rssi} dBm` : n.state }))));

  renderAlerts(s.alert_center);
}

// ---------------------------------------------------------------- alerts and banners (v3.1)

const ago = (sec) => (sec < 90 ? t("alerts.secs", { n: Math.round(sec) }) : t("alerts.mins", { n: Math.round(sec / 60) }));

function alertAction(action, id, extra = {}) {
  return attempt(() => api("POST", "/api/alerts", { action, id, ...extra }));
}

function renderAlerts(ac) {
  if (!ac) return;
  // banners overlay the top of the page, just under the status strip: controls never move under a finger
  $("#banners").style.top = Math.round($("#health").getBoundingClientRect().bottom) + "px";
  $("#banners").replaceChildren(...ac.banners.map((b) => el("div", { class: `banner ${b.severity}`, role: "alert", "data-alert": b.id },
    el("span", { class: "msg", text: `${b.device}: ${b.message}` }),
    ...(b.severity === "critical"
      ? [el("button", { class: "x", title: t("alerts.minimise"), onclick: () => alertAction("minimise", b.id) }, "–")]
      : [el("button", { class: "snooze", title: t("alerts.snooze"), onclick: () => alertAction("snooze", b.id, { for: "10min" }) }, t("alerts.snooze_10")),
        el("button", { class: "x", title: t("alerts.dismiss"), onclick: () => alertAction("dismiss", b.id) }, "✕")]))));
  const bell = $("#bell");
  bell.classList.toggle("on", ac.count > 0);
  bell.classList.toggle("critical", ac.critical);
  $("#bell-count").textContent = ac.count || "";
  if (lastNewBanner !== null && ac.new_at > lastNewBanner) beep();
  lastNewBanner = ac.new_at;
  const now = Date.now() / 1000;
  $("#alerts-quiet").checked = ac.quiet;
  $("#alerts-list").replaceChildren(...ac.list.map((a) => el("li", { class: `alert-row ${a.state} ${a.severity}`, "data-alert": a.id },
    el("span", { class: "dot " + (a.state === "cleared" ? "ok" : a.severity === "info" ? "warn" : "bad") }),
    el("b", { text: a.device }), el("span", { text: a.message }),
    el("span", { class: "muted", text: `${t("alerts.state_" + a.state)} · ${ago(now - a.changed)}` }),
    el("span", { class: "grow" }),
    ...(a.state !== "cleared" && a.severity !== "critical" ? [
      el("button", { class: "mini", onclick: () => alertAction("snooze", a.id, { for: "1h" }) }, t("alerts.snooze_1h")),
      el("button", { class: "mini", onclick: () => alertAction("snooze", a.id, { for: "gig" }) }, t("alerts.snooze_gig"))] : []),
    ...(a.severity !== "critical" ? [el("button", { class: "mini", onclick: () => alertAction("mute", a.id, { on: !ac.muted.includes(a.id) }) },
      t(ac.muted.includes(a.id) ? "alerts.unmute" : "alerts.mute"))] : []))));
  // muted devices show greyed in the status strip
  for (const tile of document.querySelectorAll("#health .tile[data-key]")) tile.classList.toggle("muted-dev", ac.muted.includes(tile.dataset.key));
}

export function init() {
  $("#master").onclick = () => cmd("master");
  $("#blackout").onclick = () => cmd("blackout");
  $("#giglock").onclick = () => attempt(() => api("POST", "/api/giglock", { on: !live.state.gig_lock }));
  $("#bell").onclick = () => $("#alerts-panel").classList.toggle("hidden");
  $("#alerts-close").onclick = () => $("#alerts-panel").classList.add("hidden");
  $("#alerts-quiet").onchange = (e) => alertAction("quiet", "", { on: e.target.checked });
  onState(render);
  onConnection((ok) => {
    document.body.classList.toggle("offline", !ok);
    if (!ok) $("#now").textContent = t("status.lost");
  });
}
