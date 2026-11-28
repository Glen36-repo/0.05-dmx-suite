"""What every effect shares: its settings (a schema the UI builds its form from), parsing them,
where each light sits along the effect (in order or across the layout), waveforms, and how a
layer's colour mixes with the layers under it.

An effect is a class registered in effects/__init__.py with:
    name, label, help    shown in the scene builder and Claude's guide
    params               list[Param]: its settings, defaults and limits
    movement = True      if it moves heads (refused on colour-only heads, rule 7)
    per_pixel = True     if each pixel of a pixel bar is its own unit (else the whole light)
    check(p, ctx)        extra checks after parsing (optional)
    render(p, run)       writes into the look for time run.t (see Run)
"""

from __future__ import annotations

import math
import random
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..fixtures import Patch
from ..look import Colour, FixtureLook, Look, LookError
from ..palettes import Palettes

# --------------------------------------------------------------------------- small helpers


def mix(a: Colour, b: Colour, f: float) -> Colour:
    keys = set(a) | set(b)
    return {k: a.get(k, 0.0) * (1 - f) + b.get(k, 0.0) * f for k in keys}


def scale(c: Colour, f: float) -> Colour:
    return {k: v * f for k, v in c.items()}


def seed(*parts: Any) -> int:
    return zlib.crc32("|".join(map(str, parts)).encode())


def num(v: Any, what: str, lo: float | None = None, hi: float | None = None) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError) as e:
        raise LookError(f"{what} must be a number, not {v!r}") from e
    if isinstance(v, bool) or (lo is not None and f < lo) or (hi is not None and f > hi):
        if hi is not None:
            raise LookError(f"{what} must be {lo:g}-{hi:g}" if lo is not None else f"{what} must be <= {hi:g}")
        raise LookError(f"{what} must be >= {lo:g}")
    return f


def hue(h: float, sat: float = 1.0) -> Colour:
    """Hue 0-1 round the colour wheel as RGB, at saturation `sat`."""
    h = (h % 1.0) * 6
    i, f = int(h), h - int(h)
    rgb = [(1, f, 0), (1 - f, 1, 0), (0, 1, f), (0, 1 - f, 1), (f, 0, 1), (1, 0, 1 - f)][i % 6]
    return {k: 1 - sat + sat * v for k, v in zip(("red", "green", "blue"), rgb)}


WAVEFORMS = ("sine", "square", "saw", "triangle", "pulse")


def wave(form: str, phase: float, width: float = 0.5) -> float:
    """Level 0-1 at `phase` (0-1) of one cycle. `width` = the lit part for square/pulse."""
    p = phase % 1.0
    if form == "sine":
        return 0.5 - 0.5 * math.cos(2 * math.pi * p)
    if form == "saw":
        return p
    if form == "triangle":
        return 1 - abs(1 - 2 * p)
    if form == "pulse":  # short and sharp: lit for `width`, fading out over it
        return max(0.0, 1 - p / width) if p < width else 0.0
    return 1.0 if p < width else 0.0  # square


# --------------------------------------------------------------------------- settings schema


@dataclass
class Param:
    """One setting. kind: number, int, bool, colour, colours, position, range, choice, angle, text."""

    key: str
    kind: str
    default: Any = None  # None = optional (absent unless given); callables get the ParseCtx
    lo: float | None = None
    hi: float | None = None
    choices: tuple[str, ...] = ()
    label: str = ""
    help: str = ""
    min_items: int = 0  # colours

    def to_json(self) -> dict[str, Any]:
        d: dict[str, Any] = {"key": self.key, "kind": self.kind, "label": self.label or self.key.replace("_", " "),
                             "help": self.help}
        if self.default is not None and not callable(self.default):
            d["default"] = list(self.default) if isinstance(self.default, tuple) else self.default
        for k in ("lo", "hi"):
            if getattr(self, k) is not None:
                d[k] = getattr(self, k)
        if self.choices:
            d["choices"] = list(self.choices)
        if self.min_items:
            d["min_items"] = self.min_items
        return d


@dataclass
class ParseCtx:
    patch: Patch
    pal: Palettes
    targets: list[str]  # fixture ids the layer can land on (fixtures + fallback)
    what: str  # "scene x layer 2", for messages


def parse_value(prm: Param, v: Any, ctx: ParseCtx) -> Any:
    what = f"{ctx.what} {prm.key}"
    k = prm.kind
    if k == "number":
        return num(v, what, prm.lo, prm.hi)
    if k == "int":
        f = num(v, what, prm.lo, prm.hi)
        return int(f)
    if k == "bool":
        return bool(v)
    if k == "colour":
        return ctx.pal.colour(v, what)
    if k == "colours":
        if not isinstance(v, list) or len(v) < max(1, prm.min_items):
            raise LookError(f"{ctx.what}: {prm.key} needs a list of at least {max(1, prm.min_items)} colours")
        return [ctx.pal.colour(c, what) for c in v]
    if k == "position":
        return ctx.pal.positions_for(v, ctx.targets, what)
    if k == "range":
        if not isinstance(v, (list, tuple)) or len(v) != 2:
            raise LookError(f"{what} must be [min, max]")
        lo, hi = (num(x, what, 0, 1) for x in v)
        if lo > hi:
            raise LookError(f"{what}: min above max")
        return (lo, hi)
    if k == "choice":
        if v not in prm.choices:
            raise LookError(f"{what} must be one of {', '.join(prm.choices)}")
        return v
    if k == "angle":
        return num(v, what) % 360
    if k == "text":
        return str(v)
    raise LookError(f"{what}: unknown setting type {k}")


# --------------------------------------------------------------------------- where each light sits along an effect

MAPPINGS = ("order", "spatial")
DIRECTIONS = ("forward", "reverse", "centre_out", "out_centre", "random", "angle")
SPREAD_PARAMS = [
    Param("mapping", "choice", "order", choices=MAPPINGS, label="mapping",
          help="order: lights in the order listed; spatial: by where they are on the layout"),
    Param("direction", "choice", "forward", choices=DIRECTIONS,
          help="which way the effect runs across the lights; 'angle' uses the angle setting (spatial)"),
    Param("angle", "angle", 0.0, help="degrees, 0 = left to right, 90 = top to bottom (spatial, direction angle)"),
    Param("groups_of", "int", 1, lo=1, hi=64, label="groups of", help="move the lights in blocks of this many"),
]


@dataclass
class Unit:
    """One thing an effect colours: a whole light, or one pixel of a pixel light."""

    fid: str
    pixel: int | None
    index: int  # position in the layer's order
    x: float = 0.5  # where it is on the layout, scaled so the layer's lights span 0-1 on their
    y: float = 0.5  # longer side (same scale both ways, so angles stay true)
    u: float = 0.0  # 0-1 along the effect (after mapping, direction and groups)


def place_units(units: list[Unit], p: dict[str, Any], seed_text: str) -> None:
    """Set each unit's u (0-1 along the effect) from mapping, direction, angle and groups_of."""
    n = len(units)
    if not n:
        return
    spatial = p.get("mapping", "order") == "spatial"
    direction = p.get("direction", "forward")
    if direction == "random":
        order = list(range(n))
        random.Random(seed(seed_text, "random-direction")).shuffle(order)
        us = [order[i] / n for i in range(n)]
    elif spatial:
        if direction in ("centre_out", "out_centre"):
            xs, ys = [un.x for un in units], [un.y for un in units]
            cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
            d = [math.hypot(un.x - cx, un.y - cy) for un in units]
            top = max(d) or 1.0
            us = [v / top for v in d]
        else:
            a = math.radians(p.get("angle", 0.0) if direction == "angle" else 0.0)
            proj = [un.x * math.cos(a) + un.y * math.sin(a) for un in units]
            lo, hi = min(proj), max(proj)
            us = [(v - lo) / (hi - lo) if hi > lo else 0.0 for v in proj]
        if direction in ("reverse", "out_centre"):
            us = [1 - v for v in us]
    else:
        idx = [un.index for un in units]
        m = max(idx) + 1
        if direction in ("centre_out", "out_centre"):
            c = (m - 1) / 2
            us = [abs(i - c) / (m / 2) for i in idx]
        else:
            us = [i / m for i in idx]
        if direction in ("reverse", "out_centre"):
            us = [1 - v - (1 / m if direction == "reverse" else 0) for v in us]
    g = int(p.get("groups_of", 1))
    if g > 1:  # blocks of g lights move together
        ranked = sorted(range(n), key=lambda i: us[i])
        groups = math.ceil(n / g)
        for rank, i in enumerate(ranked):
            us[i] = (rank // g) / groups
    for un, v in zip(units, us):
        un.u = min(max(v, 0.0), 1.0)


# --------------------------------------------------------------------------- lit (v6: black in the effect)
# `lit` 0-1 is how much of an effect is lit; the rest is black (colour off, never dimmer: rule 1 / 4).
# 1 = as programmed. Each colour effect shapes its own black (narrower bands, black palette slots,
# gaps between gradient segments); effects that don't get a regular pattern of black lights / pixels.

BLACK: dict[str, float] = {}


def window(pos: float, lit: float, edge: float = 0.0) -> float:
    """Gate 0-1 for a point `pos` (0-1 round a cycle, measured from the lit band's centre): lit within
    `lit` / 2 either side, black beyond, a linear soft edge `edge` (0-1 of the band) between."""
    if lit >= 1.0:
        return 1.0
    if lit <= 0.0:
        return 0.0
    d = abs(((pos + 0.5) % 1.0) - 0.5)  # distance from the centre, 0-0.5
    half = lit / 2
    e = max(0.0, min(1.0, edge)) * min(lit, 1 - lit) / 2
    if e <= 0:
        return 1.0 if d < half else 0.0
    return max(0.0, min(1.0, (half + e - d) / (2 * e)))


def with_black(cols: list[Any], lit: float) -> list[Any]:
    """A palette with black slots spread evenly through it: 50 % = colour, black, colour, black. No two
    blacks in a row unless lit is under 50 %."""
    if lit >= 1.0 or not cols:
        return list(cols)
    k = len(cols)
    if lit <= 0.0:
        return [BLACK]
    n = min(k * 32, max(k + 1, round(k / lit)))
    out: list[Any] = []
    used = 0
    for i in range(n):  # k colours spread evenly over n slots, starting with a colour
        if (i * k) % n < k:
            out.append(cols[used % k])
            used += 1
        else:
            out.append(BLACK)
    return out


def gapped(x: float, k: int, lit: float) -> tuple[int, float] | None:
    """`x` 0-1 round k colour segments, each squeezed into `lit` of its slot with black after it: the
    segment and where in it (0-1), or None in a gap. Total black = (1 - lit) of the span."""
    v = (x % 1.0) * k
    i = int(v) % k
    f = v - int(v)
    if lit >= 1.0:
        return i, f
    if f >= lit:
        return None
    return i, f / lit


def static_on(index: int, lit: float, offset: int = 0) -> bool:
    """A regular pattern of lit / black units with `lit` of them lit (50 % alternate, 33 % every third
    ...); `offset` slides it (the look's shift)."""
    if lit >= 1.0:
        return True
    if lit <= 0.0:
        return False
    i = index + offset
    return math.floor((i + 1) * lit) > math.floor(i * lit)


# --------------------------------------------------------------------------- playing

BLENDS = ("replace", "max", "add")


def blend(old: Colour, new: Colour, mode: str, level: float) -> Colour:
    if mode == "max":
        return {k: max(old.get(k, 0.0), new.get(k, 0.0) * level) for k in set(old) | set(new)}
    if mode == "add":
        return {k: min(1.0, old.get(k, 0.0) + new.get(k, 0.0) * level) for k in set(old) | set(new)}
    if level >= 1:
        return dict(new)
    return {k: old.get(k, 0.0) * (1 - level) + new.get(k, 0.0) * level for k in set(old) | set(new)}


@dataclass
class Run:
    """Everything an effect's render needs for one frame."""

    t: float  # effect time, seconds since the scene started (tap tempo scaled)
    fids: list[str]  # the layer's lights in this rig, in order
    look: Look
    dark: set[str]  # heads to black out (moving dark)
    pixels: Callable[[str], int]  # pixel count of a light (0 = single cell)
    units: Callable[[bool], list[Unit]]  # units(per_pixel), placed along the effect
    blend_mode: str = "replace"
    level: float = 1.0
    seed_text: str = ""
    now: float = 0.0  # the engine's clock (drum-reactive effects read hits by it, v3.3)
    _pending: dict[str, list[Colour | None]] = field(default_factory=dict)
    mask: dict[str, frozenset[int]] = field(default_factory=dict)  # v4: pixel selections - only these pixels change
    lit: float = 1.0  # v6: how much of the effect is lit (darkness already applied)
    lit_exempt: float = 1.0  # the same for exempt lights (the kick light): the look's own lit, no darkness
    exempt: frozenset[str] = frozenset()
    edge: float = 0.0  # soft black edges, 0 = hard cut (the look's fade)
    shift: float = 0.0  # the layer's shift, 0-1 (static black patterns move with it)
    auto_gate: bool = False  # the effect doesn't shape its own black: Run puts a static pattern on it
    unlit: set[tuple[str, int | None]] = field(default_factory=set)  # units blacked by lit (drum flash skips them)
    _index: dict[tuple[str, int | None], int] | None = None

    def lit_of(self, fid: str) -> float:
        return self.lit_exempt if fid in self.exempt else self.lit

    def gating(self) -> bool:
        return self.lit < 1.0 or self.lit_exempt < 1.0

    def _offset(self, n: int) -> int:
        return round(self.shift * n)

    def _gate(self, fid: str, pixel: int | None, c: Colour | None) -> Colour | None:
        """Static black pattern for effects that don't shape their own (auto_gate)."""
        if c is None or not self.auto_gate:
            return c
        lit = self.lit_of(fid)
        if lit >= 1.0:
            return c
        if self._index is None:
            units = self.units(True)
            self._index = {(un.fid, un.pixel): k for k, un in enumerate(units)}
            self._index.update({(un.fid, None): k for k, un in enumerate(units) if (un.fid, None) not in self._index})
        k = self._index.get((fid, pixel), self._index.get((fid, None), 0))
        if static_on(k, lit, self._offset(len(self._index))):
            return c
        self.unlit.add((fid, pixel))
        return BLACK

    def black(self, fid: str, pixel: int | None = None) -> Colour:
        """A unit made black by lit (remembered, so a drum flash leaves it black)."""
        self.unlit.add((fid, pixel))
        return BLACK

    def _masked(self, fid: str, cols: list[Colour | None]) -> None:
        """Write a pixel selection: the selected pixels get `cols` (blended as the layer says), the
        others keep what lower layers / earlier steps gave them, else off (rule 4)."""
        fl = self.fl(fid)
        n = max(1, self.pixels(fid))
        row = [dict(p) for p in fl.pixels] if fl.pixels else [dict(fl.colour) for _ in range(n)]
        row += [{} for _ in range(n - len(row))]
        plain = self.blend_mode == "replace" and self.level >= 1
        for px in self.mask[fid]:
            c = cols[px] if px < len(cols) else None
            if c is None:
                continue
            row[px] = dict(c) if plain else blend(row[px], c, self.blend_mode, self.level)
        fl.pixels, fl.colour = row, {}

    def fl(self, fid: str) -> FixtureLook:
        return self.look.fixtures.setdefault(fid, FixtureLook())

    # colour out, mixed with what lower layers set (blend + level)
    def set_colour(self, fid: str, c: Colour) -> None:
        if self.auto_gate and self.gating():
            if self.pixels(fid) and fid not in self.mask:  # per pixel, so a bar gets the pattern along it
                return self.set_pixels(fid, [dict(c) for _ in range(self.pixels(fid))])
            c = self._gate(fid, None, c) or BLACK
        if fid in self.mask:
            return self._masked(fid, [c] * max(1, self.pixels(fid)))
        fl = self.fl(fid)
        if self.blend_mode == "replace" and self.level >= 1:
            fl.colour, fl.pixels = dict(c), None
        elif fl.pixels:
            fl.pixels = [blend(px, c, self.blend_mode, self.level) for px in fl.pixels]
        else:
            fl.colour = blend(fl.colour, c, self.blend_mode, self.level)

    def set_pixels(self, fid: str, cols: list[Colour]) -> None:
        if self.auto_gate and self.gating():
            cols = [self._gate(fid, i, c) or BLACK for i, c in enumerate(cols)]
        if fid in self.mask:
            return self._masked(fid, list(cols))
        fl = self.fl(fid)
        if self.blend_mode == "replace" and self.level >= 1:
            fl.pixels, fl.colour = cols, {}
            return
        old = fl.pixels or [fl.colour] * len(cols)
        fl.pixels, fl.colour = [blend(o, c, self.blend_mode, self.level) for o, c in zip(old, cols)], {}

    def put(self, unit: Unit, c: Colour) -> None:
        """Colour one unit; whole lights at once, pixels gathered and written by flush()."""
        if unit.pixel is None:
            self.set_colour(unit.fid, c)  # gated there (per pixel on a pixel light)
        else:
            row = self._pending.setdefault(unit.fid, [None] * max(1, self.pixels(unit.fid)))
            row[unit.pixel] = c

    def flush(self) -> None:
        gate = self.auto_gate
        if gate and self.gating():
            for fid, row in self._pending.items():
                self._pending[fid] = [self._gate(fid, i, c) if c is not None else None for i, c in enumerate(row)]
            self.auto_gate = False  # set_pixels below mustn't gate twice
        try:
            self._flush()
        finally:
            self.auto_gate = gate

    def _flush(self) -> None:
        for fid, row in self._pending.items():
            if fid in self.mask:  # only the selected pixels were coloured; the rest keep theirs
                self._masked(fid, [dict(c) if c is not None else None for c in row])
            else:
                self.set_pixels(fid, [dict(c) if c is not None else {} for c in row])
        self._pending.clear()


class Effect:
    name = ""
    label = ""
    help = ""
    movement = False
    lit_aware = False  # v6: shapes its own black from run.lit (else Run puts a static pattern on it)
    per_pixel = False
    params: list[Param] = []

    def parse(self, d: dict[str, Any], ctx: ParseCtx) -> dict[str, Any]:
        p: dict[str, Any] = {}
        for prm in self.params:
            if prm.key in d:
                p[prm.key] = parse_value(prm, d[prm.key], ctx)
            elif prm.default is not None:
                default = prm.default(ctx) if callable(prm.default) else prm.default
                p[prm.key] = parse_value(prm, default, ctx) if prm.kind in ("colour", "colours", "position") else default
        self.check(p, ctx)
        return p

    def check(self, p: dict[str, Any], ctx: ParseCtx) -> None:
        pass

    def keys(self) -> set[str]:
        return {prm.key for prm in self.params}

    def period(self, p: dict[str, Any]) -> float | None:
        """Seconds for one cycle (scene length / repeats)."""
        if "period_s" in p:
            return float(p["period_s"])
        if p.get("rate_hz"):
            return 1.0 / float(p["rate_hz"])
        return None

    def render(self, p: dict[str, Any], run: Run) -> None:
        raise NotImplementedError

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "label": self.label, "help": self.help, "movement": self.movement,
                "per_pixel": self.per_pixel, "params": [prm.to_json() for prm in self.params]}
