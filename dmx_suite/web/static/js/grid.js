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
export function cellOffsets(n, shape = "row", cols = 0) {
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
    this.items = {};
    for (const f of cat.fixtures) if (this.layout[f.id]) this.drawLight(f.id);
    this.fit();
    this.applyView();
    if (this.selectable) this.bindPointer();
    this.host.replaceChildren(this.root);
    if (this.arrow) this.setArrow(this.arrow);
    this.markSelection();
    if (this.lastFixtures) this.update(this.lastFixtures);
  }

  cellsOf(id) {
    const f = this.fixtures[id], p = this.layout[id];
    return cellOffsets(f.pixels || 1, p.shape, p.cols).map((o) => {
      const [dx, dy] = rotated(o, p.rot || 0);
      return [p.x + dx, p.y + dy];
    });
  }

  drawLight(id) {
    const f = this.fixtures[id];
    const old = this.items[id];
    const g = svg("g", { class: `fx ${f.kind}`, "data-id": id });
    const cells = this.cellsOf(id).map(([x, y]) => {
      const r = svg("rect", { x: (x - SIZE / 2) * C, y: (y - SIZE / 2) * C, width: SIZE * C, height: SIZE * C, rx: 3, class: "cell" });
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
    g.append(label);
    const beam = f.moves ? svg("line", { class: "beam" }) : null;
    if (old) {
      old.g.replaceWith(g);
      if (old.beam) old.beam.remove();
    } else this.gLights.append(g);
    if (beam) this.gBeams.append(beam);
    this.items[id] = { g, cells, beam };
  }

  // size the drawing to what's on it (plus room to drag things further when editing)
  fit() {
    let maxX = 16, maxY = 10;
    for (const id of Object.keys(this.items)) {
      for (const [x, y] of this.cellsOf(id)) {
        maxX = Math.max(maxX, x + 1.5);
        maxY = Math.max(maxY, y + 2);
      }
    }
    if (this.edit) {
      maxX += 6;
      maxY += 4;
    }
    this.size = [Math.ceil(maxX), Math.ceil(maxY)];
    const m = this.showBeams ? 3 : 0; // room round the edge for beam lines
    this.root.setAttribute("viewBox", `${-m * C} ${-m * C} ${(this.size[0] + 2 * m) * C} ${(this.size[1] + 2 * m) * C}`);
    this.gGrid.replaceChildren();
    if (this.edit) {
      for (let x = 0; x <= this.size[0]; x++) this.gGrid.append(svg("line", { x1: x * C, y1: 0, x2: x * C, y2: this.size[1] * C }));
      for (let y = 0; y <= this.size[1]; y++) this.gGrid.append(svg("line", { x1: 0, y1: y * C, x2: this.size[0] * C, y2: y * C }));
    }
  }

  applyView() {
    if (this.edit) this.root.style.width = this.zoom + "%"; // the live view always fits its box
    this.root.classList.toggle("no-names", !this.showNames);
    this.gBeams.style.display = this.showBeams ? "" : "none";
  }

  setZoom(pct) { this.zoom = pct; this.applyView(); }

  // which way an effect runs across the layout: {angle} (degrees, 0 = left to right) or
  // {radial: "out" | "in"}; null hides it
  setArrow(arrow) {
    this.arrow = arrow;
    this.gArrow.replaceChildren();
    if (!arrow || !this.size) return;
    const [w, h] = this.size;
    const cx = (w / 2) * C, cy = (h / 2) * C, len = Math.min(w, h) * 0.38 * C;
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
  setNames(on) { this.showNames = on; this.applyView(); }
  setBeams(on) { this.showBeams = on; this.fit(); this.applyView(); }

  // ---------------------------------------------------------------- live colours + beams

  update(fixtures) {
    this.lastFixtures = fixtures;
    const lit = (c) => c && c !== "#000000";
    for (const f of fixtures) {
      const it = this.items[f.id];
      if (!it) continue;
      if (f.pixels) {
        it.cells.forEach((r, i) => {
          const c = f.pixels[i];
          r.style.fill = lit(c) ? c : "";
        });
      } else if (f.haze !== undefined) {
        it.g.classList.toggle("on", f.haze > 0);
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
    for (const id of ids) if (this.layout[id]) this.selected.add(id);
    this.markSelection();
    this.onChange("select");
  }

  toggle(id) {
    if (this.selected.has(id)) this.selected.delete(id);
    else this.selected.add(id);
    this.markSelection();
    this.onChange("select");
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
