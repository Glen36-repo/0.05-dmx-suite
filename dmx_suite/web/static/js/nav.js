// Left-hand page menu (a bottom bar on phones). Views register what to do when shown.
import { $, $$, remember } from "./dom.js";

const shown = {};
const left = {};
export const onShow = (page, fn) => (shown[page] ||= []).push(fn);
export const onLeave = (page, fn) => (left[page] ||= []).push(fn); // e.g. stop a live feed only that page uses
export let current = "live";

export function go(page) {
  if (page !== current) for (const fn of left[current] || []) fn();
  current = page;
  $$("#menu [data-page]").forEach((b) => {
    b.classList.toggle("on", b.dataset.page === page);
    b.setAttribute("aria-current", b.dataset.page === page ? "page" : "false");
  });
  $$(".page").forEach((p) => p.classList.toggle("on", p.id === "page-" + page));
  // phones: the pages not on the bottom bar sit behind More, which lights up when one of them is showing
  $("#menu-more")?.classList.toggle("on", !!$(`#menu [data-page="${page}"].extra`));
  openMore(false);
  for (const fn of shown[page] || []) fn();
  remember.set("page", page);
}

function openMore(on) {
  $("#menu").classList.toggle("open", on);
  $("#menu-more")?.setAttribute("aria-expanded", String(on));
}

export function init() {
  $$("#menu [data-page]").forEach((b) => b.addEventListener("click", () => go(b.dataset.page)));
  $("#menu-more")?.addEventListener("click", () => openMore(!$("#menu").classList.contains("open")));
  const shell = $(".shell");
  shell.classList.toggle("narrow-menu", remember.get("menu.collapsed", false));
  $("#collapse").addEventListener("click", () => {
    const on = !shell.classList.contains("narrow-menu");
    shell.classList.toggle("narrow-menu", on);
    remember.set("menu.collapsed", on);
  });
  // folding page sections stay as this screen last left them
  $$("details[data-remember]").forEach((d) => {
    const key = "fold." + d.dataset.remember;
    d.open = remember.get(key, d.open);
    d.addEventListener("toggle", () => remember.set(key, d.open));
  });
  const page = remember.get("page", "live");
  go($(`#page-${page}`) ? page : "live");
}
