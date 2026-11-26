"""Rig configs: which fixtures are present, rule profile, master levels, head limits, haze settings,
nodes, outputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .fixtures import ConfigError, Kind, Patch
from .profile import V1_DEFAULT, Profile, parse_profile, resolve_exempt

STROBE_DEFAULT_HZ = 3.0  # common photosensitive-epilepsy guidance: no more than 3 flashes a second
STROBE_MAX_HZ = 25.0


@dataclass
class HeadLimit:
    pan: tuple[float, float] = (0.0, 1.0)  # normalised 0-1
    tilt: tuple[float, float] = (0.0, 1.0)

    def clamp(self, axis: str, v: float) -> float:
        lo, hi = self.pan if axis == "pan" else self.tilt
        return min(max(v, lo), hi)


@dataclass
class Placement:
    """Where a fixture sits on the stage plan. x from stage left (as the audience sees it),
    y from the front edge, metres; rot in degrees (0 = facing the audience)."""

    x: float
    y: float
    rot: float = 0.0


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
    stage: tuple[float, float] = (6.0, 4.0)  # width, depth in metres (stage plan)
    layout: dict[str, "Placement"] = field(default_factory=dict)  # fixture id -> where it is
    profile: Profile = V1_DEFAULT  # which profile rules apply (rules 1-3)
    exempt: frozenset[str] = frozenset()  # fixture ids MASTER never affects (rule 3)
    strobe_limit_hz: float | None = STROBE_DEFAULT_HZ  # safety rule; None only in tests

    @property
    def fixtures(self):
        return [self.patch.fixtures[i] for i in self.present]

    @property
    def universes(self) -> list[int]:
        return sorted({f.universe for f in self.fixtures}) or [0]

    def limit(self, fid: str) -> HeadLimit:
        return self.head_limits.get(fid, HeadLimit())


def _pct(v: Any, what: str) -> float:
    f = float(v)
    if not 0 <= f <= 100:
        raise ConfigError(f"{what} must be 0-100 %")
    return f / 100


def _range(v: Any, what: str) -> tuple[float, float]:
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
        limits[fid] = HeadLimit(
            _range(lim.get("pan", [0, 100]), f"{fid} pan"),
            _range(lim.get("tilt", [0, 100]), f"{fid} tilt"),
        )
    h = data.get("haze") or {}
    mode = h.get("default_mode", "off")
    if mode is False:  # YAML reads a bare `off` as false
        mode = "off"
    haze = HazeConfig(
        enabled=bool(h.get("enabled", True)),
        default_mode=mode,
        level=_pct(h.get("level", 60), "haze level"),
        boost_level=_pct(h.get("boost_level", 100), "haze boost_level"),
        pulse_on_s=float(h.get("pulse_on_s", 5)),
        pulse_every_s=float(h.get("pulse_every_s", 120)),
        boost_s=float(h.get("boost_s", 0)),
        max_on_s=float(h.get("max_on_s", 60)),
        rest_s=float(h.get("rest_s", 30)),
        boost_cooldown_s=float(h.get("boost_cooldown_s", 20)),
        auto_off_s=float(h.get("auto_off_min", 0)) * 60,
    )
    if haze.default_mode not in ("off", "manual", "pulse"):
        raise ConfigError("haze default_mode must be off, manual or pulse")
    if haze.pulse_on_s >= haze.pulse_every_s:
        raise ConfigError("haze pulse_on_s must be shorter than pulse_every_s")
    kick = {k: _pct(v, f"kick colour {k}") for k, v in (data.get("kick_colour") or {"red": 100, "green": 100, "blue": 100}).items()}
    return Rig(
        name=name,
        patch=patch,
        present=present,
        grand_master=_pct(data.get("grand_master", 100), "grand_master"),
        sub_masters=subs,
        flash_level=_pct(data.get("flash_level", 100), "flash_level"),
        fade_s=float(data.get("fade_s", 0.3)),
        head_limits=limits,
        haze=haze,
        kick_colour=kick,
        startup_master=bool((data.get("startup") or {}).get("master", True)),
        nodes=[(n["mac"].upper(), n.get("name", "")) for n in data.get("nodes") or []],
        outputs=list(data.get("outputs") or [{"driver": "null"}]),
        midi_inputs=[str(x) for x in data.get("midi_inputs") or []],
        stage=_stage(data.get("stage")),
        layout=_layout(data.get("layout"), patch),
        profile=profile,
        exempt=resolve_exempt(profile, patch, present),
        strobe_limit_hz=_strobe_limit(data.get("strobe_limit_hz", STROBE_DEFAULT_HZ)),
    )


def _strobe_limit(v: Any) -> float:
    try:
        hz = float(v)
    except (TypeError, ValueError) as e:
        raise ConfigError("strobe_limit_hz must be a number of flashes per second") from e
    if not 0.5 <= hz <= STROBE_MAX_HZ:
        raise ConfigError(f"strobe_limit_hz must be 0.5-{STROBE_MAX_HZ:g} (it can't be turned off)")
    return hz


def _stage(d: Any) -> tuple[float, float]:
    if d is None:
        return (6.0, 4.0)
    try:
        w, dep = float(d["width"]), float(d["depth"])
    except (KeyError, TypeError, ValueError) as e:
        raise ConfigError("stage needs width and depth in metres") from e
    if not (1 <= w <= 50 and 1 <= dep <= 50):
        raise ConfigError("stage width and depth must be 1-50 m")
    return (w, dep)


def _layout(d: Any, patch: Patch) -> dict[str, Placement]:
    out = {}
    for fid, v in (d or {}).items():
        if fid not in patch.fixtures:
            raise ConfigError(f"layout: unknown fixture {fid!r}")
        try:
            p = Placement(float(v["x"]), float(v["y"]), float(v.get("rot", 0)) % 360)
        except (KeyError, TypeError, ValueError) as e:
            raise ConfigError(f"layout {fid}: needs x and y in metres") from e
        if not (-5 <= p.x <= 55 and -5 <= p.y <= 55):
            raise ConfigError(f"layout {fid}: x/y out of range")
        out[fid] = p
    return out


def load_rig(path: str | Path, patch: Patch) -> Rig:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return parse_rig(data, patch)
