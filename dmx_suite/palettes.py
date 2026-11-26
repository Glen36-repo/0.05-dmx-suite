"""Palettes: named colours, positions and gobos (shows/palettes.yaml).

    colours:
      blue: "#0040ff"
      warm: {red: 1.0, green: 0.55, white: 0.4}
    positions:
      drum_kit:                    # per head, since each head sees the kit from a different spot
        mh_a: {pan: 0.42, tilt: 0.30}
        mh_b: {pan: 0.58, tilt: 0.30}
      centre: {pan: 0.5, tilt: 0.5}  # same for every head
    gobos:
      open: 0
      dots: 40                      # DMX value; or per fixture type: {mhl36: 40, other_type: 25}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .fixtures import ConfigError, Patch
from .look import Colour, LookError, parse_colour

BUILTIN_COLOURS: dict[str, Colour] = {
    "off": {},
    "black": {},
    "white": {"red": 1.0, "green": 1.0, "blue": 1.0, "white": 1.0},
}

Position = tuple[float, float]


@dataclass
class Palettes:
    colours: dict[str, Colour] = field(default_factory=lambda: dict(BUILTIN_COLOURS))
    positions: dict[str, dict[str, Position]] = field(default_factory=dict)  # name -> {fid or "*": (pan, tilt)}
    gobos: dict[str, dict[str, int]] = field(default_factory=dict)  # name -> {type key or "*": value}

    def colour(self, v: Any, what: str) -> Colour:
        if isinstance(v, str) and not v.startswith("#"):
            if v not in self.colours:
                raise LookError(f"{what}: unknown colour {v!r} (palette has {', '.join(sorted(self.colours))})")
            return dict(self.colours[v])
        return parse_colour(v, what)

    def position(self, v: Any, fid: str, what: str) -> Position:
        if isinstance(v, str):
            if v not in self.positions:
                raise LookError(f"{what}: unknown position {v!r}")
            p = self.positions[v]
            if fid in p:
                return p[fid]
            if "*" in p:
                return p["*"]
            raise LookError(f"{what}: position {v!r} has no entry for {fid}")
        return _pos(v, what)

    def gobo(self, v: Any, type_key: str, what: str) -> int:
        if isinstance(v, int):
            return _dmx(v, what)
        if v not in self.gobos:
            raise LookError(f"{what}: unknown gobo {v!r}")
        g = self.gobos[v]
        if type_key in g:
            return g[type_key]
        if "*" in g:
            return g["*"]
        raise LookError(f"{what}: gobo {v!r} has no value for fixture type {type_key}")


def _unit(v: Any, what: str) -> float:
    f = float(v)
    if not 0 <= f <= 1:
        raise LookError(f"{what} must be 0-1")
    return f


def _pos(v: Any, what: str) -> Position:
    if not isinstance(v, dict) or set(v) != {"pan", "tilt"}:
        raise LookError(f"{what}: position needs pan and tilt (0-1)")
    return (_unit(v["pan"], f"{what} pan"), _unit(v["tilt"], f"{what} tilt"))


def _dmx(v: Any, what: str) -> int:
    i = int(v)
    if not 0 <= i <= 255:
        raise LookError(f"{what}: DMX value 0-255")
    return i


def parse_palettes(data: dict, patch: Patch) -> Palettes:
    p = Palettes()
    for name, v in (data.get("colours") or {}).items():
        p.colours[name] = parse_colour(v, f"colour {name}")
    for name, v in (data.get("positions") or {}).items():
        if isinstance(v, dict) and set(v) == {"pan", "tilt"}:
            p.positions[name] = {"*": _pos(v, f"position {name}")}
        elif isinstance(v, dict):
            entries = {}
            for fid, pv in v.items():
                if fid not in patch.fixtures:
                    raise ConfigError(f"position {name}: unknown fixture {fid!r}")
                if patch.fixtures[fid].type.colour_only:
                    raise ConfigError(f"position {name}: {fid} is colour only (rule 7)")
                entries[fid] = _pos(pv, f"position {name} {fid}")
            p.positions[name] = entries
        else:
            raise ConfigError(f"position {name}: needs pan/tilt or per-fixture entries")
    for name, v in (data.get("gobos") or {}).items():
        if isinstance(v, int):
            p.gobos[name] = {"*": _dmx(v, f"gobo {name}")}
        elif isinstance(v, dict):
            for tk in v:
                if tk not in patch.types:
                    raise ConfigError(f"gobo {name}: unknown fixture type {tk!r}")
            p.gobos[name] = {tk: _dmx(x, f"gobo {name}") for tk, x in v.items()}
        else:
            raise ConfigError(f"gobo {name}: DMX value or per-type values")
    return p


def load_palettes(path: str | Path, patch: Patch) -> Palettes:
    path = Path(path)
    if not path.exists():
        return Palettes()
    return parse_palettes(yaml.safe_load(path.read_text(encoding="utf-8")) or {}, patch)
