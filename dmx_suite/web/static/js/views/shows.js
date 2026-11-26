// Shows page: build a show (its sets, and each set's steps: a scene played a number of times or
// for a time, beats or bars, then faded into the next; or an auto style), and setlists.
// The page edits the same data the files hold and saves it through the store (checked, backed up).
import { api, attempt, get, toast } from "../api.js";
import { $, el } from "../dom.js";
import { t } from "../i18n.js";
import { onShow } from "../nav.js";
import { live, refreshCatalogue } from "../state.js";

const HOLDS = ["repeats", "hold_s", "hold_beats", "hold_bars"];
const ENERGIES = ["low", "mid", "high"];
const HEAD_MIX = ["matching", "white", "contrast"];
const PATTERNS = ["all", "heads_only", "bars_only", "kit"];
const MOVEMENTS = ["random", "sweep", "static"];

let colours = {}; // palette name -> hex
let showKey = null, show = null, showSaved = "", setName = null;
let listKey = null, list = null, listSaved = "";
let showTicket = 0, listTicket = 0; // a slow load must not land on top of a newer choice

const slug = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40);
const num = (v) => (v === "" || v === null || v === undefined ? undefined : +v);
function setKey(obj, k, v) {
  if (v === undefined || v === "" || v === null || (Array.isArray(v) && !v.length)) delete obj[k];
  else obj[k] = v;
}

// ---------------------------------------------------------------- shows

// v1 sets (scenes + step_s) open as steps, each held for step_s; saving writes steps
function normalise(data) {
  for (const s of Object.values(data.sets || {})) {
    if (s.scenes) {
      s.steps = s.scenes.map((scene) => ({ scene, hold_s: s.step_s ?? 40 }));
      delete s.scenes;
      delete s.step_s;
    }
  }
  return data;
}

async function openShow(k) {
  if (show && JSON.stringify(show) !== showSaved && !confirm(t("shows.discard"))) return renderShowBar();
  const ticket = ++showTicket;
  if (!k) {
    show = { name: t("shows.untitled"), default_set: "main", sets: { main: { steps: [] } } };
    showKey = null;
  } else {
    const data = await get(`/api/store/show/${encodeURIComponent(k)}`);
    if (ticket !== showTicket) return; // something newer was opened meanwhile
    if (data.error) return toast(data.error, true);
    show = normalise(data);
    showKey = k;
  }
  showSaved = JSON.stringify(show);
  setName = show.default_set || Object.keys(show.sets)[0];
  $("#show-name").value = show.name || "";
  renderShow();
}

function renderShowBar() {
  const pick = $("#show-pick");
  pick.replaceChildren(el("option", { value: "" }, t("shows.new_show")),
    ...Object.entries(live.cat.shows).map(([k, s]) => el("option", { value: k, selected: k === showKey }, `${s.name} (${k})`)));
  pick.value = showKey || "";
  const dirty = show && JSON.stringify(show) !== showSaved;
  $("#show-save").classList.toggle("sel", !!dirty);
  $("#show-del").disabled = !showKey;
  $("#show-state").textContent = dirty ? t("shows.unsaved") : showKey ? t("shows.saved_as", { key: showKey }) : "";
}

function renderShow() {
  renderShowBar();
  if (!show) return;
  $("#set-tabs").replaceChildren(...Object.keys(show.sets).map((s) => el("button", {
    role: "tab", class: s === setName ? "on" : "", "data-set": s, onclick: () => { setName = s; renderShow(); },
  }, s + (s === show.default_set ? " ★" : ""))));
  $("#set-default").checked = show.default_set === setName;
  $("#set-del").disabled = Object.keys(show.sets).length < 2;
  renderSet();
}

function changed() {
  renderShow();
}

function renderSet() {
  const s = show.sets[setName];
  const form = $("#set-form");
  if (!s) return form.replaceChildren();
  const auto = !!s.auto;
  const parts = [
    field(t("shows.kind"), el("select", { onchange: (e) => {
      if (e.target.value === "auto") { delete s.steps; s.auto = { colours: Object.keys(colours).slice(0, 3), energy: "mid" }; s.step_s ??= 40; }
      else { delete s.auto; s.steps = []; }
      changed();
    } }, el("option", { value: "steps", selected: !auto }, t("shows.kind_steps")), el("option", { value: "auto", selected: auto }, t("shows.kind_auto")))),
    field(t("shows.fade"), numInput(s.fade_s, (v) => { setKey(s, "fade_s", v); changed(); }, 0, 30, 0.1), t("shows.fade_help")),
  ];
  if (!auto) {
    parts.push(field(t("shows.order"), el("select", { onchange: (e) => { setKey(s, "order", e.target.value === "sequence" ? undefined : e.target.value); changed(); } },
      ...["sequence", "random"].map((o) => el("option", { value: o, selected: (s.order || "sequence") === o }, t("shows.order_" + o))))));
    parts.push(field(t("shows.loop"), el("input", { type: "checkbox", checked: s.loop !== false, onchange: (e) => { setKey(s, "loop", e.target.checked ? undefined : false); changed(); } })));
    parts.push(el("h3", { text: t("shows.steps") }), stepList(s), el("button", { onclick: () => {
      const first = Object.keys(live.cat.scenes)[0];
      if (!first) return toast(t("shows.no_scenes"), true);
      s.steps.push({ scene: first, hold_s: 30 });
      changed();
    } }, t("shows.add_step")));
  } else {
    parts.push(field(t("shows.step_s"), numInput(s.step_s, (v) => { setKey(s, "step_s", v); changed(); }, 1, 600, 1)));
    parts.push(...autoForm(s.auto));
  }
  form.replaceChildren(...parts);
}

function stepList(s) {
  return el("ol", { class: "steps-edit" }, ...s.steps.map((st, i) => {
    const how = HOLDS.find((h) => h in st) || "hold_s";
    const scene = el("select", { onchange: (e) => { st.scene = e.target.value; changed(); } },
      ...Object.entries(live.cat.scenes).map(([k, n]) => el("option", { value: k, selected: k === st.scene }, n)));
    const holdSel = el("select", { onchange: (e) => {
      const v = st[how];
      HOLDS.forEach((h) => delete st[h]);
      st[e.target.value] = e.target.value === "repeats" ? Math.max(1, Math.round(v || 1)) : v || 1;
      changed();
    } }, ...HOLDS.map((h) => el("option", { value: h, selected: h === how }, t("shows.hold_" + h))));
    return el("li", {}, scene, holdSel,
      numInput(st[how], (v) => { if (v !== undefined) st[how] = how === "repeats" ? Math.max(1, Math.round(v)) : v; changed(); }, how === "repeats" ? 1 : 0.25, 999, how === "repeats" ? 1 : 0.5),
      el("span", { class: "muted", text: t("shows.step_fade") }),
      numInput(st.fade_s, (v) => { setKey(st, "fade_s", v); changed(); }, 0, 30, 0.1, t("shows.set_default")),
      el("span", { class: "tools" },
        el("button", { title: t("scenes.up"), disabled: i === 0, onclick: () => { s.steps.splice(i - 1, 0, ...s.steps.splice(i, 1)); changed(); } }, "↑"),
        el("button", { title: t("scenes.down"), disabled: i === s.steps.length - 1, onclick: () => { s.steps.splice(i + 1, 0, ...s.steps.splice(i, 1)); changed(); } }, "↓"),
        el("button", { title: t("scenes.remove"), class: "danger-text", onclick: () => { s.steps.splice(i, 1); changed(); } }, "✕")));
  }));
}

function checks(options, chosen, onChange, prefix) {
  return el("span", { class: "chips" }, ...options.map((o) => el("label", { class: "check" },
    el("input", { type: "checkbox", checked: chosen.includes(o), onchange: (e) => {
      const next = e.target.checked ? [...chosen, o] : chosen.filter((x) => x !== o);
      onChange(next);
    } }), el("span", { text: prefix === null ? o : t(prefix + o) }))));
}

function autoForm(a) {
  return [
    el("h3", { text: t("shows.auto_style") }),
    field(t("shows.colours"), checks(Object.keys(colours), a.colours || [], (v) => { a.colours = v; changed(); }, null)),
    field(t("shows.energy"), el("select", { onchange: (e) => { a.energy = e.target.value; changed(); } },
      ...ENERGIES.map((x) => el("option", { value: x, selected: (a.energy || "mid") === x }, t("shows.energy_" + x))))),
    field(t("shows.head_mix"), checks(HEAD_MIX, a.head_mix || HEAD_MIX, (v) => { setKey(a, "head_mix", v); changed(); }, "shows.mix_")),
    field(t("shows.patterns"), checks(PATTERNS, a.patterns || PATTERNS, (v) => { setKey(a, "patterns", v); changed(); }, "shows.pattern_")),
    field(t("shows.movement"), checks(MOVEMENTS, a.movement || MOVEMENTS, (v) => { setKey(a, "movement", v); changed(); }, "shows.move_")),
    field(t("shows.flash"), el("input", { type: "checkbox", checked: !!a.flash, onchange: (e) => { setKey(a, "flash", e.target.checked || undefined); changed(); } })),
  ];
}

function numInput(v, onChange, lo, hi, step, placeholder) {
  return el("input", { type: "number", class: "narrow", min: lo, max: hi, step, value: v ?? "", placeholder: placeholder || "",
                       onchange: (e) => onChange(num(e.target.value)) });
}

function field(label, control, help) {
  return el("label", { class: "field", title: help || "" }, el("span", { text: label }), control);
}

async function saveShow() {
  show.name = $("#show-name").value.trim() || t("shows.untitled");
  const k = showKey || slug(show.name);
  if (!showKey && live.cat.shows[k] && !confirm(t("shows.overwrite", { key: k }))) return;
  if (await attempt(() => api("PUT", `/api/store/show/${encodeURIComponent(k)}`, { data: show }), t("shows.saved", { name: show.name }))) {
    showKey = k;
    showSaved = JSON.stringify(show);
    await refreshCatalogue();
    renderShowBar();
  }
}

// ---------------------------------------------------------------- setlists

async function openList(k) {
  if (list && JSON.stringify(list) !== listSaved && !confirm(t("setlists.discard"))) return renderList();
  const ticket = ++listTicket;
  if (!k) {
    list = { name: t("setlists.untitled"), songs: [] };
    listKey = null;
  } else {
    const data = await get(`/api/store/setlist/${encodeURIComponent(k)}`);
    if (ticket !== listTicket) return;
    list = data;
    listKey = k;
  }
  listSaved = JSON.stringify(list);
  $("#setlist-name").value = list.name || "";
  renderList();
}

function renderList() {
  const pick = $("#setlist-pick");
  pick.replaceChildren(el("option", { value: "" }, t("setlists.new_setlist")),
    ...Object.entries(live.cat.setlists).map(([k, s]) => el("option", { value: k, selected: k === listKey }, `${s.name} (${k})`)));
  pick.value = listKey || "";
  const dirty = list && JSON.stringify(list) !== listSaved;
  $("#setlist-save").classList.toggle("sel", !!dirty);
  $("#setlist-del").disabled = !listKey;
  $("#setlist-state").textContent = dirty ? t("shows.unsaved") : "";
  if (!list) return;
  $("#songs-edit").replaceChildren(...list.songs.map((sg, i) => {
    const isScene = "scene" in sg;
    const showSel = el("select", { onchange: (e) => { sg.show = e.target.value; delete sg.set; renderList(); } },
      ...Object.entries(live.cat.shows).map(([k, s]) => el("option", { value: k, selected: sg.show === k }, s.name)));
    const sets = sg.show && live.cat.shows[sg.show] ? live.cat.shows[sg.show].sets : [];
    const setSel = el("select", { onchange: (e) => { setKey(sg, "set", e.target.value || undefined); renderList(); } },
      el("option", { value: "" }, t("setlists.default_set")), ...sets.map((s) => el("option", { value: s, selected: sg.set === s }, s)));
    const sceneSel = el("select", { onchange: (e) => { sg.scene = e.target.value; renderList(); } },
      ...Object.entries(live.cat.scenes).map(([k, n]) => el("option", { value: k, selected: sg.scene === k }, n)));
    return el("li", {},
      el("input", { value: sg.name || "", placeholder: t("setlists.song_name"), oninput: (e) => { sg.name = e.target.value; renderListState(); } }),
      el("select", { onchange: (e) => {
        if (e.target.value === "scene") { delete sg.show; delete sg.set; sg.scene = Object.keys(live.cat.scenes)[0]; }
        else { delete sg.scene; sg.show = Object.keys(live.cat.shows)[0]; }
        renderList();
      } }, el("option", { value: "show", selected: !isScene }, t("setlists.a_show")), el("option", { value: "scene", selected: isScene }, t("setlists.a_scene"))),
      ...(isScene ? [sceneSel] : [showSel, setSel]),
      el("select", { title: t("setlists.master_help"), onchange: (e) => { setKey(sg, "master", e.target.value === "" ? undefined : e.target.value === "on"); renderList(); } },
        el("option", { value: "" }, t("setlists.master_keep")), el("option", { value: "on", selected: sg.master === true }, t("setlists.master_on")),
        el("option", { value: "off", selected: sg.master === false }, t("setlists.master_off"))),
      el("span", { class: "tools" },
        el("button", { disabled: i === 0, onclick: () => { list.songs.splice(i - 1, 0, ...list.songs.splice(i, 1)); renderList(); } }, "↑"),
        el("button", { disabled: i === list.songs.length - 1, onclick: () => { list.songs.splice(i + 1, 0, ...list.songs.splice(i, 1)); renderList(); } }, "↓"),
        el("button", { class: "danger-text", onclick: () => { list.songs.splice(i, 1); renderList(); } }, "✕")));
  }));
}

function renderListState() {
  const dirty = JSON.stringify(list) !== listSaved;
  $("#setlist-save").classList.toggle("sel", dirty);
  $("#setlist-state").textContent = dirty ? t("shows.unsaved") : "";
}

async function saveList() {
  list.name = $("#setlist-name").value.trim() || t("setlists.untitled");
  const k = listKey || slug(list.name);
  if (await attempt(() => api("PUT", `/api/store/setlist/${encodeURIComponent(k)}`, { data: list }), t("setlists.saved", { name: list.name }))) {
    listKey = k;
    listSaved = JSON.stringify(list);
    await refreshCatalogue();
    renderList();
  }
}

export function init() {
  $("#show-pick").onchange = (e) => openShow(e.target.value);
  $("#show-new").onclick = () => openShow("");
  $("#show-save").onclick = saveShow;
  $("#show-name").oninput = (e) => { show.name = e.target.value; renderShowBar(); };
  $("#show-del").onclick = async () => {
    if (!confirm(t("shows.confirm_delete", { name: show.name }))) return;
    if (await attempt(() => api("DELETE", `/api/store/show/${showKey}`), t("shows.deleted", { name: show.name }))) {
      showSaved = JSON.stringify(show);
      await refreshCatalogue();
      openShow(Object.keys(live.cat.shows)[0] || "");
    }
  };
  $("#set-add").onclick = () => {
    const name = slug(prompt(t("shows.set_name_prompt")) || "");
    if (!name) return;
    if (show.sets[name]) return toast(t("shows.set_exists", { name }), true);
    show.sets[name] = { steps: [] };
    setName = name;
    changed();
  };
  $("#set-del").onclick = () => {
    if (!confirm(t("shows.confirm_delete_set", { name: setName }))) return;
    delete show.sets[setName];
    if (show.default_set === setName) show.default_set = Object.keys(show.sets)[0];
    setName = Object.keys(show.sets)[0];
    changed();
  };
  $("#set-default").onchange = () => { show.default_set = setName; changed(); };

  $("#setlist-pick").onchange = (e) => openList(e.target.value);
  $("#setlist-new").onclick = () => openList("");
  $("#setlist-save").onclick = saveList;
  $("#setlist-name").oninput = (e) => { list.name = e.target.value; renderListState(); };
  $("#setlist-del").onclick = async () => {
    if (!confirm(t("setlists.confirm_delete", { name: list.name }))) return;
    if (await attempt(() => api("DELETE", `/api/store/setlist/${listKey}`), t("setlists.deleted", { name: list.name }))) {
      listSaved = JSON.stringify(list);
      await refreshCatalogue();
      openList(Object.keys(live.cat.setlists)[0] || "");
    }
  };
  $("#song-add").onclick = () => {
    const first = Object.keys(live.cat.shows)[0];
    list.songs.push(first ? { name: t("setlists.new_song"), show: first } : { name: t("setlists.new_song"), scene: Object.keys(live.cat.scenes)[0] });
    renderList();
  };

  onShow("shows", async () => {
    colours = (await get("/api/effects")).colours;
    document.body.dataset.showsReady = "";
    if (!show) await openShow(live.state?.now.show || Object.keys(live.cat.shows)[0] || "");
    else renderShow();
    if (!list) await openList(live.state?.now.setlist || Object.keys(live.cat.setlists)[0] || "");
    else renderList();
    document.body.dataset.showsReady = "1";
  });
  window.addEventListener("beforeunload", (ev) => {
    if ((show && JSON.stringify(show) !== showSaved) || (list && JSON.stringify(list) !== listSaved)) ev.preventDefault();
  });
}
