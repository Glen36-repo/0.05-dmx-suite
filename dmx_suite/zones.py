"""Head exclusion zones (v7 C1): areas of a moving head's pan/tilt range it must never point into
(a mirror, the front row's eyes). Part of rule 8, at the same layer as the head limits.

A zone is a rectangle or an ellipse in % of the head's pan / tilt range, saved in the rig file per head:

    head_zones:
      mh_a:
        - {name: Mirror, shape: rect, pan: [40, 55], tilt: [10, 30]}
        - {name: Front row, shape: ellipse, centre: [50, 80], radius: [20, 8], black: true}

At output each head's target (after the head limits) goes through a ZoneFollower:

- Clear of every zone: the target, unchanged (no zones = v6 output exactly).
- A move that would go into a zone stops at its edge (a ring half a frame's longest step outside it, so the
  line between two frames never cuts in), **on the side it came from**, and stays on that
  side while the target is inside (hysteresis: a target crossing the zone's middle never flips it to
  the far edge, which would snap the head across the zone).
- While the target is inside, the head slides along that half of the edge towards it; when the target
  comes out on another side, the head slides round the edge to it, always the same way round (chosen
  when it came out), and lets go once the straight line to the target is clear.
- While held, sliding and catching up afterwards, it never moves faster than `speed` (range a second),
  so the head never steps across the zone.
- `black: true` zones don't deflect: the head goes where it's told but its colour is off while the
  target is inside.

Zones are convex, so each is handled as a convex polygon: a rectangle's four corners, an ellipse as a
72-gon drawn just outside it (so the polygon's edge is never inside the real ellipse).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .fixtures import ConfigError

SHAPES = ("rect", "ellipse")
SIDES = 72
DEFAULT_SPEED = 1.0  # full range a second while deflecting or catching up
EPS = 1e-9

Pt = tuple[float, float]


@dataclass
class Zone:
    name: str
    shape: str
    pan: tuple[float, float] = (0.0, 0.0)  # rect: 0-1
    tilt: tuple[float, float] = (0.0, 0.0)
    centre: Pt = (0.5, 0.5)  # ellipse: 0-1
    radius: Pt = (0.1, 0.1)
    black: bool = False
    poly: list[Pt] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if not self.poly:
            self.poly = self._polygon()

    def _polygon(self) -> list[Pt]:
        if self.shape == "rect":
            (a, b), (c, d) = self.pan, self.tilt
            return [(a, c), (b, c), (b, d), (a, d)]
        (cx, cy), (rx, ry) = self.centre, self.radius
        k = (1 + 1e-6) / math.cos(math.pi / SIDES)  # circumscribed (+ a hair): every edge stays outside the ellipse
        return [(cx + rx * k * math.cos(2 * math.pi * i / SIDES), cy + ry * k * math.sin(2 * math.pi * i / SIDES))
                for i in range(SIDES)]

    @property
    def middle(self) -> Pt:
        if self.shape == "rect":
            return ((self.pan[0] + self.pan[1]) / 2, (self.tilt[0] + self.tilt[1]) / 2)
        return self.centre

    def inside(self, p: Pt, margin: float = 1e-7) -> bool:
        """Strictly inside the shape itself (the real ellipse, not its polygon)."""
        if self.shape == "rect":
            return (self.pan[0] + margin < p[0] < self.pan[1] - margin and self.tilt[0] + margin < p[1] < self.tilt[1] - margin)
        (cx, cy), (rx, ry) = self.centre, self.radius
        return ((p[0] - cx) / rx) ** 2 + ((p[1] - cy) / ry) ** 2 < 1 - margin

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"name": self.name, "shape": self.shape}
        if self.shape == "rect":
            d["pan"] = [round(self.pan[0] * 100, 2), round(self.pan[1] * 100, 2)]
            d["tilt"] = [round(self.tilt[0] * 100, 2), round(self.tilt[1] * 100, 2)]
        else:
            d["centre"] = [round(self.centre[0] * 100, 2), round(self.centre[1] * 100, 2)]
            d["radius"] = [round(self.radius[0] * 100, 2), round(self.radius[1] * 100, 2)]
        if self.black:
            d["black"] = True
        return d


# ---------------------------------------------------------------------- parsing


def _pair(v: Any, where: str, lo: float = 0, hi: float = 100) -> tuple[float, float]:
    if (not isinstance(v, (list, tuple)) or len(v) != 2 or any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in v)
            or not all(lo <= x <= hi for x in v)):
        raise ConfigError(f"{where}: [a, b], each {lo:g}-{hi:g} (%)")
    return float(v[0]) / 100, float(v[1]) / 100


def parse_zone(d: Any, where: str) -> Zone:
    if not isinstance(d, dict):
        raise ConfigError(f"{where}: {{name, shape: rect|ellipse, ...}}")
    shape = d.get("shape")
    if shape not in SHAPES:
        raise ConfigError(f"{where} shape: rect or ellipse")
    name = d.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ConfigError(f"{where}: needs a name")
    keys = {"name", "shape", "black"} | ({"pan", "tilt"} if shape == "rect" else {"centre", "radius"})
    extra = set(d) - keys
    if extra:
        raise ConfigError(f"{where}: a {shape} has {', '.join(sorted(keys))} (not {', '.join(sorted(extra))})")
    black = d.get("black", False)
    if not isinstance(black, bool):
        raise ConfigError(f"{where} black: true or false")
    if shape == "rect":
        pan, tilt = _pair(d.get("pan"), f"{where} pan"), _pair(d.get("tilt"), f"{where} tilt")
        if pan[0] >= pan[1] or tilt[0] >= tilt[1]:
            raise ConfigError(f"{where}: pan and tilt are [low, high] with low below high")
        return Zone(name.strip(), shape, pan=pan, tilt=tilt, black=black)
    centre = _pair(d.get("centre"), f"{where} centre")
    radius = _pair(d.get("radius"), f"{where} radius", 0.5, 100)
    return Zone(name.strip(), shape, centre=centre, radius=radius, black=black)


def parse_zones(data: Any, heads: dict[str, Any]) -> dict[str, list[Zone]]:
    """Rig `head_zones: {head id: [zone, ...]}`; heads = fixture id -> Fixture of the rig's moving heads."""
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError("head_zones: {head: [zones]}")
    out: dict[str, list[Zone]] = {}
    for fid, zs in data.items():
        if fid not in heads:
            raise ConfigError(f"head_zones: {fid!r} isn't a moving head in this rig")
        if not isinstance(zs, list):
            raise ConfigError(f"head_zones {fid}: a list of zones")
        parsed = [parse_zone(z, f"head_zones {fid} #{i + 1}") for i, z in enumerate(zs)]
        names = [z.name for z in parsed]
        dup = {n for n in names if names.count(n) > 1}
        if dup:
            raise ConfigError(f"head_zones {fid}: zone names must differ ({', '.join(sorted(dup))})")
        if parsed:
            out[str(fid)] = parsed
    return out


# ---------------------------------------------------------------------- geometry on a convex polygon


def _sub(a: Pt, b: Pt) -> Pt:
    return (a[0] - b[0], a[1] - b[1])


def _len(a: Pt) -> float:
    return math.hypot(a[0], a[1])


def _cross(a: Pt, b: Pt) -> float:
    return a[0] * b[1] - a[1] * b[0]


class Ring:
    """A convex polygon's edge as a loop, measured by distance along it (s, 0..length)."""

    def __init__(self, poly: list[Pt]) -> None:
        if _area(poly) < 0:
            poly = poly[::-1]  # counter-clockwise
        self.poly = poly
        self.cum = [0.0]
        for i in range(len(poly)):
            self.cum.append(self.cum[-1] + _len(_sub(poly[(i + 1) % len(poly)], poly[i])))
        self.length = self.cum[-1]

    def at(self, s: float) -> Pt:
        s %= self.length
        for i in range(len(self.poly)):
            if s <= self.cum[i + 1] + EPS:
                a, b = self.poly[i], self.poly[(i + 1) % len(self.poly)]
                seg = self.cum[i + 1] - self.cum[i]
                k = 0.0 if seg <= 0 else (s - self.cum[i]) / seg
                return (a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k)
        return self.poly[0]

    def param(self, p: Pt) -> float:
        """s of the edge point nearest p."""
        best, best_s = 1e18, 0.0
        for i in range(len(self.poly)):
            a, b = self.poly[i], self.poly[(i + 1) % len(self.poly)]
            ab = _sub(b, a)
            ll = ab[0] ** 2 + ab[1] ** 2
            k = 0.0 if ll <= 0 else max(0.0, min(1.0, ((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1]) / ll))
            q = (a[0] + ab[0] * k, a[1] + ab[1] * k)
            d = _len(_sub(p, q))
            if d < best:
                best, best_s = d, self.cum[i] + k * math.sqrt(ll)
        return best_s

    def radial(self, middle: Pt, p: Pt) -> float:
        """s where the ray from the middle through p crosses the edge."""
        d = _sub(p, middle)
        if _len(d) < EPS:
            return 0.0
        for i in range(len(self.poly)):
            a, b = self.poly[i], self.poly[(i + 1) % len(self.poly)]
            e = _sub(b, a)
            den = _cross(d, e)
            if abs(den) < EPS:
                continue
            am = _sub(a, middle)
            t = _cross(am, e) / den
            u = _cross(am, d) / den
            if t >= 0 and -EPS <= u <= 1 + EPS:
                return self.cum[i] + max(0.0, min(1.0, u)) * _len(e)
        return self.param(p)

    def gap(self, a: float, b: float) -> float:
        """Signed shortest way round from s=a to s=b."""
        d = (b - a) % self.length
        return d - self.length if d > self.length / 2 else d


def expand(poly: list[Pt], d: float, arc: int = 8) -> list[Pt]:
    """The convex polygon grown by d all round (rounded corners): the convex hull of a small circle
    round every corner."""
    if d <= 0:
        return list(poly)
    k = 1 / math.cos(math.pi / (4 * arc))  # each corner circle drawn just outside a true circle
    pts = [(x + d * k * math.cos(2 * math.pi * j / (4 * arc)), y + d * k * math.sin(2 * math.pi * j / (4 * arc)))
           for x, y in poly for j in range(4 * arc)]
    return _hull(pts)


def _hull(pts: list[Pt]) -> list[Pt]:
    pts = sorted(set(pts))
    if len(pts) < 3:
        return pts

    def half(seq: list[Pt]) -> list[Pt]:
        out: list[Pt] = []
        for p in seq:
            while len(out) >= 2 and _cross(_sub(out[-1], out[-2]), _sub(p, out[-2])) <= 0:
                out.pop()
            out.append(p)
        return out

    lower, upper = half(pts), half(pts[::-1])
    return lower[:-1] + upper[:-1]  # counter-clockwise


def _area(poly: list[Pt]) -> float:
    return sum(_cross(poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly))) / 2


def enters(poly: list[Pt], a: Pt, b: Pt) -> float | None:
    """Where (0-1 along a->b) the segment first goes inside the convex polygon, or None if it stays
    out (touching the edge doesn't count). Cyrus-Beck clipping, CCW polygon."""
    if _area(poly) < 0:
        poly = poly[::-1]
    d = _sub(b, a)
    t0, t1 = 0.0, 1.0
    for i in range(len(poly)):
        p, q = poly[i], poly[(i + 1) % len(poly)]
        e = _sub(q, p)
        num = _cross(e, _sub(a, p))  # > 0: a is inside this edge
        den = _cross(e, d)
        if abs(den) < EPS:
            if num <= EPS:
                return None
            continue
        t = -num / den
        if den > 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 >= t1 - 1e-9:
            return None
    return t0


# ---------------------------------------------------------------------- the follower


@dataclass
class _Held:
    zone: int
    entry: float  # s where it came in: the half of the edge it stays on while the target is inside
    s: float  # where it is on the edge now
    way: int = 0  # +1 / -1 round the edge once the target has come out (0 = not chosen yet)


class ZoneFollower:
    """One head's way round its zones, frame by frame."""

    def __init__(self, zones: list[Zone], speed: float = DEFAULT_SPEED, fps: float = 40.0) -> None:
        self.zones = [z for z in zones]
        self.blockers = [i for i, z in enumerate(self.zones) if not z.black]
        # the head goes round on a ring just outside the zone (half a frame's longest step out, rounded corners),
        # so the straight line between two frames on it never cuts into the zone
        pad = 0.55 * speed / fps
        self.polys = {i: expand(self.zones[i].poly, pad) for i in self.blockers}
        self.rings = {i: Ring(self.polys[i]) for i in self.blockers}
        self.speed = speed
        self.out: Pt | None = None
        self.held: _Held | None = None
        self.catching = False
        self.last = 0.0

    def black(self, target: Pt) -> bool:
        return any(z.black and z.inside(target) for z in self.zones)

    def step(self, target: Pt, now: float) -> Pt:
        dt = max(0.0, min(0.1, now - self.last)) if self.out is not None else 0.0
        self.last = now
        if self.out is None:  # first frame: start clear of every zone, at the nearest edge if need be
            self.out = target
            for i in self.blockers:
                if self.zones[i].inside(self.out):
                    r = self.rings[i]
                    s = r.radial(self.zones[i].middle, self.out)
                    self.out = r.at(s)
                    self.held = _Held(i, s, s)
            return self.out
        room = self.speed * dt
        if self.held is not None:
            return self._held(target, room)
        # catching up after sliding round: no faster than speed; otherwise straight to the target (v6)
        goal = _toward(self.out, target, room) if self.catching else target
        hit = self._first_hit(self.out, goal)
        if hit is None:
            self.out = goal
            if self.out == target:
                self.catching = False
            return self.out
        i, k = hit
        p = (self.out[0] + (goal[0] - self.out[0]) * k, self.out[1] + (goal[1] - self.out[1]) * k)
        s = self.rings[i].param(p)
        self.held = _Held(i, s, s)
        self.out = self.rings[i].at(s)
        return self.out

    def _first_hit(self, a: Pt, b: Pt) -> tuple[int, float] | None:
        best: tuple[int, float] | None = None
        for i in self.blockers:
            k = enters(self.polys[i], a, b)
            if k is not None and (best is None or k < best[1]):
                best = (i, k)
        return best

    def _held(self, target: Pt, room: float) -> Pt:
        h = self.held
        assert h is not None
        z, ring = self.zones[h.zone], self.rings[h.zone]
        here = ring.at(h.s)
        if not z.inside(target) and enters(self.polys[h.zone], here, target) is None:
            # the way to the target is clear: let go and catch up (still no faster than speed)
            self.held, self.catching = None, True
            goal = _toward(here, target, room)
            hit = self._first_hit(here, goal)
            if hit is None:
                self.out = goal
                if self.out == target:
                    self.catching = False
                return self.out
            i, k = hit  # straight into another zone: held at that one's edge instead
            p = (here[0] + (goal[0] - here[0]) * k, here[1] + (goal[1] - here[1]) * k)
            s = self.rings[i].param(p)
            self.held = _Held(i, s, s)
            self.out = self.rings[i].at(s)
            return self.out
        quarter = ring.length / 4
        if z.inside(target):  # stay on the half of the edge it came in on, as near the target as that allows
            want = ring.radial(z.middle, target)
            off = ring.gap(h.entry, want)
            if abs(off) > quarter:  # target on the far half: the near end of this half, by where it is now
                ends = (h.entry - quarter, h.entry + quarter)
                want = min(ends, key=lambda e: abs(ring.gap(h.s, e)) + (1e-9 if e == ends[0] else 0))
            h.way = 0
            move = ring.gap(h.s, want)
        else:  # target out on another side: round the edge one way (chosen now, kept) until the line is clear
            want = ring.radial(z.middle, target)
            if h.way == 0:
                g = ring.gap(h.s, want)
                h.way = 1 if g >= 0 else -1
            move = h.way * ((h.way * (want - h.s)) % ring.length)
        step = max(-room, min(room, move))
        h.s = (h.s + step) % ring.length
        self.out = ring.at(h.s)
        return self.out

    @property
    def holding(self) -> str | None:
        """The zone the head is held at the edge of (for the Heads page)."""
        return self.zones[self.held.zone].name if self.held is not None else None


def _toward(a: Pt, b: Pt, room: float) -> Pt:
    d = _sub(b, a)
    n = _len(d)
    if n <= room or n < EPS:
        return b
    return (a[0] + d[0] / n * room, a[1] + d[1] / n * room)
