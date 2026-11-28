// Drum Kit (v6 Part C) on the MIDI page: the drummer's kit defined once. Each zone is one named input:
// notes (Learn: hit the pad), role, tempo weight, velocity floor, in tempo, drum flash target, trigger.
// Hits light their row; notes heard that aren't in the kit are listed. Writes go through the store
// (validated, backed up, gig-locked).
import { api, attempt, get, toast } from "../api.js";
import { $, el } from "../dom.js";
import { t } from "../i18n.js";
import { onLeave, onShow } from "../nav.js";
import { lightItems, picker } from "../picker.js";
import { live as state } from "../state.js";

let view = null;
let timer = null;
let shownKit = "";

const kitId = () => $("#kit-pick").value || view?.active;

async function change(piece, zone, changes) {
  await attempt(() => api("POST", "/api/kits", { action: "piece", kit: kitId(), piece, zone, changes }));
  load();
}

// v7: the flash target is a tick-box picker of lights (and groups) with the pad's min level (softest hit)
function flashCell(pid, zid, z) {
  const { items, groups } = lightItems(state.cat?.fixtures, state.cat?.groups || {});
  const was = JSON.stringify(z.flash?.fixtures || []);
  const p = picker({ items, groups, value: z.flash?.fixtures || [], label: t("kit.flash"), all: t("picker.all_lights") });
  p.dataset.flash = z.input;
  p.addEventListener("toggle", () => { // saved once the picker closes (each save redraws the table)
    if (p.open || JSON.stringify(p.value) === was) return;
    change(pid, zid, { flash: p.value.length ? { ...(z.flash || {}), fixtures: p.value } : null });
  });
  const lvl = el("input", { type: "number", class: "num", min: 0, max: 100, step: 5, "data-min-level": z.input,
    value: z.flash ? Math.round((z.flash.min_level ?? 0.6) * 100) : "", disabled: !z.flash || undefined,
    title: t("kit.min_level_tip"), "aria-label": t("kit.min_level_aria", { input: z.input }),
    onchange: (e) => change(pid, zid, { flash: { ...z.flash, min_level: Math.max(0, Math.min(100, +e.target.value || 0)) / 100 } }) });
  return el("div", { class: "row kit-flash" }, p, el("label", { class: "ap-field" }, lvl, el("span", { class: "muted", text: "%" })));
}
function triggerText(tr) { return tr ? Object.entries(tr).map(([k, v]) => `${k}:${v}`).join("") : ""; }

function row(pid, piece, zid, z, first) {
  const inp = (attrs, on) => el("input", { ...attrs, onchange: (e) => on(e.target) });
  const roles = (view.roles || []).map((r) => el("option", { value: r, selected: r === z.role || undefined }, t("kit.role_" + r)));
  return el("tr", { "data-input": z.input, class: z.notes.length ? "" : "unlearned" },
    el("td", { text: first ? piece.name : "" }), el("td", { text: zid.replace(/_/g, " ") }),
    el("td", { class: "notes-cell" }, inp({ class: "notes", value: z.notes.join(" ") },
      (e) => change(pid, zid, { notes: e.value.split(/[\s,]+/).filter(Boolean).map(Number) }))),
    el("td", {}, el("select", { onchange: (e) => change(pid, zid, { role: e.target.value }) }, ...roles)),
    el("td", {}, inp({ class: "num", type: "number", step: 0.1, min: 0, max: 2, value: z.weight ?? "" }, (e) => change(pid, zid, { weight: e.value === "" ? null : +e.value }))),
    el("td", {}, inp({ class: "num", type: "number", min: 0, max: 127, value: z.velocity_floor ?? "" }, (e) => change(pid, zid, { velocity_floor: e.value === "" ? null : +e.value }))),
    el("td", {}, el("input", { type: "checkbox", checked: z.tempo !== false || undefined, onchange: (e) => change(pid, zid, { tempo: e.target.checked }) })),
    el("td", {}, flashCell(pid, zid, z)),
    el("td", {}, inp({ class: "wide", value: triggerText(z.trigger) }, (e) => {
      const [k, ...v] = e.value.split(":");
      change(pid, zid, { trigger: e.value.trim() ? { [k.trim()]: v.join(":").trim() } : null });
    })),
    el("td", {},
      el("button", { class: "mini", "data-learn": `${pid}/${zid}`, onclick: () => learn(pid, zid, false) }, t("kit.learn")),
      el("button", { class: "mini", onclick: () => learn(pid, zid, true) }, t("kit.learn_add")),
      el("button", { class: "mini danger-text", title: t("kit.remove_confirm", { piece: piece.name, zone: zid }), onclick: () => confirm(t("kit.remove_confirm", { piece: piece.name, zone: zid })) &&
        attempt(() => api("POST", "/api/kits", { action: "piece", kit: kitId(), piece: pid, zone: zid, remove: true })).then(load) }, "✕")));
}

function draw() {
  const kits = Object.keys(view.kits);
  if (!kits.includes(shownKit)) shownKit = view.active || kits[0] || "";
  $("#kit-pick").replaceChildren(...kits.map((k) => el("option", { value: k, selected: k === shownKit || undefined },
    `${view.kits[k].name}${k === view.active ? " ✓" : ""}`)));
  const kit = view.kits[shownKit];
  $("#kit-chan").textContent = kit ? t("kit.channel", { ch: kit.channel || "any" }) : "";
  $("#kit-note").textContent = view.derived ? t("kit.derived") : "";
  const rows = [];
  for (const [pid, piece] of Object.entries(kit?.pieces || {})) {
    Object.entries(piece.zones).forEach(([zid, z], i) => rows.push(row(pid, piece, zid, z, i === 0)));
  }
  $("#kit-rows").replaceChildren(...rows);
  live();
}

function live() {
  for (const tr of document.querySelectorAll("#kit-rows tr")) tr.classList.toggle("hit", !!view.live?.[tr.dataset.input]);
  const lr = view.learning;
  const box = $("#kit-learning");
  box.textContent = lr ? (lr.armed ? t("kit.learning", { piece: lr.piece, zone: lr.zone }) : lr.result ? t("kit.learned", { piece: lr.piece, zone: lr.zone, result: lr.result }) : "") : "";
  box.classList.toggle("hidden", !box.textContent);
  const um = view.unmapped || [];
  $("#kit-unmapped").textContent = um.length ? t("kit.unmapped", { notes: um.map((u) => `${u.note} ${u.name || ""} (vel ${u.velocity})`).join(", ") }) : "";
  $("#kit-unmapped").classList.toggle("hidden", !um.length);
}

async function learn(piece, zone, add) {
  await attempt(() => api("POST", "/api/kits", { action: "learn", kit: kitId(), piece, zone, add }));
  poll();
}

export async function load() {
  view = await get("/api/kits").catch(() => null);
  if (view) draw();
}

let wasArmed = false;
async function poll() {
  const v = await get("/api/kits").catch(() => null);
  if (!v) return;
  const changed = JSON.stringify(v.kits) !== JSON.stringify(view?.kits) || v.active !== view?.active;
  view = v;
  if (changed || (wasArmed && !v.learning?.armed)) draw(); else live();
  wasArmed = !!v.learning?.armed;
}

export function init() {
  $("#kit-pick").onchange = async (e) => {
    shownKit = e.target.value;
    if (shownKit !== view.active) await attempt(() => api("POST", "/api/kits", { action: "active", kit: shownKit }));
    load();
  };
  $("#kit-new").onclick = async () => {
    const id = (prompt(t("kit.new_prompt")) || "").trim();
    if (id && await attempt(() => api("POST", "/api/kits", { action: "new", kit: id }))) { shownKit = id; load(); }
  };
  $("#kit-export").onclick = async () => {
    const r = await attempt(() => get(`/api/kits/export?kit=${encodeURIComponent(kitId())}`));
    if (!r) return;
    try { await navigator.clipboard.writeText(r.yaml); toast(t("kit.copied")); } catch { prompt("", r.yaml); }
  };
  $("#kit-import").onclick = async () => {
    const text = prompt(t("kit.import_prompt"));
    if (!text) return;
    const id = (prompt(t("kit.import_id"), "") || "").trim();
    if (await attempt(() => api("POST", "/api/kits", { action: "import", yaml: text, kit: id }))) load();
  };
  $("#kit-add").onclick = () => {
    const pid = $("#kit-add-piece").value.trim(), zid = $("#kit-add-zone").value.trim() || "head";
    if (pid) change(pid, zid, { notes: [], role: "trigger_only" });
  };
  onShow("midi", () => { load(); clearInterval(timer); timer = setInterval(poll, 400); });
  onLeave("midi", () => clearInterval(timer));
}
