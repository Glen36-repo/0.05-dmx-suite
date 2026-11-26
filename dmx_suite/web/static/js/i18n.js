// All UI text lives in /static/i18n/<lang>.json. t("key", {name: "x"}) fills {name}.
// In the page: data-i18n (text), data-i18n-title, data-i18n-placeholder.
let strings = {};

export async function load(lang = "en") {
  strings = await fetch(`/static/i18n/${lang}.json`).then((r) => r.json());
}

export function t(key, vars = {}) {
  const s = strings[key];
  if (s === undefined) {
    console.warn("missing UI text", key);
    return key;
  }
  return s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m));
}

export function apply(root = document) {
  for (const e of root.querySelectorAll("[data-i18n]")) e.textContent = t(e.dataset.i18n);
  for (const e of root.querySelectorAll("[data-i18n-title]")) e.title = t(e.dataset.i18nTitle);
  for (const e of root.querySelectorAll("[data-i18n-placeholder]")) e.placeholder = t(e.dataset.i18nPlaceholder);
}
