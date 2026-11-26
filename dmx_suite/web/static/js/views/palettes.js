// Palettes page (v3.1): palettes (named colour sets with tags) and named colours. Scenes name the
// colours, so changing one changes every scene that uses it; in-use deletes are refused.
import { openWheel, toHex } from "../colourwheel.js";
import { api, attempt, get, toast } from "../api.js";
import { $, el } from "../dom.js";
import { t } from "../i18n.js";
import { onShow } from "../nav.js";
import { refreshCatalogue } from "../state.js";

let data = {}; // palettes.yaml as stored
let fx = { colours: {}, palettes: {} }; // resolved hex for drawing
let editing = null; // palette key being edited

const NAME = /^[a-z0-9][a-z0-9_-]{0,39}$/;
const hexOf = (c) => (typeof c === "string" && c.startsWith("#") ? c : fx.colours[c] || (typeof c === "object" ? toHex(c) : "#000000"));

async function load() {
  [data, fx] = await Promise.all([get("/api/store/palettes"), get("/api/effects")]);
  render();
}

async function saved(r) {
  if (r) {
    await refreshCatalogue();
    await load();
  }
  return r;
}

function putPalette(key, value) {
  return attempt(() => api("PUT", `/api/store/palettes/palettes/${encodeURIComponent(key)}`, { value }), t("palettes.saved")).then(saved);
}

function current(key) {
  const own = (data.palettes || {})[key];
  if (own) return JSON.parse(JSON.stringify(own));
  const p = fx.palettes[key];
  return { name: p.name, tags: [...p.tags], colours: [...p.colours] };
}

function chip(c, i, p, key) {
  return el("span", { class: "pal-colour" },
    el("button", { class: "sw", style: `background:${hexOf(c)}`, title: typeof c === "string" ? c : toHex(c),
      onclick: () => openWheel({ value: c, names: fx.colours, onPick: (nc) => { p.colours[i] = nc; putPalette(key, p); } }) }),
    el("button", { class: "mini", title: t("palettes.left"), disabled: i === 0 || undefined,
      onclick: () => { p.colours.splice(i - 1, 0, ...p.colours.splice(i, 1)); putPalette(key, p); } }, "‹"),
    el("button", { class: "mini danger-text", title: t("palettes.remove_colour"), disabled: p.colours.length < 2 || undefined,
      onclick: () => { p.colours.splice(i, 1); putPalette(key, p); } }, "✕"));
}

function paletteCard(key) {
  const info = fx.palettes[key];
  const p = current(key);
  const open = editing === key;
  const head = el("div", { class: "row wrap" },
    el("b", { text: info.name }), el("span", { class: "muted", text: key }),
    ...(info.builtin ? [el("span", { class: "chip", text: t("palettes.builtin") })] : []),
    ...info.tags.map((tg) => el("span", { class: "chip", text: tg })),
    el("span", { class: "grow" }),
    el("button", { onclick: () => attempt(() => api("POST", "/api/palette/preview", { palette: key, mode: "static", seconds: 8 }), (r) => r.message) }, t("palettes.preview_static")),
    el("button", { onclick: () => attempt(() => api("POST", "/api/palette/preview", { palette: key, mode: "chase", seconds: 8 }), (r) => r.message) }, t("palettes.preview_chase")),
    el("button", { class: open ? "sel" : "", onclick: () => { editing = open ? null : key; render(); } }, t("palettes.edit")));
  const strip = el("div", { class: "pal-strip" }, ...info.hex.map((hx) => el("i", { style: `background:${hx}` })));
  if (!open) return el("div", { class: "pal-card", "data-palette": key }, head, strip);
  const tags = el("input", { value: p.tags.join(", "), placeholder: t("palettes.tags_placeholder") });
  const name = el("input", { value: p.name, placeholder: t("palettes.name") });
  const scheme = el("select", {}, ...["analogous", "complementary", "triadic", "split", "mono"].map((x) => el("option", { value: x }, t("palettes.scheme_" + x))));
  const count = el("input", { type: "number", min: 2, max: 12, value: 4, class: "narrow" });
  return el("div", { class: "pal-card open", "data-palette": key }, head, strip,
    el("div", { class: "row wrap" }, ...p.colours.map((c, i) => chip(c, i, p, key)),
      el("button", { onclick: () => openWheel({ value: "#ffffff", names: fx.colours, onPick: (nc) => { p.colours.push(nc); putPalette(key, p); } }) }, t("palettes.add_colour"))),
    el("div", { class: "row wrap" }, name, tags,
      el("button", { onclick: () => { p.name = name.value.trim() || key; p.tags = tags.value.split(",").map((x) => x.trim()).filter(Boolean); putPalette(key, p); } }, t("palettes.save"))),
    el("div", { class: "row wrap" }, el("span", { class: "muted", text: t("palettes.generate") }), scheme, count,
      el("button", { onclick: async () => {
        const r = await attempt(() => api("POST", "/api/colour/generate", { base: hexOf(p.colours[0]), scheme: scheme.value, count: +count.value }));
        if (r) { p.colours = r.colours; putPalette(key, p); }
      } }, t("palettes.generate_go"))),
    el("div", { class: "row wrap" },
      el("button", { onclick: async () => {
        const to = prompt(t("palettes.copy_name"), key + "_2");
        if (to && NAME.test(to)) { editing = to; putPalette(to, { ...p, name: p.name + " 2" }); }
      } }, t("palettes.duplicate")),
      ...(info.builtin ? [] : [
        el("button", { onclick: async () => {
          const to = prompt(t("palettes.rename_to"), key);
          if (to && to !== key && NAME.test(to)) {
            editing = to;
            await attempt(() => api("POST", "/api/store/palette", { action: "rename", name: key, new_name: to }), t("palettes.saved")).then(saved);
          }
        } }, t("palettes.rename")),
        el("button", { onclick: async () => {
          const r = await attempt(() => get(`/api/palette/export/${encodeURIComponent(key)}`));
          if (r) download(`${key}.palette.json`, JSON.stringify(r, null, 2));
        } }, t("palettes.export")),
        el("button", { class: "danger-text", onclick: async () => {
          if (!confirm(t("palettes.confirm_delete", { name: info.name }))) return;
          editing = null;
          await attempt(() => api("DELETE", `/api/store/palettes/palettes/${encodeURIComponent(key)}`), t("palettes.deleted")).then(saved);
        } }, t("palettes.delete"))])));
}

function download(name, text) {
  const a = el("a", { href: URL.createObjectURL(new Blob([text], { type: "application/json" })), download: name });
  document.body.append(a);
  a.click();
  a.remove();
}

function colourRow([n, hx]) {
  return el("li", { "data-colour": n },
    el("button", { class: "sw", style: `background:${hx}`, title: t("palettes.change_colour"),
      onclick: () => openWheel({ value: hx, names: {}, onPick: (c) => attempt(() => api("PUT", `/api/store/palettes/colours/${encodeURIComponent(n)}`, { value: c }), t("palettes.saved")).then(saved) }) }),
    el("span", { text: n }),
    el("button", { class: "mini", onclick: async () => {
      const to = prompt(t("palettes.rename_to"), n);
      if (to && to !== n && NAME.test(to)) await attempt(() => api("POST", "/api/store/colour", { action: "rename", name: n, new_name: to }), t("palettes.saved")).then(saved);
    } }, t("palettes.rename")),
    el("button", { class: "mini danger-text", onclick: async () => {
      if (confirm(t("palettes.confirm_delete", { name: n }))) await attempt(() => api("DELETE", `/api/store/palettes/colours/${encodeURIComponent(n)}`), t("palettes.deleted")).then(saved);
    } }, "✕"));
}

function render() {
  $("#palette-list").replaceChildren(...Object.keys(fx.palettes).map(paletteCard));
  const own = Object.keys(data.colours || {});
  $("#named-colours").replaceChildren(...Object.entries(fx.colours).filter(([n]) => own.includes(n)).map(colourRow));
}

export function init() {
  $("#palette-new").onclick = () => {
    const key = $("#palette-new-name").value.trim();
    if (!NAME.test(key)) return toast(t("palettes.bad_name"), true);
    editing = key;
    putPalette(key, { name: key.replace(/_/g, " "), tags: [], colours: ["white"] });
  };
  $("#colour-new").onclick = () => {
    const n = $("#colour-new-name").value.trim();
    if (!NAME.test(n)) return toast(t("palettes.bad_name"), true);
    openWheel({ value: "#ffffff", names: {}, onPick: (c) => attempt(() => api("PUT", `/api/store/palettes/colours/${encodeURIComponent(n)}`, { value: c }), t("palettes.saved")).then(saved) });
  };
  $("#palette-import").onchange = async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    try {
      const body = { action: "import", data: JSON.parse(await f.text()) };
      let r = await api("POST", "/api/store/palette", body).catch((err) => err);
      if (r instanceof Error && confirm(r.message + "\n" + t("palettes.import_overwrite"))) r = await api("POST", "/api/store/palette", { ...body, overwrite: true });
      else if (r instanceof Error) throw r;
      toast(t("palettes.imported"));
      await saved(r);
    } catch (err) {
      toast(err.message, true);
    }
    e.target.value = "";
  };
  onShow("palettes", load);
}
