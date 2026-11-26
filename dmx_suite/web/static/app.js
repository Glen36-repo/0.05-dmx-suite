// 0.05 DMX Suite browser UI. Vanilla JS, no build step, no internet needed.
"use strict";

const TOKEN = document.querySelector('meta[name="dmx-token"]').content;
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k === "text") e.textContent = v;
    else e.setAttribute(k, v);
  }
  for (const k of kids) e.append(k);
  return e;
};

let state = null;
let cat = null;
let midiSeq = 0;
let lastAlert = 0;
let midiChannel = "";
let lastBadDevices = null;
let livePlan = null, arrangePlan = null, layoutDirty = false;

function onArrange(what, id) {
  if (what === "move") layoutDirty = true;
  const sel = id && arrangePlan.layout[id];
  $("#arrange-sel").textContent = sel
    ? `${id}: ${sel.x.toFixed(2)} m from stage left, ${sel.y.toFixed(2)} m from the front, facing ${Math.round(sel.rot || 0)}°`
    : "Tap a light to select it";
  $("#layout-save").classList.toggle("sel", layoutDirty);
}
$("#rot-l").onclick = () => arrangePlan.rotate(-15);
$("#rot-r").onclick = () => arrangePlan.rotate(15);
const resize = () => {
  const w = +$("#stage-w").value, d = +$("#stage-d").value;
  if (w >= 1 && d >= 1) { arrangePlan.build(cat, arrangePlan.layout, { width: w, depth: d }); layoutDirty = true; onArrange("move", arrangePlan.selected); }
};
$("#stage-w").onchange = resize;
$("#stage-d").onchange = resize;
$("#layout-reset").onclick = () => { arrangePlan.build(cat); $("#stage-w").value = cat.stage.width; $("#stage-d").value = cat.stage.depth; layoutDirty = false; onArrange("select", null); };
$("#layout-save").onclick = async () => {
  try {
    await api("PUT", "/api/layout", { stage: { width: arrangePlan.width, depth: arrangePlan.depth }, layout: arrangePlan.layout });
    cat = await get("/api/catalogue");
    buildCatalogue();
    toast("Stage plan saved");
  } catch (e) {
    toast(e.message, true);
  }
};

// ------------------------------------------------------------------ api

async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json", "X-DMX-Token": TOKEN },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}
const get = (path) => fetch(path).then((r) => r.json());

async function cmd(name, args = {}) {
  try {
    const r = await api("POST", "/api/control", { cmd: name, ...args });
    if (r.bpm) toast(`${Math.round(r.bpm)} BPM`);
    return r;
  } catch (e) {
    toast(e.message, true);
  }
}

let toastTimer;
function toast(msg, err = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (err ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), err ? 6000 : 2500);
}

// ------------------------------------------------------------------ tabs

$$("#tabs button").forEach((b) =>
  b.addEventListener("click", () => {
    $$("#tabs button").forEach((x) => x.classList.toggle("on", x === b));
    $$(".tab").forEach((t) => t.classList.toggle("on", t.id === "tab-" + b.dataset.tab));
    if (b.dataset.tab === "setup") loadAddresses();
    if (b.dataset.tab === "files") loadFiles();
    if (b.dataset.tab === "midi") loadMap();
  })
);

// generic data-cmd buttons
document.addEventListener("click", (ev) => {
  const b = ev.target.closest("[data-cmd]");
  if (!b) return;
  const args = {};
  for (const [k, v] of Object.entries(b.dataset)) if (k !== "cmd") args[k] = v;
  cmd(b.dataset.cmd, args);
});

// ------------------------------------------------------------------ live tab

$("#master").onclick = () => cmd("master");
$("#blackout").onclick = () => cmd("blackout");
$("#tap").onclick = () => cmd("tap");
$("#giglock").onclick = async () => {
  try {
    await api("POST", "/api/giglock", { on: !state.gig_lock });
  } catch (e) {
    toast(e.message, true);
  }
};
$$("[data-haze]").forEach((b) => (b.onclick = () => cmd("haze", { action: b.dataset.haze })));
const boost = $("#boost");
const boostDown = (e) => { e.preventDefault(); boost.classList.add("on"); cmd("haze", { action: "boost" }); };
const boostUp = () => { if (boost.classList.contains("on")) { boost.classList.remove("on"); cmd("haze", { action: "release" }); } };
boost.addEventListener("pointerdown", boostDown);
["pointerup", "pointerleave", "pointercancel"].forEach((ev) => boost.addEventListener(ev, boostUp));

$("#setlist-go").onclick = () => cmd("setlist", { setlist: $("#setlist").value });

function buildCatalogue() {
  const shows = $("#shows");
  shows.replaceChildren();
  for (const [k, s] of Object.entries(cat.shows)) {
    shows.append(el("button", { "data-show": k, onclick: () => cmd("show", { show: k }) }, s.name));
  }
  for (const [k, s] of Object.entries(cat.scenes)) {
    shows.append(el("button", { "data-scene": k, onclick: () => cmd("scene", { scene: k }) }, "▸ " + s));
  }
  const sl = $("#setlist");
  sl.replaceChildren(...Object.entries(cat.setlists).map(([k, s]) => el("option", { value: k }, s.name)));

  // faders
  const f = $("#faders");
  f.replaceChildren();
  const fader = (label, key, send) => {
    const out = el("span", { text: "" });
    const inp = el("input", { type: "range", min: 0, max: 100, step: 1, "data-key": key });
    inp.addEventListener("input", () => { out.textContent = inp.value + "%"; send(inp.value / 100); });
    f.append(el("div", { class: "fader" }, el("label", {}, el("span", { text: label }), out), inp));
  };
  fader("Grand master", "grand", (v) => cmd("grand", { level: v }));
  fader("Drum flash", "flash_level", (v) => cmd("flash_level", { level: v }));
  for (const k of ["head", "bar", "wash", "kick"]) fader(k[0].toUpperCase() + k.slice(1) + "s", "sub:" + k, (v) => cmd("sub", { kind: k, level: v }));

  // stage plan (live) and arrange view (setup)
  livePlan = livePlan || new StagePlan($("#stage"), false);
  livePlan.build(cat);
  arrangePlan = arrangePlan || new StagePlan($("#arrange"), true, onArrange);
  arrangePlan.build(cat);
  $("#stage-w").value = cat.stage.width;
  $("#stage-d").value = cat.stage.depth;
  layoutDirty = false;

  // find buttons + head pads
  $("#find").replaceChildren(
    ...cat.fixtures.filter((x) => x.kind !== "haze").map((x) => el("button", { "data-find": x.id, onclick: () => cmd("find", { fixture: state.setup.find === x.id ? null : x.id }) }, x.id))
  );
  const heads = $("#heads");
  heads.replaceChildren();
  for (const fx of cat.fixtures.filter((x) => x.moves)) {
    const pt = el("div", { class: "pt" });
    const area = el("div", { class: "area" }, pt);
    const status = el("span", { class: "muted" });
    const pad = el("div", { class: "pad", "data-pad": fx.id },
      el("div", { class: "head-row" }, el("b", { text: fx.id }), status,
        el("button", { onclick: () => cmd("position", { fixture: fx.id, release: true }) }, "Release")),
      area);
    let dragging = false;
    const send = (ev) => {
      const r = area.getBoundingClientRect();
      const pan = Math.min(1, Math.max(0, (ev.clientX - r.left) / r.width));
      const tilt = Math.min(1, Math.max(0, 1 - (ev.clientY - r.top) / r.height));
      cmd("position", { fixture: fx.id, pan, tilt });
    };
    area.addEventListener("pointerdown", (ev) => { dragging = true; area.setPointerCapture(ev.pointerId); send(ev); });
    area.addEventListener("pointermove", (ev) => dragging && send(ev));
    area.addEventListener("pointerup", () => (dragging = false));
    heads.append(pad);
  }
  $("#positions").replaceChildren(...cat.positions.map((p) => el("span", { class: "muted", text: p })));

  // learn actions
  $("#learn-action").replaceChildren(...cat.actions.map((a) => el("option", { value: a }, a)));
  const ch = $("#midi-filter");
  for (let i = 1; i <= 16; i++) ch.append(el("option", { value: i }, "Ch " + i));
}

$("#savepos").onclick = async () => {
  const name = $("#posname").value.trim();
  const held = state.fixtures.filter((f) => f.override);
  if (!name || !held.length) return toast("Hold at least one head on a pad and give the position a name", true);
  const value = Object.fromEntries(held.map((f) => [f.id, { pan: +f.pan.toFixed(3), tilt: +f.tilt.toFixed(3) }]));
  try {
    await api("PUT", `/api/store/palettes/positions/${encodeURIComponent(name)}`, { value });
    toast(`Saved position ${name}`);
    cat = await get("/api/catalogue");
    buildCatalogue();
  } catch (e) {
    toast(e.message, true);
  }
};

// ------------------------------------------------------------------ render state

function render() {
  const s = state;
  $("#now").textContent = s.describe;
  $("#master").classList.toggle("on", s.master);
  $("#blackout").classList.toggle("on", s.blackout);
  const lock = $("#giglock");
  lock.classList.toggle("on", s.gig_lock);
  lock.textContent = s.gig_lock ? "Gig lock ON" : "Gig lock";
  $("#preview").textContent = s.preview_s != null ? `Previewing (${Math.ceil(s.preview_s)} s)` : "";

  // show/set selection
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

  // setlist
  const songs = $("#songs");
  const sl = s.now.setlist && cat.setlists[s.now.setlist];
  songs.replaceChildren(...(sl ? sl.songs.map((n, i) => el("li", { class: i === s.now.song ? "cur" : "" }, n)) : []));

  // faders (don't fight the user's finger)
  $$("#faders input").forEach((inp) => {
    if (document.activeElement === inp) return;
    const k = inp.dataset.key;
    const v = k.startsWith("sub:") ? s.subs[k.slice(4)] : s[k];
    if (v !== undefined) {
      inp.value = Math.round(v * 100);
      inp.previousSibling.lastChild.textContent = inp.value + "%";
    }
  });

  // haze
  const h = s.haze;
  const bits = [h.enabled ? `mode ${h.mode}` : "disabled by rig", h.on ? "OUTPUT ON" : "output off"];
  if (h.boosting) bits.push("boost");
  if (h.resting) bits.push("resting (max on-time)");
  if (h.next_pulse_s != null) bits.push(`next pulse ${Math.round(h.next_pulse_s)} s`);
  if (h.auto_off_s != null) bits.push(`auto-off ${Math.round(h.auto_off_s / 60)} min`);
  if (h.boost_cooldown_s) bits.push(`boost cooldown ${Math.round(h.boost_cooldown_s)} s`);
  $("#haze").textContent = bits.join(" · ");
  $$("[data-haze]").forEach((b) => b.classList.toggle("sel", h.mode === b.dataset.haze));

  // stage plan + head pads
  livePlan.update(s.fixtures);
  arrangePlan.update(s.fixtures);
  for (const f of s.fixtures) {
    const pad = $(`[data-pad="${CSS.escape(f.id)}"]`);
    if (pad && f.pan !== undefined) {
      const pt = $(".pt", pad);
      pt.style.left = f.pan * 100 + "%";
      pt.style.top = (1 - f.tilt) * 100 + "%";
      pt.style.background = f.colour;
      $(".muted", pad).textContent = f.override ? "held" : "show";
    }
  }
  $$("#find [data-find]").forEach((b) => b.classList.toggle("sel", s.setup.find === b.dataset.find));

  // health strip + alerts
  // status bar: engine, outputs, MIDI, Claude, screens, then every node/receiver
  const realNodes = s.nodes.filter((n) => n.mac);
  const short = (d) => (d.kind === "output" || d.kind === "midi" ? d.detail.split(" · ")[0] : d.detail);
  $("#health").replaceChildren(
    ...s.devices.map((d) =>
      el("div", { class: "tile", title: `${d.name}: ${d.detail}` },
        el("span", { class: `dot ${d.state}${d.active ? " active" : ""}` }), el("span", { text: d.name }),
        el("span", { class: "muted", text: d.state === "ok" && d.kind !== "claude" ? short(d) : d.detail }))),
    ...realNodes.map((n, i) =>
      el("div", { class: "tile" + (i === 0 ? " sep" : ""), title: n.mac || "" }, el("span", { class: "dot " + n.state }),
        el("span", { text: n.name || n.mac }), el("span", { class: "muted", text: n.rssi != null ? `${n.rssi} dBm` : n.state })))
  );
  $("#devices").replaceChildren(...s.devices.map((d) => el("tr", {},
    el("td", { text: d.name }), el("td", { text: d.kind }), el("td", {}, el("span", { class: "dot " + d.state, style: "display:inline-block;margin-right:6px" }), d.state),
    el("td", { text: d.detail }))));
  const latest = s.alerts[s.alerts.length - 1];
  const banner = $("#banner");
  const bad = realNodes.filter((n) => n.state === "offline" || n.state === "weak");
  const badDev = s.devices.filter((d) => d.state === "bad");
  if (bad.length || badDev.length) {
    banner.textContent = [...badDev.map((d) => `${d.name}: ${d.detail}`),
      ...bad.map((n) => `${n.name || n.mac} ${n.state.toUpperCase()}`)].join(" · ");
    banner.classList.remove("hidden");
  } else banner.classList.add("hidden");
  if (latest && latest.time > lastAlert) {
    if (lastAlert) beep();
    lastAlert = latest.time;
  }
  const badKeys = badDev.map((d) => d.name).join("|");
  if (lastBadDevices !== null && badKeys && badKeys !== lastBadDevices) beep();  // an output or MIDI interface just dropped
  lastBadDevices = badKeys;

  // nodes table
  $("#nodes").replaceChildren(
    ...s.nodes.map((n) =>
      el("tr", {},
        el("td", { text: n.name || "(new node)" }), el("td", { text: n.mac || n.driver?.driver || "" }), el("td", { text: n.state }),
        el("td", { text: n.rssi != null ? n.rssi + " dBm" : "-" }), el("td", { text: n.loss_pct != null ? n.loss_pct + "%" : "-" }),
        el("td", { text: n.last_data_age_ms != null ? n.last_data_age_ms + " ms" : "-" }),
        el("td", {}, n.mac ? el("button", { onclick: () => nodeAction(n) }, n.name ? "Identify" : "Name…") : ""))
    )
  );

  $("#learn-state").textContent = s.learning ? `learning ${s.learning}: press a pedal or hit a pad…` : "";
}

let ctx;
function beep() {
  try {
    ctx = ctx || new AudioContext();
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.frequency.value = 880;
    g.gain.value = 0.2;
    o.connect(g).connect(ctx.destination);
    o.start();
    o.stop(ctx.currentTime + 0.35);
  } catch {}
}

async function nodeAction(n) {
  try {
    if (n.name) {
      await api("POST", "/api/nodes/identify", { mac: n.mac });
      return toast(`Identifying ${n.name}`);
    }
    const name = prompt(`Name for node ${n.mac}`);
    if (!name) return;
    const universe = prompt("Universe", "0");
    await api("POST", "/api/nodes/assign", { mac: n.mac, name, universe: +universe || 0 });
    toast(`Named ${name}`);
  } catch (e) {
    toast(e.message, true);
  }
}

// ------------------------------------------------------------------ MIDI tab

function addMidi(rows) {
  const body = $("#monitor");
  for (const r of rows) {
    if (midiChannel && String(r.channel) !== midiChannel) continue;
    const t = new Date(r.time * 1000).toLocaleTimeString("en-AU", { hour12: false }) + "." + String(Math.floor((r.time * 1000) % 1000)).padStart(3, "0");
    body.prepend(el("tr", {},
      el("td", { text: t }), el("td", { text: r.port }), el("td", { text: r.channel }), el("td", { text: r.type }),
      el("td", { text: r.number }), el("td", { text: r.value }),
      el("td", { class: r.result === "unmapped" ? "unmapped" : "hit", text: r.result })));
  }
  while (body.childElementCount > 300) body.lastChild.remove();
}
$("#midi-filter").onchange = (e) => { midiChannel = e.target.value; $("#monitor").replaceChildren(); };
$("#midi-pause").onclick = async (e) => {
  const r = await api("POST", "/api/midi/pause", {});
  e.target.classList.toggle("sel");
};
$("#midi-clear").onclick = () => { api("POST", "/api/midi/clear", {}); $("#monitor").replaceChildren(); };
$("#learn-go").onclick = async () => {
  const params = {};
  for (const kv of $("#learn-params").value.split(/\s+/).filter(Boolean)) {
    const [k, v] = kv.split("=");
    params[k] = k === "fixtures" ? v.split(",") : (/^\d+(\.\d+)?$/.test(v) ? +v : v);
  }
  try {
    await api("POST", "/api/midi/learn", { action: $("#learn-action").value, params });
  } catch (e) {
    toast(e.message, true);
  }
};
$("#learn-cancel").onclick = () => api("POST", "/api/midi/cancel", {});
$("#map-save").onclick = async () => {
  try {
    const r = await api("POST", "/api/midi/save", {});
    toast(`Saved ${r.saved}`);
  } catch (e) {
    toast(e.message, true);
  }
};
async function loadMap() {
  const m = await get("/api/midi/map");
  $("#map").replaceChildren(
    ...m.mappings.map((x) => {
      const { type, channel, number, action, port, ...p } = x;
      const extra = Object.entries(p).map(([k, v]) => `${k}=${v}`).join(" ");
      return el("tr", {}, el("td", { text: type + (port ? ` [${port}]` : "") }), el("td", { text: channel }), el("td", { text: number }),
        el("td", { text: `${action} ${extra}` }),
        el("td", {}, el("button", { onclick: async () => { await api("POST", "/api/midi/remove", { type, channel, number, port }); loadMap(); } }, "Remove")));
    })
  );
}

// ------------------------------------------------------------------ setup tab

const chan = $("#chan"), chanval = $("#chanval");
chanval.addEventListener("input", () => {
  $("#chanshow").textContent = chanval.value;
  if (chan.value) cmd("chan", { channel: +chan.value, value: +chanval.value, universe: +$("#chanuni").value });
});
$("#chan-off").onclick = () => chan.value && cmd("chan", { channel: +chan.value, value: null, universe: +$("#chanuni").value });

async function loadAddresses() {
  const a = await get("/api/addresses");
  $("#addr").replaceChildren(...a.rows.map((r) => el("tr", {},
    el("td", { text: r.id }), el("td", { text: r.type }), el("td", { text: r.universe }), el("td", { text: r.start }), el("td", { text: r.end }),
    el("td", { text: r.in_rig ? "yes" : "-" }), el("td", { text: r.verified ? "yes" : "NO" }))));
  $("#addrnotes").replaceChildren(...a.notes.map((n) => el("div", { text: n })));
}

// ------------------------------------------------------------------ files tab

async function loadFiles() {
  $("#scenes").replaceChildren(...Object.entries(cat.scenes).map(([k, n]) => el("div", { class: "item" },
    el("span", { class: "name", text: `${n} (${k})` }),
    el("button", { onclick: async () => { try { const r = await api("POST", "/api/preview", { scene: k, seconds: 10 }); toast(r.message); } catch (e) { toast(e.message, true); } } }, "Preview 10 s"),
    el("button", { onclick: () => cmd("scene", { scene: k }) }, "Play"))));
  const b = await get("/api/backups");
  $("#backups").replaceChildren(...b.map((x) => el("div", { class: "item" },
    el("span", { class: "name", text: `${x.id}  ${x.note}` }),
    ...x.files.map((f) => el("button", { onclick: async () => {
      if (!confirm(`Put ${f} back as it was before "${x.note}"?`)) return;
      try { await api("POST", "/api/store/restore", { backup: x.id, file: f }); toast(`Restored ${f}`); loadFiles(); } catch (e) { toast(e.message, true); }
    } }, "Restore " + f)))));
}

// ------------------------------------------------------------------ live stream

function connect() {
  const es = new EventSource(`/api/events?since=${midiSeq}`);
  es.onmessage = (ev) => {
    const d = JSON.parse(ev.data);
    state = d.state;
    if (d.midi.length) {
      midiSeq = d.midi[d.midi.length - 1].seq;
      addMidi(d.midi);
    }
    render();
  };
  es.onerror = () => {
    $("#now").textContent = "connection lost, retrying…";
    es.close();
    setTimeout(connect, 1000);
  };
}

(async () => {
  cat = await get("/api/catalogue");
  state = await get("/api/state");
  buildCatalogue();
  render();
  connect();
})();
