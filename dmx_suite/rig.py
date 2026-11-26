"""Rig configs: which fixtures are present, rule profile, master levels, head limits, haze settings,
nodes, outputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .fixtures import EMITTERS, ConfigError, Kind, Patch
from .profile import V1_DEFAULT, Profile, parse_profile, resolve_exempt
from .tempo import SOURCES, TempoConfig
from .versions import read_doc


@dataclass
class HeadLimit:
    pan: tuple[float, float] = (0.0, 1.0)  # normalised 0-1
    tilt: tuple[float, float] = (0.0, 1.0)

    def clamp(self, axis: str, v: float) -> float:
        lo, hi = self.pan if axis == "pan" else self.tilt
        return min(max(v, lo), hi)


STAGE_X = ("left", "centre", "right")
STAGE_Y = ("front", "middle", "back")
STAGE_Z = ("floor", "low", "mid", "high", "ceiling")


@dataclass
class Point:
    """A named aim point (v3): where each head must point to hit the same spot, per rig config.
    pan/tilt are 0-1 of the head's range (16-bit through fine channels). Not every head needs it."""

    name: str
    heads: dict[str, tuple[float, float]] = field(default_factory=dict)
    description: str = ""
    tags: list[str] = field(default_factory=list)
    stage: dict[str, str] = field(default_factory=dict)  # rough place: x left/centre/right, y, z

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        if self.description:
            d["description"] = self.description
        if self.tags:
            d["tags"] = list(self.tags)
        if self.stage:
            d["stage"] = dict(self.stage)
        d["heads"] = {f: {"pan": round(p, 5), "tilt": round(t, 5)} for f, (p, t) in self.heads.items()}
        return d


SHAPES = ("row", "ring", "grid")  # how a pixel light's pixels are laid out on the layout grid
GRID_MAX = 200  # layout size limit, cells


@dataclass
class Placement:
    """Where a light sits on the layout grid (file format 3). x, y in grid cells from the top
    left, half cells allowed; y runs down the screen with the back of the stage at the top, as in
    a plan. rot in degrees, 0 = facing the audience (down). `shape` lays out a pixel light's
    pixels: a row, a ring, or a grid `cols` wide; single-cell lights ignore it."""

    x: float
    y: float
    rot: float = 0.0
    shape: str = "row"
    cols: int = 0  # grid shape: pixels across (0 = as square as possible)
    z: float | None = None  # v4: height above the stage in metres (kept for Claude; not drawn)
    reverse: bool = False  # v4: pixel light mounted backwards: pixel 1 at the other end

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"x": self.x, "y": self.y, "rot": self.rot}
        if self.shape != "row":
            d["shape"] = self.shape
        if self.shape == "grid" and self.cols:
            d["cols"] = self.cols
        if self.z is not None:
            d["z"] = self.z
        if self.reverse:
            d["reverse"] = True
        return d


@dataclass
class HazeConfig:
    enabled: bool = True
    default_mode: str = "off"  # off | manual | pulse
    level: float = 0.6
    boost_level: float = 1.0
    pulse_on_s: float = 5.0
    pulse_every_s: float = 120.0
    boost_s: float = 0.0  # 0 = while held; >0 = timed per press
    max_on_s: float = 60.0  # safety: longest continuous output
    rest_s: float = 30.0  # forced off time after max_on_s
    boost_cooldown_s: float = 20.0
    auto_off_s: float = 0.0  # manual/pulse revert to off after this (0 = never)


@dataclass
class OscConfig:
    port: int | None = None  # None = OSC input off
    allow: list[str] = field(default_factory=list)  # networks allowed to send; empty = this computer + private


@dataclass
class Rig:
    name: str
    patch: Patch
    present: list[str]  # fixture ids in this rig
    grand_master: float = 1.0
    sub_masters: dict[Kind, float] = field(default_factory=lambda: {k: 1.0 for k in Kind})
    flash_level: float = 1.0
    fade_s: float = 0.3  # grand/sub-master fade time across the full range
    head_limits: dict[str, HeadLimit] = field(default_factory=dict)
    haze: HazeConfig = field(default_factory=HazeConfig)
    kick_colour: dict[str, float] = field(default_factory=lambda: {"red": 1.0, "green": 1.0, "blue": 1.0})
    startup_master: bool = True
    nodes: list[tuple[str, str]] = field(default_factory=list)  # (mac, name)
    outputs: list[dict[str, Any]] = field(default_factory=list)
    midi_inputs: list[str] = field(default_factory=list)  # port-name fragments; empty = every port
    layout: dict[str, Placement] = field(default_factory=dict)  # fixture id -> where it is on the grid
    osc: OscConfig = field(default_factory=OscConfig)
    change_fade_s: float = 0.0  # crossfade when picking a scene, show or look (0 = cut, as v1)
    release_fade_s: float = 0.0  # v3.4: MASTER on / blackout off / Flash FX release fade back in (0 = cut, as v1)
    radio_channel: int | None = None  # 0.05 node radio channel (1-13); None = leave it as it is
    tempo: TempoConfig = field(default_factory=TempoConfig)
    profile: Profile = V1_DEFAULT  # which profile rules apply (rules 1-3)
    exempt: frozenset[str] = frozenset()  # fixture ids MASTER never affects (rule 3)
    points: dict[str, Point] = field(default_factory=dict)  # head position points (v3)
    auto: Any = None  # classify.AutoConfig: class overrides and lights left out of the auto show (v3.3)
    autopilot: dict[str, Any] = field(default_factory=dict)  # autopilot settings over the defaults (v3.4)

    def point_problems(self) -> list[str]:
        """Points with a head outside this rig's head limits (they still clamp at output, rule 8)."""
        out = []
        for pt in self.points.values():
            for fid, (pan, tilt) in pt.heads.items():
                lim = self.limit(fid)
                if not (lim.pan[0] <= pan <= lim.pan[1] and lim.tilt[0] <= tilt <= lim.tilt[1]):
                    out.append(f"point {pt.name}: {fid} is outside its head limits (pan {pan:.0%}, tilt {tilt:.0%}); "
                               f"it's held at the limit (rule 8): re-aim it")
        return out

    @property
    def fixtures(self):
        return [self.patch.fixtures[i] for i in self.present]

    @property
    def universes(self) -> list[int]:
        return sorted({f.universe for f in self.fixtures}) or [0]

    def limit(self, fid: str) -> HeadLimit:
        return self.head_limits.get(fid, HeadLimit())


def _secs(v: Any, what: str, lo: float = 0.0) -> float:
    """Seconds, at least `lo` (haze timers, fade time)."""
    try:
        f = float(v)
    except (TypeError, ValueError) as e:
        raise ConfigError(f"{what} must be a number of seconds, not {v!r}") from e
    if isinstance(v, bool) or f < lo or f != f or f == float("inf"):
        raise ConfigError(f"{what} must be {lo:g} s or more")
    return f


def _pct(v: Any, what: str) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError) as e:
        raise ConfigError(f"{what} must be a number 0-100 %, not {v!r}") from e
    if not 0 <= f <= 100:
        raise ConfigError(f"{what} must be 0-100 %")
    return f / 100


def _range(v: Any, what: str) -> tuple[float, float]:
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        raise ConfigError(f"{what} must be [min, max] in %")
    lo, hi = (_pct(x, what) for x in v)
    if lo > hi:
        raise ConfigError(f"{what}: min above max")
    return (lo, hi)


def parse_rig(data: dict, patch: Patch) -> Rig:
    name = data.get("name", "rig")
    present = patch.resolve(data.get("fixtures", ["all"]))
    profile = parse_profile(data.get("profile"))
    subs = {k: 1.0 for k in Kind}
    for k, v in (data.get("sub_masters") or {}).items():
        try:
            subs[Kind(k)] = _pct(v, f"sub_master {k}")
        except ValueError as e:
            raise ConfigError(f"unknown sub-master {k!r}") from e
    limits = {}
    for fid, lim in (data.get("head_limits") or {}).items():
        if fid not in patch.fixtures:
            raise ConfigError(f"head_limits: unknown fixture {fid!r}")
        if not isinstance(lim, dict):
            raise ConfigError(f"head_limits {fid}: needs pan: [min, max] and/or tilt: [min, max] in %")
        limits[fid] = HeadLimit(
            _range(lim.get("pan", [0, 100]), f"{fid} pan"),
            _range(lim.get("tilt", [0, 100]), f"{fid} tilt"),
        )
    h = data.get("haze") or {}
    if not isinstance(h, dict):
        raise ConfigError("haze: needs settings like level: 60")
    mode = h.get("default_mode", "off")
    if mode is False:  # YAML reads a bare `off` as false
        mode = "off"
    haze = HazeConfig(
        enabled=bool(h.get("enabled", True)),
        default_mode=mode,
        level=_pct(h.get("level", 60), "haze level"),
        boost_level=_pct(h.get("boost_level", 100), "haze boost_level"),
        pulse_on_s=_secs(h.get("pulse_on_s", 5), "haze pulse_on_s", 0.1),
        pulse_every_s=_secs(h.get("pulse_every_s", 120), "haze pulse_every_s", 0.2),
        boost_s=_secs(h.get("boost_s", 0), "haze boost_s"),
        max_on_s=_secs(h.get("max_on_s", 60), "haze max_on_s", 1),
        rest_s=_secs(h.get("rest_s", 30), "haze rest_s"),
        boost_cooldown_s=_secs(h.get("boost_cooldown_s", 20), "haze boost_cooldown_s"),
        auto_off_s=_secs(h.get("auto_off_min", 0), "haze auto_off_min") * 60,
    )
    if haze.default_mode not in ("off", "manual", "pulse"):
        raise ConfigError("haze default_mode must be off, manual or pulse")
    if haze.pulse_on_s >= haze.pulse_every_s:
        raise ConfigError("haze pulse_on_s must be shorter than pulse_every_s")
    kick_data = data.get("kick_colour") or {"red": 100, "green": 100, "blue": 100}
    if not isinstance(kick_data, dict) or set(kick_data) - set(EMITTERS):
        raise ConfigError(f"kick_colour: emitter levels in %, from {', '.join(EMITTERS)}")
    kick = {k: _pct(v, f"kick colour {k}") for k, v in kick_data.items()}
    return Rig(
        name=name,
        patch=patch,
        present=present,
        grand_master=_pct(data.get("grand_master", 100), "grand_master"),
        sub_masters=subs,
        flash_level=_pct(data.get("flash_level", 100), "flash_level"),
        fade_s=_secs(data.get("fade_s", 0.3), "fade_s"),
        head_limits=limits,
        haze=haze,
        kick_colour=kick,
        startup_master=bool((data.get("startup") or {}).get("master", True)),
        nodes=[(n["mac"].upper(), n.get("name", "")) for n in data.get("nodes") or []],
        outputs=list(data.get("outputs") or [{"driver": "null"}]),
        midi_inputs=[str(x) for x in data.get("midi_inputs") or []],
        layout=_layout(data.get("layout"), patch),
        profile=profile,
        exempt=resolve_exempt(profile, patch, present),
        osc=_osc(data.get("osc")),
        change_fade_s=_secs(data.get("change_fade_s", 0), "change_fade_s"),
        release_fade_s=_secs(data.get("release_fade_s", 0), "release_fade_s"),
        radio_channel=_channel(data.get("radio_channel")),
        tempo=_tempo(data.get("tempo")),
        points=parse_points(data.get("positions"), patch),
        auto=_auto(data.get("auto"), patch),
        autopilot=_autopilot(data.get("autopilot")),
    )


def _autopilot(d: Any) -> dict[str, Any]:
    from .autopilot import parse_config

    return parse_config(d)


def _auto(d: Any, patch: Patch) -> Any:
    from .classify import parse_auto

    return parse_auto(d, patch)


def _unit(v: Any, what: str) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError) as e:
        raise ConfigError(f"{what} must be 0-1") from e
    if isinstance(v, bool) or not 0 <= f <= 1:
        raise ConfigError(f"{what} must be 0-1")
    return f


def parse_point(name: str, v: Any, patch: Patch) -> Point:
    import re

    what = f"position {name}"
    if not re.match(r"^[a-z0-9][a-z0-9_-]{0,39}$", str(name)):
        raise ConfigError(f"{what}: names use lower case letters, digits, _ or -")
    if not isinstance(v, dict) or set(v) - {"description", "tags", "stage", "heads"}:
        raise ConfigError(f"{what}: description, tags, stage and heads: {{head: {{pan, tilt}}}}")
    heads: dict[str, tuple[float, float]] = {}
    for fid, pv in (v.get("heads") or {}).items():
        if fid not in patch.fixtures:
            raise ConfigError(f"{what}: unknown fixture {fid!r}")
        t = patch.fixtures[fid].type
        if t.colour_only:
            raise ConfigError(f"{what}: {fid} is colour only (rule 7)")
        if not t.has("pan"):
            raise ConfigError(f"{what}: {fid} has no pan/tilt")
        if not isinstance(pv, dict) or set(pv) != {"pan", "tilt"}:
            raise ConfigError(f"{what} {fid}: needs pan and tilt (0-1)")
        heads[str(fid)] = (_unit(pv["pan"], f"{what} {fid} pan"), _unit(pv["tilt"], f"{what} {fid} tilt"))
    tags = v.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    if not isinstance(tags, list) or not all(isinstance(x, str) and x.strip() for x in tags):
        raise ConfigError(f"{what}: tags is a list of words, e.g. [band, safe]")
    stage = v.get("stage") or {}
    if not isinstance(stage, dict):
        raise ConfigError(f"{what}: stage is {{x, y, z}}")
    for k, allowed in (("x", STAGE_X), ("y", STAGE_Y), ("z", STAGE_Z)):
        if k in stage and stage[k] not in allowed:
            raise ConfigError(f"{what}: stage {k} is one of {', '.join(allowed)}")
    if set(stage) - {"x", "y", "z"}:
        raise ConfigError(f"{what}: stage is {{x, y, z}}")
    return Point(str(name), heads, str(v.get("description") or ""), [str(x).strip() for x in tags],
                 {k: str(x) for k, x in stage.items()})


def parse_points(d: Any, patch: Patch) -> dict[str, Point]:
    if d is None:
        return {}
    if not isinstance(d, dict):
        raise ConfigError("positions: named points, each with heads: {head: {pan, tilt}}")
    return {str(k): parse_point(str(k), v, patch) for k, v in d.items()}


def _channel(v: Any) -> int | None:
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 13:
        raise ConfigError("radio_channel must be 1-13 (the Wi-Fi channel the node and receivers use)")
    return v


def _tempo(d: Any) -> TempoConfig:
    if d is None:
        return TempoConfig()
    if not isinstance(d, dict) or set(d) - {"source", "kick_note", "timeout_s"}:
        raise ConfigError("tempo: source (tap, kick, midi_clock), kick_note, timeout_s")
    src = d.get("source", "tap")
    if src not in SOURCES:
        raise ConfigError(f"tempo source must be one of {', '.join(SOURCES)}")
    try:
        note = int(d.get("kick_note", 36))
    except (TypeError, ValueError) as e:
        raise ConfigError("tempo kick_note must be a MIDI note number") from e
    if not 0 <= note <= 127:
        raise ConfigError("tempo kick_note must be 0-127")
    return TempoConfig(src, note, _secs(d.get("timeout_s", 30), "tempo timeout_s", 1))


def _osc(d: Any) -> OscConfig:
    if d is None or d is False:
        return OscConfig()
    if not isinstance(d, dict):
        raise ConfigError("osc: needs port (and optionally allow: [networks])")
    try:
        port = int(d["port"])
    except (KeyError, TypeError, ValueError) as e:
        raise ConfigError("osc: needs a port number, e.g. port: 9000") from e
    if not 1024 <= port <= 65535:
        raise ConfigError("osc port must be 1024-65535")
    allow = d.get("allow") or []
    if not isinstance(allow, list):
        raise ConfigError("osc allow: a list of addresses or networks, e.g. [192.168.1.0/24]")
    import ipaddress

    for a in allow:
        try:
            ipaddress.ip_network(str(a), strict=False)
        except ValueError as e:
            raise ConfigError(f"osc allow: {a!r} isn't an address or network") from e
    return OscConfig(port, [str(a) for a in allow])


def parse_placement(fid: str, v: Any) -> Placement:
    if not isinstance(v, dict):
        raise ConfigError(f"layout {fid}: needs x and y in grid cells")
    try:
        x, y = float(v["x"]), float(v["y"])
        rot = float(v.get("rot", 0)) % 360
        cols = int(v.get("cols", 0))
        z = None if v.get("z") is None else float(v["z"])
    except (KeyError, TypeError, ValueError) as e:
        raise ConfigError(f"layout {fid}: needs x and y in grid cells (z, if given, in metres)") from e
    bad = set(v) - {"x", "y", "rot", "shape", "cols", "z", "reverse"}
    if bad:
        raise ConfigError(f"layout {fid}: unknown keys {sorted(bad)}; a place is x, y, z, rot, shape, cols, reverse")
    if not isinstance(v.get("reverse", False), bool):
        raise ConfigError(f"layout {fid}: reverse is true or false")
    if z is not None and not -10 <= z <= 50:
        raise ConfigError(f"layout {fid}: z is metres above the stage, -10 to 50")
    shape = v.get("shape", "row")
    if shape not in SHAPES:
        raise ConfigError(f"layout {fid}: shape must be {', '.join(SHAPES)}")
    if not (0 <= x <= GRID_MAX and 0 <= y <= GRID_MAX):
        raise ConfigError(f"layout {fid}: x/y must be 0-{GRID_MAX} cells")
    if not 0 <= cols <= 64:
        raise ConfigError(f"layout {fid}: cols must be 0-64")
    return Placement(_half(x), _half(y), round(rot, 1), shape, cols, z, bool(v.get("reverse", False)))


def _half(n: float) -> float:
    return round(n * 2) / 2


def _layout(d: Any, patch: Patch) -> dict[str, Placement]:
    if d is not None and not isinstance(d, dict):
        raise ConfigError("layout: needs `fixture: {x, y}` lines")
    out = {}
    for fid, v in (d or {}).items():
        if fid not in patch.fixtures:
            raise ConfigError(f"layout: unknown fixture {fid!r}")
        out[fid] = parse_placement(fid, v)
    return out


def load_rig(path: str | Path, patch: Patch) -> Rig:
    return parse_rig(read_doc(path, "rig"), patch)
