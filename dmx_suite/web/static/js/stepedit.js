// Step scene editor (v3.2), inside the scene builder: steps programmed by hand with step and fade
// times. Each step only lists what changes (tracking): select lights, set colour / position / gobo
// / channels, or capture what they show now. Heads move dark or glide lit.
import { api, attempt, toast } from "./api.js";
import { $, el } from "./dom.js";
import { t } from "./i18n.js";
import { live } from "./state.js";

let currentStep = 0;

const num = (v) => (v === "" || v === undefined || v === null ? undefined : +v);

function setOrDrop(obj, k, v) {
  if (v === undefined || v === null || v === "" || Number.isNaN(v)) delete obj[k];
  else obj[k] = v;
}

export function isSteps(doc) {
  return doc.type === "steps";
}

export function toggleSteps(doc, on) {
  if (on) {
    doc.type = "steps";
    doc.steps ||= [{ name: t("steps.step_n", { n: 1 }), set: {} }];
    doc.step_s ??= 2;
  } else {
    for (const k of ["type", "steps", "step_s", "step_beats", "fade_s", "playback", "advance", "move", "dark_s"]) delete doc[k];
  }
  currentStep = 0;
}

function field(label, control) {
  return el("label", { class: "field" }, el("span", { text: label }), control);
}

function numIn(value, onChange, opts = {}) {
  return el("input", { type: "number", class: "narrow", min: 0, step: opts.step || 0.1, value: value ?? "", placeholder: opts.placeholder || "",
    onchange: (e) => onChange(num(e.target.value)) });
}

function select(options, value, onChange) {
  return el("select", { onchange: (e) => onChange(e.target.value) },
    ...options.map(([v, label]) => el("option", { value: v, selected: v === value || undefined }, label)));
}

export function renderSteps(doc, ctx) {
  const box = $("#steps-editor");
  if (!isSteps(doc)) return box.classList.add("hidden");
  box.classList.remove("hidden");
  const steps = doc.steps;
  currentStep = Math.min(currentStep, steps.length - 1);
  const inputs = ctx.inputs || [];
  const adv = typeof doc.advance === "object" ? "input:" + doc.advance.input : doc.advance || "timer";

  const settings = el("div", { class: "form" },
    field(t("steps.step_time"), numIn(doc.step_s, (v) => { setOrDrop(doc, "step_s", v); ctx.changed(); })),
    field(t("steps.step_beats"), numIn(doc.step_beats, (v) => { setOrDrop(doc, "step_beats", v); ctx.changed(); }, { step: 1, placeholder: t("steps.beats_hint") })),
    field(t("steps.fade_time"), numIn(doc.fade_s, (v) => { setOrDrop(doc, "fade_s", v); ctx.changed(); })),
    field(t("steps.playback"), select(["loop", "once", "bounce"].map((p) => [p, t("steps.playback_" + p)]), doc.playback || "loop",
      (v) => { setOrDrop(doc, "playback", v === "loop" ? undefined : v); ctx.changed(); })),
    field(t("steps.advance"), select([["timer", t("steps.advance_timer")], ["manual", t("steps.advance_manual")],
      ...inputs.map((i) => ["input:" + i.id, t("steps.advance_input", { name: i.name })])], adv, (v) => {
      setOrDrop(doc, "advance", v === "timer" ? undefined : v.startsWith("input:") ? { input: v.slice(6) } : v);
      ctx.changed();
    })),
    field(t("steps.move"), select([["", t("steps.move_profile")], ["dark", t("steps.move_dark")], ["lit", t("steps.move_lit")]], doc.move || "",
      (v) => { setOrDrop(doc, "move", v || undefined); ctx.changed(); })));

  const list = el("ol", { class: "layers steps-list" }, ...steps.map((st, i) => el("li", { class: i === currentStep ? "on" : "", "data-step": i },
    el("button", { class: "link name", onclick: () => { currentStep = i; ctx.changed(); } },
      `${i + 1}. ${st.name || ""}` + (st.step_s !== undefined ? ` · ${st.step_s}s` : "") + (st.fade_s !== undefined ? ` · ${t("steps.fade_short", { s: st.fade_s })}` : "") + (st.move ? ` · ${t("steps.move_" + st.move)}` : "")),
    el("span", { class: "tools" },
      el("button", { title: t("scenes.up"), disabled: i === 0 || undefined, onclick: () => { steps.splice(i - 1, 0, ...steps.splice(i, 1)); currentStep = i - 1; ctx.changed(); } }, "↑"),
      el("button", { title: t("scenes.down"), disabled: i === steps.length - 1 || undefined, onclick: () => { steps.splice(i + 1, 0, ...steps.splice(i, 1)); currentStep = i + 1; ctx.changed(); } }, "↓"),
      el("button", { title: t("steps.duplicate"), onclick: () => { steps.splice(i + 1, 0, JSON.parse(JSON.stringify(st))); currentStep = i + 1; ctx.changed(); } }, "⧉"),
      el("button", { title: t("steps.preview_step"), onclick: () => previewStep(doc, ctx, i) }, "▶"),
      el("button", { title: t("scenes.remove"), class: "danger-text", disabled: steps.length < 2 || undefined, onclick: () => { steps.splice(i, 1); currentStep = Math.max(0, i - 1); ctx.changed(); } }, "✕")))));

  const st = steps[currentStep];
  const stepForm = el("div", { class: "form" },
    field(t("steps.name"), el("input", { value: st.name || "", oninput: (e) => { st.name = e.target.value; }, onchange: () => ctx.changed() })),
    field(t("steps.step_time_own"), numIn(st.step_s, (v) => { setOrDrop(st, "step_s", v); ctx.changed(); }, { placeholder: t("steps.default") })),
    field(t("steps.fade_time_own"), numIn(st.fade_s, (v) => { setOrDrop(st, "fade_s", v); ctx.changed(); }, { placeholder: t("steps.default") })),
    field(t("steps.move"), select([["", t("steps.move_scene")], ["dark", t("steps.move_dark")], ["lit", t("steps.move_lit")]], st.move || "",
      (v) => { setOrDrop(st, "move", v || undefined); ctx.changed(); })));

  st.set ||= {};
  const sets = el("ul", { class: "step-sets" }, ...Object.entries(st.set).map(([target, attrs]) => el("li", {},
    el("b", { text: target }),
    ctx.swatch(attrs.colour, (c) => { setOrDrop(attrs, "colour", c); ctx.changed(); }, true, [target]),
    ...(ctx.moves(target) ? [select([["", t("steps.no_position")], ...(ctx.fx.positions || []).map((p) => [p, p])], typeof attrs.position === "string" ? attrs.position : "",
      (v) => { setOrDrop(attrs, "position", v || undefined); ctx.changed(); })] : []),
    ...(ctx.hasGobo(target) ? [select([["", t("steps.no_gobo")], ...(ctx.fx.gobos || []).map((g) => [g, g])], typeof attrs.gobo === "string" ? attrs.gobo : "",
      (v) => { setOrDrop(attrs, "gobo", v || undefined); ctx.changed(); })] : []),
    ...["zoom", "focus", "frost"].filter((k) => ctx.hasRole(target, k)).map((k) => field(t("steps.channel_" + k),
      el("input", { type: "range", min: 0, max: 1, step: 0.01, value: attrs[k] ?? 0, onchange: (e) => { attrs[k] = +e.target.value; ctx.changed(); } }))),
    el("button", { class: "danger-text mini", onclick: () => { delete st.set[target]; ctx.changed(); } }, "✕"))));

  box.replaceChildren(
    el("h2", { text: t("steps.title") }),
    el("details", { class: "scene-more" }, el("summary", { text: t("steps.settings") }), settings),
    list,
    el("div", { class: "row wrap" },
      el("button", { onclick: () => { steps.splice(currentStep + 1, 0, { name: t("steps.step_n", { n: steps.length + 1 }), set: {} }); currentStep += 1; ctx.changed(); } }, t("steps.add")),
      el("button", { onclick: () => playFrom(ctx, currentStep) }, t("steps.play_from"))),
    el("h3", { text: t("steps.this_step", { n: currentStep + 1 }) }),
    el("p", { class: "muted", text: t("steps.tracking_help") }),
    stepForm,
    el("div", { class: "row wrap" },
      el("button", { onclick: () => setSelected(ctx, st) }, t("steps.set_selected")),
      el("button", { onclick: () => capture(ctx, st) }, t("steps.capture"))),
    sets);
}

function setSelected(ctx, st) {
  const names = ctx.selectionNames();
  if (!names.length) return toast(t("scenes.select_first"), true);
  const key = names.length === 1 ? names[0] : names.join(",");
  if (names.length > 1) { // several lights: one entry each
    for (const n of names) st.set[n] ||= { colour: "white" };
  } else st.set[key] ||= { colour: "white" };
  ctx.changed();
}

async function capture(ctx, st) {
  const names = ctx.selectionNames();
  if (!names.length) return toast(t("scenes.select_first"), true);
  const r = await attempt(() => api("POST", "/api/steps/capture", { fixtures: names }));
  if (!r) return;
  Object.assign(st.set, r.set);
  toast(t("steps.captured", { n: Object.keys(r.set).length }));
  ctx.changed();
}

function previewStep(doc, ctx, i) {
  if (live.state?.gig_lock) return toast(t("wheel.preview_locked"), true);
  const data = { ...doc, name: doc.name || "preview" };
  attempt(() => api("POST", "/api/preview", { scene_data: data, seconds: 10, step: i }), (r) => r.message);
}

function playFrom(ctx, i) {
  if (!ctx.key()) return toast(t("steps.save_first"), true);
  attempt(() => api("POST", "/api/control", { cmd: "scene_step", scene: ctx.key(), step: i }));
}
