// Haze settings panel (v4, Live page): one block per mode with sliders + numbers, applied live while
// editing, Save writes the rig's haze: block, Revert goes back to what's saved. A Test button runs one
// cycle of a mode. Only the haze controller is touched; scenes and shows never set haze (rule 5).
import { api, attempt, cmd, toast } from "./api.js";
import { $, el } from "./dom.js";
import { t } from "./i18n.js";
import { infoButton } from "./info.js";

// [key, unit, min, max, step]
const BLOCKS = {
  manual: [["level", "pct", 0, 100, 1]],
  pulse: [["pulse_level", "pct", 0, 100, 1], ["pulse_on_s", "s", 0.1, 60, 0.1], ["pulse_every_s", "s", 0.2, 3600, 1]],
  boost: [["boost_level", "pct", 0, 100, 1], ["boost_s", "s", 0, 120, 0.5], ["boost_cooldown_s", "s", 0, 600, 1]],
  safety: [["max_on_s", "s", 1, 600, 1], ["rest_s", "s", 0, 600, 1], ["auto_off_min", "min", 0, 600, 1]],
};
const UNIT = { pct: "haze.u_pct", s: "haze.u_s", min: "haze.u_min" };

let saved = null; // the rig's saved haze settings
let draft = null; // what's on screen (applied live)
let timer = null;
let built = false;

function duty() {
  const on = +draft.pulse_on_s, every = +draft.pulse_every_s;
  return t("haze.duty", { on, every, pct: every ? Math.round((on / every) * 100) : 0 });
}

function field(key, unit, min, max, step) {
  const val = () => (draft[key] ?? (key === "pulse_level" ? draft.level : 0));
  const range = el("input", { type: "range", min, max: Math.min(max, unit === "pct" ? 100 : max), step, value: val(), "aria-label": t("haze.f_" + key) });
  const num = el("input", { type: "number", class: "num", min, max, step, value: val(), "data-key": key });
  const set = (v) => {
    v = Math.max(min, Math.min(max, +v));
    if (Number.isNaN(v)) return;
    draft[key] = v;
    range.value = v;
    if (document.activeElement !== num) num.value = v;
    changed();
  };
  range.oninput = (e) => set(e.target.value);
  num.onchange = (e) => set(e.target.value);
  return el("label", { class: "hz-field" }, el("span", { text: t("haze.f_" + key) }), range, num, el("span", { class: "muted", text: t(UNIT[unit]) }));
}

function build() {
  const blocks = Object.entries(BLOCKS).map(([mode, fields]) => {
    const head = el("h3", {}, el("span", { text: t("haze.b_" + mode) }), infoButton(`haze.${mode}`));
    if (mode !== "safety") head.append(el("button", { class: "mini", "data-test": mode, title: t("haze.test_tip"), onclick: () => test(mode) }, t("haze.test")));
    const box = el("div", { class: "hz-block", "data-block": mode }, head, ...fields.map((f) => field(...f)));
    if (mode === "pulse") box.append(el("div", { class: "hz-duty", id: "hz-duty", text: duty() }));
    if (mode === "safety") {
      box.append(el("label", { class: "hz-field" }, el("span", { text: t("haze.f_default_mode") }),
        el("select", { "data-key": "default_mode", onchange: (e) => { draft.default_mode = e.target.value; changed(); } },
          ...["off", "manual", "pulse"].map((m) => el("option", { value: m, selected: draft.default_mode === m }, t("haze." + m))))));
    }
    return box;
  });
  $("#hz-blocks").replaceChildren(...blocks);
}

function changed() {
  const dirty = JSON.stringify(draft) !== JSON.stringify(saved);
  $("#hz-save").disabled = !dirty;
  $("#hz-revert").disabled = !dirty;
  const d = $("#hz-duty");
  if (d) d.textContent = duty();
  clearTimeout(timer);
  if (dirty) timer = setTimeout(() => attempt(() => api("POST", "/api/haze/settings", { changes: draftChanges(), save: false })), 150);
}

function draftChanges() {
  const out = {};
  for (const [k, v] of Object.entries(draft)) if (k !== "presets" && JSON.stringify(v) !== JSON.stringify(saved[k])) out[k] = v;
  return out;
}

async function test(mode) {
  const r = await attempt(() => api("POST", "/api/haze/test", { mode }));
  if (r) toast(t("haze.testing", { mode: t("haze.b_" + mode) }));
}

// the live state brings the saved settings; the panel only rebuilds when nothing is being edited
export function renderHazePanel(h) {
  if (!h?.settings) return;
  $("#haze-rig").textContent = t("haze.rig", { rig: h.rig || "" });
  const presets = h.settings.presets || [];
  const sel = $("#haze-preset");
  const names = presets.map((p) => p.name).join("|");
  if (sel.dataset.names !== names) {
    sel.dataset.names = names;
    sel.replaceChildren(el("option", { value: "" }, t("haze.preset_none")), ...presets.map((p) => el("option", { value: p.name }, `${p.name} (${p.level}%)`)));
  }
  sel.classList.toggle("hidden", !presets.length);
  if (document.activeElement !== sel) sel.value = h.preset || "";
  const incoming = JSON.stringify(h.settings);
  const editing = draft && JSON.stringify(draft) !== JSON.stringify(saved);
  if (!built || (!editing && incoming !== JSON.stringify(saved) && !$("#hz-blocks").contains(document.activeElement))) {
    if (editing) return;
    saved = JSON.parse(incoming);
    draft = JSON.parse(incoming);
    build();
    built = true;
    changed();
  }
}

export function initHazePanel() {
  $("#haze-preset").onchange = (e) => e.target.value && cmd("haze", { action: "preset", preset: e.target.value });
  $("#hz-save").onclick = async () => {
    const r = await attempt(() => api("POST", "/api/haze/settings", { changes: draftChanges(), save: true }), t("haze.saved"));
    if (r) { saved = JSON.parse(JSON.stringify(r.settings)); draft = JSON.parse(JSON.stringify(r.settings)); build(); changed(); }
  };
  $("#hz-revert").onclick = async () => {
    const r = await attempt(() => api("POST", "/api/haze/revert", {}));
    if (r) { draft = JSON.parse(JSON.stringify(saved)); build(); changed(); }
  };
}
