// MIDI page: live monitor, MIDI learn, the mapping table.
import { api, attempt, get, toast } from "../api.js";
import { $, el } from "../dom.js";
import { t } from "../i18n.js";
import { onCatalogue, onMidi, onState } from "../state.js";
import { onShow } from "../nav.js";

let channel = "";
let paused = false;

function addRows(rows) {
  const body = $("#monitor");
  for (const r of rows) {
    if (channel && String(r.channel) !== channel) continue;
    const ms = String(Math.floor((r.time * 1000) % 1000)).padStart(3, "0");
    const time = new Date(r.time * 1000).toLocaleTimeString("en-AU", { hour12: false }) + "." + ms;
    body.prepend(el("tr", {},
      el("td", { text: time }), el("td", { text: r.port }), el("td", { text: r.channel }), el("td", { text: r.type }),
      el("td", { text: r.number }), el("td", { text: r.value }),
      el("td", { class: r.result === "unmapped" ? "unmapped" : "hit", text: r.result })));
  }
  while (body.childElementCount > 300) body.lastChild.remove();
}

async function loadMap() {
  const m = await get("/api/midi/map");
  $("#map").replaceChildren(...m.mappings.map((x) => {
    const { type, channel: ch, number, action, port, address, ...p } = x;
    const extra = Object.entries(p).map(([k, v]) => `${k}=${v}`).join(" ");
    const input = type === "osc" ? `OSC ${address}` : type + (port ? ` [${port}]` : "");
    return el("tr", {}, el("td", { text: input }), el("td", { text: ch ?? "" }), el("td", { text: number ?? "" }),
      el("td", { text: `${action} ${extra}` }),
      el("td", {}, el("button", { onclick: async () => {
        if (await attempt(() => api("POST", "/api/midi/remove", { type, channel: ch, number, port, address }))) loadMap();
      } }, t("midi.remove"))));
  }));
}

function parseParams(text) {
  const params = {};
  for (const kv of text.split(/\s+/).filter(Boolean)) {
    const i = kv.indexOf("=");
    if (i < 1) throw new Error(t("midi.params_bad", { part: kv }));
    const k = kv.slice(0, i), v = kv.slice(i + 1);
    params[k] = k === "fixtures" ? v.split(",") : /^\d+(\.\d+)?$/.test(v) ? +v : v;
  }
  return params;
}

export function init() {
  const filter = $("#midi-filter");
  filter.replaceChildren(el("option", { value: "" }, t("midi.all_channels")),
    ...[...Array(16)].map((_, i) => el("option", { value: i + 1 }, t("midi.channel", { n: i + 1 }))));
  filter.onchange = (e) => { channel = e.target.value; $("#monitor").replaceChildren(); };
  $("#midi-pause").onclick = async () => {
    if (await attempt(() => api("POST", "/api/midi/pause", {}))) paused = !paused;
    $("#midi-pause").classList.toggle("sel", paused);
    $("#midi-pause").textContent = t(paused ? "midi.resume" : "midi.pause");
  };
  $("#midi-clear").onclick = () => { attempt(() => api("POST", "/api/midi/clear", {})); $("#monitor").replaceChildren(); };
  $("#learn-go").onclick = () => {
    let params;
    try {
      params = parseParams($("#learn-params").value);
    } catch (e) {
      return toast(e.message, true);
    }
    attempt(() => api("POST", "/api/midi/learn", { action: $("#learn-action").value, params }));
  };
  $("#learn-cancel").onclick = () => attempt(() => api("POST", "/api/midi/cancel", {}));
  $("#map-save").onclick = () => attempt(() => api("POST", "/api/midi/save", {}), (r) => t("midi.saved", { name: r.saved }));
  onCatalogue((cat) => $("#learn-action").replaceChildren(...cat.actions.map((a) => el("option", { value: a }, a))));
  onMidi(addRows);
  onState((s) => ($("#learn-state").textContent = s.learning ? t("midi.learning", { action: s.learning }) : ""));
  onShow("midi", loadMap);
}
