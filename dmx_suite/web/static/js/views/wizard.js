// First-run setup wizard: DMX interface, lights, rule profile, starter show, PIN. Opens by itself
// on a laptop that hasn't finished or skipped it, and from the Setup page any time. Every step can
// be skipped; each one saves through the same checked, backed-up, undoable store calls as the
// rest of the app.
import { api, attempt, get, toast } from "../api.js";
import { $, el } from "../dom.js";
import { t } from "../i18n.js";
import { live, refreshCatalogue } from "../state.js";
import { autoPatch } from "./fixtures.js";

const STEPS = ["interface", "lights", "profile", "starter", "pin"];
let step = 0;
let fixtures = null; // fixtures.yaml
let rig = null;
const picks = { iface: null, host: "", counts: {}, profile: null, starter: true, pin: "" };

function dialog() {
  return $("#wizard");
}

export async function open() {
  step = 0;
  fixtures = await get("/api/store/fixtures");
  rig = await get(`/api/store/rig/${encodeURIComponent(live.cat.rig_name)}`);
  picks.profile = typeof rig.profile === "string" ? rig.profile : "generic";
  const d = dialog();
  if (!d.open) d.showModal();
  render();
}

async function finish(state) {
  await attempt(() => api("POST", "/api/settings", { wizard: state }));
  dialog().close();
  if (state === "done") toast(t("wizard.finished"));
}

function nav(onNext) {
  return el("div", { class: "row wrap wizard-nav" },
    el("button", { onclick: () => finish("skipped"), class: "link" }, t("wizard.skip_all")),
    el("span", { class: "spacer" }),
    step > 0 ? el("button", { onclick: () => { step -= 1; render(); } }, t("wizard.back")) : "",
    el("button", { onclick: () => { step += 1; render(); } }, t("wizard.skip_step")),
    el("button", { class: "primary", id: "wizard-next", onclick: async () => {
      if (await onNext() === false) return;
      if (step === STEPS.length - 1) return finish("done");
      step += 1;
      render();
    } }, t(step === STEPS.length - 1 ? "wizard.finish" : "wizard.next")));
}

let renderId = 0; // a slow check (port scan) mustn't draw over a newer step

async function render() {
  const mine = ++renderId;
  const name = STEPS[step];
  const body = el("div", { class: "wizard-body" });
  const head = el("div", {}, el("p", { class: "muted", text: t("wizard.step", { n: step + 1, of: STEPS.length }) }),
    el("h2", { text: t(`wizard.${name}_title`) }), el("p", { text: t(`wizard.${name}_help`) }));
  if (step >= STEPS.length) return finish("done");
  let next = async () => true;

  if (name === "interface") {
    const found = await get("/api/interfaces");
    const options = [...found.map((f) => ({ key: `${f.driver || "serial"}|${f.port}`, label: `${f.port}: ${f.description}` + (f.driver ? ` (${t("wizard.looks_like", { what: t("wizard.drv_" + f.driver) })})` : ""), out: { driver: f.driver || "enttec_open", port: f.port } })),
      { key: "artnet", label: t("wizard.drv_artnet"), out: { driver: "artnet" }, host: true },
      { key: "sacn", label: t("wizard.drv_sacn"), out: { driver: "sacn" }, host: true },
      { key: "log", label: t("wizard.drv_log"), out: { driver: "log" } }];
    picks.iface ||= options[0].key;
    body.append(...(found.length ? [] : [el("p", { class: "muted", text: t("wizard.none_found") })]),
      ...options.map((o) => el("label", { class: "check block" },
        el("input", { type: "radio", name: "iface", checked: picks.iface === o.key, onchange: () => { picks.iface = o.key; render(); } }), el("span", { text: o.label }))));
    const chosen = options.find((o) => o.key === picks.iface);
    if (chosen?.host) body.append(el("input", { value: picks.host, placeholder: t("wizard.host_placeholder"), oninput: (e) => (picks.host = e.target.value.trim()) }));
    next = async () => {
      const out = { ...chosen.out };
      if (chosen.host && picks.host) out.host = picks.host;
      rig.outputs = [out];
      const r = await attempt(() => api("PUT", `/api/store/rig/${encodeURIComponent(live.cat.rig_name)}`, { data: rig }));
      if (r?.notes?.length) toast(r.notes.join(" · "));
      return !!r;
    };
  }

  if (name === "lights") {
    const types = Object.entries(fixtures.types || {});
    body.append(el("p", { class: "muted", text: t("wizard.lights_now", { n: (fixtures.fixtures || []).length }) }),
      el("table", { class: "grid-table" }, el("tbody", {}, ...types.map(([k, ty]) => el("tr", {},
        el("td", { text: ty.name || k }), el("td", { class: "muted", text: t("wizard.channels", { n: (ty.channels || []).length }) }),
        el("td", {}, el("input", { type: "number", min: 0, max: 64, class: "num", value: picks.counts[k] || 0, oninput: (e) => (picks.counts[k] = +e.target.value || 0) })))))),
      el("p", { class: "muted", text: t("wizard.lights_more") }));
    next = async () => {
      const rows = [...(fixtures.fixtures || [])];
      const ids = new Set(rows.map((f) => f.id));
      for (const [k, n] of Object.entries(picks.counts)) {
        for (let i = 1, made = 0; made < n; i++) {
          const id = `${k}_${i}`;
          if (!ids.has(id)) { ids.add(id); rows.push({ id, type: k, universe: 0, address: 0 }); made++; }
        }
      }
      if (rows.length === (fixtures.fixtures || []).length) return true;
      autoPatch(rows, fixtures.types, false);
      if (!(await attempt(() => api("PUT", "/api/store/patch", { fixtures: rows }), t("wizard.lights_added")))) return false;
      fixtures.fixtures = rows;
      picks.counts = {};
      if (Array.isArray(rig.fixtures) && !rig.fixtures.includes("all")) {
        rig.fixtures = ["all"];
        await attempt(() => api("PUT", `/api/store/rig/${encodeURIComponent(live.cat.rig_name)}`, { data: rig }));
      }
      await refreshCatalogue();
      return true;
    };
  }

  if (name === "profile") {
    body.append(...[["generic", t("wizard.profile_generic")], ["0.05_band", t("wizard.profile_band")]].map(([v, label]) => el("label", { class: "check block" },
      el("input", { type: "radio", name: "profile", checked: picks.profile === v, onchange: () => (picks.profile = v) }), el("span", { text: label }))));
    next = async () => {
      if (rig.profile === picks.profile) return true;
      rig.profile = picks.profile;
      return !!(await attempt(() => api("PUT", `/api/store/rig/${encodeURIComponent(live.cat.rig_name)}`, { data: rig })));
    };
  }

  if (name === "starter") {
    body.append(el("label", { class: "check block" }, el("input", { type: "checkbox", checked: picks.starter, onchange: (e) => (picks.starter = e.target.checked) }),
      el("span", { text: t("wizard.starter_make") })));
    next = async () => {
      if (!picks.starter) return true;
      let r = await api("POST", "/api/starter", {}).catch((e) => ({ error: e.message }));
      if (r.error && r.error.includes("already") && confirm(t("wizard.starter_replace"))) {
        r = await api("POST", "/api/starter", { overwrite: true }).catch((e) => ({ error: e.message }));
      }
      if (r.error) { toast(r.error, true); return false; }
      toast(t("wizard.starter_playing"));
      await refreshCatalogue();
      return true;
    };
  }

  if (name === "pin") {
    const st = await get("/api/access");
    if (st.pin_set) body.append(el("p", { class: "muted", text: t("wizard.pin_already") }));
    else body.append(el("input", { type: "password", autocomplete: "new-password", placeholder: t("access.pin_new"), oninput: (e) => (picks.pin = e.target.value) }));
    next = async () => {
      if (st.pin_set || !picks.pin) return true;
      return !!(await attempt(() => api("POST", "/api/access", { action: "set_pin", pin: picks.pin }), t("access.pin_saved")));
    };
  }

  if (mine !== renderId) return;
  dialog().replaceChildren(el("form", { method: "dialog", class: "wizard", onsubmit: (e) => e.preventDefault() }, head, body, nav(next)));
}

export function init() {
  $("#wizard-open").onclick = open;
  // a laptop that hasn't been through it yet: offer it once the page is up
  setTimeout(async () => {
    try {
      const s = await get("/api/settings");
      if (s.first_run && !document.body.dataset.noWizard) open();
    } catch {}
  }, 800);
}
