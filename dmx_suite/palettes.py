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
    # v3: named colour sets (palette editor): name -> {name, tags, colours: [colour names or values]}
    sets: dict[str, dict[str, Any]] = field(default_factory=dict)
    point_info: dict[str, dict[str, Any]] = field(default_factory=dict)  # head points: description, tags, stage
    warnings: set[str] = field(default_factory=set)  # e.g. a point a head doesn't have

    def with_points(self, points: dict[str, Any], also: dict[str, Any] | None = None) -> Palettes:
        """These palettes with a rig's head points laid over the (legacy) palette positions.
        `also`: other rigs' points, so a scene naming a point only another rig has still loads
        (the heads it doesn't cover stay where they are, with a warning)."""
        out = Palettes(dict(self.colours), {k: dict(v) for k, v in self.positions.items()}, self.gobos, self.sets,
                       dict(self.point_info))
        for src in (also or {}, points):
            for name, pt in src.items():
                if src is also and name in points:
                    continue
                out.positions[name] = dict(pt.heads) if src is points else {}
                out.point_info[name] = {"description": pt.description, "tags": list(pt.tags), "stage": dict(pt.stage)}
        return out

    def colour(self, v: Any, what: str) -> Colour:
        if isinstance(v, str) and not v.startswith("#"):
            if v not in self.colours:
                raise LookError(f"{what}: unknown colour {v!r} (palette has {', '.join(sorted(self.colours))})")
            return dict(self.colours[v])
        return parse_colour(v, what)

    def position(self, v: Any, fid: str, what: str) -> Position | None:
        """A head's pan/tilt for a named point (or a {pan, tilt} given directly). None when the
        point has no entry for this head: it stays where it is, and a warning is noted (v3)."""
        if isinstance(v, str):
            if v not in self.positions:
                raise LookError(f"{what}: unknown position {v!r}")
            p = self.positions[v]
            if fid in p:
                return p[fid]
            if "*" in p:
                return p["*"]
            self.warnings.add(f"{what}: point {v!r} isn't set for {fid}; it stays where it is")
            return None
        return _pos(v, what)

    def positions_for(self, v: Any, fids: list[str], what: str) -> dict[str, Position]:
        """{head: (pan, tilt)} for the heads the point covers."""
        out = {}
        for f in fids:
            p = self.position(v, f, what)
            if p is not None:
                out[f] = p
        return out

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
    from .versions import read_doc

    return parse_palettes(read_doc(path, "palettes"), patch)
