// Autopilot page (v3.4 "Ride page"): ride the auto show live. Autopilot, mood and hold along the top; Move FX on the
// left, Flash FX in the middle, Colour FX on the right; drum FX, palettes and ride faders below; the
// haze controls stay alongside (separate: the auto show never touches haze). Big touch targets.
// "Learn" makes any control MIDI/OSC-learnable: tap it, then hit a pad or press a pedal.
import { api, attempt, cmd, get, toast } from "../api.js";
import { $, el } from "../dom.js";
import { LightGrid } from "../grid.js";
import { t } from "../i18n.js";
import { go, onLeave, onShow } from "../nav.js";
import { review } from "./review.js";
import { live, onCatalogue, onState } from "../state.js";

let fx = null; // /api/fx
let grid = null;
let learning = false;
let excluding = false; // Exclude mode: a tap on a type leaves it out of the autopilot (or puts it back)
const HOLD_MS = 600; // long-press on a type does the same, any time
let bank = ""; // fader tab: "" = everything, or move / colour / drum
const FADERS = ["speed", "fade", "fan", "size", "shift"];
const CLASSES = ["head", "wash", "pixel", "strobe", "effect"];

function act(action, params = {}, level) {
  if (learning) {
    learning = false;
    $("#ride-learn").classList.remove("sel");
    return attempt(() => api("POST", "/api/autopilot/learn", { action, params }), (r) => r.message);
  }
  return attempt(() => api("POST", "/api/autopilot/action", { action, ...params, ...(level !== undefined ? { level } : {}) }));
}

function fxTitle(item) {
  return `${item.label} · ${t("autopilot.busy", { n: Math.round(item.busy * 100) })}` + (item.excluded ? ` · ${t("autopilot.excluded_tip")}` : "");
}

// a type button: tap plays it (or, in Exclude mode, leaves it out / puts it back); hold to exclude any time
function fxButton(item, onClick) {
  const b = el("button", { class: "ride-fx" + (item.excluded ? " excluded" : ""), "data-fx": item.id, title: fxTitle(item) }, item.label);
  let timer = null, held = false;
  const cancel = () => { clearTimeout(timer); timer = null; };
  b.addEventListener("pointerdown", (e) => {
    if (e.button > 0) return;
    held = false;
    cancel();
    timer = setTimeout(() => { held = true; timer = null; navigator.vibrate?.(15); toggleExcluded(item, b); }, HOLD_MS);
  });
  for (const ev of ["pointerup", "pointerleave", "pointercancel"]) b.addEventListener(ev, cancel);
  b.addEventListener("contextmenu", (e) => e.preventDefault()); // a long touch mustn't open the browser's menu
  b.addEventListener("click", (e) => {
    if (held) { held = false; e.preventDefault(); return; } // the long-press already did its job
    if (excluding && !learning) return toggleExcluded(item, b);
    onClick();
  });
  return b;
}

async function toggleExcluded(item, b) {
  const want = !item.excluded;
  item.excluded = want; // shown at once; put back if the laptop says no
  b.classList.toggle("excluded", want);
  b.title = fxTitle(item);
  try {
    await api("POST", "/api/autopilot/exclude", { item: item.id, excluded: want });
    toast(t(want ? "autopilot.excluded_toast" : "autopilot.included_toast", { name: item.label }));
  } catch (err) {
    item.excluded = !want;
    b.classList.toggle("excluded", !want);
    b.title = fxTitle(item);
    toast(err.message, true);
  }
}

function setExcluding(on) {
  excluding = on;
  $("#ride-exclude").classList.toggle("on", on);
  $("#ride-exclude").textContent = t(on ? "autopilot.exclude_done" : "autopilot.exclude");
  $("#page-autopilot").classList.toggle("excluding", on);
  if (on) toast(t("autopilot.exclude_help"));
}

function flashButton(item) {
  const b = el("button", { class: "ride-fx flash", "data-flash": item.id }, item.label);
  const down = (e) => {
    e.preventDefault();
    if (learning) return act("flash_fx", { fx: item.id });
    b.classList.add("on");
    api("POST", "/api/flashfx", { fx: item.id, down: true, colour: "show" }).catch((err) => toast(err.message, true));
  };
  const up = () => {
    if (!b.classList.contains("on")) return;
    b.classList.remove("on");
    api("POST", "/api/flashfx", { fx: item.id, down: false }).catch(() => {});
  };
  b.addEventListener("pointerdown", down);
  b.addEventListener("pointerup", up);
  b.addEventListener("pointerleave", up);
  return b;
}

async function load() {
  fx = await get("/api/fx");
  render();
  loadWhy();
  loadPresets();
}

async function loadPresets() {
  const pres = await get("/api/presets");
  $("#ride-presets").replaceChildren(...Object.entries(pres).map(([k, p]) => el("button", {
    class: "ride-pal", "data-preset": k, title: p.tags.join(", "),
    onclick: () => act("preset", { preset: k }) }, p.name)));
}

function render() {
  if (!fx) return;
  const ok = fx.items.filter((i) => i.available);
  const pick = live.state?.ride?.pick || fx.pick;
  const byBank = (b) => ok.filter((i) => i.bank === b);
  $("#ride-move").replaceChildren(
    el("button", { class: "ride-fx" + (!pick.move ? " sel" : ""), "data-fx": "", onclick: () => act("autopilot_fx", { bank: "move", item: "" }) }, t("autopilot.no_move")),
    ...byBank("move").map((i) => fxButton(i, () => act("autopilot_fx", { bank: "move", item: i.id }))));
  $("#ride-colour").replaceChildren(...byBank("colour").map((i) => fxButton(i, () => act("autopilot_fx", { bank: "colour", item: i.id }))));
  $("#ride-flash").replaceChildren(...byBank("flash").map(flashButton));
  $("#ride-drum").replaceChildren(
    el("button", { class: "ride-fx" + (!pick.drum ? " sel" : ""), "data-fx": "", onclick: () => act("autopilot_fx", { bank: "drum", item: "" }) }, t("autopilot.no_drum")),
    ...byBank("drum").map((i) => fxButton(i, () => act("autopilot_fx", { bank: "drum", item: i.id }))));
  $("#ride-palettes").replaceChildren(...Object.entries(fx.palettes).map(([k, p]) => el("button", {
    class: "ride-pal", "data-palette": k, onclick: () => act("autopilot_palette", { palette: k }) }, p.name)));
  $("#ride-tabs").replaceChildren(...["", "move", "colour", "drum"].map((b) => el("button", {
    class: b === bank ? "on" : "", onclick: () => { bank = b; render(); } }, b ? t("autopilot.bank_" + b) : t("autopilot.all_banks"))));
  $("#ride-faders").replaceChildren(...FADERS.map((k) => {
    const src = bank ? pick.bank_feel?.[bank] || { speed: 1, fade: 0.5, fan: 0.5, size: 0.5, shift: 0 } : pick.feel;
    const v = k === "speed" ? (Math.log(src.speed) / Math.log(4) + 1) / 2 : src[k];
    const inp = el("input", { type: "range", min: 0, max: 1, step: 0.01, value: v, "aria-label": t("autopilot.fader_" + k) });
    let last = 0;
    inp.addEventListener("input", () => {
      const now = performance.now();
      if (now - last < 120) return;
      last = now;
      act("feel_" + k, bank ? { bank } : {}, +inp.value);
    });
    inp.addEventListener("pointerdown", (e) => { if (learning) { e.preventDefault(); act("feel_" + k, bank ? { bank } : {}); } });
    return el("label", { class: "ride-fader" }, el("span", { text: t("autopilot.fader_" + k) }), inp);
  }));
  renderLights();
  update(live.state);
}

function renderLights() {
  const rig = fx.rig;
  const rows = [];
  for (const c of CLASSES) for (const f of rig.classes[c] || []) rows.push([f, c]);
  for (const f of rig.excluded) rows.push([f, null]);
  $("#ride-lights").replaceChildren(...rows.map(([f, c]) => el("li", {},
    el("b", { text: f }),
    el("select", { onchange: (e) => saveClass(f, e.target.value) },
      ...CLASSES.map((x) => el("option", { value: x, selected: x === c || undefined }, t("autopilot.class_" + x))),
      el("option", { value: "exclude", selected: c === null || undefined }, t("autopilot.class_exclude"))))));
}

async function saveClass(fid, value) {
  const rig = fx.rig;
  const classes = {};
  const exclude = rig.excluded.filter((f) => f !== fid);
  if (value === "exclude") exclude.push(fid);
  else classes[fid] = value;
  const r = await attempt(() => api("POST", "/api/store/auto", { classes, exclude }), t("autopilot.lights_saved"));
  if (r) load();
}

async function loadWhy() {
  const r = await get("/api/autopilot?n=12");
  $("#ride-why").replaceChildren(...r.log.slice().reverse().map((d) => el("li", {
    title: t("autopilot.why_open"), onclick: () => { review.jump = d.look; go("review"); } },
    el("span", { class: "muted", text: new Date(d.time * 1000).toLocaleTimeString("en-AU", { hour12: false }) }),
    el("b", { text: [d.look.move, d.look.colour, d.look.drum].filter(Boolean).join(" + ") + " · " + d.look.palette }),
    el("span", { text: t("autopilot.why_line", { why: d.why, mood: t("autopilot.mood_" + d.mood), energy: Math.round(d.energy * 100) }) }))));
}

let lastDecision = null;

// v6 Darkness: the slider sends at most every 60 ms; the server eases it in over the look's fade
let dkLast = 0, dkTimer = null, dkHeld = false;
function sendDarkness(v) {
  clearTimeout(dkTimer);
  const go = () => { dkLast = performance.now(); api("POST", "/api/darkness", { value: v }).catch(() => null); };
  if (performance.now() - dkLast > 60) go(); else dkTimer = setTimeout(go, 60);
}

function drawDarkness(dk) {
  if (!dk) return;
  if (!dkHeld) $("#dk-slider").value = dk.darkness;
  $("#dk-val").textContent = `${Math.round(dk.darkness)} %`;
  $("#dk-src").textContent = t("darkness.src_" + dk.source) + (dk.cc ? ` · ${dk.cc.describe}` : "");
  document.querySelectorAll("#ride-darkness [data-dkset]").forEach((b) => {
    const v = dk.set_darkness[b.dataset.dkset];
    b.textContent = t("darkness.set_btn", { set: t("autopilot.mood_" + b.dataset.dkset), v: v === null ? t("darkness.none") : `${v} %` });
  });
}

function update(s) {
  if (!s || !fx || !$("#page-autopilot").classList.contains("on")) return;
  const ap = s.autopilot, pick = s.ride.pick;
  drawDarkness(ap.darkness);
  $("#ap-toggle").classList.toggle("on", ap.on);
  $("#ap-toggle").textContent = t(ap.on ? "autopilot.autopilot_on" : "autopilot.autopilot_off");
  $("#ap-hold").classList.toggle("on", ap.hold);
  document.querySelectorAll("#ride-moods [data-mood]").forEach((b) => b.classList.toggle("sel",
    b.dataset.mood === "auto" ? !ap.mood_manual : ap.mood_manual && ap.mood === b.dataset.mood));
  $("#ap-energy").style.width = Math.round(ap.energy * 100) + "%";
  $("#ap-state").textContent = [t("autopilot.mood_now", { mood: t("autopilot.mood_" + ap.mood) }),
    ap.paused ? t("autopilot.paused") : ap.between ? t("autopilot.between") : ap.next_change_s != null ? t("autopilot.next_in", { s: Math.round(ap.next_change_s) }) : "",
    t("autopilot.priority_" + s.priority.top)].filter(Boolean).join(" · ");
  const now = ap.pick || pick;
  // one green button per bank: the type running now ("No movement" / "No drum FX" when there's none)
  document.querySelectorAll("#ride-move [data-fx]").forEach((b) => b.classList.toggle("sel", b.dataset.fx === (now.move || "")));
  document.querySelectorAll("#ride-colour [data-fx]").forEach((b) => b.classList.toggle("sel", b.dataset.fx === now.colour));
  document.querySelectorAll("#ride-drum [data-fx]").forEach((b) => b.classList.toggle("sel", b.dataset.fx === (now.drum || "")));
  document.querySelectorAll("#ride-palettes [data-palette]").forEach((b) => b.classList.toggle("sel", b.dataset.palette === now.palette));
  $("#ride-lock").classList.toggle("on", s.ride.palette_lock);
  if (grid) grid.update(s.fixtures, s.haze);
  const lastT = ap.last?.time;
  if (lastT && lastT !== lastDecision) { lastDecision = lastT; loadWhy(); }
}

export function init() {
  $("#ap-toggle").onclick = () => act("autopilot", { state: "toggle" });
  $("#ap-hold").onclick = () => act("hold");
  $("#ap-next").onclick = () => act("look_next");
  $("#ap-prev").onclick = () => act("look_prev");
  $("#ride-walk-on").onclick = () => act("walk_on");
  $("#ride-walk-off").onclick = () => act("walk_off");
  $("#ride-lock").onclick = () => act("palette_lock");
  $("#ride-save-preset").onclick = async () => {
    const id = (prompt(t("autopilot.preset_name")) || "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
    if (!id) return;
    if (await attempt(() => api("POST", "/api/store/preset", { id }), t("autopilot.preset_saved", { id }))) loadPresets();
  };
  $("#ride-capture").onclick = async () => {
    const id = (prompt(t("autopilot.capture_name")) || "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
    if (id) await attempt(() => api("POST", "/api/capture", { key: id }), t("autopilot.captured", { id }));
  };
  $("#ride-reroll").onclick = () => {
    const locks = [...document.querySelectorAll("[data-lock]")].filter((c) => c.checked).map((c) => c.dataset.lock);
    attempt(() => api("POST", "/api/autopilot/reroll", { locks }));
  };
  $("#ride-more").onclick = async () => {
    const r = await attempt(() => api("POST", "/api/autopilot/more", { n: 4 }));
    if (r) $("#ride-variations").replaceChildren(...r.picks.map((p, i) => el("button", {
      onclick: () => attempt(() => api("POST", "/api/autopilot/play", { pick: p })) }, t("autopilot.variation", { n: i + 1, palette: p.palette }))));
  };
  document.querySelectorAll("#ride-moods [data-mood]").forEach((b) => (b.onclick = () => act("mood", { mood: b.dataset.mood })));
  $("#ride-learn").onclick = () => {
    learning = !learning;
    $("#ride-learn").classList.toggle("sel", learning);
    if (learning) toast(t("autopilot.learn_help"));
  };
  const boost = $("#ride-boost");
  boost.addEventListener("pointerdown", (e) => { e.preventDefault(); boost.classList.add("on"); cmd("haze", { action: "boost" }); });
  const up = () => { if (boost.classList.contains("on")) { boost.classList.remove("on"); cmd("haze", { action: "release" }); } };
  boost.addEventListener("pointerup", up);
  boost.addEventListener("pointerleave", up);
  onCatalogue((cat) => {
    grid = grid || new LightGrid($("#ride-grid"));
    grid.build(cat);
  });
  onState(update);
  const dk = $("#dk-slider");
  dk.addEventListener("pointerdown", (e) => { if (learning) { e.preventDefault(); act("darkness", {}); return; } dkHeld = true; });
  dk.addEventListener("pointerup", () => { dkHeld = false; });
  dk.addEventListener("input", () => sendDarkness(+dk.value));
  document.querySelectorAll("#ride-darkness [data-dkset]").forEach((b) => (b.onclick = async () => {
    const r = await attempt(() => api("POST", "/api/darkness/set", { set: b.dataset.dkset, value: +dk.value }));
    if (r) toast(t("darkness.stored", { set: t("autopilot.mood_" + b.dataset.dkset), v: +dk.value }));
  }));
  $("#ride-exclude").onclick = () => setExcluding(!excluding);
  onLeave("autopilot", () => { if (excluding) setExcluding(false); });
  onShow("autopilot", load);
}
