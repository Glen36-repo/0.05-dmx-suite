// Heads page: hold a moving head at a spot with a drag pad; save held spots as a palette position.
import { api, attempt, cmd, toast } from "../api.js";
import { $, el } from "../dom.js";
import { t } from "../i18n.js";
import { live, onCatalogue, onState, refreshCatalogue } from "../state.js";

function buildCatalogue(cat) {
  const heads = $("#heads");
  heads.replaceChildren();
  for (const fx of cat.fixtures.filter((x) => x.moves)) {
    const pt = el("div", { class: "pt" });
    const area = el("div", { class: "area", role: "slider", "aria-label": t("heads.pad_label", { id: fx.id }) }, pt);
    const status = el("span", { class: "muted" });
    heads.append(el("div", { class: "pad", "data-pad": fx.id },
      el("div", { class: "head-row" }, el("b", { text: fx.id }), status,
        el("button", { onclick: () => cmd("position", { fixture: fx.id, release: true }) }, t("heads.release"))),
      area));
    let dragging = false, last = 0;
    const send = (ev, force = false) => {
      const now = performance.now();
      if (!force && now - last < 40) return; // at most 25 a second
      last = now;
      const r = area.getBoundingClientRect();
      const pan = Math.min(1, Math.max(0, (ev.clientX - r.left) / r.width));
      const tilt = Math.min(1, Math.max(0, 1 - (ev.clientY - r.top) / r.height));
      cmd("position", { fixture: fx.id, pan, tilt });
    };
    area.addEventListener("pointerdown", (ev) => { dragging = true; area.setPointerCapture(ev.pointerId); send(ev, true); });
    area.addEventListener("pointermove", (ev) => dragging && send(ev));
    area.addEventListener("pointerup", (ev) => { if (dragging) send(ev, true); dragging = false; });
  }
  $("#positions").replaceChildren(...cat.positions.map((p) => el("span", { class: "chip", text: p })));
}

function render(s) {
  for (const f of s.fixtures) {
    const pad = document.querySelector(`[data-pad="${CSS.escape(f.id)}"]`);
    if (pad && f.pan !== undefined) {
      const pt = $(".pt", pad);
      pt.style.left = f.pan * 100 + "%";
      pt.style.top = (1 - f.tilt) * 100 + "%";
      pt.style.background = f.colour;
      $(".muted", pad).textContent = t(f.override ? "heads.held" : "heads.show");
    }
  }
}

export function init() {
  $("#savepos").onclick = async () => {
    const name = $("#posname").value.trim();
    const held = live.state.fixtures.filter((f) => f.override);
    if (!name || !held.length) return toast(t("heads.save_need"), true);
    const value = Object.fromEntries(held.map((f) => [f.id, { pan: +f.pan.toFixed(3), tilt: +f.tilt.toFixed(3) }]));
    const r = await attempt(() => api("PUT", `/api/store/palettes/positions/${encodeURIComponent(name)}`, { value }),
      t("heads.saved", { name }));
    if (r) await refreshCatalogue();
  };
  onCatalogue(buildCatalogue);
  onState(render);
}
