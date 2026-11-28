"""Auto classification (v3.3): every light sorted by what it can do, for the FX banks, the Ride
page, the autopilot and the generator. New lights join the moment they're patched; a rig change
needs no reprogramming.

Classes:
    head    moving head (pan/tilt, not colour-only)
    wash    a single colour (pars, washes, colour-only heads)
    pixel   several colour cells (LED bars)
    strobe  white-only or a strobe/blinder with no colour mixing
    effect  colour wheel or gobo but no colour mixing and no movement (effect lights, derbies)
    kick    a light MASTER doesn't touch (rule 3, e.g. the kick-drum light): takes the look's colour (v7), never a move/drum/flash

Haze machines are never part of the auto show (rule 5).

Override per rig config (`auto:` in the rig file):
    auto:
      classes: {uk_a: head, wash_3: strobe}     # the class to treat a light as
      exclude: [smoke_2, wash_4]                # leave out of the auto show
      exclude_fx: [static, police]              # FX types the autopilot never picks (still playable by hand)
      exclude_palettes: [ice]                   # v7: palettes it never picks (a tap still plays one)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .fixtures import ConfigError, Fixture, Kind, Patch

CLASSES = ("head", "wash", "pixel", "strobe", "effect", "kick")
RGB = {"red", "green", "blue"}


def natural_class(fx: Fixture) -> str | None:
    """What a light is by its channels alone (None = haze: never in the auto show)."""
    t = fx.type
    if fx.kind == Kind.HAZE or t.has("haze"):
        return None
    if t.has("pan") and t.has("tilt") and not t.colour_only:
        return "head"
    em = t.emitters
    if t.pixels:
        return "pixel"
    if em and not (em & RGB) and ("white" in em or t.has("strobe")):
        return "strobe"
    if not (em & RGB) and (t.has("colour_wheel") or t.has("gobo")):
        return "effect"
    return "wash"


@dataclass
class AutoConfig:
    classes: dict[str, str] = field(default_factory=dict)  # fixture id -> class (override)
    exclude: list[str] = field(default_factory=list)
    exclude_fx: list[str] = field(default_factory=list)  # FX bank item ids the autopilot leaves out
    exclude_palettes: list[str] = field(default_factory=list)  # v7: palettes the autopilot never picks

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        if self.classes:
            d["classes"] = dict(self.classes)
        if self.exclude:
            d["exclude"] = list(self.exclude)
        if self.exclude_fx:
            d["exclude_fx"] = list(self.exclude_fx)
        if self.exclude_palettes:
            d["exclude_palettes"] = list(self.exclude_palettes)
        return d


def parse_auto(d: Any, patch: Patch) -> AutoConfig:
    if d is None:
        return AutoConfig()
    if not isinstance(d, dict) or set(d) - {"classes", "exclude", "exclude_fx", "exclude_palettes"}:
        raise ConfigError("auto: classes {light: class}, exclude [lights], exclude_fx [FX types] and "
                          "exclude_palettes [palettes]")
    classes = d.get("classes") or {}
    if not isinstance(classes, dict):
        raise ConfigError("auto classes: {light: class}")
    for fid, c in classes.items():
        if fid not in patch.fixtures:
            raise ConfigError(f"auto classes: unknown fixture {fid!r}")
        if c not in CLASSES[:-1]:
            raise ConfigError(f"auto classes {fid}: one of {', '.join(CLASSES[:-1])}")
        fx = patch.fixtures[fid]
        if c == "head" and (not fx.type.has("pan") or fx.type.colour_only):
            raise ConfigError(f"auto classes {fid}: can't move, so it can't be a head (rule 7)")
        if c == "pixel" and not fx.type.pixels:
            raise ConfigError(f"auto classes {fid}: has no pixels")
        if natural_class(fx) is None:
            raise ConfigError(f"auto classes {fid}: haze is never part of the auto show (rule 5)")
    excl = d.get("exclude") or []
    if not isinstance(excl, list):
        raise ConfigError("auto exclude: a list of lights")
    for fid in excl:
        if fid not in patch.fixtures:
            raise ConfigError(f"auto exclude: unknown fixture {fid!r}")
    xfx = d.get("exclude_fx") or []
    if not isinstance(xfx, list):
        raise ConfigError("auto exclude_fx: a list of FX types")
    from .fxbanks import BY_ID  # fxbanks imports this module

    for k in xfx:
        item = BY_ID.get(str(k))
        if item is None:
            raise ConfigError(f"auto exclude_fx: unknown FX type {k!r}")
        if item.bank == "flash":
            raise ConfigError(f"auto exclude_fx: {k} is a Flash FX (played by hand, never by the autopilot)")
    xpal = d.get("exclude_palettes") or []  # v7; a palette deleted later is just ignored
    if not isinstance(xpal, list) or not all(isinstance(x, str) and x for x in xpal):
        raise ConfigError("auto exclude_palettes: a list of palette names")
    return AutoConfig({str(k): str(v) for k, v in classes.items()}, [str(x) for x in excl],
                      list(dict.fromkeys(str(x) for x in xfx)), list(dict.fromkeys(xpal)))


@dataclass
class AutoRig:
    """The rig as the auto show sees it."""

    classes: dict[str, list[str]]  # class -> fixture ids, in patch order
    of: dict[str, str]  # fixture id -> class
    excluded: list[str]
    left: list[str]  # by where they are on the layout (split looks)
    right: list[str]
    pixels: int = 0  # pixel cells across the pixel lights
    has_layout: bool = False
    excluded_fx: frozenset[str] = frozenset()  # FX types the autopilot leaves out (auto: exclude_fx)
    excluded_palettes: frozenset[str] = frozenset()  # v7: auto: exclude_palettes

    def ids(self, *classes: str) -> list[str]:
        out: list[str] = []
        for c in classes:
            out += self.classes.get(c, [])
        return out

    @property
    def colour_lights(self) -> list[str]:
        """Everything the colour bank paints (heads too: they carry the look's colour)."""
        return self.ids("wash", "pixel", "head")

    def count(self, c: str) -> int:
        return len(self.classes.get(c, []))

    def summary(self) -> dict[str, Any]:
        return {"classes": {c: list(v) for c, v in self.classes.items() if v}, "excluded": self.excluded,
                "pixels": self.pixels, "left": self.left, "right": self.right, "excluded_fx": sorted(self.excluded_fx),
                "excluded_palettes": sorted(self.excluded_palettes)}


def auto_rig(rig: Any) -> AutoRig:
    from .layout import full_layout

    cfg: AutoConfig = getattr(rig, "auto", None) or AutoConfig()
    classes: dict[str, list[str]] = {c: [] for c in CLASSES}
    of: dict[str, str] = {}
    excluded = []
    for fx in rig.fixtures:
        nat = natural_class(fx)
        if nat is None:
            continue  # haze
        if fx.id in cfg.exclude:
            excluded.append(fx.id)
            continue
        c = "kick" if fx.id in rig.exempt else cfg.classes.get(fx.id, nat)
        classes[c].append(fx.id)
        of[fx.id] = c
    layout = full_layout(rig)
    placed = [f for f in of if f in layout and of[f] != "kick"]
    xs = {f: layout[f].x for f in placed}
    mid = (min(xs.values()) + max(xs.values())) / 2 if xs else 0.0
    left = [f for f in placed if xs[f] < mid] or [f for i, f in enumerate(placed) if i % 2 == 0]
    right = [f for f in placed if f not in left]
    pixels = sum(rig.patch.fixtures[f].type.pixels for f in classes["pixel"])
    # full_layout always places every light
    return AutoRig(classes, of, excluded, left, right, pixels, True, frozenset(cfg.exclude_fx),
                   frozenset(cfg.exclude_palettes))
