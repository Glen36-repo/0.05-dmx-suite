"""Fixture types (channel maps) and the patch (where each fixture sits). Loaded from shows/fixtures.yaml.

A type lists its channels in order, each with a role. From v2 R7 a type can also have:
- `colour_mix: auto` (new types) or `off` (types from before R7, so shows look the same): with
  auto, a colour is mixed for what the fixture has: white (and amber) taken out of RGB, a
  white-only or dimmer-only light at the colour's brightness, a colour-wheel-only light on the
  nearest named wheel slot.
- `wheel: {name: value or {value, colour}}` and `gobos: {name: value}`: named slots, so scenes can
  say `colour_wheel: red` or `gobo: dots`.
- `sub: wash` (or on a patched fixture): which sub-master it follows, if not the one for its kind.
- a `<role>_fine` channel after dimmer, pan, tilt, zoom or focus for 16-bit; `invert: true` on
  pan, tilt, zoom, focus, frost or pt_speed.
- zoom, focus, frost (0-1) and prism (DMX value) channels.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

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
FINE = ("dimmer", "pan", "tilt", "zoom", "focus")  # roles that can have a `<role>_fine` channel
INVERTIBLE = ("pan", "tilt", "zoom", "focus", "frost", "pt_speed")
ROLES = frozenset(
    EMITTERS
    + (
        "dimmer",
        "pan",
        "tilt",
        "pt_speed",
        "colour_wheel",
        "gobo",
        "strobe",
        "haze",
        "fixed",
        "zoom",
        "focus",
        "frost",
        "prism",
    )
    + tuple(f"{r}_fine" for r in FINE)
)
MIX = ("auto", "off")
SUBS = ("head", "bar", "wash", "kick")  # sub-masters (haze never has one)


@dataclass(frozen=True)
class Channel:
    offset: int  # 0-based within the fixture
    role: str
    default: int = 0  # value when nothing drives it (e.g. strobe open, mode channels)
    pixel: int | None = None  # for per-pixel emitters
    invert: bool = False  # pt_speed: DMX 0 = fastest; pan/tilt/zoom/focus/frost: run the other way


@dataclass(frozen=True)
class WheelSlot:
    value: int  # DMX value
    colour: dict[str, float] | None = None  # what it looks like (for picking the nearest slot)


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
    colour_mix: str = "auto"  # auto: mix colours for this fixture's emitters; off: as given (pre-R7)
    wheel: dict[str, WheelSlot] = field(default_factory=dict)  # named colour wheel slots
    gobos: dict[str, int] = field(default_factory=dict)  # named gobo slots
    sub: Kind | None = None  # sub-master to follow (None: the one for its kind)

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

    def invert(self, role: str) -> bool:
        return any(c.role == role and c.invert for c in self.channels)

    def wheel_value(self, v: int | str) -> int | None:
        """A wheel slot by DMX value or name (None: this fixture has no such slot)."""
        if isinstance(v, str):
            s = self.wheel.get(v)
            return s.value if s else None
        return v

    def gobo_value(self, v: int | str) -> int | None:
        return self.gobos.get(v) if isinstance(v, str) else v


@dataclass
class Fixture:
    id: str
    type: FixtureType
    universe: int
    address: int  # 1-based
    groups: list[str] = field(default_factory=list)
    sub_master: Kind | None = None  # overrides the type's

    @property
    def kind(self) -> Kind:
        return self.type.kind

    @property
    def sub(self) -> Kind:
        """The sub-master this fixture follows."""
        return self.sub_master or self.type.sub or self.type.kind

    def slot(self, ch: Channel) -> int:
        """0-based index into the universe frame."""
        return self.address - 1 + ch.offset




def parse_pixels(spec: str, n: int, where: str) -> frozenset[int]:
    """`px3`, `px1-4`, `px1,8`, `px1-2,7-8`, `odd`, `even`, `first3`, `last3` -> 0-based pixel indexes
    of a light with n pixels (numbers on screen and in files start at 1)."""
    s = spec.strip().lower()
    if s in ("odd", "even"):
        return frozenset(range(0 if s == "odd" else 1, n, 2))
    m = re.fullmatch(r"(first|last)(\d+)", s)
    if m:
        k = int(m.group(2))
        if not 1 <= k <= n:
            raise ConfigError(f"{where}: {s} - the light has {n} pixels")
        return frozenset(range(k)) if m.group(1) == "first" else frozenset(range(n - k, n))
    if not s.startswith("px"):
        raise ConfigError(f"{where}: pixels are px3, px1-4, px1,8, odd, even, first3 or last3 (not {spec!r})")
    out: set[int] = set()
    for part in s[2:].split(","):
        a, _, b = part.partition("-")
        try:
            lo, hi = int(a), int(b or a)
        except ValueError as e:
            raise ConfigError(f"{where}: pixels are numbers, e.g. px1-4 or px1,8 (not {spec!r})") from e
        if lo > hi or lo < 1 or hi > n:
            raise ConfigError(f"{where}: pixel {hi if hi > n else lo} - the light has pixels 1-{n}")
        out |= set(range(lo - 1, hi))
    return frozenset(out)


@dataclass
class Patch:
    types: dict[str, FixtureType]
    fixtures: dict[str, Fixture]
    pixel_groups: dict[str, dict[str, frozenset[int]]] = field(default_factory=dict)  # v4: name -> {fid: pixels}

    def resolve_targets(self, names: list[str]) -> dict[str, frozenset[int] | None]:
        """Fixture ids, each with the pixels selected (None = the whole light), from ids, groups, `all`,
        saved pixel groups and pixel selectors: `bar_1:px3`, `bar_1:px1-4`, `bars:px1,8`, `bars:odd`.
        A light named both whole and by pixels is whole; two pixel selections on one light add up."""
        groups = self.groups()
        out: dict[str, frozenset[int] | None] = {}

        def add(fid: str, px: frozenset[int] | None) -> None:
            if fid not in out:
                out[fid] = px
                return
            had = out[fid]
            out[fid] = None if had is None or px is None else had | px

        for raw in names:
            name, _, spec = str(raw).partition(":")
            if name in self.pixel_groups and not spec:
                for fid, px in self.pixel_groups[name].items():
                    add(fid, px)
                continue
            if name == "all":
                ids = list(self.fixtures)
            elif name in self.fixtures:
                ids = [name]
            elif name in groups:
                ids = groups[name]
            else:
                raise ConfigError(f"unknown fixture or group {name!r}")
            if not spec:
                for fid in ids:
                    add(fid, None)
                continue
            pixel_ids = [f for f in ids if self.fixtures[f].type.pixels > 1]
            if not pixel_ids:
                raise ConfigError(f"{raw}: {name} has no pixel lights; pixel selections are for bars")
            for fid in pixel_ids:
                add(fid, parse_pixels(spec, self.fixtures[fid].type.pixels, str(raw)))
        return out

    def groups(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for f in self.fixtures.values():
            for g in f.groups:
                out.setdefault(g, []).append(f.id)
        return out

    def resolve(self, names: list[str]) -> list[str]:
        """Fixture ids from a list of ids and/or group names (and 'all'). Pixel selectors and pixel
        groups name their lights whole here; layers keep the pixels (resolve_targets)."""
        return list(self.resolve_targets(names))


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
    invert = bool(spec.get("invert", False))
    if invert and role not in INVERTIBLE:
        raise ConfigError(f"{type_key}: channel {offset + 1} ({role}) can't be inverted; only {', '.join(INVERTIBLE)}")
    return Channel(offset, role, default, pixel, invert)


def _rgb(v: Any, what: str) -> dict[str, float]:
    """A slot colour: '#rrggbb' or [r, g, b] 0-1."""
    if isinstance(v, str) and len(v.lstrip("#")) == 6:
        s = v.lstrip("#")
        try:
            return {k: int(s[i:i + 2], 16) / 255 for k, i in (("red", 0), ("green", 2), ("blue", 4))}
        except ValueError:
            pass
    if isinstance(v, (list, tuple)) and len(v) == 3 and all(isinstance(x, (int, float)) and 0 <= x <= 1 for x in v):
        return dict(zip(("red", "green", "blue"), map(float, v), strict=True))
    raise ConfigError(f"{what}: colour must be #rrggbb or [r, g, b] 0-1, not {v!r}")


def _dmx(v: Any, what: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 255:
        raise ConfigError(f"{what}: DMX value must be a whole number 0-255, not {v!r}")
    return v


def _sub(v: Any, what: str) -> Kind | None:
    if v is None:
        return None
    if v not in SUBS:
        raise ConfigError(f"{what}: sub must be one of {', '.join(SUBS)}")
    return Kind(v)


def _slots(key: str, d: dict) -> tuple[dict[str, WheelSlot], dict[str, int]]:
    wheel: dict[str, WheelSlot] = {}
    raw = d.get("wheel") or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{key}: wheel needs `name: value` lines")
    for name, v in raw.items():
        what = f"{key} wheel {name}"
        if isinstance(v, dict):
            wheel[str(name)] = WheelSlot(_dmx(v.get("value"), what), _rgb(v["colour"], what) if "colour" in v else None)
        else:
            wheel[str(name)] = WheelSlot(_dmx(v, what))
    raw = d.get("gobos") or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{key}: gobos needs `name: value` lines")
    gobos = {str(n): _dmx(v, f"{key} gobo {n}") for n, v in raw.items()}
    return wheel, gobos


def _type(key: str, d: dict) -> FixtureType:
    try:
        kind = Kind(d["kind"])
    except (KeyError, ValueError) as e:
        raise ConfigError(f"{key}: kind must be one of {[k.value for k in Kind]}") from e
    chans = [_channel(i, c, key) for i, c in enumerate(d.get("channels", []))]
    if not chans:
        raise ConfigError(f"{key}: no channels")
    roles = {c.role for c in chans}
    for r in FINE:
        if f"{r}_fine" in roles and r not in roles:
            raise ConfigError(f"{key}: {r}_fine needs a {r} channel too")
    mix = d.get("colour_mix", "auto")
    if mix not in MIX:
        raise ConfigError(f"{key}: colour_mix must be auto or off")
    wheel, gobos = _slots(key, d)
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
        colour_mix=mix,
        wheel=wheel,
        gobos=gobos,
        sub=_sub(d.get("sub"), key),
    )
    if kind == Kind.HAZE and not t.has("haze"):
        raise ConfigError(f"{key}: haze fixture needs a haze channel")
    if kind != Kind.HAZE and t.has("haze"):
        raise ConfigError(f"{key}: only haze fixtures may have a haze channel")
    return t


def load_patch(path: str | Path) -> Patch:
    from .versions import read_doc

    data = read_doc(path, "fixtures")
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
        fixtures[fid] = Fixture(fid, t, uni, addr, list(d.get("groups", [])), _sub(d.get("sub"), fid))
    patch = Patch(types, fixtures)
    pg = data.get("pixel_groups") or {}
    if not isinstance(pg, dict):
        raise ConfigError("pixel_groups: {name: selector or [selectors]}, e.g. bar_tips: bars:px1,8")
    for name, sel in pg.items():
        if name in fixtures or name in patch.groups() or name == "all":
            raise ConfigError(f"pixel group {name!r}: that name is already a fixture or group")
        sels = sel if isinstance(sel, list) else [sel]
        if not sels or not all(isinstance(x, str) and ":" in x for x in sels):
            raise ConfigError(f"pixel group {name}: selectors like bars:px1,8 or bar_1:px1-4")
        got = patch.resolve_targets(sels)
        patch.pixel_groups[name] = {f: px for f, px in got.items() if px is not None}
    return patch
