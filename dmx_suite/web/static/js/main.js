// 0.05 DMX Suite UI: plain ES modules, no build step, no internet needed.
import { cmd } from "./api.js";
import { apply, load } from "./i18n.js";
import * as nav from "./nav.js";
import { start } from "./state.js";
import * as files from "./views/files.js";
import * as heads from "./views/heads.js";
import * as layout from "./views/layout.js";
import * as liveView from "./views/live.js";
import * as midi from "./views/midi.js";
import * as scenes from "./views/scenes.js";
import * as setup from "./views/setup.js";
import * as top from "./views/top.js";

// any button with data-cmd sends that control command, with its other data-* as arguments
document.addEventListener("click", (ev) => {
  const b = ev.target.closest("[data-cmd]");
  if (!b) return;
  const args = {};
  for (const [k, v] of Object.entries(b.dataset)) if (k !== "cmd" && !k.startsWith("i18n")) args[k] = v;
  cmd(b.dataset.cmd, args);
});

(async () => {
  await load("en");
  apply();
  for (const view of [top, liveView, layout, scenes, heads, midi, setup, files]) view.init();
  nav.init();
  await start();
  document.body.classList.add("ready");
})();
