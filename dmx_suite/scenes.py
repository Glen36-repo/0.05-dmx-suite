"""Scenes: layers (colour + effect + movement + beam) applied to fixture groups, played as a Look
every frame. Everything is time-based (period_s), so the same scene runs at any frame rate.

    name: Blue kit
    show_colour: blue                     # drum flashes use this (palette name or colour)
    layers:
      - {fixtures: [bars], effect: pixel_chase, colour: blue, background: off, width: 3, period_s: 2}
      - {fixtures: [washes], colour: blue}
      - {fixtures: [movers], effect: colour_chase, colours: [blue, white], period_s: 4, spread: 0.5}
      - {fixtures: [movers], position: drum_kit, gobo: dots}
      - {fixtures: [movers], effect: random_move, period_s: 6, dark_move_s: 1.0}

Timing: `period_s` is one full cycle. `spread` (0-1) is how much of a cycle is spread across the
layer's fixtures in order: 0 = all in step, 1 = evenly round the whole cycle.

Layers apply in order; a later layer overrides what an earlier one set on the same fixture.
No layer can set haze (rule 5) or move a colour-only head (rule 7). A layer may set `intensity`
(0-1) only where the rig's profile doesn't make MASTER own on/off (rule 1, see profile.py).
Fixtures missing from the active rig are skipped.
"""

from __future__ import annotations

import math
import random
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from .fixtures import EMITTERS, Patch
from .look import FORBIDDEN, Colour, FixtureLook, Look, LookError
from .palettes import Palettes, Position
from .rig import Rig

EFFECTS = {
    "colour_chase": {"colours", "period_s", "spread", "fade"},
    "pixel_chase": {"colour", "background", "width", "tail", "period_s", "bounce", "reverse"},
    "flash": {"colour", "rate_hz", "duty", "spread"},
    "sweep": {"from", "to", "period_s", "spread", "speed"},
    "random_move": {"period_s", "pan", "tilt", "dark_move_s", "stagger", "speed", "seed"},
}
MOVEMENT = {"sweep", "random_move"}
STATIC_KEYS = {"colour", "pixels", "position", "gobo", "colour_wheel", "speed", "strobe"}
COMMON = {"fixtures", "effect", "name", "fallback", "intensity"}


# --------------------------------------------------------------------------- model


@dataclass
class Layer:
    fixtures: list[str]  # resolved ids (whole patch; filtered to the rig when played)
    effect: str | None
    params: dict[str, Any]
    name: str = ""
    fallback: list[str] = field(default_factory=list)  # used when none of `fixtures` is in the rig


@dataclass
class Scene:
    name: str
    layers: list[Layer]
    show_colour: Colour = field(default_factory=lambda: {"red": 1.0, "green": 1.0, "blue": 1.0})

    @property
    def uses_intensity(self) -> bool:
        return any("intensity" in ly.params for ly in self.layers)


# --------------------------------------------------------------------------- parsing / validation


def _forbid(d: dict, what: str) -> None:
    for k in d:
        if k in FORBIDDEN:
            raise LookError(f"{what}: {FORBIDDEN[k]}")


def _num(v: Any, what: str, lo: float, hi: float | None = None) -> float:
    f = float(v)
    if f < lo or (hi is not None and f > hi):
        raise LookError(f"{what} must be {lo}-{hi}" if hi is not None else f"{what} must be >= {lo}")
    return f


def _range(v: Any, what: str) -> tuple[float, float]:
    lo, hi = (_num(x, what, 0, 1) for x in v)
    if lo > hi:
        raise LookError(f"{what}: min above max")
    return (lo, hi)


def parse_layer(d: dict, patch: Patch, pal: Palettes, what: str) -> Layer:
    _forbid(d, what)
    if "fixtures" not in d:
        raise LookError(f"{what}: needs fixtures")
    names = d["fixtures"] if isinstance(d["fixtures"], list) else [d["fixtures"]]
    fids = patch.resolve(names)
    fb = patch.resolve(d["fallback"] if isinstance(d.get("fallback"), list) else [d["fallback"]]) if "fallback" in d else []
    targets = fids + [f for f in fb if f not in fids]  # params cover both, checks apply to both
    eff = d.get("effect")
    allowed = COMMON | (EFFECTS[eff] if eff in EFFECTS else STATIC_KEYS)
    if eff is not None and eff not in EFFECTS:
        raise LookError(f"{what}: unknown effect {eff!r}; one of {sorted(EFFECTS)}")
    bad = set(d) - allowed
    if bad:
        raise LookError(f"{what}: unknown keys {sorted(bad)}")

    moves = eff in MOVEMENT or "position" in d
    if moves:
        stuck = [f for f in targets if patch.fixtures[f].type.colour_only]
        if stuck:
            raise LookError(f"{what}: {', '.join(stuck)} colour only, can't move (rule 7); use a group without them")
        no_pt = [f for f in targets if not patch.fixtures[f].type.has("pan")]
        if no_pt:
            raise LookError(f"{what}: {', '.join(no_pt)} have no pan/tilt")

    p: dict[str, Any] = {}
    # static attributes
    if "colour" in d:
        p["colour"] = pal.colour(d["colour"], what)
    if "pixels" in d:
        p["pixels"] = [pal.colour(c, f"{what} pixel {i + 1}") for i, c in enumerate(d["pixels"])]
    if "position" in d and eff is None:
        p["position"] = {f: pal.position(d["position"], f, what) for f in targets}
    if "gobo" in d:
        p["gobo"] = {f: pal.gobo(d["gobo"], patch.fixtures[f].type.key, what) for f in targets}
    if "colour_wheel" in d:
        p["colour_wheel"] = int(_num(d["colour_wheel"], f"{what} colour_wheel", 0, 255))
    if "strobe" in d:
        p["strobe"] = int(_num(d["strobe"], f"{what} strobe", 0, 255))
    if "intensity" in d:
        p["intensity"] = _num(d["intensity"], f"{what} intensity", 0, 1)
    if "speed" in d:
        p["speed"] = _num(d["speed"], f"{what} speed", 0, 1)

    # effect parameters
    if eff == "colour_chase":
        cols = d.get("colours") or []
        if len(cols) < 2:
            raise LookError(f"{what}: colour_chase needs at least 2 colours")
        p["colours"] = [pal.colour(c, what) for c in cols]
        p["period_s"] = _num(d.get("period_s", 4), f"{what} period_s", 0.05)
        p["spread"] = _num(d.get("spread", 0), f"{what} spread", 0, 1)
        p["fade"] = bool(d.get("fade", False))
    elif eff == "pixel_chase":
        p.setdefault("colour", pal.colour("white", what))
        p["background"] = pal.colour(d.get("background", "off"), what)
        p["width"] = int(_num(d.get("width", 1), f"{what} width", 1))
        p["tail"] = int(_num(d.get("tail", 0), f"{what} tail", 0))
        p["period_s"] = _num(d.get("period_s", 2), f"{what} period_s", 0.05)
        p["bounce"] = bool(d.get("bounce", False))
        p["reverse"] = bool(d.get("reverse", False))
    elif eff == "flash":
        p.setdefault("colour", pal.colour("white", what))
        p["rate_hz"] = _num(d.get("rate_hz", 4), f"{what} rate_hz", 0.1, 25)
        p["duty"] = _num(d.get("duty", 0.5), f"{what} duty", 0.01, 0.99)
        p["spread"] = _num(d.get("spread", 0), f"{what} spread", 0, 1)
    elif eff == "sweep":
        if "from" not in d or "to" not in d:
            raise LookError(f"{what}: sweep needs from and to positions")
        p["from"] = {f: pal.position(d["from"], f, what) for f in targets}
        p["to"] = {f: pal.position(d["to"], f, what) for f in targets}
        p["period_s"] = _num(d.get("period_s", 8), f"{what} period_s", 0.2)
        p["spread"] = _num(d.get("spread", 0), f"{what} spread", 0, 1)
    elif eff == "random_move":
        p["period_s"] = _num(d.get("period_s", 6), f"{what} period_s", 0.5)
        p["pan"] = _range(d.get("pan", [0, 1]), f"{what} pan")
        p["tilt"] = _range(d.get("tilt", [0, 1]), f"{what} tilt")
        p["dark_move_s"] = _num(d.get("dark_move_s", 0), f"{what} dark_move_s", 0)
        if p["dark_move_s"] >= p["period_s"]:
            raise LookError(f"{what}: dark_move_s must be shorter than period_s")
        p["stagger"] = bool(d.get("stagger", True))  # independent timing per head
        p["seed"] = str(d.get("seed", what))
    return Layer(fids, eff, p, d.get("name", ""), fb)


def parse_scene(data: dict, patch: Patch, pal: Palettes, name: str = "scene") -> Scene:
    _forbid(data, name)
    bad = set(data) - {"name", "show_colour", "layers"}
    if bad:
        raise LookError(f"{name}: unknown keys {sorted(bad)}")
    layers = [parse_layer(d or {}, patch, pal, f"{name} layer {i + 1}") for i, d in enumerate(data.get("layers") or [])]
    if not layers:
        raise LookError(f"{name}: no layers")
    sc = Scene(data.get("name", name), layers)
    if "show_colour" in data:
        sc.show_colour = pal.colour(data["show_colour"], f"{name} show_colour")
    return sc


def load_scenes(folder: str | Path, patch: Patch, pal: Palettes) -> dict[str, Scene]:
    out = {}
    for path in sorted(Path(folder).glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        out[path.stem] = parse_scene(data, patch, pal, path.stem)
    return out


# --------------------------------------------------------------------------- playback


def _mix(a: Colour, b: Colour, f: float) -> Colour:
    keys = set(a) | set(b)
    return {k: a.get(k, 0.0) * (1 - f) + b.get(k, 0.0) * f for k in keys}


def _scale(c: Colour, f: float) -> Colour:
    return {k: v * f for k, v in c.items()}


def _seed(*parts: Any) -> int:
    return zlib.crc32("|".join(map(str, parts)).encode())


class ScenePlayer:
    """Callable(now) -> Look. Starts its clock when created."""

    def __init__(
        self, scene: Scene, rig: Rig, start: float, timebase: Callable[[float], float] | None = None
    ) -> None:
        self.scene = scene
        self.rig = rig
        self.timebase = timebase or (lambda now: now)  # tap tempo: effect time vs real time
        self.start = self.timebase(start)
        present = set(rig.present)
        self._layers = []
        for ly in scene.layers:
            fids = [f for f in ly.fixtures if f in present]
            if not fids:  # shows adapt: move the layer to what's there
                fids = [f for f in ly.fallback if f in present]
            self._layers.append((ly, fids))

    def __call__(self, now: float) -> Look:
        t = self.timebase(now) - self.start
        look = Look(show_colour=self.scene.show_colour)
        dark: set[str] = set()
        for layer, fids in self._layers:
            if fids:
                self._apply(layer, fids, t, look, dark)
        for f in dark:  # heads move between positions dark
            fl = look.fixtures.get(f)
            if fl:
                fl.colour, fl.pixels = {}, None
        return look

    def _fl(self, look: Look, fid: str) -> FixtureLook:
        return look.fixtures.setdefault(fid, FixtureLook())

    def _apply(self, ly: Layer, fids: list[str], t: float, look: Look, dark: set[str]) -> None:
        p = ly.params
        n = len(fids)
        # static attributes (also allowed alongside an effect's own keys)
        for f in fids:
            fl = self._fl(look, f)
            if ly.effect is None and "colour" in p:
                fl.colour, fl.pixels = dict(p["colour"]), None
            if "pixels" in p:
                fl.pixels = [dict(c) for c in p["pixels"]]
            if "position" in p:
                fl.pan, fl.tilt = p["position"][f]
            if "gobo" in p:
                fl.gobo = p["gobo"][f]
            if "colour_wheel" in p:
                fl.colour_wheel = p["colour_wheel"]
            if "strobe" in p:
                fl.strobe = p["strobe"]
            if "speed" in p:
                fl.speed = p["speed"]
            if "intensity" in p:
                fl.intensity = p["intensity"]

        eff = ly.effect
        if eff == "colour_chase":
            cols, k = p["colours"], len(p["colours"])
            for i, f in enumerate(fids):
                phase = (t / p["period_s"] + p["spread"] * i / n) % 1.0
                pos = phase * k
                idx, frac = int(pos) % k, pos - int(pos)
                c = _mix(cols[idx], cols[(idx + 1) % k], frac) if p["fade"] else cols[idx]
                fl = self._fl(look, f)
                fl.colour, fl.pixels = dict(c), None
        elif eff == "pixel_chase":
            self._pixel_chase(p, fids, t, look)
        elif eff == "flash":
            for i, f in enumerate(fids):
                phase = (t * p["rate_hz"] + p["spread"] * i / n) % 1.0
                fl = self._fl(look, f)
                fl.colour, fl.pixels = (dict(p["colour"]) if phase < p["duty"] else {}), None
        elif eff == "sweep":
            for i, f in enumerate(fids):
                phase = (t / p["period_s"] + p["spread"] * i / n) % 1.0
                x = 0.5 - 0.5 * math.cos(2 * math.pi * phase)  # smooth there and back
                (p0, t0), (p1, t1) = p["from"][f], p["to"][f]
                fl = self._fl(look, f)
                fl.pan, fl.tilt = p0 + (p1 - p0) * x, t0 + (t1 - t0) * x
        elif eff == "random_move":
            period = p["period_s"]
            for i, f in enumerate(fids):
                offset = (_seed(p["seed"], f, "offset") % 1000) / 1000 * period if p["stagger"] else 0.0
                slot = math.floor((t + offset) / period)
                first = math.floor(offset / period)
                rng = random.Random(_seed(p["seed"], f, slot))
                fl = self._fl(look, f)
                fl.pan = rng.uniform(*p["pan"])
                fl.tilt = rng.uniform(*p["tilt"])
                # dark for dark_move_s after each new position (not at scene start)
                if p["dark_move_s"] and slot > first and (t + offset) - slot * period < p["dark_move_s"]:
                    dark.add(f)

    def _pixel_chase(self, p: dict, fids: list[str], t: float, look: Look) -> None:
        # one strip made of every fixture's pixels in layer order (bars: 8 each)
        strip: list[tuple[str, int]] = []
        for f in fids:
            px = self.rig.patch.fixtures[f].type.pixels or 1
            strip += [(f, i) for i in range(px)]
        total = len(strip)
        phase = (t / p["period_s"]) % 1.0
        if p["bounce"]:
            head = (1 - abs(1 - 2 * phase)) * (total - 1)  # end to end and back
        else:
            head = phase * total
        width, tail = p["width"], p["tail"]
        values: list[Colour] = []
        for j in range(total):
            d = head - j  # distance behind the head
            if not p["bounce"]:
                d %= total  # wrap round the strip
            if 0 <= d < width:
                values.append(dict(p["colour"]))
            elif tail and width <= d < width + tail:
                f = 1 - (d - width + 1) / (tail + 1)
                values.append(_mix(p["background"], p["colour"], max(0.0, f)))
            else:
                values.append(dict(p["background"]))
        if p["reverse"]:
            values.reverse()
        for f in fids:
            fl = self._fl(look, f)
            mine = [values[j] for j, (ff, _) in enumerate(strip) if ff == f]
            if self.rig.patch.fixtures[f].type.pixels:
                fl.pixels, fl.colour = mine, {}
            else:
                fl.colour, fl.pixels = mine[0], None


def static_source(look: Look) -> Callable[[float], Look]:
    return lambda now: look


__all__ = ["Scene", "Layer", "ScenePlayer", "parse_scene", "load_scenes", "EFFECTS", "EMITTERS"]
