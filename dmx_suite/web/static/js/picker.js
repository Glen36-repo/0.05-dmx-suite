// Tick-box picker (v7): a dropdown listing items (lights, groups, inputs) with a tick each, grouped
// (Moving heads / Pixel bars / Pars / Kick …, or a device), with All / None and a tick per group.
// Closed, it shows a summary: "All lights", "4 bars, kick", "None". Used by Autopilot › Between songs
// (ignore inputs), Fixtures › Groups and the drum flash targets.
//
//   picker({ items: [{id, label, group}], groups: [{id, label, count?: (n) => "4 bars"}],
//            value: [ids], onChange: (ids) => …, label: "Flash targets", all: "All lights",
//            extra: {label: "+ New group", onClick} })
// returns the element; el.value is the ticked ids (in item order), el.set(ids) changes them.
import { el } from "./dom.js";
import { t } from "./i18n.js";

// one picker open at a time; an outside tap or Escape closes it
const opened = () => [...document.querySelectorAll("details.picker[open]")];
document.addEventListener("pointerdown", (e) => {
  for (const p of opened()) if (!p.contains(e.target)) p.open = false;
});
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  for (const p of opened()) { p.open = false; p.querySelector("summary")?.focus(); }
});

export function summaryOf(items, groups, ticked, allText) {
  const on = new Set(ticked);
  const n = items.filter((i) => on.has(i.id)).length;
  if (!items.length || !n) return t("picker.none");
  if (n === items.length) return allText || t("picker.all");
  const parts = [];
  for (const g of groups) {
    const mine = items.filter((i) => i.group === g.id);
    const sel = mine.filter((i) => on.has(i.id));
    if (!sel.length) continue;
    if (sel.length === mine.length && mine.length > 1) parts.push(g.count ? g.count(sel.length) : `${sel.length} ${g.label.toLowerCase()}`);
    else parts.push(...sel.map((i) => i.label));
  }
  for (const i of items) if (on.has(i.id) && !groups.some((g) => g.id === i.group)) parts.push(i.label);
  return parts.join(", ");
}

export function picker({ items, groups = [], value = [], onChange = () => {}, label = "", all = "", extra = null }) {
  let ticked = items.filter((i) => value.includes(i.id)).map((i) => i.id);
  const text = el("span", { class: "picker-text" });
  const summary = el("summary", { class: "picker-summary", "aria-label": label || undefined }, text);
  const body = el("div", { class: "picker-body", role: "group", "aria-label": label || undefined });
  const root = el("details", { class: "picker" }, summary, body);
  const boxes = new Map(); // id -> checkbox
  const groupBoxes = new Map(); // group id -> checkbox

  function refresh() {
    const on = new Set(ticked);
    for (const [id, b] of boxes) b.checked = on.has(id);
    for (const [gid, b] of groupBoxes) {
      const mine = items.filter((i) => i.group === gid);
      const n = mine.filter((i) => on.has(i.id)).length;
      b.checked = n === mine.length && n > 0;
      b.indeterminate = n > 0 && n < mine.length;
    }
    text.textContent = summaryOf(items, groups, ticked, all);
    root.title = text.textContent;
  }
  function set(ids, fire = true) {
    const on = new Set(ids);
    ticked = items.filter((i) => on.has(i.id)).map((i) => i.id);
    refresh();
    if (fire) onChange([...ticked]);
  }
  const tick = (id, on) => set(on ? [...ticked, id] : ticked.filter((x) => x !== id));

  const row = (cls, box, words) => el("label", { class: cls }, box, el("span", { text: words }));
  const box = (onchange, data) => el("input", { type: "checkbox", onchange, ...data });

  body.append(el("div", { class: "picker-quick" },
    el("button", { type: "button", class: "mini", "data-pick": "all", onclick: () => set(items.map((i) => i.id)) }, t("picker.select_all")),
    el("button", { type: "button", class: "mini", "data-pick": "none", onclick: () => set([]) }, t("picker.select_none"))));
  const listed = new Set();
  for (const g of groups) {
    const mine = items.filter((i) => i.group === g.id);
    if (!mine.length) continue;
    const gb = box((e) => { const ids = mine.map((i) => i.id); set(e.target.checked ? [...ticked, ...ids] : ticked.filter((x) => !ids.includes(x))); },
      { "data-group": g.id });
    groupBoxes.set(g.id, gb);
    const sec = el("div", { class: "picker-group" }, row("picker-head", gb, g.label));
    for (const i of mine) {
      const b = box((e) => tick(i.id, e.target.checked), { "data-item": i.id });
      boxes.set(i.id, b);
      listed.add(i.id);
      sec.append(row("picker-item", b, i.label));
    }
    body.append(sec);
  }
  const loose = items.filter((i) => !listed.has(i.id));
  if (loose.length) {
    const sec = el("div", { class: "picker-group" });
    for (const i of loose) {
      const b = box((e) => tick(i.id, e.target.checked), { "data-item": i.id });
      boxes.set(i.id, b);
      sec.append(row("picker-item", b, i.label));
    }
    body.append(sec);
  }
  if (!items.length) body.append(el("p", { class: "muted", text: t("picker.empty") }));
  if (extra) body.append(el("button", { type: "button", class: "mini picker-extra", onclick: extra.onClick }, extra.label));

  root.addEventListener("toggle", () => {
    if (root.open) for (const p of opened()) if (p !== root) p.open = false;
  });
  refresh();
  Object.defineProperty(root, "value", { get: () => [...ticked] });
  root.set = (ids) => set(ids, false);
  return root;
}

// lights of the running rig grouped by kind, for pickers of fixtures (haze never: rule 5)
const KIND_GROUPS = ["head", "bar", "wash", "kick"];
export function lightItems(fixtures) {
  const items = (fixtures || []).filter((f) => f.kind !== "haze").map((f) => ({ id: f.id, label: f.id, group: f.kind }));
  const groups = KIND_GROUPS.map((k) => ({ id: k, label: t(`picker.kind_${k}`), count: (n) => t(`picker.count_${k}`, { n }) }));
  return { items, groups };
}
