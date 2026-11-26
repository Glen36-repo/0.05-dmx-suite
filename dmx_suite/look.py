"""What the show layer asks for. A Look never carries the haze channel (rule 5) or a raw dimmer
channel. It can carry an `intensity` (0-1), which only rigs whose profile doesn't use MASTER on/off
accept (rule 1, see profile.py); under "0.05 band" MASTER owns on/off and scenes are colour only.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .fixtures import EMITTERS, ConfigError, Patch

Colour = dict[str, float]  # emitter role -> 0..1

FORBIDDEN = {"dimmer": "scenes never set the dimmer channel; use intensity, and only where the rig's "
                       "profile doesn't make MASTER own on/off (rule 1)",
             "haze": "haze is only set by the Haze controls (rule 5)"}
INTENSITY_RULE1 = "sets intensity, but MASTER owns on/off under this rig's profile (rule 1)"


class LookError(ConfigError):
    pass


@dataclass
class FixtureLook:
    colour: Colour = field(default_factory=dict)  # whole-fixture colour; empty = off
    pixels: list[Colour] | None = None  # per-pixel colours (bars)
    colour_wheel: int | None = None  # DMX value
    gobo: int | None = None
    pan: float | None = None  # 0..1, None = hold position
    tilt: float | None = None
    speed: float | None = None  # 0..1, 1 = fastest
    strobe: int | None = None
    intensity: float | None = None  # 0..1; only under profiles without MASTER on/off (rule 1)
    zoom: float | None = None  # 0..1 (R7 beam controls)
    focus: float | None = None
    frost: float | None = None
    prism: int | None = None  # DMX value

    def is_on(self) -> bool:
        if any(v > 0 for v in self.colour.values()):
            return True
        if self.pixels and any(v > 0 for px in self.pixels for v in px.values()):
            return True
        return self.colour_wheel is not None and not self.colour


@dataclass
class Look:
    fixtures: dict[str, FixtureLook] = field(default_factory=dict)
    show_colour: Colour = field(default_factory=lambda: {"red": 1.0, "green": 1.0, "blue": 1.0})

    @property
    def uses_intensity(self) -> bool:
        return any(fl.intensity is not None for fl in self.fixtures.values())


def _unit(v: Any, what: str) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError) as e:
        raise LookError(f"{what} must be a number 0-1, not {v!r}") from e
    if isinstance(v, bool) or not 0 <= f <= 1:
        raise LookError(f"{what} must be 0-1")
    return f


def dmx_value(v: Any, what: str) -> int:
    """A raw DMX value (wheel slot, gobo, strobe): whole number 0-255. Checked at load, because a
    bad one would otherwise only fail when the frame is written, mid-show."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != int(v) or not 0 <= v <= 255:
        raise LookError(f"{what} must be a DMX value: a whole number 0-255, not {v!r}")
    return int(v)


def parse_colour(v: Any, what: str) -> Colour:
    """[r, g, b], '#rrggbb', or {red: .., white: ..} (0-1)."""
    if isinstance(v, str):
        s = v.lstrip("#")
        if len(s) != 6:
            raise LookError(f"{what}: colour {v!r} not #rrggbb")
        return {k: int(s[i : i + 2], 16) / 255 for k, i in (("red", 0), ("green", 2), ("blue", 4))}
    if isinstance(v, (list, tuple)):
        if len(v) != 3:
            raise LookError(f"{what}: colour list must be [r, g, b]")
        return {k: _unit(x, what) for k, x in zip(("red", "green", "blue"), v)}
    if isinstance(v, dict):
        bad = set(v) - set(EMITTERS)
        if bad:
            raise LookError(f"{what}: unknown colour channels {sorted(bad)}")
        return {k: _unit(x, what) for k, x in v.items()}
    raise LookError(f"{what}: bad colour {v!r}")


def parse_fixture_look(d: dict, what: str) -> FixtureLook:
    for k in d:
        if k in FORBIDDEN:
            raise LookError(f"{what}: {FORBIDDEN[k]}")
    allowed = {"colour", "pixels", "colour_wheel", "gobo", "pan", "tilt", "speed", "strobe", "intensity",
               "zoom", "focus", "frost", "prism"}
    bad = set(d) - allowed
    if bad:
        raise LookError(f"{what}: unknown keys {sorted(bad)}")
    return FixtureLook(
        colour=parse_colour(d["colour"], what) if "colour" in d else {},
        pixels=[parse_colour(p, f"{what} pixel {i + 1}") for i, p in enumerate(d["pixels"])] if "pixels" in d else None,
        colour_wheel=_slot(d["colour_wheel"], f"{what} colour_wheel") if "colour_wheel" in d else None,
        gobo=_slot(d["gobo"], f"{what} gobo") if "gobo" in d else None,
        pan=_unit(d["pan"], f"{what} pan") if "pan" in d else None,
        tilt=_unit(d["tilt"], f"{what} tilt") if "tilt" in d else None,
        speed=_unit(d["speed"], f"{what} speed") if "speed" in d else None,
        strobe=dmx_value(d["strobe"], f"{what} strobe") if "strobe" in d else None,
        intensity=_unit(d["intensity"], f"{what} intensity") if "intensity" in d else None,
        zoom=_unit(d["zoom"], f"{what} zoom") if "zoom" in d else None,
        focus=_unit(d["focus"], f"{what} focus") if "focus" in d else None,
        frost=_unit(d["frost"], f"{what} frost") if "frost" in d else None,
        prism=dmx_value(d["prism"], f"{what} prism") if "prism" in d else None,
    )


def _slot(v: Any, what: str) -> Any:
    """A wheel or gobo slot: DMX value, or a name the fixture type gives (resolved per fixture)."""
    return v if isinstance(v, str) and v else dmx_value(v, what)


def parse_look(data: dict, patch: Patch) -> Look:
    """`fixtures:` keys may be fixture ids or group names."""
    for k in data:
        if k in FORBIDDEN:
            raise LookError(FORBIDDEN[k])
    look = Look()
    if "show_colour" in data:
        look.show_colour = parse_colour(data["show_colour"], "show_colour")
    fixtures = data.get("fixtures") or {}
    if not isinstance(fixtures, dict):
        raise LookError("fixtures: needs `fixture or group: {colour: ..}` lines")
    for key, d in fixtures.items():
        if d is not None and not isinstance(d, dict):
            raise LookError(f"{key}: needs settings like {{colour: blue}}, not {d!r}")
        fl = parse_fixture_look(d or {}, key)
        named = {r: getattr(fl, r) for r in ("colour_wheel", "gobo") if isinstance(getattr(fl, r), str)}
        found = dict.fromkeys(named, False)
        for fid in patch.resolve([key]):
            fx = patch.fixtures[fid]
            if fx.type.colour_only and (fl.pan is not None or fl.tilt is not None):
                raise LookError(f"{key}: {fx.type.name} is colour only, no pan/tilt (rule 7)")
            mine = fl
            if named:  # slot names become each fixture's own DMX value
                mine = replace(fl)
                for role, name in named.items():
                    v = fx.type.wheel_value(name) if role == "colour_wheel" else fx.type.gobo_value(name)
                    setattr(mine, role, v)
                    found[role] = found[role] or v is not None
            look.fixtures[fid] = mine
        for role, ok in found.items():
            if not ok:
                raise LookError(f"{key}: no fixture there has a {role.replace('_', ' ')} slot named {named[role]!r}")
    return look


def load_look(path: str | Path, patch: Patch) -> Look:
    from .versions import read_doc

    return parse_look(read_doc(path, "look"), patch)
