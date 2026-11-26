"""Light layout: where each light sits on the layout grid (see rig.Placement). Lights not placed
yet get a default spot, so a new rig always has a layout to start arranging from: moving heads
in a row at the back, bars end to end across the middle, washes and the kick light at the front,
haze to the side."""

from __future__ import annotations

import math

from .fixtures import Kind
from .rig import Placement, Rig

ROWS = {Kind.HEAD: 2.0, Kind.BAR: 6.0, Kind.WASH: 10.0, Kind.KICK: 10.0, Kind.HAZE: 14.0}


def full_layout(rig: Rig) -> dict[str, Placement]:
    """The rig's layout with defaults filled in for lights that haven't been placed."""
    placed = dict(rig.layout)
    x_next: dict[float, float] = {}
    for f in rig.fixtures:
        if f.id in placed:
            continue
        y = ROWS.get(f.kind, 14.0)
        width = max(1, f.type.pixels or 1)  # a pixel bar is a row of cells
        x = x_next.get(y, 1.0)
        placed[f.id] = Placement(x + (width - 1) / 2, y)  # x, y are the light's centre
        x_next[y] = x + width + 1
    return {f.id: placed[f.id] for f in rig.fixtures if f.id in placed}


def cell_offsets(n: int, shape: str = "row", cols: int = 0) -> list[tuple[float, float]]:
    """Where each pixel of a light sits relative to its centre, in cells, before rotation.
    Same as cellOffsets in web/static/js/grid.js, so effects land where the screen shows them."""
    n = max(1, n or 1)
    if n == 1:
        return [(0.0, 0.0)]
    if shape == "ring":
        r = max(1.0, (n * 1.05) / (2 * math.pi))
        return [(r * math.cos(2 * math.pi * i / n - math.pi / 2), r * math.sin(2 * math.pi * i / n - math.pi / 2))
                for i in range(n)]
    if shape == "grid":
        w = cols if cols > 0 else math.ceil(math.sqrt(n))
        h = math.ceil(n / w)
        return [((i % w) - (w - 1) / 2, (i // w) - (h - 1) / 2) for i in range(n)]
    return [(i - (n - 1) / 2, 0.0) for i in range(n)]


def cell_positions(p: Placement, pixels: int) -> list[tuple[float, float]]:
    """Grid positions of a light's cells (one per pixel, or one for a single-cell light)."""
    a = math.radians(p.rot)
    out = []
    for x, y in cell_offsets(pixels, p.shape, p.cols):
        out.append((p.x + x * math.cos(a) - y * math.sin(a), p.y + x * math.sin(a) + y * math.cos(a)))
    return out


# ---------------------------------------------------------------------- overlaps (v4)

MIN_GAP = 0.25  # cells: lights closer than this (edge to edge) are flagged too close


def footprint(p: Placement, pixels: int) -> tuple[float, float, float, float]:
    """The box a light takes on the grid (x0, y0, x1, y1), segments included."""
    cells = cell_positions(p, pixels)
    r = 0.5 if pixels > 1 else 0.41  # a pixel bar's segments touch; a single light is a 0.82 square
    xs, ys = [x for x, _ in cells], [y for _, y in cells]
    return min(xs) - r, min(ys) - r, max(xs) + r, max(ys) + r


def layout_problems(rig: Rig, min_gap: float = MIN_GAP) -> list[dict[str, object]]:
    """Lights whose places overlap or nearly touch. Spatial effects (mapping: spatial, linear wave,
    radial, gradient, bars, noise, split) use these places, so two lights in one spot always show the
    same part of an effect. Haze machines aren't on the stage and are left out."""
    lay = full_layout(rig)
    boxes = [(f.id, footprint(lay[f.id], f.type.pixels)) for f in rig.fixtures
             if f.id in lay and f.kind != Kind.HAZE]
    out: list[dict[str, object]] = []
    for i, (a, ba) in enumerate(boxes):
        for b, bb in boxes[i + 1:]:
            gap = max(bb[0] - ba[2], ba[0] - bb[2], bb[1] - ba[3], ba[1] - bb[3])  # < 0: they overlap
            if gap < 0:
                out.append({"a": a, "b": b, "kind": "overlap", "gap": round(gap, 2)})
            elif gap < min_gap:
                out.append({"a": a, "b": b, "kind": "close", "gap": round(gap, 2)})
    return sorted(out, key=lambda p: p["kind"] != "overlap")  # the worst first


def layout_warnings(rig: Rig) -> list[str]:
    out = []
    for p in layout_problems(rig):
        if p["kind"] == "overlap":
            out.append(f"layout: {p['a']} and {p['b']} are in the same place; spatial effects show them the same - "
                       "move one on the Layout page")
        else:
            out.append(f"layout: {p['a']} and {p['b']} touch; leave a gap so they read as two lights")
    return out
