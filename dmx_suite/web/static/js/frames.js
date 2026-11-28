// Live DMX frames from one interface (v4: Monitor page, Layout address map). Opened only while a
// page shows them and closed when it hides, so the 10 Hz state feed stays small.
//   const stop = watchFrames(0, "", (v) => ...)   v: {universe, out, source, values: Uint8Array | null, no_frames, stats}
export function watchFrames(universe, out, onFrame) {
  const qs = new URLSearchParams({ u: String(universe) });
  if (out !== "" && out !== null && out !== undefined) qs.set("out", String(out));
  const es = new EventSource(`/api/events/frames?${qs}`);
  es.onmessage = (ev) => {
    const v = JSON.parse(ev.data);
    v.values = v.frame ? Uint8Array.from(atob(v.frame), (c) => c.charCodeAt(0)) : null; // never guess values
    onFrame(v);
  };
  return () => es.close();
}
