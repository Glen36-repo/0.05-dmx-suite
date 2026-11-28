// Live page: the rig's lights, shows and sets, setlist, masters, haze.
import { cmd } from "../api.js";
import { $, $$, el } from "../dom.js";
import { fillGrid } from "../btngrid.js";
import { LightGrid } from "../grid.js";
import { initHazePanel, renderHazePanel } from "../hazepanel.js";
import { t } from "../i18n.js";
import { live, onCatalogue, onState } from "../state.js";

let grid;

function buildCatalogue(cat) {
  grid = grid || new LightGrid($("#live-grid"));
  grid.build(cat);

  // Shows, Scenes, then starter / generated ones (folded away): aligned grids in a saved order
  const gen = new Set(cat.generated || []);
  const showItem = ([k, s]) => ({ id: `show:${k}`, label: s.name, attrs: { "data-show": k }, onclick: () => cmd("show", { show: k }) });
  const sceneItem = ([k, s]) => ({ id: `scene:${k}`, label: "▸ " + s, attrs: { "data-scene": k }, onclick: () => cmd("scene", { scene: k }) });
  const shows = Object.entries(cat.shows).map(showItem), scenes = Object.entries(cat.scenes).map(sceneItem);
  fillGrid($("#shows"), "shows", shows.filter((i) => !gen.has(i.id)));
  fillGrid($("#scenes"), "scenes", scenes.filter((i) => !gen.has(i.id)));
  fillGrid($("#generated"), "generated", [...shows, ...scenes].filter((i) => gen.has(i.id)));
  $("#generated-section").classList.toggle("hidden", !gen.size);
  $("#sets").dataset.sets = "";
  $("#setlist").replaceChildren(...Object.entries(cat.setlists).map(([k, s]) => el("option", { value: k }, s.name)));

  const faders = $("#faders");
  faders.replaceChildren();
  const fader = (label, key, send) => {
    const out = el("span");
    const inp = el("input", { type: "range", min: 0, max: 100, step: 1, "data-key": key, "aria-label": label });
    let last = 0;
    inp.addEventListener("input", () => {
      out.textContent = inp.value + "%";
      const now = performance.now();
      if (now - last > 40) { last = now; send(inp.value / 100); } // at most 25 a second
    });
    inp.addEventListener("change", () => send(inp.value / 100)); // and always the final value
    inp.addEventListener("pointerdown", (e) => {
      inp.dataset.busy = "1";
      inp.setPointerCapture?.(e.pointerId); // the release comes here even if the finger slides off
    });
    for (const ev of ["pointerup", "pointercancel", "lostpointercapture", "blur"]) inp.addEventListener(ev, () => delete inp.dataset.busy);
    faders.append(el("div", { class: "fader" }, el("label", {}, el("span", { text: label }), out), inp));
  };
  fader(t("live.grand"), "grand", (v) => cmd("grand", { level: v }));
  fader(t("live.speed"), "speed", (v) => cmd("speed", { value: 4 ** (2 * v - 1) })); // middle = as set
  fader(t("live.flash_level"), "flash_level", (v) => cmd("flash_level", { level: v }));
  for (const k of ["head", "bar", "wash", "kick"]) fader(t("live.sub_" + k), "sub:" + k, (v) => cmd("sub", { kind: k, level: v }));
}

function render(s) {
  const cat = live.cat;
  if (!cat) return;
  $("#preview").textContent = s.preview_s != null ? t("live.previewing", { s: Math.ceil(s.preview_s) }) : "";
  $$("#page-live [data-show]").forEach((b) => b.classList.toggle("sel", s.now.show === b.dataset.show));
  $$("#page-live [data-scene]").forEach((b) => b.classList.toggle("sel", s.now.mode === "scene" && s.now.scene === b.dataset.scene));
  const sets = $("#sets");
  const show = s.now.show && cat.shows[s.now.show];
  const want = show ? show.sets.join("|") : "";
  if (sets.dataset.sets !== want) {
    sets.dataset.sets = want;
    sets.replaceChildren(...(show ? show.sets.map((k) => el("button", { "data-set": k, onclick: () => cmd("set", { set: k }) }, k.toUpperCase())) : []));
  }
  $$("#sets [data-set]").forEach((b) => b.classList.toggle("sel", s.now.set === b.dataset.set));

  // the playing set's steps: tap one to jump to it
  const steps = show && s.now.set ? show.steps?.[s.now.set] || [] : [];
  const list = $("#steps");
  const key = `${s.now.show}|${s.now.set}|${steps.length}`;
  if (list.dataset.key !== key) {
    list.dataset.key = key;
    list.replaceChildren(...steps.map((st, i) => el("li", {}, el("button", { class: "link", "data-step": i, onclick: () => cmd("step", { step: i }) },
      st.name + (st.repeats ? ` ×${st.repeats}` : st.hold_beats ? ` · ${st.hold_beats} ${t("live.beats")}` : st.hold_s ? ` · ${st.hold_s} s` : "")))));
  }
  $$("#steps [data-step]").forEach((b) => b.parentElement.classList.toggle("cur", +b.dataset.step === s.now.step_index));
  const info = [];
  if (s.now.repeat) info.push(t("live.repeat", { n: s.now.repeat[0], of: s.now.repeat[1] }));
  if (s.now.time_left_s != null) info.push(t("live.time_left", { s: Math.ceil(s.now.time_left_s) }));
  $("#step-info").textContent = info.join(" · ");

  const sl = s.now.setlist && cat.setlists[s.now.setlist];
  $("#songs").replaceChildren(...(sl ? sl.songs.map((n, i) =>
    el("li", { class: i === s.now.song ? "cur" : "" }, el("button", { class: "link", onclick: () => cmd("song", { song: i }) }, n))) : []));

  $$("#faders input").forEach((inp) => {
    if (inp.dataset.busy || document.activeElement === inp) return; // don't fight the finger
    const k = inp.dataset.key;
    const v = k === "speed" ? (Math.log(s.tempo?.speed || 1) / Math.log(4) + 1) / 2 : k.startsWith("sub:") ? s.subs[k.slice(4)] : s[k];
    if (v !== undefined) {
      inp.value = Math.round(v * 100);
      inp.previousSibling.lastChild.textContent = k === "speed" ? `×${(s.tempo?.speed || 1).toFixed(2)}` : inp.value + "%";
    }
  });

  const h = s.haze;
  const bits = [h.enabled ? t("haze.mode", { mode: t("haze." + h.mode) }) : t("haze.disabled"), t(h.on ? "haze.output_on" : "haze.output_off")];
  if (h.boosting) bits.push(t("haze.boosting"));
  if (h.resting) bits.push(t("haze.resting"));
  if (h.next_pulse_s != null) bits.push(t("haze.next_pulse", { s: Math.round(h.next_pulse_s) }));
  if (h.auto_off_s != null) bits.push(t("haze.auto_off", { min: Math.round(h.auto_off_s / 60) }));
  if (h.boost_cooldown_s) bits.push(t("haze.cooldown", { s: Math.round(h.boost_cooldown_s) }));
  if (h.testing) bits.push(t("haze.testing", { mode: t("haze.b_" + h.testing) }));
  $("#haze").textContent = bits.join(" · ");
  $$("[data-haze]").forEach((b) => b.classList.toggle("sel", h.mode === b.dataset.haze));
  renderHazePanel(h);

  grid.update(s.fixtures, s.haze);
  grid.mark(Object.keys(s.override?.lights || {})); // lights held by Override buttons
}

export function init() {
  $("#tap").onclick = () => cmd("tap");
  $("#bpm-set").onclick = () => { const v = +$("#bpm").value; if (v) cmd("tempo", { bpm: v }); };
  $("#setlist-go").onclick = () => cmd("setlist", { setlist: $("#setlist").value });
  $$("[data-haze]").forEach((b) => (b.onclick = () => cmd("haze", { action: b.dataset.haze })));
  const boost = $("#boost");
  boost.addEventListener("pointerdown", (e) => { e.preventDefault(); boost.classList.add("on"); cmd("haze", { action: "boost" }); });
  const up = () => { if (boost.classList.contains("on")) { boost.classList.remove("on"); cmd("haze", { action: "release" }); } };
  ["pointerup", "pointerleave", "pointercancel"].forEach((ev) => boost.addEventListener(ev, up));
  initHazePanel();
  onCatalogue(buildCatalogue);
  onState(render);
}
