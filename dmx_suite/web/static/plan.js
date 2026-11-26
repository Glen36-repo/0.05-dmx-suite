// Stage plan: top-down view of the rig, like Daslight's fixture view.
// Live: every light in its real spot with its live colour; moving heads draw a beam line from
// pan/tilt. Arrange mode: drag fixtures into place, rotate them, set the stage size, save.
"use strict";

const SVGNS = "http://www.w3.org/2000/svg";
const M = 40; // margin round the stage, cm
const AUD = 46; // audience strip, cm

function svg(tag, attrs = {}, ...kids) {
  const e = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  for (const k of kids) e.append(k);
  return e;
}

class StagePlan {
  constructor(host, editable = false, onChange = null) {
    this.host = host;
    this.editable = editable;
    this.onChange = onChange;
    this.selected = null;
    this.items = {};
  }

  // ---------------------------------------------------------------- geometry (metres <-> svg cm)
  sx(x) { return M + x * 100; }
  sy(y) { return M + (this.depth - y) * 100; }

  build(cat, layout = null, stage = null) {
    this.cat = cat;
    this.layout = JSON.parse(JSON.stringify(layout || cat.layout));
    this.width = (stage || cat.stage).width;
    this.depth = (stage || cat.stage).depth;
    const W = this.width * 100 + 2 * M, H = this.depth * 100 + 2 * M + AUD;
    const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "plan" + (this.editable ? " edit" : ""), role: "img",
      "aria-label": "Stage plan" });
    // stage floor with a 1 m grid
    const floor = svg("g");
    floor.append(svg("rect", { x: M, y: M, width: this.width * 100, height: this.depth * 100, rx: 6, class: "floor" }));
    for (let x = 1; x < this.width; x++) floor.append(svg("line", { x1: this.sx(x), y1: M, x2: this.sx(x), y2: M + this.depth * 100, class: "grid" }));
    for (let y = 1; y < this.depth; y++) floor.append(svg("line", { x1: M, y1: this.sy(y), x2: M + this.width * 100, y2: this.sy(y), class: "grid" }));
    const aud = svg("text", { x: W / 2, y: H - 14, class: "aud", "text-anchor": "middle" });
    aud.textContent = "AUDIENCE";
    const up = svg("text", { x: W / 2, y: M - 12, class: "aud back", "text-anchor": "middle" });
    up.textContent = "back of stage";
    floor.append(aud, up);
    root.append(floor);

    const beams = svg("g", { class: "beams" });
    const fixtures = svg("g");
    root.append(beams, fixtures);
    this.items = {};
    for (const fx of cat.fixtures) {
      if (!this.layout[fx.id]) continue;
      const g = svg("g", { class: "fx " + fx.kind, "data-id": fx.id });
      const body = svg("g");
      let parts = {};
      if (fx.kind === "head") {
        parts.ring = svg("circle", { r: 19, class: "rim" });
        parts.lamp = svg("circle", { r: 15, class: "lamp" });
        body.append(parts.ring, parts.lamp);
        if (fx.colour_only) body.append(svg("circle", { r: 5, class: "dotc" }));
      } else if (fx.kind === "bar") {
        const n = Math.max(1, fx.pixels || 1), len = 100, pw = len / n;
        body.append(svg("rect", { x: -len / 2 - 3, y: -9, width: len + 6, height: 18, rx: 3, class: "rim" }));
        parts.px = [];
        for (let i = 0; i < n; i++) {
          const r = svg("rect", { x: -len / 2 + i * pw + 1, y: -6, width: pw - 2, height: 12, rx: 1.5, class: "lamp" });
          parts.px.push(r);
          body.append(r);
        }
      } else if (fx.kind === "wash") {
        body.append(svg("rect", { x: -22, y: -14, width: 44, height: 28, rx: 7, class: "rim" }));
        parts.lamp = svg("rect", { x: -18, y: -10, width: 36, height: 20, rx: 5, class: "lamp" });
        body.append(parts.lamp);
      } else if (fx.kind === "kick") {
        body.append(svg("circle", { r: 30, class: "rim" }));
        parts.lamp = svg("circle", { r: 25, class: "lamp" });
        body.append(parts.lamp);
      } else {
        parts.lamp = svg("rect", { x: -24, y: -11, width: 48, height: 22, rx: 11, class: "lamp haze" });
        const t = svg("text", { y: 4, "text-anchor": "middle", class: "hz" });
        t.textContent = "HAZE";
        body.append(parts.lamp, t);
      }
      // a little nose shows which way a fixture faces (rot 0 = towards the audience)
      const edge = { head: 20, bar: 10, wash: 15 }[fx.kind];
      if (edge) body.append(svg("path", { d: `M -5 ${edge} L 0 ${edge + 7} L 5 ${edge} Z`, class: "nose" }));
      const label = svg("text", { "text-anchor": "middle", class: "label" });
      label.textContent = fx.id;
      g.append(body, label);
      fixtures.append(g);
      const beam = fx.kind === "head" && fx.moves ? svg("line", { class: "beam" }) : null;
      if (beam) beams.append(beam);
      this.items[fx.id] = { fx, g, body, label, beam, parts };
      this.place(fx.id);
      if (this.editable) this.dragify(g, fx.id);
    }
    this.root = root;
    this.host.replaceChildren(root);
    if (this.editable) this.select(this.selected && this.items[this.selected] ? this.selected : null);
  }

  place(id) {
    const it = this.items[id], p = this.layout[id];
    const x = this.sx(p.x), y = this.sy(p.y);
    it.g.setAttribute("transform", `translate(${x} ${y})`);
    it.body.setAttribute("transform", `rotate(${p.rot || 0})`);
    const below = { head: 44, bar: 34, wash: 40, kick: 48, haze: 30 }[it.fx.kind] || 40;
    it.label.setAttribute("y", below);
  }

  // ---------------------------------------------------------------- live colours + beams
  update(fixtures) {
    for (const f of fixtures) {
      const it = this.items[f.id];
      if (!it) continue;
      const lit = (c) => c && c !== "#000000";
      if (f.pixels && it.parts.px) {
        f.pixels.forEach((c, i) => it.parts.px[i] && (it.parts.px[i].style.fill = lit(c) ? c : ""));
      } else if (f.haze !== undefined) {
        it.parts.lamp.classList.toggle("on", f.haze > 0);
      } else if (it.parts.lamp) {
        it.parts.lamp.style.fill = lit(f.colour) ? f.colour : "";
        it.parts.lamp.style.filter = lit(f.colour) ? `drop-shadow(0 0 10px ${f.colour})` : "none";
      }
      if (it.beam && f.pan !== undefined) {
        const p = this.layout[f.id];
        let ang = (p.rot || 0) + (f.pan - 0.5) * it.fx.pan_range;
        const t = f.tilt - 0.5;
        const len = 26 + 120 * Math.min(1, Math.abs(t) * 2);
        if (t < 0) ang += 180;
        const rad = (ang * Math.PI) / 180;
        const x = this.sx(p.x), y = this.sy(p.y);
        it.beam.setAttribute("x1", x);
        it.beam.setAttribute("y1", y);
        it.beam.setAttribute("x2", x - Math.sin(rad) * len);
        it.beam.setAttribute("y2", y + Math.cos(rad) * len);
        const on = lit(f.colour);
        it.beam.setAttribute("stroke", on ? f.colour : "#3a3a46");
        it.beam.classList.toggle("dark", !on);
      }
    }
  }

  // ---------------------------------------------------------------- arrange mode
  select(id) {
    this.selected = id;
    for (const [k, it] of Object.entries(this.items)) it.g.classList.toggle("sel", k === id);
    if (this.onChange) this.onChange("select", id);
  }

  toStage(ev) {
    const pt = this.root.createSVGPoint();
    pt.x = ev.clientX;
    pt.y = ev.clientY;
    const p = pt.matrixTransform(this.root.getScreenCTM().inverse());
    const snap = (v) => Math.round(v * 20) / 20; // 5 cm
    return {
      x: Math.min(this.width, Math.max(0, snap((p.x - M) / 100))),
      y: Math.min(this.depth, Math.max(0, snap(this.depth - (p.y - M) / 100))),
    };
  }

  dragify(g, id) {
    let drag = null;
    g.addEventListener("pointerdown", (ev) => {
      ev.preventDefault();
      this.select(id);
      const start = this.toStage(ev), p = this.layout[id];
      drag = { dx: p.x - start.x, dy: p.y - start.y };
      g.setPointerCapture(ev.pointerId);
    });
    g.addEventListener("pointermove", (ev) => {
      if (!drag) return;
      const s = this.toStage(ev), p = this.layout[id];
      p.x = Math.min(this.width, Math.max(0, Math.round((s.x + drag.dx) * 20) / 20));
      p.y = Math.min(this.depth, Math.max(0, Math.round((s.y + drag.dy) * 20) / 20));
      this.place(id);
      if (this.onChange) this.onChange("move", id);
    });
    const end = () => (drag = null);
    g.addEventListener("pointerup", end);
    g.addEventListener("pointercancel", end);
  }

  rotate(deg) {
    if (!this.selected) return;
    const p = this.layout[this.selected];
    p.rot = (((p.rot || 0) + deg) % 360 + 360) % 360;
    this.place(this.selected);
    if (this.onChange) this.onChange("move", this.selected);
  }
}

window.StagePlan = StagePlan;
