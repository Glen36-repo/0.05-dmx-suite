// Always on screen: what's playing, MASTER, blackout, gig lock, the status strip and alerts.
import { api, attempt, cmd } from "../api.js";
import { $, el } from "../dom.js";
import { t } from "../i18n.js";
import { go } from "../nav.js";
import { openClaude } from "./claude.js";
import { focusPane, openFaultFind } from "./monitor.js";

// status bar tiles that open a Monitor pane (v4)
const PANE = { output: "dmx", routing: "dmx", device: "dmx", midi: "midi-in", device_new: "midi-in", dmx_check: "dmx", test: "test" };
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

// The header: what's playing, short (the tempo has its own box on the right, so it isn't repeated here)
function nowText(s) {
  const n = s.now;
  if (!n) return s.describe;
  const parts = [n.label === "static look" ? t("top.static_look") : n.label];
  if (n.mode === "show" && n.step) {
    parts.push(t("top.now_step", { n: n.step, scene: n.scene || "" }) + (n.time_left_s != null ? ` · ${t("top.now_left", { s: Math.round(n.time_left_s) })}` : ""));
  }
  if (n.setlist && n.song != null) parts.push(t("top.now_song", { n: n.song + 1, name: n.song_name || "" }));
  return parts.join("  ·  ");
}

function render(s) {
  $("#now").textContent = nowText(s);
  $("#now").title = s.describe; // the full line on hover
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
      el("div", { class: "tile" + (d.kind === "claude" || PANE[d.kind] ? " link" : ""),
        title: `${d.name}: ${d.detail}` + (d.model ? ` (${d.model})` : ""), "data-key": `${d.kind}:${d.name}`,
        onclick: d.kind === "claude" ? openClaude : PANE[d.kind] ? () => {
          go("monitor");
          focusPane(PANE[d.kind]);
          // v5: a red / amber DMX badge opens the "Rig not responding" wizard
          if ((d.kind === "output" || d.kind === "dmx_check") && (d.state === "bad" || d.state === "warn")) openFaultFind();
        } : undefined },
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

// Draw the banners and the bell's list only when something in them changes: the state comes in ~10
// times a second, and redrawing every time swapped the button out from under a press, so ✕ never
// fired. A press acts at once on the server's reply rather than the next state push.
let bannerSig = "";
let listSig = "";
let shown = null; // the alerts view last drawn

async function alertAction(action, id, extra = {}) {
  if (action !== "quiet" && action !== "mute") $(`#banners [data-alert="${CSS.escape(id)}"]`)?.remove();
  bannerSig = ""; // whatever happens, draw the reply (or the next state) afresh
  const r = await attempt(() => api("POST", "/api/alerts", { action, id, ...extra }));
  if (r) renderAlerts(r);
  return r;
}

function renderAlerts(ac) {
  if (!ac) return;
  shown = ac;
  // banners overlay the top of the page, just under the status strip: controls never move under a finger
  $("#banners").style.top = Math.round($("#health").getBoundingClientRect().bottom) + "px";
  const bSig = JSON.stringify(ac.banners.map((b) => [b.id, b.severity, b.device, b.message]));
  if (bSig !== bannerSig) {
    bannerSig = bSig;
    $("#banners").replaceChildren(...ac.banners.map((b) => el("div", { class: `banner ${b.severity}`, role: "alert", "data-alert": b.id },
      el("span", { class: "msg", text: `${b.device}: ${b.message}` }),
      ...(b.severity === "critical"
        ? [el("button", { class: "x", title: t("alerts.minimise"), onclick: () => alertAction("minimise", b.id) }, "–")]
        : [el("button", { class: "snooze", title: t("alerts.snooze"), onclick: () => alertAction("snooze", b.id, { for: "10min" }) }, t("alerts.snooze_10")),
          el("button", { class: "x", title: t("alerts.dismiss"), onclick: () => alertAction("dismiss", b.id) }, "✕")]))));
  }
  const bell = $("#bell");
  bell.classList.toggle("on", ac.count > 0);
  bell.classList.toggle("critical", ac.critical);
  $("#bell-count").textContent = ac.count || "";
  if (lastNewBanner !== null && ac.new_at > lastNewBanner) beep();
  lastNewBanner = ac.new_at;
  const now = Date.now() / 1000;
  $("#alerts-quiet").checked = ac.quiet;
  const lSig = JSON.stringify([ac.list.map((a) => [a.id, a.state, a.severity, a.device, a.message]), ac.muted]);
  if (lSig !== listSig) {
    listSig = lSig;
    $("#alerts-list").replaceChildren(...ac.list.map((a) => el("li", { class: `alert-row ${a.state} ${a.severity}`, "data-alert": a.id },
      el("span", { class: "dot " + (a.state === "cleared" ? "ok" : a.severity === "info" ? "warn" : "bad") }),
      el("b", { text: a.device }), el("span", { text: a.message }),
      el("span", { class: "muted when" }),
      el("span", { class: "grow" }),
      ...(a.state !== "cleared" && a.severity !== "critical" ? [
        el("button", { class: "mini", onclick: () => alertAction("snooze", a.id, { for: "1h" }) }, t("alerts.snooze_1h")),
        el("button", { class: "mini", onclick: () => alertAction("snooze", a.id, { for: "gig" }) }, t("alerts.snooze_gig"))] : []),
      ...(a.severity !== "critical" ? [el("button", { class: "mini", onclick: () => alertAction("mute", a.id, { on: !shown.muted.includes(a.id) }) },
        t(ac.muted.includes(a.id) ? "alerts.unmute" : "alerts.mute"))] : []))));
  }
  // the "x s ago" text changes every tick: update it in place
  for (const a of ac.list) {
    const when = $(`#alerts-list [data-alert="${CSS.escape(a.id)}"] .when`);
    if (when) when.textContent = `${t("alerts.state_" + a.state)} · ${ago(now - a.changed)}`;
  }
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
