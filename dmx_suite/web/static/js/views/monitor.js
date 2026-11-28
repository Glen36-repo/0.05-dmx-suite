// Monitor page (v4): watch what goes out over DMX and what comes in / goes out over MIDI. Read-only:
// nothing here changes the output (works under gig lock); only Learn (inputs.yaml), the MIDI test send and
// the v5 test patterns (straight to the interface, stopped when this page is left) change anything, and
// those follow the usual locks (gig lock: keep-alive only).
import { api, attempt, get, toast } from "../api.js";
import { $, $$, el, remember } from "../dom.js";
import { watchFrames } from "../frames.js";
import { t } from "../i18n.js";
import { onLeave, onShow } from "../nav.js";
import { live, onCatalogue } from "../state.js";

let uni = remember.get("monitor.uni", 0);
let out = remember.get("monitor.out", "");
let view = remember.get("monitor.view", "grid");
let stopFeed = null;
let names = {}; // channel -> "bar_2 red px5"
let frame = null; // Uint8Array of what the interface sent, or null
let lastFrame = null;
const movedAt = new Float64Array(512); // when each channel last changed (changed-only view)
const paused = { dmx: false, "midi-in": false, "midi-out": false, tempo: false };
let inSeq = 0, outSeq = 0;
let inRows = [], outRows = [];
const heat = new Map(); // note -> last velocity (drum pad check)
let timer = null;
const KEEP = 2000; // rows kept on screen per log (the server keeps 5000)

const shown = () => $("#page-monitor").classList.contains("on");
const ms = (v) => (v === null || v === undefined ? t("layout.never") : t("layout.ms_ago", { n: v }));
const clock = (ts) => new Date(ts * 1000).toLocaleTimeString("en-AU", { hour12: false }) + "." + String(Math.floor((ts * 1000) % 1000)).padStart(3, "0");

// ---------------------------------------------------------------- DMX out

async function loadSources() {
  const r = await get("/api/routing").catch(() => null);
  if (!r) return;
  const us = r.universes.length ? r.universes : [0];
  if (!us.includes(uni)) uni = us[0];
  $("#mon-uni").replaceChildren(...us.map((u) => el("option", { value: u, selected: u === uni }, t("monitor.u", { u }))));
  const outs = r.rows.filter((x) => x.universe === uni && x.output !== null && x.output !== undefined);
  $("#mon-out").replaceChildren(...outs.map((x) => el("option", { value: String(x.output), selected: String(x.output) === out }, x.interface)),
    el("option", { value: "engine", selected: out === "engine" }, t("monitor.engine")));
  if (!outs.some((x) => String(x.output) === out) && out !== "engine") out = outs.length ? String(outs[0].output) : "engine";
  $("#mon-out").value = out;
  names = await get(`/api/monitor/channels?u=${uni}`).catch(() => ({}));
  routing = r;
  testTargets();
}

function watch() {
  stopFeed?.();
  stopFeed = null;
  if (!shown()) return;
  stopFeed = watchFrames(uni, out, (f) => {
    if (paused.dmx) return;
    frame = f.values;
    const now = performance.now();
    if (frame && lastFrame) for (let i = 0; i < 512; i++) if (frame[i] !== lastFrame[i]) movedAt[i] = now;
    lastFrame = frame;
    const s = f.stats || {};
    $("#mon-dmx").classList.toggle("testing", !!f.test);
    $("#mon-dmx-stats").textContent = (f.test ? `TEST: ${f.test.name} · ` : "") + t("monitor.stats", { source: f.source, fps: s.fps ?? "-", frames: s.frames ?? "-",
      errors: s.errors ?? "-", jitter: s.jitter_ms ?? "-", last: ms(s.last_frame_age_ms) });
    drawTiming(f);
    const flag = f.no_frames ? t("monitor.no_frames", { source: f.source, u: uni })
      : s.all_zero ? t("monitor.all_zero")
      : s.last_frame_age_ms > 2000 ? t("monitor.stale", { s: Math.round(s.last_frame_age_ms / 1000) }) : "";
    $("#mon-dmx-flag").textContent = flag;
    $("#mon-dmx-flag").classList.toggle("hidden", !flag);
    drawDmx();
  });
}

// v5: the interface's driver and measured timing beside the targets, and any failing checks with the fix
function drawTiming(f) {
  const tm = f.timing, ck = f.checks;
  const line = $("#mon-dmx-timing");
  if (!tm) { line.textContent = ""; $("#mon-dmx-checks").replaceChildren(); return; }
  const m = tm.measured, g = tm.target;
  const driver = t(`timing.${ck?.driver_type || (tm.backend === "d2xx" ? "d2xx" : "vcp")}`);
  line.textContent = t("timing.line", { driver, method: tm.method_name, brk: m.break_us ?? "-", tbrk: g.break_us,
    mab: m.mab_us ?? "-", tmab: g.mab_us, fps: m.fps ?? "-", tfps: g.fps, write: m.write_ms ?? "-", jit: m.jitter_ms ?? "-" });
  line.classList.toggle("amber", tm.warnings.length > 0);
  line.title = [...tm.warnings, tm.note].join("\n");
  const key = JSON.stringify(ck);
  if (line.dataset.k === key) return;
  line.dataset.k = key;
  const rows = (ck?.problems || []).map((p) => el("div", { class: "ck warn" }, el("b", { text: "⚠ " }), p));
  const tools = [el("button", { class: "mini", onclick: checkNow }, t("checks.now"))];
  if (ck && ck.driver_type === "d2xx" && ck.latency_ms > 1) tools.push(el("button", { class: "mini", onclick: setLatency }, t("checks.latency")));
  $("#mon-dmx-checks").replaceChildren(...(rows.length ? rows : ck ? [el("div", { class: "ck", text: t("checks.all_pass") })] : []), ...tools);
}

async function checkNow() {
  const r = await attempt(() => get("/api/outputs/check"));
  if (r) { $("#mon-dmx-timing").dataset.k = ""; toast(r.outputs.map((o) => `${o.interface}: ${o.result}`).join(" · ") || "-"); }
}

async function setLatency() {
  if (!confirm(t("checks.latency_confirm"))) return;
  const r = await attempt(() => api("POST", "/api/outputs/latency", { output: +out, ms: 1 }));
  if (r) toast(t("checks.latency_done", { ms: r.latency_ms }));
}

function drawDmx() {
  const body = $("#mon-dmx-body");
  if (view === "hex") {
    const lines = [];
    for (let r = 0; r < 32; r++) {
      const row = frame ? [...frame.slice(r * 16, r * 16 + 16)].map((v) => v.toString(16).padStart(2, "0")).join(" ") : "";
      lines.push(String(r * 16 + 1).padStart(3, " ") + ": " + row);
    }
    body.replaceChildren(el("div", { class: "dmx-hex", text: lines.join("\n") }));
    return;
  }
  if (view === "fixture") {
    const by = {};
    for (const [c, n] of Object.entries(names)) { const [fid, ...rest] = n.split(" "); (by[fid] ||= []).push([+c, rest.join(" ")]); }
    body.replaceChildren(el("div", { class: "dmx-fx" }, ...Object.entries(by).map(([fid, chs]) => el("div", { class: "fxbox" },
      el("strong", { text: fid }), ...chs.map(([c, n]) => {
        const v = frame ? frame[c - 1] : null;
        return el("div", { class: "ch", title: `ch ${c}` }, el("span", { text: n }), el("span", { text: v ?? "" }),
          el("div", { class: "bar", style: `width:${v ? (v / 255) * 100 : 0}%` }));
      })))));
    return;
  }
  let grid = body.querySelector(".dmx-grid");
  if (!grid) {
    grid = el("div", { class: "dmx-grid" });
    for (let c = 1; c <= 512; c++) grid.append(el("div", { class: "dc", "data-ch": c }, el("span", { class: "n", text: c }), el("span", { class: "v" })));
    body.replaceChildren(grid);
  }
  const now = performance.now();
  grid.querySelectorAll(".dc").forEach((cell, i) => {
    const v = frame ? frame[i] : null;
    const name = names[i + 1];
    cell.classList.toggle("patched", !!name);
    cell.title = `ch ${i + 1}${name ? " · " + name : ""}${v !== null ? " = " + v : ""}`;
    const recent = now - movedAt[i] < 3000;
    cell.classList.toggle("moved", recent);
    const hide = view === "changed" && !recent;
    cell.querySelector(".v").textContent = v === null || hide ? "" : v || "";
    cell.style.setProperty("--v", v && !hide ? v / 255 : 0);
  });
}

// ---------------------------------------------------------------- test patterns (v5)

let routing = null;
let myTest = false; // started from this page: stopped when the page is left
let myTestAt = 0; // when it was confirmed (performance.now()); Infinity while the start is on its way

function testFields() {
  const p = $("#test-pattern").value;
  $("#test-fixture").classList.toggle("hidden", !(p === "find" || p === "ramp"));
  $("#test-channel").classList.toggle("hidden", p !== "ramp");
  $("#test-value").classList.toggle("hidden", !(p === "ramp" || p === "keep_alive"));
  $("#test-dwell").classList.toggle("hidden", p !== "chase");
  $("#test-patched-l").classList.toggle("hidden", p !== "all_full");
  const locked = !!live.state?.gig_lock;
  const [kind, n] = ($("#test-target").value || "").split(":");
  const row = kind === "o" && routing ? routing.rows.find((r) => String(r.output) === n) : null;
  $("#cycle-go").classList.toggle("hidden", !(row && row.timing));
  $("#cycle-go").disabled = locked;
  $("#test-go").disabled = locked && p !== "keep_alive";
  $("#test-go").title = locked && p !== "keep_alive" ? t("test.locked") : "";
}

function testTargets() {
  if (!routing) return;
  const us = routing.universes.length ? routing.universes : [0];
  const opts = [];
  for (const u of us) {
    opts.push(el("option", { value: `u:${u}` }, t("test.all_outputs", { u })));
    for (const r of routing.rows) if (r.universe === u && r.output !== null && r.output !== undefined)
      opts.push(el("option", { value: `o:${r.output}` }, t("test.one_output", { u, name: r.interface })));
  }
  const keep = $("#test-target").value;
  $("#test-target").replaceChildren(...opts);
  if (keep) $("#test-target").value = keep;
  const fids = [...new Set(Object.values(names).map((n) => n.split(" ")[0]))];
  const kf = $("#test-fixture").value;
  $("#test-fixture").replaceChildren(...fids.map((f) => el("option", { value: f }, f)));
  if (kf) $("#test-fixture").value = kf;
}

async function startTest() {
  const p = $("#test-pattern").value;
  const [kind, n] = $("#test-target").value.split(":");
  const body = { pattern: p, timeout_s: +$("#test-timeout").value || 60, patched_only: $("#test-patched").checked };
  if (kind === "o") body.output = +n; else body.universe = +n;
  if (p === "find" || p === "ramp") body.fixture = $("#test-fixture").value;
  if (p === "ramp") {
    if ($("#test-channel").value) { body.channel = +$("#test-channel").value; delete body.fixture; }
    else body.role = (prompt(t("test.channel")) || "red").trim();
  }
  if ((p === "ramp" || p === "keep_alive") && $("#test-value").value !== "") body.value = +$("#test-value").value;
  if (p === "chase") body.dwell_s = +$("#test-dwell").value || 2;
  // ours from the moment it's asked for: the live feed can show it running before the reply comes back, and
  // leaving the page in that gap must still stop it
  myTest = true;
  myTestAt = Infinity;
  if (await attempt(() => api("POST", "/api/test/run", body))) { myTestAt = performance.now(); pollTest(); }
  else myTest = false;
}

async function stopTest(why = "stopped") {
  myTest = false;
  await api("POST", "/api/test/stop", { why }).catch(() => null);
  pollTest();
}

async function startCycle() {
  const [, n] = $("#test-target").value.split(":");
  myTest = true;
  myTestAt = Infinity;
  if (await attempt(() => api("POST", "/api/cycle/start", { output: +n }))) { myTestAt = performance.now(); pollTest(); }
  else myTest = false;
}

function drawCycle(c) {
  const running = c && c.state === "running";
  $("#cycle-live").classList.toggle("hidden", !running);
  if (running) {
    $("#cycle-of").textContent = t("cycle.of", { step: c.step, of: c.of });
    $("#cycle-step").textContent = c.label;
  }
  const res = !c || running ? "" : c.state === "confirmed" ? t("cycle.confirmed", { label: c.result.label })
    : c.state === "no_response" ? t("cycle.no_response", { method: c.original.break_method, us: c.original.break_us })
    : t("cycle.stopped");
  $("#cycle-result").textContent = res;
}

async function pollTest() {
  const asked = performance.now(); // a status asked for before our start was confirmed mustn't disown it
  const cy = await get("/api/cycle").catch(() => null);
  if (cy) drawCycle(cy.cycle);
  const r = await get("/api/test").catch(() => null);
  if (!r) return;
  const tst = r.test;
  $("#test-live").classList.toggle("hidden", !tst);
  if (tst) {
    $("#test-name").textContent = `${t("test.running")} ${tst.name}`;
    $("#test-what").textContent = tst.now || "";
    $("#test-left").textContent = t("test.left", { s: Math.round(tst.left_s) });
  } else if (asked > myTestAt) myTest = false;
  $("#test-log").replaceChildren(...r.log.slice(-4).reverse().map((x) => el("div", { text: t("test.log", {
    time: new Date(x.time * 1000).toLocaleTimeString("en-AU", { hour12: false }), what: x.what, pattern: x.pattern,
    u: x.universe, out: x.output !== null ? ` output ${x.output + 1}` : "", by: x.by }) })));
  testFields();
}

// ---------------------------------------------------------------- "Rig not responding" (v5)

let ffSummary = "";

function drawFaultFind(v) {
  $("#ff").classList.remove("hidden");
  ffSummary = v.summary || "";
  $("#ff-where").textContent = v.stage === "steps" ? t("ff.step", { n: v.number, of: v.of }) : "";
  $("#ff-flag").textContent = v.flag || "";
  $("#ff-flag").classList.toggle("hidden", !v.flag);
  $("#ff-text").textContent = v.instruction || "";
  const label = (a) => ["yes", "no", "pass", "fail", "restart"].includes(a) ? t(`ff.a_${a}`) : a;
  const btns = (v.answers || []).map((a) => el("button", { class: a === "pass" || a === "yes" ? "primary" : "",
    onclick: () => ffDo({ action: "answer", answer: a }) }, label(a)));
  if (v.test) {
    const tb = el("button", { disabled: !v.test_allowed, title: v.test_allowed ? "" : t("ff.locked"),
      onclick: async () => { myTest = true; myTestAt = Infinity; await ffDo({ action: "test" }); myTestAt = performance.now(); pollTest(); } },
    t("ff.test"));
    btns.unshift(tb);
  }
  $("#ff-answers").replaceChildren(...btns);
  $("#ff-history").replaceChildren(...(v.history || []).map((h) => el("li", { text: `${h.step}: ${h.result}${h.detail ? " · " + h.detail : ""}` })));
}

async function ffDo(body) {
  const v = await attempt(() => api("POST", "/api/faultfind", body));
  if (v) drawFaultFind(v);
}

export function openFaultFind() {
  ffDo({ action: "start" });
}

// ---------------------------------------------------------------- tempo (v6 Part B)

const LANES = ["kick", "snare", "hat", "tom", "cymbal"];
let tempoParams = null;

function css(name, fallback) { return getComputedStyle(document.body).getPropertyValue(name).trim() || fallback; }

function sized(cv) {
  const w = cv.clientWidth || 600, h = cv.height;
  if (cv.width !== w) cv.width = w;
  return [cv.getContext("2d"), w, h];
}

function drawTempo(r) {
  const st = r.status, dbg = r.debug || {};
  $("#tempo-source").value = st.source;
  $("#tempo-bpm").textContent = st.bpm ? t("tempo2.bpm", { bpm: st.bpm }) : t("tempo2.none");
  $("#tempo-beat").textContent = st.bar_beat ? t("tempo2.beat", { beat: st.bar_beat }) : "";
  $("#tempo-info").textContent = st.source === "drums" ? t("tempo2.info", { raw: st.raw_bpm ?? "-", conf: st.confidence ?? "-",
    state: t(st.freewheel ? "tempo2.freewheel" : "tempo2.locked"), seed: st.seed_source || "-" }) : "";
  const span = 8;
  const [c, w, h] = sized($("#tempo-lanes"));
  c.clearRect(0, 0, w, h);
  const x = (tt) => w * (1 + tt / span);
  const lh = h / LANES.length;
  c.font = "10px sans-serif";
  c.fillStyle = css("--muted", "#888");
  LANES.forEach((l, i) => c.fillText(l, 2, i * lh + 11));
  for (const g of dbg.grid || []) {
    c.strokeStyle = css("--line", "#666");
    c.lineWidth = g.beat === 1 ? 2 : 0.5;
    c.beginPath(); c.moveTo(x(g.t), 0); c.lineTo(x(g.t), h); c.stroke();
  }
  c.fillStyle = css("--accent", "#3a8");
  for (const o of dbg.onsets || []) {
    const i = LANES.indexOf(o.role);
    if (i < 0) continue;
    c.globalAlpha = 0.4 + 0.6 * Math.min(1, o.w);
    c.fillRect(x(o.t) - 2, i * lh + 2, 4, lh - 4);
  }
  c.globalAlpha = 1;
  const hint = (ctx, w0, h0, text) => {
    ctx.fillStyle = css("--muted", "#888"); ctx.font = "13px sans-serif"; ctx.textAlign = "center";
    ctx.fillText(text, w0 / 2, h0 / 2 + 4); ctx.textAlign = "start";
  };
  if (!(dbg.onsets || []).length) hint(c, w, h, t(st.source === "drums" ? "tempo2.empty_hits" : "tempo2.empty_other"));
  const [g2, w2, h2] = sized($("#tempo-graph"));
  g2.clearRect(0, 0, w2, h2);
  const hist = dbg.history || [];
  const vals = hist.flatMap(([, raw, outb]) => [raw, outb]).filter((v) => v);
  if (vals.length) {
    const lo = Math.min(...vals) - 2, hi = Math.max(...vals) + 2;
    const y = (v) => h2 - ((v - lo) / (hi - lo)) * h2;
    const xs = (tt) => w2 * (1 + tt / 60);
    for (const [idx, col, lw] of [[1, css("--muted", "#888"), 1], [2, css("--accent", "#3a8"), 2.5]]) {
      g2.strokeStyle = col; g2.lineWidth = lw; g2.beginPath();
      let started = false;
      for (const row of hist) { if (!row[idx]) continue; const px = xs(row[0]), py = y(row[idx]); started ? g2.lineTo(px, py) : g2.moveTo(px, py); started = true; }
      g2.stroke();
    }
    g2.fillStyle = css("--muted", "#888"); g2.font = "10px sans-serif";
    g2.fillText(`${Math.round(hi)}`, 2, 10); g2.fillText(`${Math.round(lo)}`, 2, h2 - 2);
  } else hint(g2, w2, h2, t("tempo2.empty_graph"));
  if (r.params && JSON.stringify(r.params) !== JSON.stringify(tempoParams)) { tempoParams = r.params; drawParams(); }
}

function drawParams() {
  const p = tempoParams;
  const num = (k, v, path) => el("label", {}, el("span", { text: k }), el("input", { type: "number", step: "any", value: v,
    onchange: (e) => setParam(path, +e.target.value) }));
  const rows = Object.entries(p).filter(([k]) => k !== "weights").map(([k, v]) => num(k, v, [k]));
  rows.push(...Object.entries(p.weights || {}).map(([k, v]) => num(`weight ${k}`, v, ["weights", k])));
  rows.push(el("button", { class: "mini", onclick: saveParams }, t("tempo2.save")));
  $("#tempo-params").replaceChildren(...rows);
}

async function setParam(path, v) {
  const params = path.length === 2 ? { weights: { [path[1]]: v } } : { [path[0]]: v };
  await attempt(() => api("POST", "/api/tempo", { action: "params", params }));
}

async function saveParams() {
  const { weights, ...rest } = tempoParams;
  if (await attempt(() => api("POST", "/api/tempo", { action: "params", params: { ...rest, weights }, save: true }))) toast(t("tempo2.saved"));
}

async function pollTempo() {
  const r = await get("/api/tempo?debug=1").catch(() => null);
  if (r && r.status) drawTempo(r);
}

function dmxCsv() {
  const rows = [["channel", "name", "value"], ...[...Array(512).keys()].map((i) => [i + 1, names[i + 1] || "", frame ? frame[i] : ""])];
  return rows.map((r) => r.join(",")).join("\n");
}

// ---------------------------------------------------------------- MIDI in / out

function inQuery() {
  const qs = new URLSearchParams({ dir: "in", since: String(inSeq), n: "500" });
  if ($("#mon-in-port").value.trim()) qs.set("port", $("#mon-in-port").value.trim());
  if (+$("#mon-in-ch").value) qs.set("channel", $("#mon-in-ch").value);
  if ($("#mon-in-type").value) qs.set("type", $("#mon-in-type").value);
  if ($("#mon-in-unmapped").checked) qs.set("unmapped", "1");
  return qs;
}

async function poll() {
  if (!shown()) return;
  const st = await get("/api/monitor/status").catch(() => null);
  if (st) drawPorts(st);
  pollTest();
  if (!paused.tempo) pollTempo();
  if (!paused["midi-in"]) {
    const rows = await get(`/api/monitor/midi?${inQuery()}`).catch(() => []);
    if (rows.length) {
      inSeq = rows[rows.length - 1].seq;
      inRows = [...inRows, ...rows].slice(-KEEP);
      for (const r of rows) if (r.type === "note_on" && r.value > 0) heat.set(r.number, r.value);
      drawIn(rows);
    }
  }
  if (!paused["midi-out"]) {
    const rows = await get(`/api/monitor/midi?dir=out&since=${outSeq}&n=500`).catch(() => []);
    if (rows.length) {
      outSeq = rows[rows.length - 1].seq;
      outRows = [...outRows, ...rows].slice(-KEEP);
      drawOut(rows);
    }
  }
}

function drawPorts(st) {
  const ins = st.midi_in_sim ? [el("span", { text: t("monitor.sim_in") })]
    : st.midi_in.map((m) => el("span", { class: "port" },
      el("span", { class: "led " + (m.connected ? (m.last && Date.now() / 1000 - m.last < 0.5 ? "act" : "ok") : "bad") }),
      `${m.alias || m.name}${m.port && m.port !== m.name ? ` (${m.port})` : ""} · ${t(m.connected ? "monitor.connected" : "monitor.unplugged")}  `));
  $("#mon-in-ports").replaceChildren(...ins, el("span", { class: "muted",
    text: " " + t("monitor.rates", { hits: st.rates.hits_per_s, clock: st.rates.clock_per_s, energy: st.energy }) }));
  $("#mon-out-ports").replaceChildren(...(st.midi_out.length ? st.midi_out.map((m) => el("span", {},
    el("span", { class: "led " + (m.connected ? "ok" : "bad") }), `${m.name} · ${t(m.connected ? "monitor.connected" : "monitor.unplugged")}  `))
    : [el("span", { text: t("monitor.no_out") }), " ", el("a", { href: "#", onclick: (e) => { e.preventDefault(); goSetup(); } }, t("menu.setup"))]));
  const ports = st.midi_out.filter((m) => m.connected);
  const sel = $("#send-port");
  if (sel.dataset.k !== ports.map((p) => p.port).join("|")) {
    sel.dataset.k = ports.map((p) => p.port).join("|");
    sel.replaceChildren(...ports.map((p) => el("option", { value: p.port }, p.name)));
  }
  $("#send-go").disabled = !ports.length || !!live.state?.gig_lock;
  $("#mon-heat").replaceChildren(...[...heat.entries()].sort((a, b) => a[0] - b[0]).map(([n, v]) =>
    el("span", { class: "hn", style: `--v:${v / 127}`, title: `note ${n} vel ${v}` }, `${n}:${v}`)));
}

function inRow(r) {
  const learn = el("button", { class: "mini", title: t("monitor.learn_tip"), onclick: () => learnFrom(r) }, t("monitor.learn"));
  return el("tr", { class: r.result === "unmapped" ? "unmapped" : "" },
    el("td", { text: clock(r.time), title: `+${r.since_start}s` }), el("td", { text: r.port }), el("td", { text: r.channel }),
    el("td", { text: r.type }), el("td", { text: r.note ? `${r.number} ${r.note}` : r.number }), el("td", { text: r.value }),
    el("td", { text: r.input + (r.roles ? ` (${r.roles})` : "") }), el("td", { text: r.result }), el("td", {}, r.input ? "" : learn));
}

function drawIn(rows) {
  const body = $("#mon-in-log");
  body.prepend(...rows.slice().reverse().map(inRow));
  while (body.children.length > KEEP) body.lastChild.remove();
}

function drawOut(rows) {
  const body = $("#mon-out-log");
  body.prepend(...rows.slice().reverse().map((r) => el("tr", {},
    el("td", { text: clock(r.time) }), el("td", { text: r.port }), el("td", { text: r.channel }), el("td", { text: r.type }),
    el("td", { text: r.note ? `${r.number} ${r.note}` : r.number }), el("td", { text: r.value }), el("td", { text: r.result }))));
  while (body.children.length > KEEP) body.lastChild.remove();
}

// an event -> a named input in inputs.yaml (the same store path as the MIDI page's inputs)
async function learnFrom(r) {
  const name = (prompt(t("monitor.learn_prompt")) || "").trim().toLowerCase().replace(/[^a-z0-9_]+/g, "_");
  if (!name) return;
  const type = r.type.startsWith("note") ? "note" : r.type;
  const value = { name, type, channel: r.channel, ...(type === "note" ? { notes: [r.number] } : { number: r.number }) };
  if (await attempt(() => api("POST", "/api/store/input", { action: "put", device: "learned", name, value }),
    t("monitor.learned", { name }))) inRows = [];
}

const csvLog = (rows) => [["time", "since_start_s", "port", "channel", "type", "number", "note", "value", "input", "roles", "result"],
  ...rows.map((r) => [new Date(r.time * 1000).toISOString(), r.since_start, r.port, r.channel, r.type, r.number, r.note, r.value,
    r.input, r.roles, r.result].map((x) => `"${String(x ?? "").replace(/"/g, '""')}"`))].map((r) => r.join(",")).join("\n");

function download(name, text) {
  const a = el("a", { download: name, href: URL.createObjectURL(new Blob([text], { type: "text/csv" })) });
  document.body.append(a);
  a.click();
  a.remove();
}

function goSetup() { $("#menu [data-page=setup]").click(); }

// the status bar's DMX / MIDI tiles open the matching pane
export function focusPane(pane) {
  const p = $(`#page-monitor [data-pane="${pane}"]`);
  if (p) p.scrollIntoView({ block: "nearest" });
}

export function init() {
  $("#mon-uni").onchange = async (e) => { uni = +e.target.value; remember.set("monitor.uni", uni); out = ""; lastFrame = null; await loadSources(); watch(); };
  $("#mon-out").onchange = (e) => { out = e.target.value; remember.set("monitor.out", out); lastFrame = null; watch(); };
  $$("#mon-dmx-view [data-view]").forEach((b) => {
    b.classList.toggle("sel", b.dataset.view === view);
    b.onclick = () => {
      view = b.dataset.view;
      remember.set("monitor.view", view);
      $$("#mon-dmx-view [data-view]").forEach((x) => x.classList.toggle("sel", x === b));
      $("#mon-dmx-body").replaceChildren();
      drawDmx();
    };
  });
  for (const pane of $$("#page-monitor .mon-pane")) {
    const key = pane.dataset.pane;
    pane.querySelectorAll("[data-act]").forEach((b) => (b.onclick = () => {
      const act = b.dataset.act;
      if (act === "pause") { paused[key] = !paused[key]; b.textContent = t(paused[key] ? "monitor.resume" : "monitor.pause"); b.classList.toggle("sel", paused[key]); }
      if (act === "full") pane.classList.toggle("full");
      if (act === "clear" && key === "midi-in") { inRows = []; heat.clear(); $("#mon-in-log").replaceChildren(); }
      if (act === "clear" && key === "midi-out") { outRows = []; $("#mon-out-log").replaceChildren(); }
      if (act === "csv") {
        if (key === "dmx") download(`dmx-U${uni}.csv`, dmxCsv());
        else download(`midi-${key === "midi-in" ? "in" : "out"}.csv`, csvLog(key === "midi-in" ? inRows : outRows));
      }
    }));
  }
  ["#mon-in-port", "#mon-in-ch", "#mon-in-type", "#mon-in-unmapped"].forEach((s) => $(s).addEventListener("change", () => {
    inSeq = 0; inRows = []; $("#mon-in-log").replaceChildren(); poll();
  }));
  $("#send-go").onclick = async () => {
    const r = await attempt(() => api("POST", "/api/monitor/send", { port: $("#send-port").value, type: $("#send-type").value,
      channel: +$("#send-ch").value, number: +$("#send-num").value, value: +$("#send-val").value }));
    if (r) toast(t("monitor.sent", { port: r.port }));
  };
  onShow("monitor", async () => {
    await loadSources();
    watch();
    poll();
    clearInterval(timer);
    timer = setInterval(poll, 300);
  });
  $("#ff-open").onclick = openFaultFind;
  $("#tempo-source").onchange = (e) => attempt(() => api("POST", "/api/tempo", { action: "source", source: e.target.value }));
  $("#tempo-tap").onclick = () => api("POST", "/api/tempo", { action: "tap" }).catch(() => null);
  $("#tempo-params-btn").onclick = () => $("#tempo-params").classList.toggle("hidden");
  $("#ff-close").onclick = () => $("#ff").classList.add("hidden");
  $("#ff-copy").onclick = async () => { try { await navigator.clipboard.writeText(ffSummary); toast(t("ff.copied")); } catch { prompt("", ffSummary); } };
  $("#test-pattern").onchange = testFields;
  $("#test-target").onchange = testFields;
  $("#cycle-go").onclick = startCycle;
  $("#cycle-yes").onclick = async () => { await attempt(() => api("POST", "/api/cycle/confirm", {})); pollTest(); };
  $("#test-go").onclick = startTest;
  $("#test-stop").onclick = () => stopTest();
  onLeave("monitor", () => {
    stopFeed?.(); stopFeed = null; clearInterval(timer);
    if (myTest) stopTest("page left");
  });
  onCatalogue(() => { if (shown()) loadSources(); });
}
