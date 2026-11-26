// Live state from the engine (server-sent events, ~10 a second) and the catalogue of names.
import { get } from "./api.js";

export const live = { state: null, cat: null, midiSeq: 0 };
const stateListeners = [];
const catListeners = [];
const midiListeners = [];
const connListeners = [];

export const onState = (fn) => stateListeners.push(fn);
export const onCatalogue = (fn) => catListeners.push(fn);
export const onMidi = (fn) => midiListeners.push(fn);
export const onConnection = (fn) => connListeners.push(fn);

export async function refreshCatalogue() {
  live.cat = await get("/api/catalogue");
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

export function connect() {
  const es = new EventSource(`/api/events?since=${live.midiSeq}`);
  let first = true;
  es.onmessage = (ev) => {
    const d = JSON.parse(ev.data);
    live.state = d.state;
    if (first) {
      first = false;
      for (const fn of connListeners) fn(true);
    }
    if (d.midi.length) {
      live.midiSeq = d.midi[d.midi.length - 1].seq;
      for (const fn of midiListeners) fn(d.midi);
    }
    emitState();
  };
  es.onerror = () => {
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
  await refreshCatalogue();
  live.state = await get("/api/state");
  emitState();
  connect();
}
