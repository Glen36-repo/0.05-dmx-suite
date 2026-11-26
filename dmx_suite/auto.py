"""Auto-show generator: builds a fresh scene for each step from a style, using only the fixtures in
the active rig. Every scene goes through parse_scene, so the hard rules are checked exactly as for
hand-written scenes.

Style (a set's `auto:` block in shows/shows/*.yaml):
    colours: [blue, purple, amber]    palette colours to draw from
    energy: low | mid | high          speed and type of effects
    head_mix: [matching, white, contrast]
    patterns: [all, heads_only, bars_only, kit]   (default depends on energy)
    movement: [random, sweep, static]             (default depends on energy)
    flash: false                      allow the strobe-style flash effect (high energy)
    fades: true                       colour chases fade rather than step
"""

from __future__ import annotations

import colorsys
import random
import zlib
from dataclasses import dataclass, field
from typing import Any

from .fixtures import ConfigError, Kind
from .look import LookError
from .palettes import Palettes
from .rig import Rig
from .scenes import Scene, parse_scene

ENERGIES = ("low", "mid", "high")
HEAD_MIX = ("matching", "white", "contrast")
PATTERNS = ("all", "heads_only", "bars_only", "kit")
MOVEMENTS = ("random", "sweep", "static")

DEFAULT_PATTERNS = {
    "low": {"all": 5, "kit": 3, "bars_only": 2},
    "mid": {"all": 5, "heads_only": 2, "bars_only": 2, "kit": 1},
    "high": {"all": 6, "heads_only": 2, "bars_only": 2},
}
DEFAULT_MOVEMENT = {"low": ("sweep", "static"), "mid": ("random", "sweep"), "high": ("random", "sweep")}


@dataclass
class AutoStyle:
    colours: list[str]
    energy: str = "mid"
    head_mix: list[str] = field(default_factory=lambda: list(HEAD_MIX))
    patterns: list[str] | None = None
    movement: list[str] | None = None
    flash: bool = False
    fades: bool | None = None  # default: fade at low energy, step otherwise


def parse_style(d: dict, pal: Palettes, what: str) -> AutoStyle:
    allowed = {"colours", "energy", "head_mix", "patterns", "movement", "flash", "fades"}
    bad = set(d) - allowed
    if bad:
        raise ConfigError(f"{what}: unknown auto keys {sorted(bad)}")
    cols = d.get("colours") or []
    if not cols:
        raise ConfigError(f"{what}: auto needs colours")
    for c in cols:
        pal.colour(c, what)  # must exist
    st = AutoStyle(colours=list(cols), energy=d.get("energy", "mid"), flash=bool(d.get("flash", False)), fades=d.get("fades"))
    if st.energy not in ENERGIES:
        raise ConfigError(f"{what}: energy must be one of {ENERGIES}")
    for key, options in (("head_mix", HEAD_MIX), ("patterns", PATTERNS), ("movement", MOVEMENTS)):
        if key in d:
            vals = list(d[key])
            bad = set(vals) - set(options)
            if bad or not vals:
                raise ConfigError(f"{what}: {key} must be from {options}")
            setattr(st, key, vals)
    return st


# --------------------------------------------------------------------------- helpers


def _hue(c: dict[str, float]) -> float | None:
    r, g, b = c.get("red", 0), c.get("green", 0), c.get("blue", 0)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    return h if s > 0.15 and v > 0 else None  # whites/greys have no useful hue


def contrast_of(a: str, colours: list[str], pal: Palettes) -> str:
    """Colour in the list furthest round the hue wheel from `a` (white if there isn't one)."""
    ha = _hue(pal.colours[a])
    best, dist = "white", 0.0
    for c in colours:
        hc = _hue(pal.colours[c])
        if c == a or hc is None or ha is None:
            continue
        d = min(abs(ha - hc), 1 - abs(ha - hc))
        if d > dist:
            best, dist = c, d
    return best if dist >= 0.15 else "white"


@dataclass
class RigGroups:
    bars: list[str]
    washes: list[str]
    movers: list[str]
    ukings: list[str]
    kick: list[str]

    @classmethod
    def of(cls, rig: Rig) -> RigGroups:
        # fixtures MASTER doesn't affect (rule 3, e.g. the 0.05 kick light) get the kick treatment;
        # a kick-kind light that isn't exempt (Generic profile) is used like a wash
        ex = rig.exempt
        fx = [f for f in rig.fixtures if f.id not in ex]
        return cls(
            bars=[f.id for f in fx if f.kind == Kind.BAR],
            washes=[f.id for f in fx if f.kind in (Kind.WASH, Kind.KICK)],
            movers=[f.id for f in fx if f.kind == Kind.HEAD and not f.type.colour_only and f.type.has("pan")],
            ukings=[f.id for f in fx if f.kind == Kind.HEAD and (f.type.colour_only or not f.type.has("pan"))],
            kick=[f.id for f in rig.fixtures if f.id in ex],
        )

    @property
    def heads(self) -> list[str]:
        return self.movers + self.ukings


def _kit_ok(pal: Palettes, movers: list[str]) -> bool:
    p = pal.positions.get("drum_kit")
    if not p or not movers:
        return False
    return "*" in p or all(m in p for m in movers)


def _seed(*parts: Any) -> int:
    return zlib.crc32("|".join(map(str, parts)).encode())


# --------------------------------------------------------------------------- generator


def generate(style: AutoStyle, rig: Rig, pal: Palettes, step: int, seed: str = "auto", name: str = "auto") -> Scene:
    rng = random.Random(_seed(seed, step))
    g = RigGroups.of(rig)
    e = style.energy
    fades = style.fades if style.fades is not None else e == "low"

    a = rng.choice(style.colours)
    b = contrast_of(a, style.colours, pal)
    if b == "white" and len(style.colours) > 1:
        b = rng.choice([c for c in style.colours if c != a])

    # pattern: only ones this rig can do
    weights = {k: v for k, v in DEFAULT_PATTERNS[e].items() if style.patterns is None or k in style.patterns}
    if style.patterns:
        weights.update({k: 1 for k in style.patterns if k not in weights})
    if not g.heads:
        weights = {k: v for k, v in weights.items() if k in ("all", "bars_only")}
    if not g.bars and not g.washes:
        weights.pop("bars_only", None)
    if not _kit_ok(pal, g.movers):
        weights.pop("kit", None)
    if not g.bars and not g.heads:
        weights = {"all": 1}
    pattern = rng.choices(list(weights), list(weights.values()))[0] if weights else "all"

    heads_lit = pattern in ("all", "heads_only", "kit")
    bars_lit = pattern in ("all", "bars_only", "kit")

    layers: list[dict[str, Any]] = []

    # bars + washes: the colour "engine" of the look
    bar_chase: dict[str, Any] | None = None
    if g.bars:
        if not bars_lit:
            layers.append({"fixtures": g.bars, "colour": "off"})
        else:
            kinds = {"low": ["static", "fade_chase"], "mid": ["pixel", "chase"], "high": ["pixel", "chase"]}[e]
            if e == "high" and style.flash:
                kinds.append("flash")
            kind = "static" if pattern == "kit" else rng.choice(kinds)
            if kind == "static":
                layers.append({"fixtures": g.bars, "colour": a})
            elif kind == "fade_chase":
                bar_chase = {"effect": "colour_chase", "colours": [a, b], "period_s": round(rng.uniform(8, 16), 1),
                             "spread": 1, "fade": True}
            elif kind == "chase":
                period = round(rng.uniform(2, 4) if e == "mid" else rng.uniform(0.5, 1.2), 2)
                bar_chase = {"effect": "colour_chase", "colours": [a, b], "period_s": period, "spread": 1, "fade": fades}
            elif kind == "pixel":
                period = round(rng.uniform(2, 4) if e == "mid" else rng.uniform(0.6, 1.5), 2)
                layers.append({"fixtures": g.bars, "effect": "pixel_chase", "colour": a,
                               "background": b if e == "high" else "off", "width": rng.choice([2, 3, 4]), "tail": 2,
                               "period_s": period, "bounce": rng.random() < 0.3})
            else:  # flash
                layers.append({"fixtures": g.bars, "effect": "flash", "colour": "white", "rate_hz": rng.choice([4, 6, 8]),
                               "duty": 0.3, "spread": rng.choice([0, 0.25, 1])})
            if bar_chase:
                layers.append({"fixtures": g.bars, **bar_chase})
    if g.washes:
        if not bars_lit:
            layers.append({"fixtures": g.washes, "colour": "off"})
        elif e == "high" and rng.random() < 0.5:
            layers.append({"fixtures": g.washes, "effect": "colour_chase", "colours": [a, b], "period_s": 1, "spread": 1})
        else:
            layers.append({"fixtures": g.washes, "colour": a})

    # heads: colour mix, synced with the bars' chase when there is one
    if g.heads:
        if not heads_lit:
            layers.append({"fixtures": g.heads, "colour": "off"})
        else:
            mix = rng.choice(style.head_mix)
            if mix == "matching" and bar_chase:
                layers.append({"fixtures": g.heads, **bar_chase})  # same colours, period, start: in sync
            else:
                col = {"matching": a, "white": "white", "contrast": b}[mix]
                layers.append({"fixtures": g.heads, "colour": col})

    # movement (movers only; U'Kings are colour only)
    if g.movers:
        if pattern == "kit":
            layers.append({"fixtures": g.movers, "position": "drum_kit", "speed": 0.5})
        else:
            moves = style.movement or list(DEFAULT_MOVEMENT[e])
            mv = rng.choice(moves)
            if mv == "random":
                period = round(rng.uniform(6, 10) if e != "high" else rng.uniform(2.5, 4), 1)
                layers.append({"fixtures": g.movers, "effect": "random_move", "period_s": period, "tilt": [0.15, 0.85],
                               "dark_move_s": 1.0 if e != "high" else 0.5, "seed": f"{seed}-{step}"})
            elif mv == "sweep":
                ends = [p for p in ("audience_l", "audience_r", "ceiling", "centre") if p in pal.positions]
                if len(ends) >= 2:
                    frm, to = rng.sample(ends, 2)
                    period = round({"low": rng.uniform(20, 40), "mid": rng.uniform(6, 12), "high": rng.uniform(2, 4)}[e], 1)
                    layers.append({"fixtures": g.movers, "effect": "sweep", "from": frm, "to": to, "period_s": period,
                                   "spread": 1, "speed": 0.2 if e == "low" else 0.8})
                elif _kit_ok(pal, g.movers):
                    layers.append({"fixtures": g.movers, "position": "drum_kit"})
            else:  # static
                pos = "drum_kit" if _kit_ok(pal, g.movers) else ("centre" if "centre" in pal.positions else None)
                if pos:
                    layers.append({"fixtures": g.movers, "position": pos, "speed": 0.3})

    # kick light: bright most of the time, sometimes follows the show colour
    if g.kick:
        layers.append({"fixtures": g.kick, "colour": a if rng.random() < 0.3 else "white"})

    if not layers:
        raise LookError("auto show: nothing in this rig to light")
    label = f"{name} {e} #{step + 1} ({pattern})"
    return parse_scene({"name": label, "show_colour": a, "layers": layers}, rig.patch, pal, label)
