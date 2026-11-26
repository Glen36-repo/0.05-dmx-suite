// MIDI page: named inputs and devices (v3.1), live monitor, MIDI learn, the mapping table.
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
      el("td", { class: "input-name", text: r.input || "" }),
      el("td", { class: r.result === "unmapped" ? "unmapped" : "hit", text: r.result })));
  }
  while (body.childElementCount > 300) body.lastChild.remove();
}

async function loadMap() {
  const [m, ins] = await Promise.all([get("/api/midi/map"), get("/api/inputs")]);
  inputs = ins;
  const byId = Object.fromEntries(ins.inputs.map((i) => [i.id, i]));
  $("#map").replaceChildren(...m.mappings.map((x) => {
    const { type, channel: ch, number, action, port, address, input, ...p } = x;
    const extra = Object.entries(p).map(([k, v]) => `${k}=${v}`).join(" ");
    const named = input ? byId[input] : null;
    const what = input ? (named ? named.name : input) : type === "osc" ? `OSC ${address}` : type + (port ? ` [${port}]` : "");
    const msg = input ? (named ? named.describe : t("midi.no_input")) : "";
    return el("tr", {}, el("td", { text: what }), el("td", { class: "muted", text: msg || (ch ?? "") }), el("td", { text: number ?? "" }),
      el("td", { text: `${action} ${extra}` }),
      el("td", {}, el("button", { onclick: async () => {
        if (!confirm(t("midi.confirm_remove"))) return;
        const body = input ? { type: "input", input } : { type, channel: ch, number, port, address };
        if (await attempt(() => api("POST", "/api/midi/remove", body))) loadMap();
      } }, t("midi.remove"))));
  }));
  renderInputs();
}

// ---------------------------------------------------------------- named inputs and devices (v3.1)

let inputs = { devices: [], inputs: [], profiles: [] };
const ROLES = ["kick", "snare", "tom", "cymbal", "count_in", "activity"];
const NAME = /^[a-z0-9][a-z0-9_-]{0,39}$/;

function renderInputs() {
  const byId = Object.fromEntries(inputs.inputs.map((i) => [i.id, i]));
  $("#inputs").replaceChildren(...inputs.devices.map((d) => el("div", { class: "device", "data-device": d.id },
    el("div", { class: "row wrap" }, el("b", { text: d.name }), el("span", { class: "muted", text: d.id }),
      ...(d.port ? [el("span", { class: "chip", text: d.port })] : []),
      ...(d.channel ? [el("span", { class: "chip", text: t("midi.channel", { n: d.channel }) })] : []),
      el("span", { class: "grow" }),
      el("button", { onclick: () => newInput(d.id) }, t("midi.add_input")),
      el("button", { onclick: () => attempt(() => api("POST", "/api/store/device", { action: "export", device: d.id }), t("midi.device_exported")) }, t("midi.export_device")),
      el("button", { class: "danger-text", onclick: async () => {
        if (confirm(t("midi.confirm_delete_device", { name: d.name }))) await attempt(() => api("POST", "/api/store/device", { action: "delete", device: d.id }), t("midi.deleted")).then(reload);
      } }, "✕")),
    el("table", { class: "map inputs" }, el("tbody", {}, ...d.inputs.map((iid) => inputRow(byId[iid])))))));
  $("#profile-pick").replaceChildren(el("option", { value: "" }, t("midi.load_profile")),
    ...inputs.profiles.map((p) => el("option", { value: p.id }, `${p.name} (${p.inputs})`)));
}

function inputRow(i) {
  if (!i) return null;
  return el("tr", { "data-input": i.id },
    el("td", {}, el("span", { class: "dot inline", style: i.colour ? `background:${i.colour}` : "" }), el("b", { text: i.name })),
    el("td", { class: "muted", text: i.id }),
    el("td", { text: i.describe }),
    el("td", {}, ...i.roles.map((r) => el("span", { class: "chip", text: t("midi.role_" + r) }))),
    el("td", { class: "muted mapped", text: i.mapped || "", title: i.mapped || "" }),
    el("td", { class: "tools" },
      el("button", { onclick: () => attempt(() => api("POST", "/api/midi/learn_input", { input: i.id }), (r) => r.message) }, t("midi.learn_input")),
      ...(i.type === "note" ? [el("button", { onclick: () => attempt(() => api("POST", "/api/midi/learn_input", { input: i.id, add: true }), (r) => r.message) }, t("midi.add_note"))] : []),
      el("button", { onclick: () => editInput(i) }, t("midi.edit")),
      ...(i.type === "note" ? [el("button", { onclick: () => calibrate(i) }, t("midi.calibrate"))] : []),
      el("button", { class: "danger-text", onclick: async () => {
        const used = (await get(`/api/inputs/used/${encodeURIComponent(i.id)}`)).used;
        if (used.length) return toast(t("midi.input_used", { name: i.name, where: used.join(", ") }), true);
        if (confirm(t("midi.confirm_delete_input", { name: i.name }))) await attempt(() => api("POST", "/api/store/input", { action: "delete", name: i.id }), t("midi.deleted")).then(reload);
      } }, "✕")));
}

async function reload(r) {
  if (r) await loadMap();
  return r;
}

function newInput(device) {
  const id = prompt(t("midi.new_input_id"));
  if (!id) return;
  if (!NAME.test(id)) return toast(t("midi.bad_id"), true);
  editInput({ id, name: id, device, type: "note", notes: [], roles: [] }, true);
}

function editInput(i, isNew = false) {
  const box = $("#input-edit");
  const name = el("input", { value: i.name || "", placeholder: t("midi.input_name") });
  const type = el("select", {}, ...["note", "program_change", "control_change", "osc"].map((x) => el("option", { value: x, selected: x === i.type || undefined }, t("midi.type_" + x))));
  const nums = el("input", { value: (i.notes || i.numbers || (i.number !== undefined ? [i.number] : [])).join(", "), placeholder: t("midi.numbers") });
  const address = el("input", { value: i.address || "", placeholder: "/osc/address" });
  const channel = el("input", { value: i.channel ?? "", placeholder: t("midi.channel_any"), class: "narrow" });
  const roles = ROLES.map((r) => el("label", { class: "chip" }, el("input", { type: "checkbox", value: r, checked: (i.roles || []).includes(r) || undefined }), t("midi.role_" + r)));
  const shared = el("input", { type: "checkbox", checked: i.shared || undefined });
  const colour = el("input", { type: "color", value: i.colour || "#808080" });
  const save = async () => {
    const v = { name: name.value.trim() || i.id, type: type.value };
    if (type.value === "osc") v.address = address.value.trim();
    else {
      const list = nums.value.split(/[\s,]+/).filter(Boolean).map(Number);
      if (type.value === "note") v.notes = list; else v.number = list[0];
      if (channel.value.trim()) v.channel = channel.value.trim() === "any" ? "any" : +channel.value;
    }
    const rs = roles.map((l) => $("input", l)).filter((x) => x.checked).map((x) => x.value);
    if (rs.length) v.roles = rs;
    if (shared.checked) v.shared = true;
    if (colour.value !== "#808080") v.colour = colour.value;
    if (i.curve) v.curve = i.curve;
    if (i.velocity && (i.velocity[0] !== 0 || i.velocity[1] !== 127)) v.velocity = i.velocity;
    if (i.port && i.port !== (inputs.devices.find((d) => d.id === i.device) || {}).port) v.port = i.port;
    const r = await attempt(() => api("POST", "/api/store/input", { action: "put", device: i.device, name: i.id, value: v }), t("midi.input_saved", { name: v.name }));
    if (r) { box.replaceChildren(); reload(r); }
  };
  box.replaceChildren(el("div", { class: "card" },
    el("b", { text: isNew ? t("midi.new_input") : i.id }),
    el("div", { class: "row wrap" }, name, type, nums, address, channel, colour),
    el("div", { class: "row wrap" }, ...roles, el("label", { class: "chip" }, shared, t("midi.shared"))),
    el("div", { class: "row" }, el("button", { class: "sel", onclick: save }, t("midi.save_input")), el("button", { onclick: () => box.replaceChildren() }, t("wheel.cancel")))));
}

async function calibrate(i) {
  const box = $("#input-edit");
  const step = (level) => el("button", { onclick: async () => {
    if (!(await attempt(() => api("POST", "/api/midi/calibrate", { input: i.id, level, step: "start" })))) return;
    box.replaceChildren(el("div", { class: "card" }, el("b", { text: t("midi.calibrate_play", { name: i.name, level: t("midi.level_" + level) }) }),
      el("div", { class: "row" },
        el("button", { class: "sel", onclick: async () => {
          const r = await attempt(() => api("POST", "/api/midi/calibrate", { input: i.id, level, step: "done" }), (x) => t("midi.calibrated", { v: x.velocity, n: x.hits }));
          if (r) { i.curve = r.curve; calibrate(i); reload(r); }
        } }, t("midi.calibrate_done")),
        el("button", { onclick: () => { api("POST", "/api/midi/calibrate", { input: i.id, level, step: "cancel" }); box.replaceChildren(); } }, t("wheel.cancel")))));
  } }, t("midi.level_" + level) + (i.curve?.[level] ? ` (${i.curve[level]})` : ""));
  box.replaceChildren(el("div", { class: "card" }, el("b", { text: t("midi.calibrate_title", { name: i.name }) }),
    el("p", { class: "muted", text: t("midi.calibrate_help") }),
    el("div", { class: "row" }, step("quiet"), step("normal"), step("loud"), el("button", { onclick: () => box.replaceChildren() }, t("wheel.cancel")))));
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
  $("#map-save").onclick = () => attempt(() => api("POST", "/api/midi/save", {}), (r) => t("midi.saved", { name: r.saved })).then((r) => r && loadMap());
  $("#device-new").onclick = async () => {
    const id = $("#device-new-id").value.trim();
    if (!NAME.test(id)) return toast(t("midi.bad_id"), true);
    await attempt(() => api("POST", "/api/store/device", { action: "put", device: id, value: { name: id.replace(/_/g, " "), inputs: {} } }), t("midi.device_added")).then(reload);
  };
  $("#profile-pick").onchange = async (e) => {
    const id = e.target.value;
    if (!id) return;
    const as = prompt(t("midi.profile_as"), id);
    if (as && NAME.test(as)) await attempt(() => api("POST", "/api/store/device", { action: "load", profile: id, as }), t("midi.device_added")).then(reload);
    e.target.value = "";
  };
  onCatalogue((cat) => $("#learn-action").replaceChildren(...cat.actions.map((a) => el("option", { value: a }, a))));
  onMidi(addRows);
  let wasLearning = null;
  onState((s) => {
    $("#learn-state").textContent = s.learning ? t("midi.learning", { action: s.learning }) : "";
    if (wasLearning && wasLearning.startsWith("input ") && !s.learning) setTimeout(loadMap, 300); // the input changed
    wasLearning = s.learning;
  });
  onShow("midi", loadMap);
}
