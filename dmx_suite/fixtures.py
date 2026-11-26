"""Fixture types (channel maps) and the patch (where each fixture sits). Loaded from shows/fixtures.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

DMX_CHANNELS = 512
MAX_UNIVERSE = 15


class ConfigError(ValueError):
    pass


class Kind(str, Enum):
    """Fixture category. Also the sub-master each fixture follows."""

    HEAD = "head"
    BAR = "bar"
    WASH = "wash"
    KICK = "kick"
    HAZE = "haze"


EMITTERS = ("red", "green", "blue", "white", "amber", "uv")
ROLES = frozenset(
    EMITTERS
    + (
        "dimmer",
        "pan",
        "pan_fine",
        "tilt",
        "tilt_fine",
        "pt_speed",
        "colour_wheel",
        "gobo",
        "strobe",
        "haze",
        "fixed",
    )
)


@dataclass(frozen=True)
class Channel:
    offset: int  # 0-based within the fixture
    role: str
    default: int = 0  # value when nothing drives it (e.g. strobe open, mode channels)
    pixel: int | None = None  # for per-pixel emitters
    invert: bool = False  # pt_speed: DMX 0 = fastest


@dataclass
class FixtureType:
    key: str
    name: str
    kind: Kind
    channels: list[Channel]
    colour_only: bool = False  # U'King heads: never move
    home: dict[str, float] = field(default_factory=lambda: {"pan": 0.5, "tilt": 0.5})
    verified: bool = False  # channel map checked against the real fixture / Daslight patch
    pan_range: float = 540.0  # degrees, for the stage plan's beam lines
    tilt_range: float = 270.0

    @property
    def footprint(self) -> int:
        return len(self.channels)

    @property
    def has_dimmer(self) -> bool:
        return any(c.role == "dimmer" for c in self.channels)

    @property
    def pixels(self) -> int:
        px = [c.pixel for c in self.channels if c.pixel is not None]
        return max(px) + 1 if px else 0

    @property
    def emitters(self) -> set[str]:
        return {c.role for c in self.channels if c.role in EMITTERS}

    def has(self, role: str) -> bool:
        return any(c.role == role for c in self.channels)


@dataclass
class Fixture:
    id: str
    type: FixtureType
    universe: int
    address: int  # 1-based
    groups: list[str] = field(default_factory=list)

    @property
    def kind(self) -> Kind:
        return self.type.kind

    def slot(self, ch: Channel) -> int:
        """0-based index into the universe frame."""
        return self.address - 1 + ch.offset


@dataclass
class Patch:
    types: dict[str, FixtureType]
    fixtures: dict[str, Fixture]

    def groups(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for f in self.fixtures.values():
            for g in f.groups:
                out.setdefault(g, []).append(f.id)
        return out

    def resolve(self, names: list[str]) -> list[str]:
        """Fixture ids from a list of ids and/or group names (and 'all')."""
        groups = self.groups()
        out: list[str] = []
        for n in names:
            if n == "all":
                ids = list(self.fixtures)
            elif n in self.fixtures:
                ids = [n]
            elif n in groups:
                ids = groups[n]
            else:
                raise ConfigError(f"unknown fixture or group {n!r}")
            out += [i for i in ids if i not in out]
        return out


# --------------------------------------------------------------------------- loading


def _channel(offset: int, spec: Any, type_key: str) -> Channel:
    if isinstance(spec, str):
        spec = {"role": spec}
    if not isinstance(spec, dict) or "role" not in spec:
        raise ConfigError(f"{type_key}: channel {offset + 1} needs a role")
    role = spec["role"]
    if role not in ROLES:
        raise ConfigError(f"{type_key}: channel {offset + 1} unknown role {role!r}")
    default = int(spec.get("default", 0))
    if not 0 <= default <= 255:
        raise ConfigError(f"{type_key}: channel {offset + 1} default out of range")
    pixel = spec.get("pixel")
    if pixel is not None and role not in EMITTERS:
        raise ConfigError(f"{type_key}: only colour channels can have a pixel number")
    return Channel(offset, role, default, pixel, bool(spec.get("invert", False)))


def _type(key: str, d: dict) -> FixtureType:
    try:
        kind = Kind(d["kind"])
    except (KeyError, ValueError) as e:
        raise ConfigError(f"{key}: kind must be one of {[k.value for k in Kind]}") from e
    chans = [_channel(i, c, key) for i, c in enumerate(d.get("channels", []))]
    if not chans:
        raise ConfigError(f"{key}: no channels")
    t = FixtureType(
        key=key,
        name=d.get("name", key),
        kind=kind,
        channels=chans,
        colour_only=bool(d.get("colour_only", False)),
        home={"pan": 0.5, "tilt": 0.5, **d.get("home", {})},
        verified=bool(d.get("verified", False)),
        pan_range=float(d.get("pan_range", 540)),
        tilt_range=float(d.get("tilt_range", 270)),
    )
    if kind == Kind.HAZE and not t.has("haze"):
        raise ConfigError(f"{key}: haze fixture needs a haze channel")
    if kind != Kind.HAZE and t.has("haze"):
        raise ConfigError(f"{key}: only haze fixtures may have a haze channel")
    return t


def load_patch(path: str | Path) -> Patch:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return parse_patch(data)


def parse_patch(data: dict) -> Patch:
    types = {k: _type(k, v) for k, v in (data.get("types") or {}).items()}
    fixtures: dict[str, Fixture] = {}
    used: dict[tuple[int, int], str] = {}
    for d in data.get("fixtures") or []:
        fid = d.get("id")
        if not fid or fid in fixtures:
            raise ConfigError(f"fixture id missing or duplicated: {fid!r}")
        if d.get("type") not in types:
            raise ConfigError(f"{fid}: unknown type {d.get('type')!r}")
        t = types[d["type"]]
        uni, addr = int(d.get("universe", 0)), int(d["address"])
        if not 0 <= uni <= MAX_UNIVERSE:
            raise ConfigError(f"{fid}: universe must be 0-{MAX_UNIVERSE}")
        if addr < 1 or addr + t.footprint - 1 > DMX_CHANNELS:
            raise ConfigError(f"{fid}: address {addr} + {t.footprint} channels doesn't fit in 512")
        for s in range(addr, addr + t.footprint):
            if (uni, s) in used:
                raise ConfigError(f"{fid}: channel {s} overlaps {used[(uni, s)]}")
            used[(uni, s)] = fid
        fixtures[fid] = Fixture(fid, t, uni, addr, list(d.get("groups", [])))
    return Patch(types, fixtures)
