// Address map (32 x 16 per universe, live values) and the universe routing table (v4, Layout; v7, Fixtures:
// the one place for universes and addresses). Values come from the chosen interface's last-sent frame,
// never guessed: no frames = blank.
import { $$, el } from "./dom.js";
import { watchFrames } from "./frames.js";
import { t } from "./i18n.js";
import { addressMap, footprintOf } from "./patch.js";

export const hue = (id) => [...id].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);

export function universesOf(doc, cat) {
  const set = new Set((cat?.fixtures || []).map((f) => f.universe ?? 0));
  for (const f of doc?.fixtures || []) set.add(+f.universe || 0);
  return [...set].sort((a, b) => a - b);
}

export class AddressMaps {
  constructor(box, { cat = () => null, selected = () => new Set() } = {}) {
    this.box = box;
    this.cat = cat;
    this.selected = selected;
    this.values = {}; // universe -> Uint8Array (what the chosen interface sent)
    this.stops = [];
    this.out = "";
  }

  render(doc, us) {
    this.doc = doc;
    this.us = us;
    this.box.replaceChildren(...us.map((u) => {
      const { cells } = addressMap(doc.fixtures, doc.types, u);
      const grid32 = el("div", { class: "addr-map", "data-u": u });
      for (let c = 1; c <= 512; c++) {
        const ids = cells[c - 1];
        const cell = el("div", { class: "ac" + (ids.length ? " used" : "") + (ids.length > 1 ? " clash" : ""), "data-ch": c,
          "data-ids": ids.join(",") }, el("span", { class: "n", text: c }), el("span", { class: "v" }));
        if (ids.length) {
          const f = doc.fixtures.find((x) => x.id === ids[0]);
          const n = footprintOf(doc.types, f.type);
          cell.style.setProperty("--h", hue(ids[0]));
          const name = this.cat()?.fixtures.find((x) => x.id === ids[0])?.channels?.[c - f.address];
          cell.title = `${ids.join(" + ")} · ch ${c}` + (name ? ` · ${name}` : "") + ` (${f.address}-${f.address + n - 1})`;
          if (c === f.address) { cell.classList.add("start"); cell.append(el("span", { class: "lbl", text: ids[0] })); }
        }
        grid32.append(cell);
      }
      return el("div", {}, el("h3", { text: t("layout.addr_title", { u }) }), el("div", { class: "addr-note", "data-note": u }), grid32);
    }));
    this.mark();
    this.paint();
  }

  mark() {
    const sel = this.selected();
    $$(".ac", this.box).forEach((c) => c.classList.toggle("hl", (c.dataset.ids || "").split(",").some((x) => sel.has(x))));
  }

  paint() {
    for (const map of $$(".addr-map", this.box)) {
      const u = +map.dataset.u, v = this.values[u];
      map.querySelectorAll(".ac").forEach((cell, i) => {
        const x = v ? v[i] : null;
        cell.querySelector(".v").textContent = x === null || x === undefined || !v ? "" : x || "";
        cell.style.setProperty("--v", x ? x / 255 : 0);
      });
    }
  }

  // live values while shown; stop() when hidden
  watch(on) {
    this.stop();
    if (!on || !this.us) return;
    this.stops = this.us.map((u) => watchFrames(u, this.out, (f) => {
      this.values[u] = f.values;
      const note = this.box.querySelector(`[data-note="${u}"]`);
      if (note) {
        note.textContent = f.no_frames ? t("layout.addr_no_frames", { source: f.source, u }) : f.stats?.all_zero ? t("layout.addr_all_zero", { source: f.source }) : f.source;
        note.classList.toggle("bad", !!(f.no_frames || f.stats?.all_zero));
      }
      this.paint();
    }));
  }

  stop() {
    this.stops.forEach((s) => s());
    this.stops = [];
  }
}

// ---------------------------------------------------------------- routing table

export const ago = (ms) => (ms === null || ms === undefined ? t("layout.never") : t("layout.ms_ago", { n: ms }));

// v5: USB DMX (Open) rows: driver (VCP / D2XX), break method, measured vs target; amber when out of range
function timingCell(r) {
  const tm = r.timing;
  if (!tm) return el("td", { text: "" });
  const m = tm.measured, g = tm.target, ck = r.checks;
  const driver = t(`timing.${ck?.driver_type || (tm.backend === "d2xx" ? "d2xx" : "vcp")}`);
  const text = t("timing.short", { driver, method: tm.method_name, brk: m.break_us ?? "-", tbrk: g.break_us, mab: m.mab_us ?? "-", tmab: g.mab_us });
  const warn = tm.warnings.length || (ck && ck.result !== "pass");
  return el("td", { class: warn ? "amber" : "", text, title: [...tm.warnings, ...(ck?.problems || []), tm.note].join("\n") });
}

export function routingRows(routing, uni = "all") {
  return routing.rows.map((r) => el("tr", { class: uni !== "all" && r.universe === uni ? "on" : "" },
    el("td", { text: r.universe ?? "?" }),
    el("td", { text: r.interface + (r.port ? ` (${r.port})` : r.mac ? ` (${r.mac})` : ""), title: r.detail || "" }),
    el("td", {}, el("span", { class: `st-dot ${r.state}` }), r.state),
    el("td", { text: r.fps ?? "-" }), el("td", { text: r.frames ?? r.packets ?? "-" }), el("td", { text: r.errors ?? "-" }),
    el("td", { text: ago(r.last_frame_age_ms) }), timingCell(r)));
}

// where address-map values come from: auto (the first interface carrying it), one interface, or the engine
export function sourceOptions(routing, us, current, carriers) {
  const opts = [["", "auto"], ...routing.rows.filter((r) => r.output !== null && r.output !== undefined)
    .map((r) => [String(r.output), r.interface]), ["engine", t("layout.addr_engine")]];
  const seen = new Set();
  return opts.filter(([v]) => !seen.has(v) && seen.add(v)).map(([v, label]) =>
    el("option", { value: v, selected: v === current }, v === "" ? (carriers(us[0])[0] || label) : label));
}
