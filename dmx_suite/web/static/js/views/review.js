// Look review page (v3.5): go through every look the rig can do (or some), at rehearsal; rate it
// (thumbs up / down) or ban it, and the autopilot and generator follow. Below: the generator,
// making editable scenes and shows from the same FX banks.
import { api, attempt, get, toast } from "../api.js";
import { $, el } from "../dom.js";
import { t } from "../i18n.js";
import { onShow } from "../nav.js";
import { live, refreshCatalogue } from "../state.js";

let list = { total: 0, looks: [] };
let index = 0;
let offset = 0;
let timer = null;
export const review = { jump: null }; // a look to open (from the Ride page's decision log)

const label = (lk) => [lk.move || t("review.no_move"), lk.colour, lk.drum].filter(Boolean).join(" + ") + " · " + lk.palette;

async function load() {
  const qs = new URLSearchParams({ mood: $("#rv-mood").value, bank: $("#rv-bank").value, palette: $("#rv-palette").value,
    offset, limit: 40 });
  list = await get("/api/review?" + qs);
  if (review.jump) {
    list.looks.unshift({ ...review.jump, key: "", rating: 0 });
    review.jump = null;
    index = 0;
    play();
  }
  render();
}

function render() {
  $("#rv-count").textContent = t("review.count", { from: offset + 1, to: offset + list.looks.length, total: list.total });
  const cur = list.looks[index];
  $("#rv-now").textContent = cur ? label(cur) : "";
  $("#rv-list").replaceChildren(...list.looks.map((lk, i) => el("li", { class: (i === index ? "on " : "") + "r" + lk.rating, "data-look": lk.key },
    el("button", { class: "link", onclick: () => { index = i; play(); render(); } }, label(lk)),
    el("span", { class: "muted", text: lk.rating === 1 ? "👍" : lk.rating === -1 ? "👎" : lk.rating === -2 ? t("review.banned") : "" }))));
}

function play() {
  const lk = list.looks[index];
  if (!lk) return;
  attempt(() => api("POST", "/api/ride", { pick: { move: lk.move, colour: lk.colour, drum: lk.drum || null, palette: lk.palette }, fade_s: 0.5 }));
}

async function rate(v) {
  const lk = list.looks[index];
  if (!lk) return;
  const r = await attempt(() => api("POST", "/api/rate", { pick: lk, value: v }), t(v === -2 ? "review.banned_toast" : "review.rated"));
  if (r) {
    lk.rating = v;
    step(1);
  }
}

function step(d) {
  index += d;
  if (index >= list.looks.length && offset + list.looks.length < list.total) { offset += list.looks.length; index = 0; load().then(play); return; }
  if (index < 0 && offset > 0) { offset = Math.max(0, offset - 40); index = 39; load().then(play); return; }
  index = Math.max(0, Math.min(list.looks.length - 1, index));
  play();
  render();
}

function auto(on) {
  clearInterval(timer);
  $("#rv-auto").classList.toggle("sel", on);
  if (on) timer = setInterval(() => step(1), Math.max(2, +$("#rv-every").value || 8) * 1000);
}

async function generate(kind, body) {
  const r = await attempt(() => api("POST", "/api/generate", { kind, ...body }),
    (x) => t("review.generated", { scenes: x.scenes.length, shows: x.shows.length, seed: x.seed }));
  if (r) {
    await refreshCatalogue();
    $("#gen-out").textContent = [...r.shows.map((s) => "▶ " + s), ...r.scenes].join(", ");
  }
}

export function init() {
  for (const id of ["rv-mood", "rv-bank", "rv-palette"]) $("#" + id).onchange = () => { offset = 0; index = 0; load(); };
  $("#rv-prev").onclick = () => step(-1);
  $("#rv-next").onclick = () => step(1);
  $("#rv-up").onclick = () => rate(1);
  $("#rv-down").onclick = () => rate(-1);
  $("#rv-ban").onclick = () => rate(-2);
  $("#rv-clear").onclick = () => rate(0);
  $("#rv-auto").onclick = () => auto(!$("#rv-auto").classList.contains("sel"));
  $("#gen-scenes").onclick = () => generate("scenes", { mood: $("#gen-mood").value, style: $("#gen-style").value || undefined,
    palette: $("#gen-palette").value || undefined, count: +$("#gen-count").value || 4, prefix: $("#gen-prefix").value.trim() || undefined,
    seed: $("#gen-seed").value.trim() || undefined });
  $("#gen-show").onclick = () => generate("show", { name: $("#gen-show-name").value.trim() || "Generated show",
    style: $("#gen-style").value || undefined, palette: $("#gen-palette").value || undefined, seed: $("#gen-seed").value.trim() || undefined });
  $("#gen-setlist").onclick = () => {
    const key = $("#gen-setlist-pick").value;
    if (!key) return toast(t("review.pick_setlist"), true);
    generate("setlist", { setlist: key, style: $("#gen-style").value || undefined, seed: $("#gen-seed").value.trim() || undefined });
  };
  onShow("review", async () => {
    const fx = await get("/api/fx");
    const pals = Object.entries(fx.palettes);
    $("#rv-palette").replaceChildren(el("option", { value: "" }, t("review.all_palettes")), ...pals.map(([k, p]) => el("option", { value: k }, p.name)));
    $("#gen-palette").replaceChildren(el("option", { value: "" }, t("review.any_palette")), ...pals.map(([k, p]) => el("option", { value: k }, p.name)));
    $("#gen-setlist-pick").replaceChildren(el("option", { value: "" }, t("review.pick_setlist")),
      ...Object.entries(live.cat.setlists).map(([k, s]) => el("option", { value: k }, s.name)));
    load();
  });
}
