// Live state from the engine (server-sent events, ~10 a second) and the catalogue of names.
import { get } from "./api.js";

export const live = { state: null, cat: null, midiSeq: 0 };
let filesRev = null; // the files the catalogue was fetched for; another screen or Claude changing them bumps it
const stateListeners = [];
const catListeners = [];
const midiListeners = [];
const connListeners = [];

export const onState = (fn) => stateListeners.push(fn);
export const onCatalogue = (fn) => catListeners.push(fn);
export const onMidi = (fn) => midiListeners.push(fn);
export const onConnection = (fn) => connListeners.push(fn);

export async function refreshCatalogue() {
  const rev = live.state?.files_rev;
  live.cat = await get("/api/catalogue");
  if (rev !== undefined && (filesRev === null || rev > filesRev)) filesRev = rev;
  for (const fn of catListeners) fn(live.cat);
}

function emitState() {
  for (const fn of stateListeners) {
    try {
      fn(live.state);
    } catch (e) {
      console.error(e);
    }
  }
}

// The server sends the state when it changes, MIDI lines as they come, and a heartbeat at least
// every 5 s; nothing for 12 s means the link is dead (Wi-Fi gone, laptop asleep): reconnect.
const STALL_MS = 12000;

export function connect() {
  const es = new EventSource(`/api/events?since=${live.midiSeq}`);
  let first = true;
  let last = Date.now();
  const watchdog = setInterval(() => {
    if (Date.now() - last > STALL_MS) es.onerror();
  }, 2000);
  es.onmessage = (ev) => {
    last = Date.now();
    const d = JSON.parse(ev.data);
    if (d.state) live.state = d.state;
    // the show files changed (any screen, Claude, undo, a restore): every open screen fetches them again
    if (d.state && filesRev !== null && d.state.files_rev !== undefined && d.state.files_rev !== filesRev) {
      filesRev = d.state.files_rev;
      refreshCatalogue().catch(() => {});
    }
    if (first && live.state) {
      first = false;
      for (const fn of connListeners) fn(true);
    }
    if (d.midi?.length) {
      live.midiSeq = d.midi[d.midi.length - 1].seq;
      for (const fn of midiListeners) fn(d.midi);
    }
    if (d.state) emitState();
  };
  es.onerror = () => {
    clearInterval(watchdog);
    es.onerror = null;
    es.close();
    for (const fn of connListeners) fn(false);
    // the files may have changed meanwhile (Claude, a restore): fetch the names again
    setTimeout(async () => {
      try {
        await refreshCatalogue();
      } catch {}
      connect();
    }, 1000);
  };
}

export async function start() {
  live.state = await get("/api/state");
  await refreshCatalogue();
  filesRev = live.state.files_rev ?? 0;
  emitState();
  connect();
}
