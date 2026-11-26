"""Busking: a page of buttons and faders laid out by the user, for playing the lights by hand on
top of whatever show is running. Saved in shows/panels.yaml:

    panels:
      band:                          # shown while the band show plays (else `default`)
        name: Band busk
        release_fade_s: 0.5          # how long a released override takes to fade back to the show
        widgets:
          - {id: red, type: colour, label: All red, fixtures: [all], colour: red, mode: latch}
          - {id: wht, type: flash, label: White hit, fixtures: [bars], colour: white}
          - {id: solo_heads, type: solo, label: Heads only, fixtures: [heads]}
          - {id: rainbow, type: effect, label: Rainbow, scene: rainbow_bars}
          - {id: chorus, type: go, label: Chorus, show: band, set: high}
          - {id: spd, type: fader, label: Speed, target: speed}
          - {id: hz, type: haze, label: Haze boost, action: boost}

Widget types: colour (latch on/off, or `mode: flash` while held), flash (while held), solo
(while held: everything else dark), effect (latch a scene's layers over the show), go (pick a
scene, or a show and set), fader (grand, sub:<kind>, flash_level or speed), haze (off, manual,
pulse, boost). Every widget can be mapped to MIDI or OSC (action `busk`, panel + widget).

Overrides sit above the show and below the rule layer, so the rules still hold: colour only
(MASTER owns on/off under the 0.05 band profile), lights not lit stay fully off, and solo leaves
lights that MASTER doesn't touch (the kick light) alone unless they're in the solo.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from .fade import mix_looks
from .fixtures import ConfigError, Kind, Patch
from .look import Colour, FixtureLook, Look
from .palettes import Palettes

TYPES = ("colour", "flash", "solo", "effect", "go", "fader", "haze")
HAZE = ("off", "manual", "pulse", "boost")
ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


@dataclass
class Widget:
    id: str
    type: str
    label: str
    fixtures: list[str] = field(default_factory=list)  # resolved ids
    names: list[str] = field(default_factory=list)  # as written (groups kept)
    colour: Colour | None = None
    mode: str = "latch"  # colour: latch | flash
    scene: str | None = None
    show: str | None = None
    set: str | None = None
    target: str | None = None  # fader
    action: str | None = None  # haze


@dataclass
class Panel:
    key: str
    name: str
    widgets: list[Widget]
    release_fade_s: float = 0.5

    def widget(self, wid: str) -> Widget:
        for w in self.widgets:
            if w.id == wid:
                return w
        raise ConfigError(f"panel {self.key} has no widget {wid!r}")


def parse_panels(data: dict[str, Any], patch: Patch, pal: Palettes, scenes: dict[str, Any],
                 shows: dict[str, Any]) -> dict[str, Panel]:
    out: dict[str, Panel] = {}
    panels = data.get("panels") or {}
    if not isinstance(panels, dict):
        raise ConfigError("panels: needs `name: {widgets: [...]}` entries")
    for key, pd in panels.items():
        what = f"panel {key}"
        if not isinstance(pd, dict):
            raise ConfigError(f"{what}: needs widgets")
        bad = set(pd) - {"name", "widgets", "release_fade_s"}
        if bad:
            raise ConfigError(f"{what}: unknown keys {sorted(bad)}")
        widgets: list[Widget] = []
        for i, wd in enumerate(pd.get("widgets") or []):
            w = _widget(wd, patch, pal, scenes, shows, f"{what} widget {i + 1}")
            if any(x.id == w.id for x in widgets):
                raise ConfigError(f"{what}: two widgets called {w.id}")
            widgets.append(w)
        try:
            fade = float(pd.get("release_fade_s", 0.5))
        except (TypeError, ValueError) as e:
            raise ConfigError(f"{what}: release_fade_s must be seconds") from e
        if not 0 <= fade <= 30:
            raise ConfigError(f"{what}: release_fade_s must be 0-30")
        out[str(key)] = Panel(str(key), str(pd.get("name", key)), widgets, fade)
    return out


def _widget(d: Any, patch: Patch, pal: Palettes, scenes: dict[str, Any], shows: dict[str, Any], what: str) -> Widget:
    if not isinstance(d, dict):
        raise ConfigError(f"{what}: needs id and type")
    allowed = {"id", "type", "label", "fixtures", "colour", "mode", "scene", "show", "set", "target", "action"}
    bad = set(d) - allowed
    if bad:
        raise ConfigError(f"{what}: unknown keys {sorted(bad)}")
    wid, typ = str(d.get("id", "")), d.get("type")
    if not ID.match(wid):
        raise ConfigError(f"{what}: id must be letters, digits, _ or -")
    if typ not in TYPES:
        raise ConfigError(f"{what}: type must be one of {', '.join(TYPES)}")
    w = Widget(wid, typ, str(d.get("label", wid)))
    if typ in ("colour", "flash", "solo"):
        names = d.get("fixtures") or []
        names = names if isinstance(names, list) else [names]
        if not names:
            raise ConfigError(f"{what}: needs fixtures")
        w.names, w.fixtures = [str(n) for n in names], patch.resolve([str(n) for n in names])
    if typ in ("colour", "flash"):
        w.colour = pal.colour(d.get("colour", "white"), what)
        w.mode = "flash" if typ == "flash" else d.get("mode", "latch")
        if w.mode not in ("latch", "flash"):
            raise ConfigError(f"{what}: mode must be latch or flash")
    elif typ == "effect":
        if d.get("scene") not in scenes:
            raise ConfigError(f"{what}: unknown scene {d.get('scene')!r}")
        w.scene = d["scene"]
    elif typ == "go":
        if "scene" in d:
            if d["scene"] not in scenes:
                raise ConfigError(f"{what}: unknown scene {d['scene']!r}")
            w.scene = d["scene"]
        elif "show" in d:
            if d["show"] not in shows:
                raise ConfigError(f"{what}: unknown show {d['show']!r}")
            w.show, w.set = d["show"], d.get("set")
            if w.set is not None and w.set not in shows[w.show].sets:
                raise ConfigError(f"{what}: show {w.show} has no set {w.set!r}")
        else:
            raise ConfigError(f"{what}: go needs a scene or a show")
    elif typ == "fader":
        t = str(d.get("target", ""))
        kinds = {f"sub:{k.value}" for k in Kind}
        if t not in {"grand", "flash_level", "speed", "step_speed", "step_fade"} | kinds:
            raise ConfigError(f"{what}: target must be grand, flash_level, speed, step_speed, step_fade or sub:<kind>")
        w.target = t
    elif typ == "haze":
        if d.get("action") not in HAZE:
            raise ConfigError(f"{what}: action must be one of {', '.join(HAZE)}")
        w.action = d["action"]
    return w


# --------------------------------------------------------------------------- overrides on the look


@dataclass
class Override:
    key: str  # panel/widget
    kind: str  # colour | solo | effect
    fixtures: frozenset[str] = frozenset()
    colour: Colour | None = None
    source: Callable[[float], Look] | None = None  # effect: a scene player
    keep: frozenset[str] = frozenset()  # solo: lights it never darkens (MASTER-exempt)
    released_at: float | None = None
    fade_s: float = 0.0
    fn: Callable[[Look, float], Look] | None = None  # kind "fn": Flash FX, laid over the look (v3.3)


def apply(look: Look, overrides: list[Override], now: float) -> Look:
    """The look with these overrides laid over it, in order."""
    if not overrides:
        return look
    fixtures = dict(look.fixtures)
    for o in overrides:
        if o.kind == "colour" and o.colour is not None:
            for fid in o.fixtures:
                base = fixtures.get(fid, FixtureLook())
                fixtures[fid] = replace(base, colour=dict(o.colour), pixels=None)
        elif o.kind == "solo":
            for fid, fl in list(fixtures.items()):
                if fid not in o.fixtures and fid not in o.keep:
                    fixtures[fid] = replace(fl, colour={}, pixels=None)
        elif o.kind == "effect" and o.source is not None:
            fixtures.update(o.source(now).fixtures)
        elif o.kind == "fn" and o.fn is not None:
            fixtures = dict(o.fn(Look(fixtures=fixtures, show_colour=look.show_colour), now).fixtures)
    return Look(fixtures=fixtures, show_colour=look.show_colour)


def apply_with_releases(look: Look, overrides: list[Override], now: float) -> tuple[Look, list[Override]]:
    """Lay the held overrides over the look; released ones fade out over their fade time.
    Returns the look and the overrides still in play (finished releases dropped)."""
    live = [o for o in overrides if o.released_at is None or now - o.released_at < o.fade_s
            or (o.kind == "fn" and now < o.released_at)]  # a timed Flash FX: still on until its end
    held = [o for o in live if o.released_at is None or now < o.released_at]
    fading = [o for o in live if o.released_at is not None and now >= o.released_at]
    with_held = apply(look, held, now)
    if not fading:
        return with_held, live
    progress = min((now - o.released_at) / o.fade_s for o in fading if o.released_at is not None)
    return mix_looks(apply(look, live, now), with_held, progress), live
