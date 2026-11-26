// Live page: the rig's lights, shows and sets, setlist, masters, haze.
import { cmd } from "../api.js";
import { $, $$, el } from "../dom.js";
import { LightGrid } from "../grid.js";
import { t } from "../i18n.js";
import { live, onCatalogue, onState } from "../state.js";

let grid;

function buildCatalogue(cat) {
  grid = grid || new LightGrid($("#live-grid"));
  grid.build(cat);

  const shows = $("#shows");
  shows.replaceChildren(
    ...Object.entries(cat.shows).map(([k, s]) => el("button", { "data-show": k, onclick: () => cmd("show", { show: k }) }, s.name)),
    ...Object.entries(cat.scenes).map(([k, s]) => el("button", { "data-scene": k, onclick: () => cmd("scene", { scene: k }) }, "▸ " + s)));
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
    inp.addEventListener("pointerdown", () => (inp.dataset.busy = "1"));
    inp.addEventListener("pointerup", () => delete inp.dataset.busy);
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
  $$("#shows [data-show]").forEach((b) => b.classList.toggle("sel", s.now.show === b.dataset.show));
  $$("#shows [data-scene]").forEach((b) => b.classList.toggle("sel", s.now.mode === "scene" && s.now.scene === b.dataset.scene));
  const sets = $("#sets");
  const show = s.now.show && cat.shows[s.now.show];
  const want = show ? show.sets.join("|") : "";
  if (sets.dataset.sets !== want) {
    sets.dataset.sets = want;
    sets.replaceChildren(...(show ? show.sets.map((k) => el("button", { "data-set": k, onclick: () => cmd("set", { set: k }) }, k.toUpperCase())) : []));
  }
  $$("#sets [data-set]").forEach((b) => b.classList.toggle("sel", s.now.set === b.dataset.set));

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
  $("#haze").textContent = bits.join(" · ");
  $$("[data-haze]").forEach((b) => b.classList.toggle("sel", h.mode === b.dataset.haze));

  grid.update(s.fixtures);
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
  onCatalogue(buildCatalogue);
  onState(render);
}
