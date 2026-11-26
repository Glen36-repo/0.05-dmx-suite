// Light layout grid: every light (and every pixel of a pixel bar) is a square, laid out on a grid
// of cells, showing its live colour. The live page only shows it; the layout page edits it:
// select (tap, shift-tap, rectangle, lasso), move, align, distribute, make a row/ring/grid,
// rotate, and lay a pixel light's pixels out as a row, ring or grid.
//
// Layout entries (rig file format 3): {x, y, rot, shape, cols}, x/y = the light's centre in cells
// from the top left (back of the stage at the top), half cells allowed.
import { svg } from "./dom.js";

const C = 24; // svg units per cell
const SIZE = 0.82; // square size, cells
const GRID_MAX = 200;
const half = (v) => Math.round(v * 2) / 2;
const clamp = (v) => Math.min(GRID_MAX, Math.max(0, v));

// where each pixel sits relative to the light's centre, in cells, before rotation
export function cellOffsets(n, shape = "row", cols = 0, reverse = false) {
  const out = offsets(n, shape, cols);
  return reverse ? out.reverse() : out; // mounted backwards: pixel 1 at the other end
}

function offsets(n, shape, cols) {
  n = Math.max(1, n || 1);
  if (n === 1) return [[0, 0]];
  if (shape === "ring") {
    const r = Math.max(1, (n * 1.05) / (2 * Math.PI));
    return [...Array(n)].map((_, i) => {
      const a = (2 * Math.PI * i) / n - Math.PI / 2;
      return [r * Math.cos(a), r * Math.sin(a)];
    });
  }
  if (shape === "grid") {
    const w = cols > 0 ? cols : Math.ceil(Math.sqrt(n));
    const h = Math.ceil(n / w);
    return [...Array(n)].map((_, i) => [(i % w) - (w - 1) / 2, Math.floor(i / w) - (h - 1) / 2]);
  }
  return [...Array(n)].map((_, i) => [i - (n - 1) / 2, 0]);
}

// ---------------------------------------------------------------- labels

const CH_W = 0.23, LABEL_H = 0.52; // label size in cells (9 px text and its halo on a 24 px cell)

// a short name for a crowded spot: "uking_l" -> "UK L", "bar_3" -> "BA 3", "mh_a" -> "MH A"
export function shortName(id) {
  const parts = String(id).split(/[_\s-]+/).filter(Boolean);
  if (parts.length < 2) return String(id).slice(0, 5);
  return `${parts[0].slice(0, 2).toUpperCase()} ${parts.slice(1).join("").slice(0, 3).toUpperCase()}`;
}

const hits = (a, b) => a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3];

/** Where each light's name goes so that no two names and no name and light overlap.
 * items: [{id, icon: [x0, y0, x1, y1] (cells), full, short}]. Tries under the light, then a little
 * lower, then beside; then the short name (full id on hover); last resort, further down with a leader
 * line. Returns {id: {x (centre), y (top), text, short, leader}}. Pure, so it's tested on its own. */
export function placeLabels(items) {
  const out = {};
  const icons = items.map((it) => it.icon);
  const placed = [];
  const order = items.slice().sort((a, b) => a.icon[1] - b.icon[1] || a.icon[0] - b.icon[0]);
  const box = (cx, top, text) => { const w = text.length * CH_W; return [cx - w / 2, top, cx + w / 2, top + LABEL_H]; };
  const free = (b, it) => !placed.some((p) => hits(p, b)) && !icons.some((ic) => ic !== it.icon && hits(ic, b));
  for (const it of order) {
    const [x0, , x1, y1] = it.icon, cx = (x0 + x1) / 2, top = y1 + 0.05;
    const spots = (text) => {
      const w = text.length * CH_W;
      const r = LABEL_H + 0.04; // one label row lower
      return [[cx, top], [cx, top + r], [cx - w / 2 - 0.3, top], [cx + w / 2 + 0.3, top], [cx, top + 2 * r]];
    };
    let done = null;
    for (const [text, short] of [[it.full, false], [it.short, true]]) {
      for (const [x, y] of spots(text)) {
        const b = box(x, y, text);
        if (free(b, it)) { done = { x, y, text, short, leader: Math.abs(x - cx) > 0.01 || y > top + 0.01 }; placed.push(b); break; }
      }
      if (done) break;
    }
    if (!done) { // crowded: go further down until there's room, with a line back to the light
      let y = top + 3 * (LABEL_H + 0.04);
      while (!free(box(cx, y, it.short), it) && y < top + 8) y += LABEL_H + 0.04;
      done = { x: cx, y, text: it.short, short: true, leader: true };
      placed.push(box(cx, y, it.short));
    }
    out[it.id] = done;
  }
  return out;
}

function rotated([x, y], deg) {
  const a = (deg * Math.PI) / 180;
  return [x * Math.cos(a) - y * Math.sin(a), x * Math.sin(a) + y * Math.cos(a)];
}

function inPolygon([x, y], poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

export class LightGrid {
  /** host: element to draw in. opts.edit: arranging allowed; opts.select: picking lights only
   * (scene builder). opts.onChange(kind): "select" | "move". */
  constructor(host, opts = {}) {
    this.host = host;
    this.edit = !!opts.edit;
    this.selectable = this.edit || !!opts.select;
    this.onChange = opts.onChange || (() => {});
    this.tool = "select"; // select | lasso | move
    this.selected = new Set();
    this.items = {};
    this.history = [];
    this.zoom = 100;
    this.view = null; // null: fit to the lights; else [x, y, w, h] in cells (zoomed / panned by hand)
    this.onView = opts.onView || (() => {});
    this.showBeams = false;
    this.showNames = true;
  }

  // ---------------------------------------------------------------- drawing

  build(cat, layout = null) {
    this.cat = cat;
    this.fixtures = Object.fromEntries(cat.fixtures.map((f) => [f.id, f]));
    this.layout = JSON.parse(JSON.stringify(layout || cat.layout));
    this.saved = JSON.stringify(this.layout);
    for (const id of [...this.selected]) if (!this.layout[id]) this.selected.delete(id);
    this.root = svg("svg", { class: "lightgrid" + (this.selectable ? " edit" : ""), role: "img" });
    this.gGrid = svg("g", { class: "gridlines" });
    this.gBeams = svg("g", { class: "beams" });
    this.gLights = svg("g");
    this.gMarquee = svg("g");
    this.gArrow = svg("g", { class: "arrow" });
    this.root.append(this.gGrid, this.gBeams, this.gLights, this.gArrow, this.gMarquee);
    this.patchKey = this.patchKey === undefined ? null : this.patchKey;
    const key = cat.fixtures.map((f) => f.id).join(",");
    if (key !== this.patchKey) this.view = null; // patch changed: fit again
    this.patchKey = key;
    this.items = {};
    // haze machines aren't lights on the stage: a fixed indicator in the corner shows them instead
    this.hazeIds = cat.fixtures.filter((f) => f.kind === "haze").map((f) => f.id);
    this.gHaze = svg("g", { class: "haze-ind" + (this.hazeIds.length ? "" : " hidden") });
    this.gHaze.append(svg("rect", { class: "hz-box", rx: 4 }), svg("text", { class: "hz-text" }));
    this.root.append(this.gHaze);
    for (const f of cat.fixtures) if (this.layout[f.id] && f.kind !== "haze") this.drawLight(f.id);
    this.fit();
    this.applyView();
    if (this.selectable) this.bindPointer();
    if (this.edit) this.bindView();
    this.host.replaceChildren(this.root);
    // window or box resized: the drawing scales itself (view box); the corner indicator follows
    this.resizer?.disconnect();
    this.resizer = new ResizeObserver(() => this.placeHaze());
    this.resizer.observe(this.root);
    this.placeHaze();
    if (this.arrow) this.setArrow(this.arrow);
    this.markSelection();
    if (this.lastFixtures) this.update(this.lastFixtures);
  }

  cellsOf(id) {
    const f = this.fixtures[id], p = this.layout[id];
    return cellOffsets(f.pixels || 1, p.shape, p.cols, p.reverse).map((o) => {
      const [dx, dy] = rotated(o, p.rot || 0);
      return [p.x + dx, p.y + dy];
    });
  }

  drawLight(id) {
    const f = this.fixtures[id];
    const old = this.items[id];
    const g = svg("g", { class: `fx ${f.kind}` + ((f.pixels || 1) > 1 ? " pixel" : ""), "data-id": id });
    const p0 = this.layout[id];
    if ((f.pixels || 1) > 1) {
      // a pixel light is one object: an outline round its segments, drawn in the light's own frame and turned with it
      const offs = cellOffsets(f.pixels, p0.shape, p0.cols);
      const xs = offs.map(([x]) => x), ys = offs.map(([, y]) => y), m = 0.46; // bars end to end still show a gap
      const [x0, x1, y0, y1] = [Math.min(...xs) - m, Math.max(...xs) + m, Math.min(...ys) - m, Math.max(...ys) + m];
      g.append(svg("rect", { class: "outline", x: (p0.x + x0) * C, y: (p0.y + y0) * C, width: (x1 - x0) * C, height: (y1 - y0) * C, rx: 5,
                             transform: `rotate(${p0.rot || 0} ${p0.x * C} ${p0.y * C})` }));
    }
    const cs = (f.pixels || 1) > 1 ? 0.74 : SIZE; // segments sit inside the outline
    const cells = this.cellsOf(id).map(([x, y]) => {
      const r = svg("rect", { x: (x - cs / 2) * C, y: (y - cs / 2) * C, width: cs * C, height: cs * C, rx: 3, class: "cell" });
      g.append(r);
      return r;
    });
    const p = this.layout[id];
    if (f.moves) g.append(svg("circle", { cx: p.x * C, cy: p.y * C, r: 2.5, class: "mark" }));
    if (f.kind === "haze") {
      const txt = svg("text", { x: p.x * C, y: p.y * C + 4, class: "hz", "text-anchor": "middle" });
      txt.textContent = "HZ";
      g.append(txt);
    }
    const ys = this.cellsOf(id).map(([, y]) => y);
    const label = svg("text", { x: p.x * C, y: (Math.max(...ys) + 0.95) * C, class: "name", "text-anchor": "middle" });
    label.textContent = id;
    const tip = svg("title");
    tip.textContent = f.type ? `${id} (${f.type})` : id; // full id on hover, whatever the label shows
    g.append(tip, label);
    const beam = f.moves ? svg("line", { class: "beam" }) : null;
    if (old) {
      old.g.replaceWith(g);
      if (old.beam) old.beam.remove();
    } else this.gLights.append(g);
    if (beam) this.gBeams.append(beam);
    this.items[id] = { g, cells, beam, label };
  }

  // the box round what's on it, in cells: tight round the lights when only showing or picking them
  // (so they fill the box), with room round the edge when arranging them
  contentBox() {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const id of Object.keys(this.items)) {
      for (const [x, y] of this.cellsOf(id)) {
        minX = Math.min(minX, x); minY = Math.min(minY, y);
        maxX = Math.max(maxX, x); maxY = Math.max(maxY, y);
      }
    }
    if (minX === Infinity) [minX, minY, maxX, maxY] = [0, 0, 8, 4];
    const pad = this.edit ? 2 : 0.6; // cells
    const names = this.showNames ? (this.edit ? 1 : 0.6) : 0;
    return [minX - pad, minY - pad, maxX - minX + 2 * pad, maxY - minY + 2 * pad + names];
  }

  // zoom to fit (the default), re-fitted whenever the lights change; a hand zoom / pan keeps its view
  // until Fit (or the patch changes)
  fit() {
    const box = this.contentBox();
    this.box = box;
    this.size = [box[0] + box[2], box[1] + box[3]];
    const m = this.showBeams ? 3 : 0; // room round the edge for beam lines
    const vb = this.view || [box[0] - m, box[1] - m, box[2] + 2 * m, box[3] + 2 * m];
    this.root.setAttribute("viewBox", vb.map((v) => v * C).join(" "));
    this.root.setAttribute("preserveAspectRatio", "xMidYMid meet");
    // the narrowest it may be drawn (a phone scrolls sideways rather than shrink the lights below --min-cell)
    this.root.style.setProperty("--cells", String(box[2] + 2 * m));
    this.gGrid.replaceChildren();
    if (this.edit) {
      // grid lines over everything that can be on screen, whatever the box's shape
      const [x0, y0, w, h] = vb, ext = Math.max(w, h);
      const gx0 = Math.floor(x0 - ext), gx1 = Math.ceil(x0 + w + ext), gy0 = Math.floor(y0 - ext), gy1 = Math.ceil(y0 + h + ext);
      for (let x = gx0; x <= gx1; x++) this.gGrid.append(svg("line", { x1: x * C, y1: gy0 * C, x2: x * C, y2: gy1 * C }));
      for (let y = gy0; y <= gy1; y++) this.gGrid.append(svg("line", { x1: gx0 * C, y1: y * C, x2: gx1 * C, y2: y * C }));
    }
    if (this.layoutLabels) this.layoutLabels();
    this.placeHaze();
  }

  // the haze indicator sits in the top right corner of what's on screen
  placeHaze() {
    if (!this.gHaze || !this.hazeIds.length) return;
    const [vx, vy, vw, vh] = this.root.getAttribute("viewBox").split(" ").map(Number);
    const r = this.root.getBoundingClientRect();
    // with "meet" the box may be wider/taller than the view box: find the visible top right
    const s = r.width && r.height ? Math.max(vw / r.width, vh / r.height) : 1;
    const right = vx + vw / 2 + (r.width * s) / 2, top = vy + vh / 2 - (r.height * s) / 2;
    const w = 3.4 * C, h = 0.8 * C, pad = 0.25 * C;
    const rect = this.gHaze.querySelector("rect"), txt = this.gHaze.querySelector("text");
    rect.setAttribute("x", right - w - pad); rect.setAttribute("y", top + pad);
    rect.setAttribute("width", w); rect.setAttribute("height", h);
    txt.setAttribute("x", right - w / 2 - pad); txt.setAttribute("y", top + pad + h * 0.68);
    txt.setAttribute("text-anchor", "middle");
    this.drawHaze();
  }

  // haze status from the live state: {mode, on, level, resting, boosting}
  setHaze(h) { this.haze = h; this.drawHaze(); }

  drawHaze() {
    if (!this.gHaze || !this.hazeIds.length) return;
    const h = this.haze || {}, lvl = this.hazeLevel;
    const pct = lvl !== undefined ? Math.round(lvl * 100) : h.on ? Math.round(h.level ?? 0) : 0;
    const state = h.boosting ? "boost" : h.resting ? "rest" : h.mode || "off";
    this.gHaze.querySelector("text").textContent = `HZ ${pct}% · ${state}`;
    this.gHaze.classList.toggle("on", pct > 0);
  }

  get fitted() { return !this.view; }

  // the box a light takes up (cells), segments and outline included
  iconBox(id) {
    const f = this.fixtures[id], pts = this.cellsOf(id), r = (f.pixels || 1) > 1 ? 0.5 : SIZE / 2;
    const xs = pts.map(([x]) => x), ys = pts.map(([, y]) => y);
    return [Math.min(...xs) - r, Math.min(...ys) - r, Math.max(...xs) + r, Math.max(...ys) + r];
  }

  // lights in the same place or touching (same test as layout.layout_problems on the server)
  problems(minGap = 0.25) {
    const ids = Object.keys(this.items), out = [];
    const bx = Object.fromEntries(ids.map((id) => [id, this.iconBox(id)]));
    for (let i = 0; i < ids.length; i++) {
      for (let j = i + 1; j < ids.length; j++) {
        const a = bx[ids[i]], b = bx[ids[j]];
        const gap = Math.max(b[0] - a[2], a[0] - b[2], b[1] - a[3], a[1] - b[3]);
        if (gap < minGap - 1e-9) out.push({ a: ids[i], b: ids[j], kind: gap < -1e-9 ? "overlap" : "close" });
      }
    }
    return out.sort((x, y) => (x.kind === "overlap" ? 0 : 1) - (y.kind === "overlap" ? 0 : 1));
  }

  layoutLabels() {
    if (!this.showNames) return;
    const ids = Object.keys(this.items).filter((id) => this.items[id].label);
    const spots = placeLabels(ids.map((id) => ({ id, icon: this.iconBox(id), full: id, short: shortName(id) })));
    for (const id of ids) {
      const it = this.items[id], s = spots[id], icon = this.iconBox(id);
      it.label.textContent = s.text;
      it.label.setAttribute("x", s.x * C);
      it.label.setAttribute("y", (s.y + LABEL_H * 0.72) * C);
      it.label.classList.toggle("short", s.short);
      it.g.querySelector(".leader")?.remove();
      if (s.leader) {
        it.g.insertBefore(svg("line", { class: "leader", x1: ((icon[0] + icon[2]) / 2) * C, y1: icon[3] * C, x2: s.x * C, y2: s.y * C }), it.label);
      }
    }
  }

  fitView() {
    this.view = null;
    this.zoom = 100;
    this.fit();
    this.onView();
  }

  // zoom by `factor` round a point (cells; default the middle of what's showing)
  zoomBy(factor, at = null) {
    const vb = this.view || this.currentBox();
    const [cx, cy] = at || [vb[0] + vb[2] / 2, vb[1] + vb[3] / 2];
    const w = Math.min(GRID_MAX * 2, Math.max(2, vb[2] / factor)), h = vb[3] * (w / vb[2]);
    this.view = [cx - (cx - vb[0]) * (w / vb[2]), cy - (cy - vb[1]) * (h / vb[3]), w, h];
    this.zoom = Math.round((this.box[2] / w) * 100);
    this.fit();
    this.onView();
  }

  panBy(dx, dy) {
    const vb = this.view || this.currentBox();
    this.view = [vb[0] - dx, vb[1] - dy, vb[2], vb[3]];
    this.fit();
    this.onView();
  }

  currentBox() {
    const m = this.showBeams ? 3 : 0, b = this.box || this.contentBox();
    return [b[0] - m, b[1] - m, b[2] + 2 * m, b[3] + 2 * m];
  }

  // wheel = zoom round the pointer; middle button, or Space + drag, pans
  bindView() {
    this.root.addEventListener("wheel", (ev) => {
      ev.preventDefault();
      this.zoomBy(ev.deltaY < 0 ? 1.15 : 1 / 1.15, this.toCells(ev));
    }, { passive: false });
    let pan = null;
    const spaceDown = () => document.body.classList.contains("space-held");
    this.root.addEventListener("pointerdown", (ev) => {
      if (ev.button !== 1 && !(ev.button === 0 && spaceDown())) return;
      ev.preventDefault();
      ev.stopImmediatePropagation();
      pan = { at: this.toCells(ev) };
      this.root.setPointerCapture(ev.pointerId);
    }, true);
    this.root.addEventListener("pointermove", (ev) => {
      if (!pan) return;
      ev.stopImmediatePropagation();
      const [x, y] = this.toCells(ev);
      this.panBy(x - pan.at[0], y - pan.at[1]);
    }, true);
    const end = (ev) => { if (pan) { pan = null; ev.stopImmediatePropagation(); } };
    this.root.addEventListener("pointerup", end, true);
    this.root.addEventListener("pointercancel", end, true);
  }

  applyView() {
    this.root.classList.toggle("no-names", !this.showNames);
    this.gBeams.style.display = this.showBeams ? "" : "none";
  }

  // the zoom slider (%): 100 = fit
  setZoom(pct) {
    if (pct === 100) return this.fitView();
    const cur = this.view ? this.box[2] / this.view[2] * 100 : 100;
    this.zoomBy(pct / cur);
  }


  // which way an effect runs across the layout: {angle} (degrees, 0 = left to right) or
  // {radial: "out" | "in"}; null hides it
  setArrow(arrow) {
    this.arrow = arrow;
    this.gArrow.replaceChildren();
    if (!arrow || !this.size) return;
    const [x0, y0, w, h] = this.box;
    const cx = (x0 + w / 2) * C, cy = (y0 + h / 2) * C, len = Math.min(w, h) * 0.38 * C;
    if (arrow.radial) {
      for (const a of [0, 90, 180, 270]) {
        const r = (a * Math.PI) / 180;
        const [x1, y1, x2, y2] = arrow.radial === "out"
          ? [cx, cy, cx + Math.cos(r) * len, cy + Math.sin(r) * len]
          : [cx + Math.cos(r) * len, cy + Math.sin(r) * len, cx + Math.cos(r) * len * 0.25, cy + Math.sin(r) * len * 0.25];
        this.gArrow.append(svg("line", { x1, y1, x2, y2, "marker-end": "url(#arrowhead)" }));
      }
    } else {
      const r = ((arrow.angle || 0) * Math.PI) / 180;
      this.gArrow.append(svg("line", { x1: cx - Math.cos(r) * len, y1: cy - Math.sin(r) * len,
                                       x2: cx + Math.cos(r) * len, y2: cy + Math.sin(r) * len, "marker-end": "url(#arrowhead)" }));
    }
    if (!this.root.querySelector("#arrowhead")) {
      const defs = svg("defs", {}, svg("marker", { id: "arrowhead", viewBox: "0 0 10 10", refX: 7, refY: 5, markerWidth: 5,
                                                   markerHeight: 5, orient: "auto-start-reverse" }, svg("path", { d: "M0 0 L10 5 L0 10 z" })));
      this.root.prepend(defs);
    }
  }
  setNames(on) { this.showNames = on; this.fit(); this.applyView(); }
  setBeams(on) { this.showBeams = on; this.fit(); this.applyView(); }

  // ---------------------------------------------------------------- live colours + beams

  update(fixtures, haze) {
    this.lastFixtures = fixtures;
    if (haze) this.haze = haze;
    const lit = (c) => c && c !== "#000000";
    for (const f of fixtures) {
      if (f.haze !== undefined && this.hazeIds?.includes(f.id)) { this.hazeLevel = f.haze; this.drawHaze(); continue; }
      const it = this.items[f.id];
      if (!it) continue;
      if (f.pixels) {
        it.cells.forEach((r, i) => {
          const c = f.pixels[i];
          r.style.fill = lit(c) ? c : "";
        });
      } else {
        for (const r of it.cells) r.style.fill = lit(f.colour) ? f.colour : "";
      }
      if (it.beam && f.pan !== undefined) this.drawBeam(f, it.beam, lit(f.colour));
    }
  }

  drawBeam(f, line, on) {
    const p = this.layout[f.id], fx = this.fixtures[f.id];
    let ang = (p.rot || 0) + (f.pan - 0.5) * (fx.pan_range || 540);
    const t = f.tilt - 0.5;
    const len = 0.6 + 2.6 * Math.min(1, Math.abs(t) * 2);
    if (t < 0) ang += 180;
    const a = (ang * Math.PI) / 180;
    line.setAttribute("x1", p.x * C);
    line.setAttribute("y1", p.y * C);
    line.setAttribute("x2", (p.x - Math.sin(a) * len) * C);
    line.setAttribute("y2", (p.y + Math.cos(a) * len) * C);
    line.setAttribute("stroke", on ? f.colour : "var(--muted)");
    line.classList.toggle("dark", !on);
  }

  // ---------------------------------------------------------------- selection

  select(ids, add = false) {
    if (!add) this.selected.clear();
    for (const id of ids) if (this.layout[id] && this.items[id]) this.selected.add(id); // not the haze machine
    this.markSelection();
    this.onChange("select");
  }

  toggle(id) {
    if (this.selected.has(id)) this.selected.delete(id);
    else this.selected.add(id);
    this.markSelection();
    this.onChange("select");
  }

  // a dashed outline on lights something is holding (busk buttons)
  mark(ids) {
    const set = new Set(ids);
    for (const [id, it] of Object.entries(this.items)) it.g.classList.toggle("held", set.has(id));
  }

  markSelection() {
    for (const [id, it] of Object.entries(this.items)) it.g.classList.toggle("sel", this.selected.has(id));
  }

  toCells(ev) {
    const pt = this.root.createSVGPoint();
    pt.x = ev.clientX;
    pt.y = ev.clientY;
    const p = pt.matrixTransform(this.root.getScreenCTM().inverse());
    return [p.x / C, p.y / C];
  }

  bindPointer() {
    let drag = null, marquee = null;
    this.root.addEventListener("pointerdown", (ev) => {
      if (ev.button !== 0) return;
      ev.preventDefault();
      const hit = ev.target.closest("[data-id]");
      const at = this.toCells(ev);
      this.root.setPointerCapture(ev.pointerId);
      if (hit) {
        const id = hit.dataset.id;
        if (this.tool === "move" && this.edit) {
          if (!this.selected.has(id)) this.select([id], ev.shiftKey);
          drag = { at, from: Object.fromEntries([...this.selected].map((k) => [k, { ...this.layout[k] }])), moved: false,
                   before: JSON.stringify(this.layout) };
        } else if (ev.shiftKey || ev.ctrlKey || ev.metaKey) this.toggle(id);
        else this.select([id]);
        return;
      }
      marquee = { start: at, points: [at], add: ev.shiftKey, shape: this.tool === "lasso" ? svg("path", { class: "marquee" }) : svg("rect", { class: "marquee" }) };
      this.gMarquee.replaceChildren(marquee.shape);
    });
    this.root.addEventListener("pointermove", (ev) => {
      if (drag) {
        const [x, y] = this.toCells(ev);
        const dx = half(x - drag.at[0]), dy = half(y - drag.at[1]);
        if (!dx && !dy && !drag.moved) return;
        drag.moved = true;
        for (const [id, p] of Object.entries(drag.from)) {
          this.layout[id].x = clamp(p.x + dx);
          this.layout[id].y = clamp(p.y + dy);
          this.drawLight(id);
        }
        this.markSelection();
        if (this.lastFixtures) this.update(this.lastFixtures);
      } else if (marquee) {
        const at = this.toCells(ev);
        marquee.points.push(at);
        if (this.tool === "lasso") {
          marquee.shape.setAttribute("d", "M" + marquee.points.map(([x, y]) => `${x * C} ${y * C}`).join(" L") + " Z");
        } else {
          const [x0, y0] = marquee.start;
          marquee.shape.setAttribute("x", Math.min(x0, at[0]) * C);
          marquee.shape.setAttribute("y", Math.min(y0, at[1]) * C);
          marquee.shape.setAttribute("width", Math.abs(at[0] - x0) * C);
          marquee.shape.setAttribute("height", Math.abs(at[1] - y0) * C);
        }
      }
    });
    const end = (ev) => {
      if (drag) {
        if (drag.moved) {
          this.history.push(drag.before);
          this.fit();
          this.onChange("move");
        }
        drag = null;
      } else if (marquee) {
        const pts = marquee.points;
        const last = pts[pts.length - 1];
        let ids;
        if (this.tool === "lasso" && pts.length > 2) {
          ids = Object.keys(this.items).filter((id) => inPolygon([this.layout[id].x, this.layout[id].y], pts));
        } else {
          const [x0, y0] = marquee.start;
          const [x1, x2] = [Math.min(x0, last[0]), Math.max(x0, last[0])];
          const [y1, y2] = [Math.min(y0, last[1]), Math.max(y0, last[1])];
          ids = Object.keys(this.items).filter((id) => {
            const p = this.layout[id];
            return p.x >= x1 && p.x <= x2 && p.y >= y1 && p.y <= y2;
          });
        }
        this.select(ids, marquee.add);
        this.gMarquee.replaceChildren();
        marquee = null;
      }
      if (ev && this.root.hasPointerCapture?.(ev.pointerId)) this.root.releasePointerCapture(ev.pointerId);
    };
    this.root.addEventListener("pointerup", end);
    this.root.addEventListener("pointercancel", end);
  }

  // ---------------------------------------------------------------- arranging (edit mode)

  change(fn) {
    const ids = [...this.selected];
    if (!ids.length) return false;
    const before = JSON.stringify(this.layout);
    fn(ids);
    if (JSON.stringify(this.layout) === before) return false;
    this.history.push(before);
    for (const id of ids) this.drawLight(id);
    this.fit();
    this.markSelection();
    if (this.lastFixtures) this.update(this.lastFixtures);
    this.onChange("move");
    return true;
  }

  extent(id) {
    const cs = this.cellsOf(id);
    const xs = cs.map(([x]) => x), ys = cs.map(([, y]) => y);
    return { left: Math.min(...xs), right: Math.max(...xs), top: Math.min(...ys), bottom: Math.max(...ys) };
  }

  align(edge) {
    return this.change((ids) => {
      const ex = Object.fromEntries(ids.map((id) => [id, this.extent(id)]));
      const P = (id) => this.layout[id];
      if (edge === "left") { const v = Math.min(...ids.map((id) => ex[id].left)); ids.forEach((id) => (P(id).x = half(P(id).x - ex[id].left + v))); }
      if (edge === "right") { const v = Math.max(...ids.map((id) => ex[id].right)); ids.forEach((id) => (P(id).x = half(P(id).x - ex[id].right + v))); }
      if (edge === "top") { const v = Math.min(...ids.map((id) => ex[id].top)); ids.forEach((id) => (P(id).y = half(P(id).y - ex[id].top + v))); }
      if (edge === "bottom") { const v = Math.max(...ids.map((id) => ex[id].bottom)); ids.forEach((id) => (P(id).y = half(P(id).y - ex[id].bottom + v))); }
      if (edge === "hcentre") { const v = half(ids.reduce((s, id) => s + P(id).x, 0) / ids.length); ids.forEach((id) => (P(id).x = v)); }
      if (edge === "vcentre") { const v = half(ids.reduce((s, id) => s + P(id).y, 0) / ids.length); ids.forEach((id) => (P(id).y = v)); }
    });
  }

  distribute(axis) {
    return this.change((ids) => {
      if (ids.length < 3) return;
      const k = axis === "h" ? "x" : "y";
      const sorted = ids.slice().sort((a, b) => this.layout[a][k] - this.layout[b][k]);
      const lo = this.layout[sorted[0]][k], hi = this.layout[sorted[sorted.length - 1]][k];
      sorted.forEach((id, i) => (this.layout[id][k] = half(lo + ((hi - lo) * i) / (sorted.length - 1))));
    });
  }

  // put the selected lights in a row, a ring or a grid around where they are now
  make(shape) {
    return this.change((ids) => {
      ids.sort((a, b) => this.layout[a].x - this.layout[b].x || this.layout[a].y - this.layout[b].y);
      const cx = ids.reduce((s, id) => s + this.layout[id].x, 0) / ids.length;
      const cy = ids.reduce((s, id) => s + this.layout[id].y, 0) / ids.length;
      const step = Math.max(...ids.map((id) => { const e = this.extent(id); return Math.max(e.right - e.left, e.bottom - e.top); })) + 1.5;
      const spots = cellOffsets(ids.length, shape, 0).map(([x, y]) => [x * step, y * step]);
      ids.forEach((id, i) => {
        this.layout[id].x = clamp(half(cx + spots[i][0]));
        this.layout[id].y = clamp(half(cy + spots[i][1]));
      });
    });
  }

  rotate(deg) {
    return this.change((ids) => ids.forEach((id) => (this.layout[id].rot = (((this.layout[id].rot || 0) + deg) % 360 + 360) % 360)));
  }

  setShape(shape) {
    return this.change((ids) => ids.filter((id) => (this.fixtures[id].pixels || 1) > 1).forEach((id) => (this.layout[id].shape = shape)));
  }

  undo() {
    const prev = this.history.pop();
    if (!prev) return false;
    this.layout = JSON.parse(prev);
    for (const id of Object.keys(this.items)) this.drawLight(id);
    this.fit();
    this.markSelection();
    if (this.lastFixtures) this.update(this.lastFixtures);
    this.onChange("move");
    return true;
  }

  get dirty() {
    return JSON.stringify(this.layout) !== this.saved;
  }
}
