// Small line icons for tool buttons (v4 ARRANGE panel). 16 x 16, currentColor, no external files.
const P = {
  "align-left": "M2 1v14 M5 4h9v3H5z M5 9h6v3H5z",
  "align-hcentre": "M8 1v14 M3 4h10v3H3z M5 9h6v3H5z",
  "align-right": "M14 1v14 M2 4h9v3H2z M5 9h6v3H5z",
  "align-top": "M1 2h14 M4 5v9h3V5z M9 5v6h3V5z",
  "align-vcentre": "M1 8h14 M4 3v10h3V3z M9 5v6h3V5z",
  "align-bottom": "M1 14h14 M4 2v9h3V2z M9 5v6h3V5z",
  "distribute-h": "M1 2v12 M15 2v12 M4 5h2v6H4z M10 5h2v6h-2z",
  "distribute-v": "M2 1h12 M2 15h12 M5 4v2h6V4z M5 10v2h6v-2z",
  "make-row": "M1 7h3v3H1z M6.5 7h3v3h-3z M12 7h3v3h-3z",
  "make-ring": "M6.5 1h3v3h-3z M12 6.5h3v3h-3z M6.5 12h3v3h-3z M1 6.5h3v3H1z",
  "make-grid": "M2 2h4v4H2z M10 2h4v4h-4z M2 10h4v4H2z M10 10h4v4h-4z",
  "rotate-l": "M3 8a5 5 0 1 0 2-4 M5 1v3H2",
  "rotate-r": "M13 8a5 5 0 1 1-2-4 M11 1v3h3",
  "flip-h": "M8 1v14 M6 4 2 8l4 4z M10 4l4 4-4 4z",
  "flip-v": "M1 8h14 M4 6l4-4 4 4z M4 10l4 4 4-4z",
  "pixels-row": "M1 6h14v4H1z M5 6v4 M8 6v4 M11 6v4",
  "pixels-ring": "M8 2a6 6 0 1 0 .01 0z M8 5a3 3 0 1 0 .01 0z",
  "pixels-grid": "M2 2h12v12H2z M6 2v12 M10 2v12 M2 6h12 M2 10h12",
  "reverse": "M2 5h11l-3-3 M14 11H3l3 3",
};

export function icon(name) {
  const d = P[name];
  return d ? `<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path d="${d}" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round" stroke-linecap="round"/></svg>` : "";
}

// fill every <button data-icon="..."> under root (keeps a text label after the icon if there is one)
export function fillIcons(root = document) {
  for (const b of root.querySelectorAll("[data-icon]")) {
    if (b.querySelector("svg")) continue;
    b.insertAdjacentHTML("afterbegin", icon(b.dataset.icon));
  }
}
