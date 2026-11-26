// Button grids in a fixed, saved order (v4): each panel keeps the order it was last arranged in (drag a
// button to move it), new items go at the end and nothing else moves, so a button's place - and a MIDI
// or muscle-memory position - stays put when things are added. The first time, A-Z.
import { el, remember } from "./dom.js";
import { t } from "./i18n.js";

export function ordered(key, items) {
  const saved = remember.get(`order.${key}`, null);
  const ids = items.map((i) => i.id);
  let order;
  if (!saved) order = items.slice().sort((a, b) => a.label.localeCompare(b.label, "en-AU")).map((i) => i.id);
  else order = [...saved.filter((id) => ids.includes(id)), ...ids.filter((id) => !saved.includes(id))];
  remember.set(`order.${key}`, order);
  const byId = Object.fromEntries(items.map((i) => [i.id, i]));
  return order.map((id) => byId[id]);
}

// items: [{id, label, attrs, onclick}]
export function fillGrid(box, key, items) {
  const buttons = ordered(key, items).map((it) => el("button", { ...it.attrs, "data-item": it.id, title: `${it.label} · ${t("live.drag_tip")}`,
    draggable: "true", onclick: it.onclick }, it.label));
  box.replaceChildren(...buttons);
  let dragged = null;
  for (const b of buttons) {
    b.addEventListener("dragstart", (e) => { dragged = b; b.classList.add("dragging"); e.dataTransfer.effectAllowed = "move"; });
    b.addEventListener("dragend", () => { b.classList.remove("dragging"); buttons.forEach((x) => x.classList.remove("drop-before")); });
    b.addEventListener("dragover", (e) => { if (dragged && dragged !== b) { e.preventDefault(); b.classList.add("drop-before"); } });
    b.addEventListener("dragleave", () => b.classList.remove("drop-before"));
    b.addEventListener("drop", (e) => {
      e.preventDefault();
      if (!dragged || dragged === b) return;
      box.insertBefore(dragged, b);
      remember.set(`order.${key}`, [...box.children].map((x) => x.dataset.item));
    });
  }
}
