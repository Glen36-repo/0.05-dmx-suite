// Left-hand page menu (a bottom bar on phones). Views register what to do when shown.
import { $, $$, remember } from "./dom.js";

const shown = {};
export const onShow = (page, fn) => (shown[page] ||= []).push(fn);
export let current = "live";

export function go(page) {
  current = page;
  $$("#menu [data-page]").forEach((b) => {
    b.classList.toggle("on", b.dataset.page === page);
    b.setAttribute("aria-current", b.dataset.page === page ? "page" : "false");
  });
  $$(".page").forEach((p) => p.classList.toggle("on", p.id === "page-" + page));
  for (const fn of shown[page] || []) fn();
  remember.set("page", page);
}

export function init() {
  $$("#menu [data-page]").forEach((b) => b.addEventListener("click", () => go(b.dataset.page)));
  const shell = $(".shell");
  shell.classList.toggle("narrow-menu", remember.get("menu.collapsed", false));
  $("#collapse").addEventListener("click", () => {
    const on = !shell.classList.contains("narrow-menu");
    shell.classList.toggle("narrow-menu", on);
    remember.set("menu.collapsed", on);
  });
  const page = remember.get("page", "live");
  go($(`#page-${page}`) ? page : "live");
}
