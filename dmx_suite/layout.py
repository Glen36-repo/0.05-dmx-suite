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


def cell_offsets(n: int, shape: str = "row", cols: int = 0, reverse: bool = False) -> list[tuple[float, float]]:
    """Where each pixel of a light sits relative to its centre, in cells, before rotation.
    Same as cellOffsets in web/static/js/grid.js, so effects land where the screen shows them.
    `reverse`: the light is mounted backwards, pixel 1 at the other end."""
    out = _offsets(n, shape, cols)
    return out[::-1] if reverse else out


def _offsets(n: int, shape: str, cols: int) -> list[tuple[float, float]]:
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
    for x, y in cell_offsets(pixels, p.shape, p.cols, p.reverse):
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


# ---------------------------------------------------------------------- reading / setting places (v4, Claude)


def layout_view(rig: Rig) -> dict[str, object]:
    """Every light's place (defaults filled in, `placed: false` for those), the stage size the lights
    take up, and any overlaps. Haze machines aren't drawn on the stage and are listed apart."""
    lay = full_layout(rig)
    out: dict[str, dict[str, object]] = {}
    hazes = []
    for f in rig.fixtures:
        if f.kind == Kind.HAZE:
            hazes.append(f.id)
            continue
        if f.id in lay:
            out[f.id] = {**lay[f.id].to_dict(), "placed": f.id in rig.layout}
    boxes = [footprint(lay[f.id], f.type.pixels) for f in rig.fixtures if f.id in out]
    w = max((b[2] for b in boxes), default=0.0)
    h = max((b[3] for b in boxes), default=0.0)
    cx, cy = rig.layout_centre()
    return {"layout": out, "haze": hazes,
            "centre": {"x": cx, "y": cy, "set": rig.centre is not None},  # v8 stage centrelines (cells)
            "stage": {"w_cells": round(w, 2), "h_cells": round(h, 2), "cells_per_m": 4,
                      "note": "x, y in cells (25 cm) from the top left; back of the stage at the top; "
                              "rot 0 = facing the audience"},
            "problems": layout_problems(rig)}


def merge_positions(rig: Rig, current: dict[str, object] | None, positions: dict[str, object]) -> dict[str, object]:
    """The rig file's `layout:` with `positions` ({fixture: {x, y, z, rot | rotation}}) set over it. A
    fixture not placed yet starts from its default spot, so a partial place (only rot, say) works."""
    from .fixtures import ConfigError
    from .rig import CENTRE_KEY, parse_placement

    if not isinstance(positions, dict) or not positions:
        raise ConfigError("positions: {fixture id: {x, y, z, rot}}")
    lay = full_layout(rig)
    out = dict(current or {})
    for fid, v in positions.items():
        if fid == CENTRE_KEY and fid not in rig.patch.fixtures:  # v8: the stage centrelines, null = the middle
            if v is None:
                out.pop(CENTRE_KEY, None)
            elif not isinstance(v, dict) or set(v) - {"x", "y"}:
                raise ConfigError("layout centre: {x, y} in grid cells, or null for the middle of the lights")
            else:
                old = out.get(CENTRE_KEY)
                cur: dict[str, object] = old if isinstance(old, dict) else {}
                now = rig.layout_centre()
                out[CENTRE_KEY] = {"x": v.get("x", cur.get("x", now[0])), "y": v.get("y", cur.get("y", now[1]))}
            continue
        if fid not in rig.patch.fixtures:
            raise ConfigError(f"layout: unknown fixture {fid!r}")
        if not isinstance(v, dict):
            raise ConfigError(f"layout {fid}: {{x, y, z, rot}}")
        v = dict(v)
        if "rotation" in v:
            v["rot"] = v.pop("rotation")
        base = out.get(fid) if isinstance(out.get(fid), dict) else (lay[fid].to_dict() if fid in lay else {})
        out[fid] = parse_placement(fid, {**base, **v}).to_dict()  # type: ignore[dict-item]
    return out
