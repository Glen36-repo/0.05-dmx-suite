// Screen-reader names for controls the views build in tables: a field in a table cell with no label of its
// own gets "<row> <column>" (e.g. "bar_1 Address") from its row's first cell and its column header. Runs
// as views render, so every table (patch, kit, shows, palettes ...) is covered without each view doing it.
function named(e) {
  return e.getAttribute("aria-label") || e.title || e.getAttribute("aria-labelledby") || e.closest("label")
    || (e.id && document.querySelector(`label[for="${CSS.escape(e.id)}"]`));
}

function rowName(tr) {
  const first = tr.cells[0];
  if (!first) return "";
  const f = first.querySelector("input, select");
  return (f ? (f.value || f.placeholder || "") : first.textContent || "").trim().slice(0, 40);
}

function colName(td) {
  const table = td.closest("table");
  const head = table?.tHead?.rows[0];
  const th = head?.cells[td.cellIndex];
  return (th?.textContent || "").trim();
}

function label(root) {
  for (const e of root.querySelectorAll?.("td input:not([type=hidden]), td select, td textarea") || []) {
    if (named(e)) continue;
    const td = e.closest("td");
    const name = [rowName(td.parentElement), colName(td)].filter(Boolean).join(" ") || e.placeholder || "";
    if (name) e.setAttribute("aria-label", name);
  }
}

export function initA11y() {
  label(document);
  let pending = false;
  new MutationObserver(() => {
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => { pending = false; label(document); });
  }).observe(document.body, { childList: true, subtree: true });
}
