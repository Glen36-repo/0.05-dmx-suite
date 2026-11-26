"""Scenes: layers (colour + effect + movement + beam) applied to fixture groups, played as a Look
every frame. Everything is time-based (period_s), so the same scene runs at any frame rate.

    name: Blue kit
    show_colour: blue                     # drum flashes use this (palette name or colour)
    length_s: 8                           # one cycle (shows repeat scenes by it; default: longest period)
    layers:
      - {fixtures: [bars], effect: pixel_chase, colour: blue, background: off, width: 3, period_s: 2}
      - {fixtures: [washes], colour: blue}
      - {fixtures: [movers], effect: colour_chase, colours: [blue, white], period_s: 4, spread: 0.5}
      - {fixtures: [movers], position: drum_kit, gobo: dots}
      - {fixtures: [all], effect: linear_wave, colour: white, angle: 45, level: 0.6, blend: max}

Effects come from the registry (effects/); each lists its own settings. Every effect that runs
across several lights also takes `mapping` (order | spatial), `direction`, `angle` and `groups_of`.
`period_s` is one full cycle; `spread` is how much of a cycle lies across the layer's lights.

Layers apply in order. `blend` says how a layer's colour meets what's under it: replace (default),
max or add; `level` (0-1) is how strongly. `mute: true` skips a layer. Static settings (colour,
position, gobo, ...) can sit alongside an effect, except a position with a movement effect.
No layer can set haze (rule 5) or move a colour-only head (rule 7). A layer may set `intensity`
(0-1) only where the rig's profile doesn't make MASTER own on/off (rule 1, see profile.py).
Fixtures missing from the active rig are skipped, or moved to the layer's `fallback` group.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import effects
from .effects import BLENDS, ParseCtx, Run, Unit, place_units
from .effects.base import num as _num_any
from .fixtures import EMITTERS, ConfigError, Patch
from .layout import cell_positions, full_layout
from .look import FORBIDDEN, Colour, FixtureLook, Look, LookError
from .palettes import Palettes
from .rig import Rig
from .tempo import BEAT_S
from .versions import read_doc

# effect name -> its setting keys, and the effects that move heads (for older callers)
EFFECTS = {name: e.keys() for name, e in effects.REGISTRY.items()}
MOVEMENT = {name for name, e in effects.REGISTRY.items() if e.movement}
STATIC_KEYS = {"colour", "pixels", "position", "gobo", "colour_wheel", "speed", "strobe"}
COMMON = {"fixtures", "effect", "name", "fallback", "intensity", "level", "blend", "mute", "beats"}


# --------------------------------------------------------------------------- model


@dataclass
class Layer:
    fixtures: list[str]  # resolved ids (whole patch; filtered to the rig when played)
    effect: str | None
    params: dict[str, Any]
    name: str = ""
    fallback: list[str] = field(default_factory=list)  # used when none of `fixtures` is in the rig
    level: float = 1.0  # how strongly this layer's colour counts (0-1)
    blend: str = "replace"  # replace | max | add
    mute: bool = False

    def period(self) -> float | None:
        e = effects.get(self.effect) if self.effect else None
        return e.period(self.params) if e else None


@dataclass
class Scene:
    name: str
    layers: list[Layer]
    show_colour: Colour = field(default_factory=lambda: {"red": 1.0, "green": 1.0, "blue": 1.0})
    length_s: float | None = None  # one cycle, if set in the file

    @property
    def uses_intensity(self) -> bool:
        return any("intensity" in ly.params for ly in self.layers)

    @property
    def length(self) -> float | None:
        """Seconds for one cycle: `length_s`, else the longest effect period (None if nothing moves)."""
        if self.length_s:
            return self.length_s
        periods = [p for ly in self.layers if not ly.mute and (p := ly.period())]
        return max(periods) if periods else None


# --------------------------------------------------------------------------- parsing / validation


def _forbid(d: dict, what: str) -> None:
    for k in d:
        if k in FORBIDDEN:
            raise LookError(f"{what}: {FORBIDDEN[k]}")


def _num(v: Any, what: str, lo: float, hi: float | None = None) -> float:
    return _num_any(v, what, lo, hi)


def parse_layer(d: dict, patch: Patch, pal: Palettes, what: str) -> Layer:
    _forbid(d, what)
    if "fixtures" not in d:
        raise LookError(f"{what}: needs fixtures")
    names = d["fixtures"] if isinstance(d["fixtures"], list) else [d["fixtures"]]
    fids = patch.resolve(names)
    fb = patch.resolve(d["fallback"] if isinstance(d.get("fallback"), list) else [d["fallback"]]) if "fallback" in d else []
    targets = fids + [f for f in fb if f not in fids]  # params cover both, checks apply to both
    name = d.get("effect")
    eff = effects.get(name) if name is not None else None
    if name is not None and eff is None:
        raise LookError(f"{what}: unknown effect {name!r}; one of {sorted(effects.REGISTRY)}")
    eff_keys = eff.keys() if eff else set()
    bad = set(d) - (COMMON | STATIC_KEYS | eff_keys)
    if bad:
        raise LookError(f"{what}: unknown keys {sorted(bad)}")
    if eff is not None and eff.movement and "position" in d:
        raise LookError(f"{what}: a position can't go with the {name} movement effect; use a separate layer")

    moves = (eff is not None and eff.movement) or "position" in d
    if moves:
        stuck = [f for f in targets if patch.fixtures[f].type.colour_only]
        if stuck:
            raise LookError(f"{what}: {', '.join(stuck)} colour only, can't move (rule 7); use a group without them")
        no_pt = [f for f in targets if not patch.fixtures[f].type.has("pan")]
        if no_pt:
            raise LookError(f"{what}: {', '.join(no_pt)} have no pan/tilt")

    p: dict[str, Any] = {}
    # static attributes (an effect's own setting of the same name wins)
    if "colour" in d and "colour" not in eff_keys:
        p["colour"] = pal.colour(d["colour"], what)
    if "pixels" in d:
        p["pixels"] = [pal.colour(c, f"{what} pixel {i + 1}") for i, c in enumerate(d["pixels"])]
    if "position" in d:
        p["position"] = {f: pal.position(d["position"], f, what) for f in targets}
    if "gobo" in d:
        p["gobo"] = {f: pal.gobo(d["gobo"], patch.fixtures[f].type.key, what) for f in targets}
    if "colour_wheel" in d:
        p["colour_wheel"] = int(_num(d["colour_wheel"], f"{what} colour_wheel", 0, 255))
    if "strobe" in d:
        p["strobe"] = int(_num(d["strobe"], f"{what} strobe", 0, 255))
    if "intensity" in d:
        p["intensity"] = _num(d["intensity"], f"{what} intensity", 0, 1)
    if "speed" in d:
        p["speed"] = _num(d["speed"], f"{what} speed", 0, 1)
    if eff is not None:
        p.update(eff.parse(d, ParseCtx(patch, pal, targets, what)))
    if "beats" in d:  # a cycle of this many beats at the current tempo (120 BPM when none is set)
        beats = _num(d["beats"], f"{what} beats", 0.125, 64)
        if "period_s" in eff_keys:
            p["period_s"] = beats * BEAT_S
        elif "rate_hz" in eff_keys:
            p["rate_hz"] = 1 / (beats * BEAT_S)
        else:
            raise LookError(f"{what}: beats needs an effect with a speed (period_s or rate_hz)")
    blend = d.get("blend", "replace")
    if blend not in BLENDS:
        raise LookError(f"{what}: blend must be one of {', '.join(BLENDS)}")
    level = _num(d.get("level", 1.0), f"{what} level", 0, 1)
    return Layer(fids, name, p, d.get("name", ""), fb, level, blend, bool(d.get("mute", False)))


def parse_scene(data: dict, patch: Patch, pal: Palettes, name: str = "scene") -> Scene:
    _forbid(data, name)
    bad = set(data) - {"name", "show_colour", "layers", "length_s"}
    if bad:
        raise LookError(f"{name}: unknown keys {sorted(bad)}")
    layers = [parse_layer(d or {}, patch, pal, f"{name} layer {i + 1}") for i, d in enumerate(data.get("layers") or [])]
    if not layers:
        raise LookError(f"{name}: no layers")
    sc = Scene(data.get("name", name), layers)
    if "show_colour" in data:
        sc.show_colour = pal.colour(data["show_colour"], f"{name} show_colour")
    if "length_s" in data:
        sc.length_s = _num(data["length_s"], f"{name} length_s", 0.1)
    return sc


def load_scenes(folder: str | Path, patch: Patch, pal: Palettes) -> dict[str, Scene]:
    out = {}
    for path in sorted(Path(folder).glob("*.yaml")):
        try:
            out[path.stem] = parse_scene(read_doc(path, "scene"), patch, pal, path.stem)
        except ConfigError:
            raise
        except (KeyError, TypeError, ValueError, AttributeError, IndexError) as e:
            raise LookError(f"scenes/{path.name}: {type(e).__name__}: {e}") from e
    return out


# --------------------------------------------------------------------------- playback


class ScenePlayer:
    """Callable(now) -> Look. Starts its clock when created."""

    def __init__(
        self, scene: Scene, rig: Rig, start: float, timebase: Callable[[float], float] | None = None
    ) -> None:
        self.scene = scene
        self.rig = rig
        self.timebase = timebase or (lambda now: now)  # tap tempo: effect time vs real time
        self.start = self.timebase(start)
        present = set(rig.present)
        self._layers: list[tuple[Layer, list[str]]] = []
        for ly in scene.layers:
            fids = [f for f in ly.fixtures if f in present]
            if not fids:  # shows adapt: move the layer to what's there
                fids = [f for f in ly.fallback if f in present]
            self._layers.append((ly, fids))
        self._units: dict[tuple[int, bool], list[Unit]] = {}
        self._cells: dict[str, list[tuple[float, float]]] | None = None

    def __call__(self, now: float) -> Look:
        t = self.timebase(now) - self.start
        look = Look(show_colour=self.scene.show_colour)
        dark: set[str] = set()
        for i, (layer, fids) in enumerate(self._layers):
            if fids and not layer.mute:
                self._apply(i, layer, fids, t, look, dark)
        for f in dark:  # heads move between positions dark
            fl = look.fixtures.get(f)
            if fl:
                fl.colour, fl.pixels = {}, None
        return look

    def _fl(self, look: Look, fid: str) -> FixtureLook:
        return look.fixtures.setdefault(fid, FixtureLook())

    def _pixels(self, fid: str) -> int:
        return self.rig.patch.fixtures[fid].type.pixels

    def _cell_map(self) -> dict[str, list[tuple[float, float]]]:
        """Where every light's cells are on the layout (spatial effects), worked out once."""
        if self._cells is None:
            layout = full_layout(self.rig)
            self._cells = {fid: cell_positions(pl, self._pixels(fid)) for fid, pl in layout.items()}
        return self._cells

    def _units_for(self, i: int, per_pixel: bool) -> list[Unit]:
        key = (i, per_pixel)
        if key not in self._units:
            layer, fids = self._layers[i]
            cells = self._cell_map()
            units: list[Unit] = []
            raw: list[tuple[float, float]] = []
            for f in fids:
                where = cells.get(f) or [(0.0, 0.0)]
                n = self._pixels(f)
                if per_pixel and n:
                    for px in range(n):
                        units.append(Unit(f, px, len(units)))
                        raw.append(where[px] if px < len(where) else where[0])
                else:
                    units.append(Unit(f, None, len(units)))
                    raw.append((sum(x for x, _ in where) / len(where), sum(y for _, y in where) / len(where)))
            if raw:  # one scale both ways so angles stay true
                xs, ys = [x for x, _ in raw], [y for _, y in raw]
                span = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
                for un, (x, y) in zip(units, raw):
                    un.x, un.y = (x - min(xs)) / span, (y - min(ys)) / span
            place_units(units, layer.params, f"{self.scene.name}|{i}")
            self._units[key] = units
        return self._units[key]

    def _apply(self, i: int, ly: Layer, fids: list[str], t: float, look: Look, dark: set[str]) -> None:
        p = ly.params
        run = Run(t, fids, look, dark, self._pixels, lambda per_pixel: self._units_for(i, per_pixel),
                  ly.blend, ly.level, f"{self.scene.name}|{i}")
        plain = ly.blend == "replace" and ly.level >= 1
        # static attributes (also allowed alongside an effect's own settings)
        for f in fids:
            fl = self._fl(look, f)
            if "colour" in p and (ly.effect is None or "colour" not in EFFECTS[ly.effect]):
                if plain:
                    fl.colour, fl.pixels = dict(p["colour"]), None
                else:
                    run.set_colour(f, p["colour"])
            if "pixels" in p:
                if plain:
                    fl.pixels = [dict(c) for c in p["pixels"]]
                else:
                    run.set_pixels(f, [dict(c) for c in p["pixels"]])
            if "position" in p:
                fl.pan, fl.tilt = p["position"][f]
            if "gobo" in p:
                fl.gobo = p["gobo"][f]
            if "colour_wheel" in p:
                fl.colour_wheel = p["colour_wheel"]
            if "strobe" in p:
                fl.strobe = p["strobe"]
            if "speed" in p:
                fl.speed = p["speed"]
            if "intensity" in p:
                fl.intensity = p["intensity"]
        if ly.effect is not None:
            effects.REGISTRY[ly.effect].render(p, run)


def static_source(look: Look) -> Callable[[float], Look]:
    return lambda now: look


__all__ = ["Scene", "Layer", "ScenePlayer", "parse_scene", "load_scenes", "EFFECTS", "EMITTERS"]
