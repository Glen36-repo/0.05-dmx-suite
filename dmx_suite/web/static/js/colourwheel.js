// Colour wheel (v3.1): hue/saturation wheel, brightness, hex and RGB, white/amber/UV when the lights
// have them, white temperature presets, palette/recent/named swatches, pick from a light, what each
// light can really make, and a throttled live preview on the rig.
//   openWheel({ value, fixtures, onPick }) -> value is "#rrggbb", a named colour, or {red, ..., uv}
import { api, get } from "./api.js";
import { $, el, remember } from "./dom.js";
import { t } from "./i18n.js";
import { live } from "./state.js";

const EXTRA = ["white", "amber", "uv"];
let kelvins = null;

const clamp = (x) => Math.min(1, Math.max(0, x));
const hex2 = (x) => Math.round(clamp(x) * 255).toString(16).padStart(2, "0");
export const toHex = (c) => "#" + hex2(c.red || 0) + hex2(c.green || 0) + hex2(c.blue || 0);
const fromHex = (h) => ({ red: parseInt(h.slice(1, 3), 16) / 255, green: parseInt(h.slice(3, 5), 16) / 255, blue: parseInt(h.slice(5, 7), 16) / 255 });

function hsv(c) {
  const r = c.red || 0, g = c.green || 0, b = c.blue || 0;
  const v = Math.max(r, g, b), d = v - Math.min(r, g, b);
  let h = 0;
  if (d) h = v === r ? ((g - b) / d) % 6 : v === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return { h: ((h * 60) + 360) % 360, s: v ? d / v : 0, v };
}

function rgb(h, s, v) {
  const f = (n) => { const k = (n + h / 60) % 6; return v - v * s * Math.max(0, Math.min(k, 4 - k, 1)); };
  return { red: f(5), green: f(3), blue: f(1) };
}

function recent() { return remember.get("wheel.recent", []); }
function addRecent(hex) { remember.set("wheel.recent", [hex, ...recent().filter((x) => x !== hex)].slice(0, 10)); }

function dialog() {
  let d = $("#wheel-dialog");
  if (!d) {
    d = el("dialog", { id: "wheel-dialog", class: "wizard-dialog wheel-dialog" });
    document.body.append(d);
  }
  return d;
}

export async function openWheel({ value, fixtures = [], names = null, onPick }) {
  kelvins = kelvins || (await get("/api/kelvin"));
  const fxCat = await get("/api/effects");
  names = names || fxCat.colours;
  const cat = live.cat || { fixtures: [], groups: {} };
  const ids = new Set(fixtures.flatMap((n) => (n === "all" ? cat.fixtures.map((f) => f.id) : cat.groups?.[n] || [n])));
  const lights = cat.fixtures.filter((f) => ids.has(f.id) && (f.emitters || []).length);
  const has = new Set(lights.flatMap((f) => f.emitters || []));
  let col = typeof value === "object" && value ? { ...value } : typeof value === "string" && value.startsWith("#") ? fromHex(value)
    : names[value] ? fromHex(names[value]) : { red: 1, green: 1, blue: 1 };
  let { h, s, v } = hsv(col);
  let previewOn = remember.get("wheel.preview", false);
  let lastPreview = 0;

  const size = 220;
  const canvas = el("canvas", { width: size, height: size, class: "wheel", "aria-label": t("wheel.title") });
  const ctx = canvas.getContext("2d");
  const img = ctx.createImageData(size, size);
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const dx = x - size / 2, dy = y - size / 2, r = Math.hypot(dx, dy) / (size / 2);
    const i = (y * size + x) * 4;
    if (r > 1) { img.data[i + 3] = 0; continue; }
    const c = rgb((Math.atan2(dy, dx) * 180 / Math.PI + 360) % 360, r, 1);
    img.data[i] = c.red * 255; img.data[i + 1] = c.green * 255; img.data[i + 2] = c.blue * 255; img.data[i + 3] = 255;
  }
  ctx.putImageData(img, 0, 0);
  const marker = el("div", { class: "wheel-pt" });
  const wheelBox = el("div", { class: "wheel-box" }, canvas, marker);
  const bright = el("input", { type: "range", min: 0, max: 100, value: Math.round(v * 100), "aria-label": t("wheel.brightness") });
  const hexIn = el("input", { class: "narrow hex", maxlength: 7, "aria-label": "hex" });
  const rgbIn = ["red", "green", "blue"].map((k) => el("input", { type: "number", min: 0, max: 255, class: "narrow", title: t("wheel." + k) }));
  const extras = EXTRA.filter((k) => has.has(k)).map((k) => [k, el("input", { type: "range", min: 0, max: 100, value: Math.round((col[k] || 0) * 100) })]);
  const swatchBox = el("div", { class: "swatches" });
  const fitBox = el("div", { class: "wheel-fit" });
  const out = el("div", { class: "wheel-out" });

  const value_ = () => {
    const c = { red: +col.red.toFixed(3), green: +col.green.toFixed(3), blue: +col.blue.toFixed(3) };
    for (const [k] of extras) if (col[k]) c[k] = +col[k].toFixed(3);
    return Object.keys(c).some((k) => EXTRA.includes(k)) ? c : toHex(c);
  };

  let fitTimer;
  const draw = (fromWheel = true) => {
    if (fromWheel) col = { ...col, ...rgb(h, s, v) };
    const rad = (size / 2) * s, a = h * Math.PI / 180;
    marker.style.left = size / 2 + rad * Math.cos(a) + "px";
    marker.style.top = size / 2 + rad * Math.sin(a) + "px";
    const hx = toHex(col);
    hexIn.value = hx;
    rgbIn.forEach((i, n) => (i.value = Math.round((col[["red", "green", "blue"][n]] || 0) * 255)));
    out.style.background = hx;
    out.style.color = (col.red || 0) * 0.3 + (col.green || 0) * 0.6 + (col.blue || 0) * 0.1 > 0.55 ? "#000" : "#fff";
    out.textContent = typeof value_() === "string" ? hx : t("wheel.with_extras");
    clearTimeout(fitTimer);
    fitTimer = setTimeout(checkFit, 120);
    if (previewOn && !live.state?.gig_lock && performance.now() - lastPreview > 250 && fixtures.length) {
      lastPreview = performance.now();
      api("POST", "/api/preview", { scene_data: { name: t("wheel.title"), layers: [{ fixtures, colour: value_() }] }, seconds: 4 }).catch(() => {});
    }
  };

  async function checkFit() {
    if (!lights.length) return fitBox.replaceChildren();
    try {
      const r = await api("POST", "/api/colour/preview", { colour: value_(), fixtures: lights.map((f) => f.id) });
      fitBox.replaceChildren(...r.fixtures.map((f) => el("span", {
        class: "fit" + (f.differs ? " differs" : ""), title: f.differs ? t("wheel.differs", { id: f.id, slot: f.slot || f.shown }) : f.id,
      }, el("i", { style: `background:${f.shown || "#000"}` }), f.id + (f.slot ? ` · ${f.slot}` : ""))));
    } catch { /* a light without colour: nothing to show */ }
  }

  const pickAt = (ev) => {
    const r = canvas.getBoundingClientRect();
    const dx = ev.clientX - r.left - r.width / 2, dy = ev.clientY - r.top - r.height / 2;
    h = (Math.atan2(dy, dx) * 180 / Math.PI + 360) % 360;
    s = clamp(Math.hypot(dx, dy) / (r.width / 2));
    if (v === 0) { v = 1; bright.value = 100; }
    draw();
  };
  let dragging = false;
  canvas.addEventListener("pointerdown", (e) => { dragging = true; canvas.setPointerCapture(e.pointerId); pickAt(e); });
  canvas.addEventListener("pointermove", (e) => dragging && pickAt(e));
  canvas.addEventListener("pointerup", () => (dragging = false));
  bright.oninput = () => { v = bright.value / 100; draw(); };
  hexIn.onchange = () => { if (/^#[0-9a-f]{6}$/i.test(hexIn.value)) { col = { ...col, ...fromHex(hexIn.value) }; ({ h, s, v } = hsv(col)); bright.value = Math.round(v * 100); draw(false); } };
  rgbIn.forEach((i, n) => (i.onchange = () => { col[["red", "green", "blue"][n]] = clamp(+i.value / 255); ({ h, s, v } = hsv(col)); bright.value = Math.round(v * 100); draw(false); }));
  for (const [k, input] of extras) input.oninput = () => { col[k] = input.value / 100; draw(false); };

  const setHex = (hx) => { col = { ...col, ...fromHex(hx) }; ({ h, s, v } = hsv(col)); bright.value = Math.round(v * 100); draw(false); };
  const chip = (hx, title, onclick) => el("button", { class: "sw", title, style: `background:${hx}`, onclick: onclick || (() => setHex(hx)) });
  const pal = Object.values(fxCat.palettes || {});
  const named = Object.entries(names).filter(([n]) => n !== "off" && n !== "black");
  swatchBox.replaceChildren(
    ...(recent().length ? [el("span", { class: "muted", text: t("wheel.recent") }), ...recent().map((hx) => chip(hx, hx))] : []),
    el("span", { class: "muted", text: t("wheel.named") }),
    ...named.map(([n, hx]) => chip(hx, n, () => finish(n, hx))),
    ...pal.slice(0, 3).flatMap((p) => [el("span", { class: "muted", text: p.name }), ...p.hex.map((hx) => chip(hx, p.name))]));

  const kelvinRow = el("div", { class: "row wrap" }, el("span", { class: "muted", text: t("wheel.white_temp") }),
    ...kelvins.map((k) => el("button", { class: "sw kelvin", style: `background:${k.hex}`, title: `${k.name} ${k.kelvin} K`,
      onclick: () => { setHex(k.hex); if (has.has("white")) { const x = extras.find(([n]) => n === "white"); if (x) { col.white = 0; x[1].value = 0; } } } })));

  const eyedrop = el("select", { "aria-label": t("wheel.eyedropper"), onchange: (e) => {
    const f = (live.state?.fixtures || []).find((x) => x.id === e.target.value);
    if (f && f.colour) setHex(f.colour);
    e.target.value = "";
  } }, el("option", { value: "" }, t("wheel.eyedropper")),
  ...(live.state?.fixtures || []).filter((f) => f.colour).map((f) => el("option", { value: f.id }, f.id)));

  const previewBox = el("label", { class: "row" }, el("input", { type: "checkbox", checked: previewOn || undefined,
    disabled: live.state?.gig_lock || !fixtures.length || undefined,
    onchange: (e) => { previewOn = e.target.checked; remember.set("wheel.preview", previewOn); if (previewOn) draw(false); } }),
  el("span", { text: t(live.state?.gig_lock ? "wheel.preview_locked" : "wheel.preview") }));

  function finish(val, hx) {
    addRecent(hx || toHex(col));
    d.close();
    onPick(val);
  }

  const d = dialog();
  d.replaceChildren(el("form", { method: "dialog", class: "wheel-form", onsubmit: (e) => e.preventDefault() },
    el("h2", { text: t("wheel.title") }),
    el("div", { class: "wheel-main" }, wheelBox,
      el("div", { class: "wheel-side" },
        el("label", { class: "field" }, el("span", { text: t("wheel.brightness") }), bright),
        el("div", { class: "row" }, hexIn, ...rgbIn),
        ...extras.map(([k, input]) => el("label", { class: "field" }, el("span", { text: t("wheel." + k) }), input)),
        out, eyedrop, previewBox)),
    kelvinRow, swatchBox,
    el("h2", { text: t("wheel.what_lights_make") }), fitBox,
    el("div", { class: "row" },
      el("button", { type: "button", class: "sel", onclick: () => finish(value_()) }, t("wheel.use")),
      el("button", { type: "button", onclick: () => d.close() }, t("wheel.cancel")))));
  d.showModal();
  draw(false);
}
