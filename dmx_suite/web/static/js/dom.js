// Small DOM helpers shared by every view.
export const $ = (s, root = document) => root.querySelector(s);
export const $$ = (s, root = document) => [...root.querySelectorAll(s)];

export function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k === "text") e.textContent = v;
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids) if (k !== null && k !== undefined) e.append(k);
  return e;
}

const SVGNS = "http://www.w3.org/2000/svg";
export function svg(tag, attrs = {}, ...kids) {
  const e = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== undefined && v !== null) e.setAttribute(k, v);
  for (const k of kids) e.append(k);
  return e;
}

// Per-screen conveniences (collapsed menu, zoom). Never needed for anything to work.
export const remember = {
  get(key, fallback) {
    try {
      const v = localStorage.getItem("dmx." + key);
      return v === null ? fallback : JSON.parse(v);
    } catch {
      return fallback;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem("dmx." + key, JSON.stringify(value));
    } catch {}
  },
};

// Motion on this screen (Setup › Appearance): auto follows the device's "reduce motion"; reduce / full override it
export function applyMotion(m = remember.get("motion", "auto")) {
  document.body.classList.toggle("reduce-motion", m === "reduce");
  document.body.classList.toggle("motion-full", m === "full");
}

export function reducedMotion() {
  const m = remember.get("motion", "auto");
  return m === "reduce" || (m === "auto" && matchMedia("(prefers-reduced-motion: reduce)").matches);
}
