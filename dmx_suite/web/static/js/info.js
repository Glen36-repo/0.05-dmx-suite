// ⓘ information buttons (v4.1): a small popover with a few lines about a section or control, and a
// link to the manual section. One popover for the whole app, wired once on the document, so buttons a
// view adds later work with nothing more to do.
//
// Gig safety:
// - the ⓘ itself never does anything else: its tap doesn't toggle a <details>, select lights or reach
//   the stage (stopped in the capture phase);
// - a tap anywhere else closes the popover AND still reaches what's under it (no backdrop: a scene or
//   MASTER tap mid-gig fires as normal);
// - Esc closes only the popover; other keys pass straight through (shortcuts, MASTER / BLACKOUT keys);
// - focus moves into the popover only when it's opened from the keyboard;
// - the manual never replaces the page: a new tab in a browser, a panel over the page in the desktop
//   window. All of it is read-only, so it works under gig lock.
import { el } from "./dom.js";
import { t } from "./i18n.js";

// which manual section each topic links to (docs/manual/<file>#<heading slug>); topics without one have no link
export const INFO_MANUAL = {
  "top.status": "troubleshooting.md#when-something-goes-wrong",
  "top.alerts": "troubleshooting.md#alerts-and-banners",
  "live.shows": "shows.md",
  "live.scenes": "scenes.md",
  "live.generated": "auto-show.md",
  "live.setlist": "shows.md",
  "live.masters": "troubleshooting.md#safety-rules-always-on",
  "live.haze": "fixtures.md#haze-settings",
  "haze.manual": "fixtures.md#haze-settings",
  "haze.pulse": "fixtures.md#haze-settings",
  "haze.boost": "fixtures.md#haze-settings",
  "haze.safety": "fixtures.md#haze-settings",
  "autopilot.autopilot": "auto-show.md",
  "autopilot.fx": "auto-show.md",
  "autopilot.palette": "auto-show.md",
  "autopilot.feel": "auto-show.md",
  "autopilot.presets": "auto-show.md",
  "autopilot.priority": "auto-show.md",
  "autopilot.why": "auto-show.md",
  "autopilot.lights": "auto-show.md",
  "override.panels": "override.md",
  "scenes.layers": "scenes.md#building-a-scene",
  "scenes.layer": "scenes.md#effects",
  "scenes.settings": "scenes.md",
  "steps.bar": "scenes.md#step-scenes",
  "steps.list": "scenes.md#step-scenes",
  "steps.programmer": "scenes.md#step-scenes",
  "steps.record": "scenes.md#step-scenes",
  "steps.live": "scenes.md#step-scenes",
  "steps.pixels": "scenes.md#single-pixels-of-a-bar",
  "shows.shows": "shows.md",
  "shows.setlists": "shows.md",
  "review.review": "auto-show.md",
  "review.rating": "auto-show.md",
  "review.generator": "auto-show.md",
  "palettes.palettes": "palettes.md",
  "palettes.named": "palettes.md",
  "layout.universes": "layout.md",
  "layout.stage": "layout.md#stage",
  "layout.arrange": "layout.md#stage",
  "layout.addresses": "layout.md#addresses",
  "layout.fixtures": "layout.md#fixture-list-and-outputs",
  "layout.routing": "monitor.md#outputs-which-universe-goes-where",
  "layout.groups": "layout.md#groups",
  "fixtures.patch": "fixtures.md",
  "fixtures.rig": "fixtures.md",
  "heads.points": "heads.md",
  "heads.store": "heads.md",
  "midi.inputs": "midi-osc.md",
  "midi.monitor": "monitor.md#monitor-page",
  "midi.learn": "midi-osc.md",
  "midi.mapping": "midi-osc.md",
  "monitor.dmx": "monitor.md#monitor-page",
  "monitor.midi_in": "monitor.md#monitor-page",
  "monitor.midi_out": "monitor.md#monitor-page",
  "setup.find": "fixtures.md",
  "setup.tester": "troubleshooting.md#safety-rules-always-on",
  "setup.found": "monitor.md#devices",
  "setup.nodes": "troubleshooting.md#when-something-goes-wrong",
  "setup.access": "getting-started.md#phones-and-the-pin",
  "setup.claude": "getting-started.md#connect-to-claude-optional",
  "setup.appearance": "layout.md#theme-and-button-size",
  "files.project": "getting-started.md",
  "files.history": "scenes.md#undo",
  "files.backups": "troubleshooting.md#when-something-goes-wrong",
};

let pop = null; // the popover element
let openFor = null; // the ⓘ it's open for

// a ⓘ for views that build their controls in JS
export function infoButton(key) {
  return el("button", { type: "button", class: "info", "data-info": key, "aria-expanded": "false",
    "aria-label": t("info.button", { topic: t(`info.${key}.title`) }) }, "ⓘ");
}

function place(btn) {
  const r = btn.getBoundingClientRect();
  const vw = document.documentElement.clientWidth, vh = document.documentElement.clientHeight;
  const topBar = document.querySelector(".top")?.getBoundingClientRect().bottom || 0;
  pop.style.left = "0px";
  pop.style.top = "0px";
  const w = pop.offsetWidth, h = pop.offsetHeight;
  const left = Math.max(8, Math.min(r.left + r.width / 2 - w / 2, vw - w - 8));
  let top = r.bottom + 6; // below; above when there's no room, but never over the top bar (MASTER, BLACKOUT)
  if (top + h > vh - 8 && r.top - 6 - h >= topBar + 4) top = r.top - 6 - h;
  top = Math.max(topBar + 4, Math.min(top, vh - h - 8));
  pop.style.left = `${Math.round(left)}px`;
  pop.style.top = `${Math.round(top)}px`;
}

function open(btn, fromKeyboard) {
  const key = btn.dataset.info;
  if (!pop) {
    pop = el("div", { class: "info-pop hidden", role: "dialog", "aria-labelledby": "info-pop-title", tabindex: "-1", id: "info-pop" });
    document.body.append(pop);
  }
  if (openFor) openFor.setAttribute("aria-expanded", "false");
  const page = INFO_MANUAL[key];
  pop.replaceChildren(
    el("div", { class: "info-pop-title", id: "info-pop-title", text: t(`info.${key}.title`) }),
    el("div", { class: "info-pop-text", text: t(`info.${key}.text`) }),
    page ? el("a", { class: "info-pop-more", href: `/manual/${page}`, "data-manual": page,
      onclick: (e) => { e.preventDefault(); closeInfo(false); openManual(page); } }, t("info.more")) : "");
  pop.dataset.key = key;
  pop.classList.remove("hidden");
  openFor = btn;
  btn.setAttribute("aria-expanded", "true");
  btn.classList.add("open");
  place(btn);
  if (fromKeyboard) (pop.querySelector("a") || pop).focus(); // only from the keyboard: a tap never moves focus
}

export function closeInfo(returnFocus = false) {
  if (!pop || pop.classList.contains("hidden")) return false;
  pop.classList.add("hidden");
  const btn = openFor;
  openFor = null;
  if (btn) {
    btn.setAttribute("aria-expanded", "false");
    btn.classList.remove("open");
    if (returnFocus) btn.focus();
  }
  return true;
}

export const infoOpen = () => !!pop && !pop.classList.contains("hidden");

// ---------------------------------------------------------------- the manual: never instead of the page

export function openManual(page) {
  const url = `/manual/${page}`;
  if (window.pywebview) return showManualPanel(url); // the desktop window: a panel over the page
  window.open(url, "_blank", "noopener"); // a browser: a new tab
}

function showManualPanel(url) {
  let panel = document.getElementById("manual-panel");
  if (!panel) {
    const frame = el("iframe", { class: "manual-frame", title: t("info.manual") });
    frame.addEventListener("load", () => externalLinksToBrowser(frame));
    panel = el("div", { class: "manual-panel", id: "manual-panel", role: "dialog", "aria-label": t("info.manual") },
      el("div", { class: "manual-panel-bar" }, el("span", { text: t("info.manual") }),
        el("button", { type: "button", class: "icon", id: "manual-close", "aria-label": t("info.close"),
          onclick: () => panel.classList.add("hidden") }, "✕")),
      frame);
    document.body.append(panel);
  }
  panel.querySelector("iframe").src = url;
  panel.classList.remove("hidden");
}

// in the desktop window, web links in the manual go to the system browser, never into the app's window
function externalLinksToBrowser(frame) {
  try {
    frame.contentDocument.addEventListener("click", (e) => {
      const a = e.target.closest?.("a[data-external]");
      if (!a) return;
      e.preventDefault();
      window.pywebview?.api?.open_url?.(a.href);
    });
  } catch {} // not reachable: nothing to do
}

// ---------------------------------------------------------------- wiring (once, on the document)

export function initInfo() {
  // the ⓘ's own press stops here, before a <summary>, the stage view or a row handler sees it
  for (const type of ["pointerdown", "mousedown", "touchstart"]) {
    document.addEventListener(type, (e) => {
      if (e.target.closest?.("[data-info]")) e.stopPropagation();
    }, { capture: true, passive: true });
  }
  document.addEventListener("click", (e) => {
    const btn = e.target.closest?.("[data-info]");
    if (btn) {
      e.preventDefault(); // a ⓘ inside <summary> mustn't fold the section
      e.stopPropagation();
      if (openFor === btn && infoOpen()) closeInfo(false);
      else open(btn, e.detail === 0); // detail 0: Enter / Space on the button
      return;
    }
    // anywhere else: close, and let the tap carry on to whatever is under it
    if (infoOpen() && !pop.contains(e.target)) closeInfo(false);
  }, true);
  document.addEventListener("pointerdown", (e) => {
    if (infoOpen() && !pop.contains(e.target) && !e.target.closest?.("[data-info]")) closeInfo(false);
  }, true);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      const panel = document.getElementById("manual-panel");
      if (infoOpen()) {
        e.stopImmediatePropagation(); // Esc closes the popover only: not the step editor, a dialog or a selection
        e.preventDefault();
        closeInfo(true);
      } else if (panel && !panel.classList.contains("hidden")) {
        e.stopImmediatePropagation();
        panel.classList.add("hidden");
      }
    }
    // every other key passes through untouched
  }, true);
  window.addEventListener("resize", () => { if (infoOpen() && openFor) place(openFor); });
  document.addEventListener("scroll", () => { if (infoOpen() && openFor) place(openFor); }, true);
}
