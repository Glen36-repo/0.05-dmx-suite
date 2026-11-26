// Always on screen: what's playing, MASTER, blackout, gig lock, the status strip and alerts.
import { api, attempt, cmd } from "../api.js";
import { $, el } from "../dom.js";
import { t } from "../i18n.js";
import { live, onConnection, onState } from "../state.js";

let lastAlert = 0;
let lastBadDevices = null;
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

function render(s) {
  $("#now").textContent = s.describe;
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
      el("div", { class: "tile", title: `${d.name}: ${d.detail}` },
        el("span", { class: `dot ${d.state}${d.active ? " active" : ""}`, "aria-label": d.state }),
        el("span", { text: d.name }),
        el("span", { class: "muted", text: d.state === "ok" && d.kind !== "claude" ? short(d) : d.detail }))),
    ...nodes.map((n, i) =>
      el("div", { class: "tile" + (i === 0 ? " sep" : ""), title: n.mac },
        el("span", { class: "dot " + n.state, "aria-label": n.state }), el("span", { text: n.name || n.mac }),
        el("span", { class: "muted", text: n.rssi != null ? `${n.rssi} dBm` : n.state }))));

  // red banner + beep when something drops out
  const badNodes = nodes.filter((n) => n.state === "offline" || n.state === "weak");
  const badDev = s.devices.filter((d) => d.state === "bad");
  const banner = $("#banner");
  if (badNodes.length || badDev.length) {
    banner.textContent = [...badDev.map((d) => `${d.name}: ${d.detail}`),
      ...badNodes.map((n) => `${n.name || n.mac} ${n.state.toUpperCase()}`)].join(" · ");
    banner.classList.remove("hidden");
  } else banner.classList.add("hidden");
  const latest = s.alerts[s.alerts.length - 1];
  if (latest && latest.time > lastAlert) {
    if (lastAlert) beep();
    lastAlert = latest.time;
  }
  const badKeys = badDev.map((d) => d.name).join("|");
  if (lastBadDevices !== null && badKeys && badKeys !== lastBadDevices) beep();
  lastBadDevices = badKeys;
}

export function init() {
  $("#master").onclick = () => cmd("master");
  $("#blackout").onclick = () => cmd("blackout");
  $("#giglock").onclick = () => attempt(() => api("POST", "/api/giglock", { on: !live.state.gig_lock }));
  onState(render);
  onConnection((ok) => {
    document.body.classList.toggle("offline", !ok);
    if (!ok) $("#now").textContent = t("status.lost");
  });
}
