// Ride page (v3.4): ride the auto show live. Autopilot, mood and hold along the top; Move FX on the
// left, Flash FX in the middle, Colour FX on the right; drum FX, palettes and ride faders below; the
// haze controls stay alongside (separate: the auto show never touches haze). Big touch targets.
// "Learn" makes any control MIDI/OSC-learnable: tap it, then hit a pad or press a pedal.
import { api, attempt, cmd, get, toast } from "../api.js";
import { $, el } from "../dom.js";
import { LightGrid } from "../grid.js";
import { t } from "../i18n.js";
import { go, onShow } from "../nav.js";
import { review } from "./review.js";
import { live, onCatalogue, onState } from "../state.js";

let fx = null; // /api/fx
let grid = null;
let learning = false;
let bank = ""; // fader tab: "" = everything, or move / colour / drum
const FADERS = ["speed", "fade", "fan", "size", "shift"];
const CLASSES = ["head", "wash", "pixel", "strobe", "effect"];

function act(action, params = {}, level) {
  if (learning) {
    learning = false;
    $("#ride-learn").classList.remove("sel");
    return attempt(() => api("POST", "/api/ride/learn", { action, params }), (r) => r.message);
  }
  return attempt(() => api("POST", "/api/ride/action", { action, ...params, ...(level !== undefined ? { level } : {}) }));
}

function fxButton(item, onClick) {
  return el("button", { class: "ride-fx", "data-fx": item.id, title: `${item.label} · ${t("ride.busy", { n: Math.round(item.busy * 100) })}`, onclick: onClick }, item.label);
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
    el("button", { class: "ride-fx" + (!pick.move ? " sel" : ""), onclick: () => act("ride_fx", { bank: "move", item: "" }) }, t("ride.no_move")),
    ...byBank("move").map((i) => fxButton(i, () => act("ride_fx", { bank: "move", item: i.id }))));
  $("#ride-colour").replaceChildren(...byBank("colour").map((i) => fxButton(i, () => act("ride_fx", { bank: "colour", item: i.id }))));
  $("#ride-flash").replaceChildren(...byBank("flash").map(flashButton));
  $("#ride-drum").replaceChildren(
    el("button", { class: "ride-fx" + (!pick.drum ? " sel" : ""), onclick: () => act("ride_fx", { bank: "drum", item: "" }) }, t("ride.no_drum")),
    ...byBank("drum").map((i) => fxButton(i, () => act("ride_fx", { bank: "drum", item: i.id }))));
  $("#ride-palettes").replaceChildren(...Object.entries(fx.palettes).map(([k, p]) => el("button", {
    class: "ride-pal", "data-palette": k, onclick: () => act("ride_palette", { palette: k }) }, p.name)));
  $("#ride-tabs").replaceChildren(...["", "move", "colour", "drum"].map((b) => el("button", {
    class: b === bank ? "on" : "", onclick: () => { bank = b; render(); } }, b ? t("ride.bank_" + b) : t("ride.all_banks"))));
  $("#ride-faders").replaceChildren(...FADERS.map((k) => {
    const src = bank ? pick.bank_ride?.[bank] || { speed: 1, fade: 0.5, fan: 0.5, size: 0.5, shift: 0 } : pick.ride;
    const v = k === "speed" ? (Math.log(src.speed) / Math.log(4) + 1) / 2 : src[k];
    const inp = el("input", { type: "range", min: 0, max: 1, step: 0.01, value: v, "aria-label": t("ride.fader_" + k) });
    let last = 0;
    inp.addEventListener("input", () => {
      const now = performance.now();
      if (now - last < 120) return;
      last = now;
      act("ride_" + k, bank ? { bank } : {}, +inp.value);
    });
    inp.addEventListener("pointerdown", (e) => { if (learning) { e.preventDefault(); act("ride_" + k, bank ? { bank } : {}); } });
    return el("label", { class: "ride-fader" }, el("span", { text: t("ride.fader_" + k) }), inp);
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
      ...CLASSES.map((x) => el("option", { value: x, selected: x === c || undefined }, t("ride.class_" + x))),
      el("option", { value: "exclude", selected: c === null || undefined }, t("ride.class_exclude"))))));
}

async function saveClass(fid, value) {
  const rig = fx.rig;
  const classes = {};
  const exclude = rig.excluded.filter((f) => f !== fid);
  if (value === "exclude") exclude.push(fid);
  else classes[fid] = value;
  const r = await attempt(() => api("POST", "/api/store/auto", { classes, exclude }), t("ride.lights_saved"));
  if (r) load();
}

async function loadWhy() {
  const r = await get("/api/autopilot?n=12");
  $("#ride-why").replaceChildren(...r.log.slice().reverse().map((d) => el("li", {
    title: t("ride.why_open"), onclick: () => { review.jump = d.look; go("review"); } },
    el("span", { class: "muted", text: new Date(d.time * 1000).toLocaleTimeString("en-AU", { hour12: false }) }),
    el("b", { text: [d.look.move, d.look.colour, d.look.drum].filter(Boolean).join(" + ") + " · " + d.look.palette }),
    el("span", { text: t("ride.why_line", { why: d.why, mood: t("ride.mood_" + d.mood), energy: Math.round(d.energy * 100) }) }))));
}

let lastDecision = null;

function update(s) {
  if (!s || !fx || !$("#page-ride").classList.contains("on")) return;
  const ap = s.autopilot, pick = s.ride.pick;
  $("#ap-toggle").classList.toggle("on", ap.on);
  $("#ap-toggle").textContent = t(ap.on ? "ride.autopilot_on" : "ride.autopilot_off");
  $("#ap-hold").classList.toggle("on", ap.hold);
  document.querySelectorAll("#ride-moods [data-mood]").forEach((b) => b.classList.toggle("sel",
    b.dataset.mood === "auto" ? !ap.mood_manual : ap.mood_manual && ap.mood === b.dataset.mood));
  $("#ap-energy").style.width = Math.round(ap.energy * 100) + "%";
  $("#ap-state").textContent = [t("ride.mood_now", { mood: t("ride.mood_" + ap.mood) }),
    ap.paused ? t("ride.paused") : ap.between ? t("ride.between") : ap.next_change_s != null ? t("ride.next_in", { s: Math.round(ap.next_change_s) }) : "",
    t("ride.priority_" + s.priority.top)].filter(Boolean).join(" · ");
  const now = ap.pick || pick;
  document.querySelectorAll("#ride-move [data-fx]").forEach((b) => b.classList.toggle("sel", b.dataset.fx === now.move));
  document.querySelectorAll("#ride-colour [data-fx]").forEach((b) => b.classList.toggle("sel", b.dataset.fx === now.colour));
  document.querySelectorAll("#ride-drum [data-fx]").forEach((b) => b.classList.toggle("sel", b.dataset.fx === now.drum));
  document.querySelectorAll("#ride-palettes [data-palette]").forEach((b) => b.classList.toggle("sel", b.dataset.palette === now.palette));
  $("#ride-lock").classList.toggle("on", s.ride.palette_lock);
  if (grid) grid.update(s.fixtures);
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
    const id = (prompt(t("ride.preset_name")) || "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
    if (!id) return;
    if (await attempt(() => api("POST", "/api/store/preset", { id }), t("ride.preset_saved", { id }))) loadPresets();
  };
  $("#ride-capture").onclick = async () => {
    const id = (prompt(t("ride.capture_name")) || "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
    if (id) await attempt(() => api("POST", "/api/capture", { key: id }), t("ride.captured", { id }));
  };
  $("#ride-reroll").onclick = () => {
    const locks = [...document.querySelectorAll("[data-lock]")].filter((c) => c.checked).map((c) => c.dataset.lock);
    attempt(() => api("POST", "/api/ride/reroll", { locks }));
  };
  $("#ride-more").onclick = async () => {
    const r = await attempt(() => api("POST", "/api/ride/more", { n: 4 }));
    if (r) $("#ride-variations").replaceChildren(...r.picks.map((p, i) => el("button", {
      onclick: () => attempt(() => api("POST", "/api/ride", { pick: p })) }, t("ride.variation", { n: i + 1, palette: p.palette }))));
  };
  document.querySelectorAll("#ride-moods [data-mood]").forEach((b) => (b.onclick = () => act("mood", { mood: b.dataset.mood })));
  $("#ride-learn").onclick = () => {
    learning = !learning;
    $("#ride-learn").classList.toggle("sel", learning);
    if (learning) toast(t("ride.learn_help"));
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
  onShow("ride", load);
}
