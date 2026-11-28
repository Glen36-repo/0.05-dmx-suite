"""FX banks (v3.3): the Move FX, Colour FX, Flash FX and drum-reactive items the Ride page, the
autopilot and the generator pick from. Each item is a registry effect with settings, plus:

    needs   what the rig must have (rig size scaling): heads, colour lights, pixels, layout, lights
    busy    0-1, how much it draws the eye (look quality rules: one leads, the other supports)
    speed   slow / mid / fast, matched to mood
    moods   which of low / mid / high it suits

Items are templates: `$palette` becomes the chosen palette's colours, `$colour` its first colour,
`$colour2` its second, `$period` the period scaled by the ride speed.

compose() turns a pick (move item + colour item + drum item + palette + ride settings) into a
normal scene (layers), checked by parse_scene against every rule like any other scene.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from .classify import AutoRig
from .fixtures import ConfigError

BANKS = ("move", "colour", "flash", "drum")
MOODS = ("low", "mid", "high")


@dataclass
class Item:
    id: str
    bank: str
    label: str
    layer: dict[str, Any]  # template layer (no fixtures)
    needs: dict[str, int] = field(default_factory=dict)  # heads, colour, pixels, lights, layout
    busy: float = 0.5
    speed: str = "mid"  # still | slow | mid | fast
    moods: tuple[str, ...] = MOODS
    targets: str = "colour"  # which lights: colour | pixel | heads | all
    # v8 per-rig settings (fxoverrides.py); the bank items carry the defaults
    priority: int = 3  # 0-5 pick weight, 0 = excluded
    darkness: Any = "follow"  # follow | exempt | 0-1 (Reduced)
    min_s: float | None = None
    max_s: float | None = None
    of: str | None = None  # a variant: the item it copies (shares no-repeat with it)
    overridden: bool = False

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "bank": self.bank, "label": self.label, "needs": self.needs, "busy": self.busy,
                "speed": self.speed, "moods": list(self.moods), "targets": self.targets,
                "effect": self.layer.get("effect"), "priority": self.priority, "darkness": self.darkness,
                "min_s": self.min_s, "max_s": self.max_s, "of": self.of, "overridden": self.overridden}


def _m(id_: str, label: str, pattern: str, busy: float, speed: str, moods: tuple[str, ...], period: float,
       size: float = 0.2, needs: dict[str, int] | None = None, **extra: Any) -> Item:
    return Item(id_, "move", label, {"effect": "move", "pattern": pattern, "period_s": period, "size": size, **extra},
                {"heads": 1, **(needs or {})}, busy, speed, moods, "heads")


def _c(id_: str, label: str, layer: dict[str, Any], busy: float, speed: str, moods: tuple[str, ...],
       needs: dict[str, int] | None = None, targets: str = "colour") -> Item:
    return Item(id_, "colour", label, layer, {"colour": 1, **(needs or {})}, busy, speed, moods, targets)


ITEMS: list[Item] = [
    # ---- Move FX (heads stay inside the head limits; jumps between points are dark)
    _m("pan_sweep", "Pan sweep", "pan_sweep", 0.4, "mid", MOODS, 8, 0.25),
    _m("tilt_sweep", "Tilt sweep", "tilt_sweep", 0.4, "mid", ("mid", "high"), 6, 0.2),
    _m("circle", "Circle", "circle", 0.5, "mid", ("mid", "high"), 6, 0.15),
    _m("figure8", "Figure 8", "figure8", 0.55, "mid", ("mid", "high"), 7, 0.18),
    _m("fan", "Fan out / in", "fan", 0.45, "mid", ("mid", "high"), 6, 0.3, {"heads": 2}),
    _m("swim", "Swim", "swim", 0.3, "slow", ("low", "mid"), 14, 0.15),
    _m("float", "Float", "float", 0.15, "slow", ("low",), 24, 0.12),
    _m("kit", "Centre / kit", "point", 0.05, "still", MOODS, 8, 0.0, tags="band"),
    _m("random_points", "Random positions", "random_points", 0.5, "mid", ("mid", "high"), 6, 0.0, spread=1.0,
       tags="safe"),
    _m("crossfire", "Crossfire", "crossfire", 0.6, "mid", ("mid", "high"), 5, 0.25, {"heads": 2}),
    _m("audience", "Audience sweep", "audience", 0.6, "mid", ("high",), 6, 0.3),
    _m("ballyhoo", "Ballyhoo", "ballyhoo", 0.95, "fast", ("high",), 3, 0.4),
    _m("mirror", "Mirror sweep", "pan_sweep", 0.45, "mid", ("mid", "high"), 7, 0.25, {"heads": 2}, mirror=True),
    # ---- Colour FX
    _c("static", "Static palette", {"effect": "palette", "colours": "$palette"}, 0.05, "still", MOODS),
    _c("rainbow", "Rainbow", {"effect": "rainbow", "period_s": 10, "spread": 1}, 0.5, "mid", ("mid", "high"), {"colour": 2}),
    _c("colour_chase", "Colour chase", {"effect": "colour_chase", "colours": "$palette", "period_s": 4, "spread": 1},
       0.6, "mid", ("mid", "high"), {"colour": 2}),
    _c("chase_in", "Chase in", {"effect": "colour_chase", "colours": "$palette", "period_s": 3, "spread": 1,
                                "direction": "out_centre"}, 0.6, "mid", ("mid", "high"), {"colour": 3}),
    _c("chase_out", "Chase out", {"effect": "colour_chase", "colours": "$palette", "period_s": 3, "spread": 1,
                                  "direction": "centre_out"}, 0.6, "mid", ("mid", "high"), {"colour": 3}),
    _c("carousel", "Carousel", {"effect": "colour_chase", "colours": "$palette", "period_s": 12, "spread": 1, "fade": True},
       0.35, "slow", MOODS, {"colour": 2}),
    _c("sparkle", "Sparkle", {"effect": "sparkle", "colour": "$colour", "background": "$colour2", "density": 0.15,
                              "rate_hz": 8}, 0.7, "fast", ("mid", "high"), {"colour": 2}),
    _c("twinkle", "Twinkle", {"effect": "twinkle", "colour": "$colour", "background": "$colour2", "period_s": 3},
       0.3, "slow", ("low", "mid"), {"colour": 2}),
    _c("colour_fade", "Colour fade", {"effect": "colour_fade", "colours": "$palette", "period_s": 8}, 0.15, "slow",
       ("low", "mid")),
    _c("split", "Split", {"effect": "split", "colours": "$palette", "mode": "sides", "period_s": 4}, 0.3, "mid", MOODS,
       {"colour": 2}),
    _c("wave", "Wave", {"effect": "wave", "colour": "$colour", "background": "$colour2", "period_s": 3}, 0.45, "mid",
       ("mid", "high"), {"colour": 2}),
    _c("pulse", "Pulse", {"effect": "pulse", "colour": "$colour", "period_s": 4}, 0.2, "slow", ("low", "mid")),
    _c("bounce", "Bounce", {"effect": "bounce", "colour": "$colour", "background": "$colour2", "period_s": 2},
       0.55, "mid", ("mid", "high"), {"pixels": 8}, "pixel"),
    _c("comet", "Comet", {"effect": "comet", "colour": "$colour", "background": "$colour2", "period_s": 1.5},
       0.65, "fast", ("mid", "high"), {"pixels": 8}, "pixel"),
    _c("fill", "Fill / unfill", {"effect": "fill", "colour": "$colour", "background": "$colour2", "period_s": 3},
       0.5, "mid", ("mid", "high"), {"pixels": 8}, "pixel"),
    _c("gradient", "Gradient sweep", {"effect": "gradient", "colours": "$palette", "mapping": "spatial"}, 0.35, "slow",
       MOODS, {"colour": 3, "layout": 1}),
    _c("radial", "Radial", {"effect": "radial", "colour": "$colour", "background": "$colour2"}, 0.5, "mid",
       ("mid", "high"), {"colour": 4, "layout": 1}),
    _c("plasma", "Plasma / noise", {"effect": "noise", "colours": "$palette"}, 0.35, "slow", ("low", "mid"),
       {"colour": 4, "layout": 1}),
    _c("bars", "Bars", {"effect": "bars", "colour": "$colour", "background": "$colour2"}, 0.55, "mid", ("mid", "high"),
       {"colour": 4, "layout": 1}),
    _c("dir_wave", "Directional wave", {"effect": "dir_sweep", "colour": "$colour", "background": "$colour2",
                                        "period_s": 2.5, "width": 0.3}, 0.5, "mid", ("mid", "high"), {"colour": 3, "layout": 1}),
    _c("dir_wave_dark", "Directional wave, dark between",
       {"effect": "dir_sweep", "colour": "$colour", "period_s": 3, "width": 0.3, "gap": 0.4}, 0.55, "mid", ("mid", "high"),
       {"colour": 3, "layout": 1}),
    _c("random_flash", "Random flash", {"effect": "random_flash", "colour": "$colour", "rate_hz": 6, "count": 2,
                                        "tail_s": 0.8}, 0.65, "fast", ("mid", "high"), {"colour": 3}),
    _c("fire", "Fire", {"effect": "fire"}, 0.45, "mid", ("mid", "high")),
    _c("lightning", "Lightning", {"effect": "lightning", "colour": "white"}, 0.7, "fast", ("high",)),
    _c("police", "Police", {"effect": "police"}, 0.75, "fast", ("high",), {"colour": 2}),
    # ---- drum-reactive (laid over the colour, MIDI only)
    Item("kick_pump", "drum", "Kick pump", {"effect": "kick_pump", "colour": "$colour", "blend": "max"}, {"colour": 1},
         0.3, "fast", ("mid", "high")),
    Item("snare_hit", "drum", "Snare hit", {"effect": "snare_hit", "colour": "white", "blend": "max"}, {"colour": 1},
         0.3, "fast", ("mid", "high")),
    Item("tom_roll", "drum", "Tom roll", {"effect": "tom_roll", "colour": "$colour", "blend": "max"}, {"colour": 3},
         0.3, "fast", ("mid", "high")),
    Item("cymbal_shimmer", "drum", "Cymbal shimmer", {"effect": "cymbal_shimmer", "colour": "white", "blend": "max"},
         {"colour": 2}, 0.3, "fast", ("mid", "high")),
    Item("fill_build", "drum", "Fill build", {"effect": "fill_build", "colour": "$colour", "blend": "max"}, {"colour": 2},
         0.4, "fast", ("high",)),
    Item("velocity_colour", "drum", "Velocity colour", {"effect": "velocity_colour", "colours": "$palette"}, {"colour": 1},
         0.25, "mid", MOODS),
]
# Flash FX are momentary (flashfx.py); listed here so the Ride page and rig scaling see them too
FLASH_ITEMS: list[Item] = [
    Item(k, "flash", label, {"flash": k}, {"colour": 1} if k not in ("blackout", "freeze") else {}, busy, "fast", MOODS, "all")
    for k, label, busy in (("blinder", "Blinder", 1.0), ("colour_hit", "Colour hit", 0.8), ("strobe", "Strobe", 1.0),
                           ("blackout", "Blackout", 0.6), ("freeze", "Freeze", 0.2), ("flash_decay", "Flash and decay", 0.8))
]
BY_ID: dict[str, Item] = {i.id: i for i in [*ITEMS, *FLASH_ITEMS]}


def lookup(x: str | None) -> Item | None:
    """A bank item by id; a variant id (`fan_v2`, v8) gives its original (same busy, speed and needs) for
    the quality rules when the rig's settings aren't to hand (AutoRig.item has the variant itself)."""
    if not x:
        return None
    if x in BY_ID:
        return BY_ID[x]
    from .fxoverrides import VARIANT_ID

    m = VARIANT_ID.match(x)
    return BY_ID.get(m["of"]) if m else None


def can_run(item: Item, ar: AutoRig) -> bool:
    """Rig size scaling: does this rig have what the item needs?"""
    n = item.needs
    if n.get("heads", 0) > ar.count("head"):
        return False
    if n.get("colour", 0) > len(ar.colour_lights):
        return False
    if n.get("pixels", 0) > ar.pixels:
        return False
    if n.get("layout", 0) and not ar.has_layout:
        return False
    return n.get("lights", 0) <= sum(len(v) for c, v in ar.classes.items() if c != "kick")


def available(ar: AutoRig, bank: str | None = None, mood: str | None = None, *,
              skip_excluded: bool = False) -> list[Item]:
    """What this rig can run; `skip_excluded` also leaves out the types excluded for the autopilot."""
    return [i for i in ar.all_items() if can_run(i, ar) and (bank is None or i.bank == bank)
            and (mood is None or mood in i.moods) and not (skip_excluded and i.id in ar.excluded_fx)]


# ---------------------------------------------------------------------- ride settings and composing


@dataclass
class RideSettings:
    """Live ride controls (Ride page faders): global, and per bank on top."""

    speed: float = 1.0  # x period speed (0.25-4)
    fade: float = 0.5  # 0-1: how soft colour changes are (0 = cut, 1 = long crossfades)
    fan: float = 0.5  # 0-1: spread across the lights
    size: float = 0.5  # 0-1: how big (movement size, pixel width, density)
    shift: float = 0.0  # 0-1: phase offset

    def to_dict(self) -> dict[str, float]:
        return {"speed": self.speed, "fade": self.fade, "fan": self.fan, "size": self.size, "shift": self.shift}

    @staticmethod
    def from_dict(d: dict[str, Any] | None) -> RideSettings:
        r = RideSettings()
        for k, (lo, hi) in RANGES.items():
            if d and k in d:
                setattr(r, k, max(lo, min(hi, float(d[k]))))
        return r


RANGES = {"speed": (0.25, 4.0), "fade": (0.0, 1.0), "fan": (0.0, 1.0), "size": (0.0, 1.0), "shift": (0.0, 1.0)}


def combine(glob: RideSettings, bank: RideSettings | None) -> RideSettings:
    """A bank's own settings ride on top of the global ones (speeds multiply; the rest average
    towards the bank's when it has been moved off the middle)."""
    if bank is None:
        return glob
    return RideSettings(
        speed=max(0.0625, min(16.0, glob.speed * bank.speed)),
        fade=max(0.0, min(1.0, glob.fade + (bank.fade - 0.5))),
        fan=max(0.0, min(1.0, glob.fan + (bank.fan - 0.5))),
        size=max(0.0, min(1.0, glob.size + (bank.size - 0.5))),
        shift=(glob.shift + bank.shift) % 1.0,
    )


def _fill(v: Any, cols: list[Any]) -> Any:
    if v == "$palette":
        return list(cols) if len(cols) > 1 else [cols[0], "off"]
    if v == "$colour":
        return cols[0]
    if v == "$colour2":
        return cols[1] if len(cols) > 1 else "off"
    return v


def _apply_ride(layer: dict[str, Any], item: Item, ride: RideSettings) -> dict[str, Any]:
    out = dict(layer)
    if "period_s" in out:
        out["period_s"] = round(max(0.2, float(out["period_s"]) / ride.speed), 3)
    elif out.get("effect") in ("sparkle", "fire", "police", "random_flash"):
        key = "rate_hz"
        base = float(out.get(key, {"sparkle": 8, "fire": 6, "police": 2, "random_flash": 6}[out["effect"]]))
        out[key] = round(min(25.0, max(0.1, base * ride.speed)), 3)
    if item.bank == "move":
        out["size"] = round(min(0.5, float(out.get("size", 0.2)) * (0.4 + 1.2 * ride.size)), 4)
        if "spread" not in out:
            out["spread"] = round(ride.fan, 3)
    elif out.get("effect") in ("colour_chase", "rainbow", "wave", "colour_fade", "pulse"):
        out["spread"] = round(ride.fan * (4 if out["effect"] in ("rainbow", "wave") else 1), 3)
        if out["effect"] == "colour_chase":
            out["fade"] = bool(out.get("fade")) or ride.fade >= 0.5
    if out.get("effect") == "sparkle":
        out["density"] = round(0.05 + 0.4 * ride.size, 3)
    if out.get("effect") in ("bounce",):
        out["width"] = round(0.05 + 0.3 * ride.size, 3)
    if out.get("effect") == "dir_sweep":  # size: how wide the band
        out["width"] = round(0.1 + 0.6 * ride.size, 3)
    if out.get("effect") == "random_flash":  # fade: how long the tail; size: how big a bit of a bar
        out["tail_s"] = round(0.2 + 1.6 * ride.fade, 3)
        out["bit"] = max(1, round(1 + 7 * ride.size))
    if ride.shift:
        out["shift"] = round(ride.shift, 3)
    return out


FEEL_KEYS = {"ride": "feel", "bank_ride": "bank_feel"}  # v4: the Ride controls are the Autopilot's Feel


def norm_pick(d: Any, what: str = "pick") -> Any:
    """A pick dict with the v4 key names (`feel`, `bank_feel`); the v3 `ride` / `bank_ride` still read."""
    if not isinstance(d, dict):
        return d
    out = dict(d)
    for old, new in FEEL_KEYS.items():
        if old in out:
            if new in out:
                raise ConfigError(f"{what}: give {new} or {old} (the old name), not both")
            out[new] = out.pop(old)
    return out


@dataclass
class Pick:
    """One look on the Ride page / from the autopilot."""

    move: str | None = None
    colour: str | None = "static"
    drum: str | None = None
    palette: str = "warm"
    ride: RideSettings = field(default_factory=RideSettings)
    bank_ride: dict[str, RideSettings] = field(default_factory=dict)  # per bank

    def key(self) -> str:
        return f"{self.move or '-'}|{self.colour or '-'}|{self.drum or '-'}|{self.palette}"

    def to_dict(self) -> dict[str, Any]:
        return {"move": self.move, "colour": self.colour, "drum": self.drum, "palette": self.palette,
                "feel": self.ride.to_dict(), "bank_feel": {k: v.to_dict() for k, v in self.bank_ride.items()}}

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Pick:
        d = norm_pick(d)
        return Pick(d.get("move"), d.get("colour"), d.get("drum"), str(d.get("palette") or "warm"),
                    RideSettings.from_dict(d.get("feel")),
                    {k: RideSettings.from_dict(v) for k, v in (d.get("bank_feel") or {}).items()})


def compose(pick: Pick, ar: AutoRig, palette_colours: list[Any], name: str = "Autopilot") -> dict[str, Any]:
    """Scene data for a pick on this rig: colour across the colour lights, movement on the heads,
    drum layer on top. Items the rig can't run are left out (rig size scaling)."""
    cols = list(palette_colours) or ["white"]
    layers: list[dict[str, Any]] = []
    colour_ids = ar.colour_lights
    ci = ar.item(pick.colour)
    if ci is not None and ci.bank == "colour" and can_run(ci, ar) and colour_ids:
        ride = combine(pick.ride, pick.bank_ride.get("colour"))
        lay = {k: _fill(v, cols) for k, v in copy.deepcopy(ci.layer).items()}
        if ci.targets == "pixel":
            rest = [f for f in colour_ids if f not in ar.classes.get("pixel", [])]
            if rest:  # the other lights hold the palette while the pixels run
                layers.append({"fixtures": rest, "effect": "palette", "colours": _fill("$palette", cols)})
            layers.append({"fixtures": list(ar.classes.get("pixel", [])), **_apply_ride(lay, ci, ride)})
        else:
            layers.append({"fixtures": colour_ids, **_apply_ride(lay, ci, ride)})
    elif colour_ids:
        layers.append({"fixtures": colour_ids, "effect": "palette", "colours": _fill("$palette", cols)})
    kick = ar.classes.get("kick", [])
    if kick:  # v7: the kick light takes the look's colour (its own layer, so the chase spread over the rest
        # is unchanged); MASTER-exempt and Darkness-exempt as before (rule 3, scenes.py), so it stays lit
        if ci is not None and ci.bank == "colour" and ci.targets != "pixel":
            lay = {k: _fill(v, cols) for k, v in copy.deepcopy(ci.layer).items()}
            layers.append({"fixtures": list(kick), **_apply_ride(lay, ci, combine(pick.ride, pick.bank_ride.get("colour")))})
        else:  # nothing to run on one light (pixel items, static): it holds the palette
            layers.append({"fixtures": list(kick), "effect": "palette", "colours": _fill("$palette", cols)})
    for c in ("strobe", "effect"):  # whites and effect lights: follow the first colour
        if ar.classes.get(c):
            layers.append({"fixtures": list(ar.classes[c]), "colour": cols[0] if c == "effect" else "white", "level": 0.6})
    mi = ar.item(pick.move)
    heads = ar.classes.get("head", [])
    if mi is not None and mi.bank == "move" and can_run(mi, ar) and heads:
        ride = combine(pick.ride, pick.bank_ride.get("move"))
        layers.append({"fixtures": list(heads), **_apply_ride(copy.deepcopy(mi.layer), mi, ride)})
    di = ar.item(pick.drum)
    if di is not None and di.bank == "drum" and can_run(di, ar) and colour_ids:
        ride = combine(pick.ride, pick.bank_ride.get("drum"))
        lay = {k: _fill(v, cols) for k, v in copy.deepcopy(di.layer).items()}
        layers.append({"fixtures": colour_ids, **_apply_ride(lay, di, ride)})
    if not layers:
        layers.append({"fixtures": ["all"], "colour": "off"})
    _darkness_shares(layers, ar, pick, ci, mi, di)
    return {"name": name, "layers": layers}


def _darkness_shares(layers: list[dict[str, Any]], ar: AutoRig, pick: Pick, ci: Item | None, mi: Item | None,
                     di: Item | None) -> None:
    """v8 FX settings: Darkness Follow / Exempt / Reduced per item and per palette, as each layer's
    `darkness:` share (left out when everything follows, so looks are exactly as before)."""
    from .fxoverrides import darkness_share, share

    ps = share(ar.palette_darkness.get(pick.palette, "follow"))
    cs = (darkness_share(ci) if ci is not None and ci.bank == "colour" else 1.0) * ps
    ms = darkness_share(mi) if mi is not None and mi.bank == "move" else 1.0
    ds = (darkness_share(di) if di is not None and di.bank == "drum" else 1.0) * ps
    heads = set(ar.classes.get("head", []))
    drum_fx = di.layer.get("effect") if di is not None and di.bank == "drum" else None
    for ly in layers:
        if ly.get("effect") == "move" or "fixtures" not in ly or ly["fixtures"] == ["all"]:
            continue
        sh = ds if drum_fx is not None and ly.get("effect") == drum_fx else cs
        d: dict[str, float] = {}
        if sh != 1.0:
            d["*"] = round(sh, 4)
        if ms != 1.0:  # a Move FX's own setting: its heads' colour
            for f in ly["fixtures"]:
                if f in heads:
                    d[f] = round(sh * ms, 4)
        if d:
            ly["darkness"] = d if set(d) != {"*"} else d["*"]
