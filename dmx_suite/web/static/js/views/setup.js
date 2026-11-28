// Setup page: find a light, channel tester, devices, nodes, addresses, theme, update check.
import { api, attempt, cmd, get, toast } from "../api.js";
import { $, $$, el } from "../dom.js";
import { t } from "../i18n.js";
import { onShow } from "../nav.js";
import { live, onCatalogue, onState } from "../state.js";

// ---------------------------------------------------------------- devices plugged in (v4)

let foundKey = "";

export async function loadFound(force = false) {
  let v;
  try { v = await get("/api/devices/list"); } catch { return; }
  const key = JSON.stringify(v);
  if (key === foundKey && !force) return;
  foundKey = key;
  const useCell = (d) => {
    if (d.kind === "serial") {
      return el("select", { "data-use": d.id },
        el("option", { value: "", selected: !d.use }, t("setup.use_none")),
        ...[...Array(16).keys()].map((u) => el("option", { value: u, selected: d.use?.universe === u }, t("setup.use_universe", { u }))));
    }
    return el("label", { class: "check" }, el("input", { type: "checkbox", "data-use": d.id, checked: !!d.use }),
      t(d.kind === "midi_in" ? "setup.use_midi_in" : "setup.use_midi_out"));
  };
  $("#found").replaceChildren(...(v.scanning ? v.devices : []).map((d) => {
    const alias = el("input", { value: d.alias || "", placeholder: d.name, "data-alias": d.id, class: "mini" });
    const use = useCell(d);
    const save = el("button", { class: "mini", onclick: async () => {
      const u = use.querySelector ? use.querySelector("input") : null;
      const body = { id: d.id, alias: alias.value.trim() || null };
      if (d.kind === "serial") { body.use = use.value !== ""; if (body.use) body.universe = +use.value; }
      else body.use = (u || use).checked;
      if (await attempt(() => api("POST", "/api/devices/set", body), t("setup.device_saved", { name: body.alias || d.name }))) loadFound(true);
    } }, t("common.save"));
    return el("tr", { "data-device": d.id },
      el("td", { text: d.name, title: [d.product, d.manufacturer, d.vid_pid, d.port].filter(Boolean).join(" · ") }),
      el("td", { class: "muted", text: d.id + (d.stable ? "" : ` (${t("setup.unstable")})`) }),
      el("td", {}, alias), el("td", {}, use), el("td", {}, save));
  }));
  if (!v.scanning) $("#found").replaceChildren(el("tr", {}, el("td", { colspan: 5, class: "muted", text: t("setup.no_scan") })));
  // a missing device: pick a plugged-in one of the same sort to take over (works under gig lock)
  const sameSort = (m) => v.devices.filter((d) => (m.midi_in ? d.kind === "midi_in" : m.midi_out ? d.kind === "midi_out" : d.kind === "serial"));
  $("#found-missing").replaceChildren(...v.missing.map((m) => {
    const pick = el("select", { "data-replace": m.device }, el("option", { value: "" }, t("setup.use_instead")),
      ...sameSort(m).map((d) => el("option", { value: d.id }, d.alias ? `${d.alias} (${d.name})` : d.name)));
    pick.onchange = async () => {
      if (pick.value && await attempt(() => api("POST", "/api/devices/replace", { missing: m.device, use: pick.value }),
        t("setup.replaced_device", { name: m.alias || m.label }))) loadFound(true);
    };
    return el("li", { "data-missing": m.device }, t("setup.missing", { name: m.alias || m.label, label: m.label }), " ", pick);
  }));
}

async function nodeAction(n) {
  if (n.name) return attempt(() => api("POST", "/api/nodes/identify", { mac: n.mac }), t("setup.identifying", { name: n.name }));
  const name = prompt(t("setup.node_name_prompt", { mac: n.mac }));
  if (!name) return;
  const universe = prompt(t("setup.node_universe_prompt"), "0");
  toast(t("setup.naming"));
  attempt(() => api("POST", "/api/nodes/assign", { mac: n.mac, name, universe: +universe || 0 }),
    (r) => t(r.confirmed ? "setup.named" : "setup.named_unconfirmed", { name }));
}

// a dead node or receiver, and a spare switched on: the spare takes its name and universe
async function replaceNode(n, spares) {
  const pick = spares.length === 1 ? spares[0].mac : prompt(t("setup.replace_pick", { macs: spares.map((s) => s.mac).join(", ") }), spares[0].mac);
  if (!pick || !confirm(t("setup.replace_confirm", { name: n.name, mac: pick }))) return;
  toast(t("setup.naming"));
  attempt(() => api("POST", "/api/nodes/replace", { old: n.mac, new: pick }),
    (r) => t(r.confirmed ? "setup.replaced" : "setup.replaced_unconfirmed", { name: r.name }));
}

function render(s) {
  $$("#find [data-find]").forEach((b) => b.classList.toggle("sel", s.setup.find === b.dataset.find));
  $("#devices").replaceChildren(...s.devices.map((d) => el("tr", {},
    el("td", { text: d.name }), el("td", { text: d.kind }),
    el("td", {}, el("span", { class: "dot inline " + d.state }), d.state), el("td", { text: d.detail }))));
  // rebuilt only when something changed, so a button isn't swapped out under a finger
  const spares = s.nodes.filter((n) => n.mac && n.state === "new");
  const key = JSON.stringify([s.node_setup?.at, s.nodes.map((n) => [n.mac, n.name, n.state, n.rssi, n.loss_pct, Math.round((n.last_data_age_ms || 0) / 500)])]);
  const nodes = $("#nodes");
  if (nodes.dataset.key === key) return;
  nodes.dataset.key = key;
  nodes.replaceChildren(...s.nodes.map((n) => el("tr", {},
    el("td", { text: n.name || t("setup.new_node") }), el("td", { text: n.mac || n.driver?.driver || "" }), el("td", { text: n.state }),
    el("td", { text: n.rssi != null ? n.rssi + " dBm" : "-" }), el("td", { text: n.loss_pct != null ? n.loss_pct + "%" : "-" }),
    el("td", { text: n.last_data_age_ms != null ? n.last_data_age_ms + " ms" : "-" }),
    el("td", {}, n.mac ? el("button", { onclick: () => nodeAction(n) }, t(n.name ? "setup.identify" : "setup.name_node")) : "",
      n.mac && n.name && n.state === "offline" && spares.length ? el("button", { onclick: () => replaceNode(n, spares) }, t("setup.replace")) : ""))));
  const setup = s.node_setup || {};
  $("#node-setup").textContent = setup.at ? t("setup.node_setup", { fw: setup.fw || "?", n: Object.keys(setup.fallbacks || {}).length }) : "";
}

// ---------------------------------------------------------------- access (PIN, phones)

let access = null;

function renderAccess(a) {
  access = a;
  const bits = [t(a.pin_set ? "access.pin_is_set" : "access.no_pin"), t(a.lan ? "access.lan_on" : "access.lan_off")];
  if (a.sessions) bits.push(t("access.sessions", { n: a.sessions }));
  $("#access-state").textContent = bits.join(" · ");
  $("#pin-old").classList.toggle("hidden", !a.pin_set);
  $("#pin-clear").classList.toggle("hidden", !a.pin_set);
  $("#access-lan").checked = a.lan;
  $("#access-lan").disabled = !a.pin_set || !a.local;
  $("#access-local").checked = a.pin_local;
  $("#access-local").disabled = !a.pin_set || !a.local;
  $("#access-hours").value = a.session_hours;
  for (const id of ["#pin-old", "#pin-new", "#pin-set", "#pin-clear", "#access-hours"]) $(id).disabled = !a.local;
  $("#lan-info").classList.toggle("hidden", !a.lan);
  const qr = $("#lan-qr");
  qr.replaceChildren();
  if (a.qr) qr.append(new DOMParser().parseFromString(a.qr, "image/svg+xml").documentElement);
  $("#lan-urls").replaceChildren(...a.urls.map((u) => el("li", {}, el("code", { text: u }))));
  $("#logout").classList.toggle("hidden", a.local && !a.pin_local);
}

async function loadAccess() {
  const a = await get("/api/access");
  if (!a.error) renderAccess(a);
}

async function changeAccess(body, ok) {
  const r = await attempt(() => api("POST", "/api/access", body), ok);
  if (r) renderAccess(r);
  else loadAccess();
  return r;
}

async function loadAddresses() {
  const a = await get("/api/addresses");
  $("#addr").replaceChildren(...a.rows.map((r) => el("tr", {},
    el("td", { text: r.id }), el("td", { text: r.type }), el("td", { text: r.universe }), el("td", { text: r.start }), el("td", { text: r.end }),
    el("td", { text: r.in_rig ? t("common.yes") : "-" }), el("td", { text: r.verified ? t("common.yes") : t("setup.not_checked") }))));
  $("#addrnotes").textContent = a.notes.join(" · ");
}

async function loadThemes() {
  const s = await get("/api/settings");
  $("#theme").replaceChildren(...Object.entries(s.themes).map(([k, v]) =>
    el("option", { value: k, selected: k === s.settings.theme }, v.name)));
  $("#density").value = s.settings.density || "compact";
}

export function init() {
  const chan = $("#chan"), val = $("#chanval");
  val.addEventListener("input", () => {
    $("#chanshow").textContent = val.value;
    if (chan.value) cmd("chan", { channel: +chan.value, value: +val.value, universe: +$("#chanuni").value });
  });
  $("#chan-off").onclick = () => chan.value && cmd("chan", { channel: +chan.value, value: null, universe: +$("#chanuni").value });
  $("#theme").onchange = async (e) => {
    if (await attempt(() => api("POST", "/api/settings", { theme: e.target.value }))) location.reload();
  };
  $("#density").onchange = async (e) => {
    const d = e.target.value;
    if (await attempt(() => api("POST", "/api/settings", { density: d }))) {
      document.body.classList.remove("density-compact", "density-comfortable");
      document.body.classList.add(`density-${d}`);
    }
  };
  $("#update-check").onclick = async () => {
    $("#update-result").textContent = t("setup.checking");
    const r = await get("/api/update");
    const out = $("#update-result");
    out.replaceChildren(r.message);
    if (r.newer && r.url) out.append(" ", el("a", { href: r.url, target: "_blank", rel: "noopener" }, t("setup.release_page")));
  };
  onCatalogue((cat) => $("#find").replaceChildren(...cat.fixtures.filter((x) => x.kind !== "haze").map((x) =>
    el("button", { "data-find": x.id, onclick: () => cmd("find", { fixture: live.state.setup.find === x.id ? null : x.id }) }, x.id))));
  $("#pin-set").onclick = async () => {
    const r = await changeAccess({ action: "set_pin", pin: $("#pin-new").value, old: $("#pin-old").value }, t("access.pin_saved"));
    if (r) $("#pin-new").value = $("#pin-old").value = "";
  };
  $("#pin-clear").onclick = async () => {
    if (!confirm(t("access.confirm_clear"))) return;
    const r = await changeAccess({ action: "clear_pin", old: $("#pin-old").value }, t("access.pin_removed"));
    if (r) $("#pin-old").value = "";
  };
  $("#access-lan").onchange = (e) => changeAccess({ action: "configure", lan: e.target.checked }, t(e.target.checked ? "access.lan_on" : "access.lan_off"));
  $("#access-local").onchange = (e) => changeAccess({ action: "configure", pin_local: e.target.checked });
  $("#access-hours").onchange = (e) => changeAccess({ action: "configure", session_hours: +e.target.value });
  $("#logout").onclick = async () => {
    await fetch("/api/logout", { method: "POST" });
    location.replace("/login");
  };
  $("#radio-move").onclick = async () => {
    const ch = +$("#radio-channel").value;
    if (!ch || !confirm(t("setup.radio_confirm", { ch }))) return;
    attempt(() => api("POST", "/api/nodes/channel", { channel: ch }), t("setup.radio_moved", { ch }));
  };
  $("#node-resend").onclick = () => attempt(() => api("POST", "/api/nodes/setup", {}), (r) => t("setup.node_setup", { fw: r.fw || "?", n: Object.keys(r.fallbacks || {}).length }));
  onState(render);
  onShow("setup", () => { loadAddresses(); loadThemes(); loadAccess(); loadFound(); });
  setInterval(() => { if ($("#page-setup").classList.contains("on")) loadFound(); }, 2000); // plug / unplug shows up
}
