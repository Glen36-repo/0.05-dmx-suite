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

`type: steps` makes a step scene (v3.2, steps.py): hand-programmed steps with step and fade times;
its `layers` (optional) are effects laid over the steps.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from . import effects
from .effects import BLENDS, ParseCtx, Run, Unit, place_units
from .effects.base import num as _num_any
from .effects.base import static_on
from .fixtures import EMITTERS, ConfigError, Kind, Patch
from .layout import cell_positions, full_layout
from .look import FORBIDDEN, Colour, FixtureLook, Look, LookError
from .palettes import Palettes
from .rig import Rig
from .tempo import BEAT_S
from .versions import read_doc

# effect name -> its setting keys, and the effects that move heads (for older callers)
EFFECTS = {name: e.keys() for name, e in effects.REGISTRY.items()}
MOVEMENT = {name for name, e in effects.REGISTRY.items() if e.movement}
STATIC_KEYS = {"colour", "pixels", "position", "gobo", "colour_wheel", "speed", "strobe", "zoom", "focus", "frost", "prism"}
COMMON = {"fixtures", "effect", "name", "fallback", "intensity", "level", "blend", "mute", "beats", "shift", "lit", "darkness"}


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
    shift: float = 0.0  # phase offset, part of a cycle (Ride "shift", v3.3)
    pixel_mask: dict[str, frozenset[int]] = field(default_factory=dict)  # v4: fid -> only these pixels (0-based)
    lit: float = 1.0  # v6: how much of the effect is lit, 0-1 (YAML `lit:` in %); the rest black (colour off)
    # v8: how much of the Autopilot's Darkness applies (FX settings: Follow 1, Exempt 0, Reduced 0-1), per
    # light with "*" for the rest. YAML `darkness: 0.5` or `darkness: {"*": 0.5, mh_a: 0}`; empty = all of it
    dark: dict[str, float] = field(default_factory=dict)

    def period(self) -> float | None:
        e = effects.get(self.effect) if self.effect else None
        return e.period(self.params) if e else None


@dataclass
class Scene:
    name: str
    layers: list[Layer]
    show_colour: Colour = field(default_factory=lambda: {"red": 1.0, "green": 1.0, "blue": 1.0})
    length_s: float | None = None  # one cycle, if set in the file
    steps: Any = None  # steps.Steps for a step scene (v3.2)
    generated: bool = False  # made by the generator / starter (v4: its own section on the Live page)

    @property
    def uses_intensity(self) -> bool:
        step_layers = [ly for st in self.steps.steps for ly in st.layers] if self.steps else []
        return any("intensity" in ly.params for ly in [*self.layers, *step_layers])

    @property
    def length(self) -> float | None:
        """Seconds for one cycle: `length_s`, else the longest effect period (None if nothing moves).
        A step scene: one pass through its steps (None when a pedal or input moves it on)."""
        if self.length_s:
            return self.length_s
        if self.steps is not None:
            return self.steps.length
        periods = [p for ly in self.layers if not ly.mute and (p := ly.period())]
        return max(periods) if periods else None


# --------------------------------------------------------------------------- parsing / validation


def _forbid(d: dict, what: str) -> None:
    for k in d:
        if k in FORBIDDEN:
            raise LookError(f"{what}: {FORBIDDEN[k]}")


def _num(v: Any, what: str, lo: float, hi: float | None = None) -> float:
    return _num_any(v, what, lo, hi)


def _gobos(v: Any, patch: Patch, pal: Palettes, targets: list[str], what: str) -> dict[str, int | None]:
    """Per fixture: a palette gobo, else the fixture type's own named gobo slot, else a DMX value."""
    if isinstance(v, str) and v not in pal.gobos:
        out = {f: patch.fixtures[f].type.gobo_value(v) for f in targets}
        if not any(x is not None for x in out.values()):
            raise LookError(f"{what}: unknown gobo {v!r} (not in the palette or any of these fixtures' gobos)")
        return out
    return {f: pal.gobo(v, patch.fixtures[f].type.key, what) for f in targets}


def _wheel(v: Any, patch: Patch, targets: list[str], what: str) -> dict[str, int | None]:
    """Per fixture: a named colour wheel slot of its type, or a DMX value."""
    if isinstance(v, str):
        out = {f: patch.fixtures[f].type.wheel_value(v) for f in targets}
        if not any(x is not None for x in out.values()):
            raise LookError(f"{what}: none of these fixtures has a colour wheel slot named {v!r}")
        return out
    n = int(_num(v, f"{what} colour_wheel", 0, 255))
    return dict.fromkeys(targets, n)


def parse_layer(d: dict, patch: Patch, pal: Palettes, what: str) -> Layer:
    _forbid(d, what)
    if "fixtures" not in d:
        raise LookError(f"{what}: needs fixtures")
    names = d["fixtures"] if isinstance(d["fixtures"], list) else [d["fixtures"]]
    sel = patch.resolve_targets(names)  # v4: `bar_1:px1-4`, `bars:odd`, pixel groups
    fids = list(sel)
    mask = {f: px for f, px in sel.items() if px is not None}
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
    if mask and (moves or "intensity" in d):
        raise LookError(f"{what}: a pixel selection ({', '.join(sorted(mask))}) is colour only (rule 1: MASTER owns "
                        "each segment's dimmer and strobe)")
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
        p["position"] = pal.positions_for(d["position"], targets, what)
    if "gobo" in d:
        p["gobo"] = _gobos(d["gobo"], patch, pal, targets, what)
    if "colour_wheel" in d:
        p["colour_wheel"] = _wheel(d["colour_wheel"], patch, targets, what)
    for k in ("zoom", "focus", "frost"):
        if k in d:
            p[k] = _num(d[k], f"{what} {k}", 0, 1)
    if "prism" in d:
        p["prism"] = int(_num(d["prism"], f"{what} prism", 0, 255))
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
    shift = _num(d.get("shift", 0.0), f"{what} shift", 0, 1)
    lit = _num(d.get("lit", 100), f"{what} lit (%)", 0, 100) / 100
    dark = _dark_share(d.get("darkness"), set(targets), what)
    return Layer(fids, name, p, d.get("name", ""), fb, level, blend, bool(d.get("mute", False)), shift, mask, lit, dark)


def _dark_share(v: Any, targets: set[str], what: str) -> dict[str, float]:
    """A layer's `darkness:` (v8): the share of the Autopilot's Darkness it takes, 0-1, or per light."""
    if v is None:
        return {}
    if not isinstance(v, dict):
        v = {"*": v}
    out: dict[str, float] = {}
    for k, x in v.items():
        if k != "*" and k not in targets:
            raise LookError(f"{what} darkness: {k!r} isn't one of this layer's lights")
        out[str(k)] = _num(x, f"{what} darkness {k}", 0, 1)
    return out


def parse_scene(data: dict, patch: Patch, pal: Palettes, name: str = "scene") -> Scene:
    from .steps import parse_steps

    _forbid(data, name)
    kind = data.get("type", "layers")
    if kind not in ("layers", "steps"):
        raise LookError(f"{name}: type is layers (the default) or steps")
    if kind == "layers":
        bad = set(data) - {"name", "show_colour", "layers", "length_s", "type", "generated", "lit"}
        if bad:
            raise LookError(f"{name}: unknown keys {sorted(bad)}")
    look_lit = data.get("lit")  # v6: the whole look's lit, for layers that don't give their own
    layers = [parse_layer({**({"lit": look_lit} if look_lit is not None and "lit" not in (d or {}) else {}), **(d or {})},
                          patch, pal, f"{name} layer {i + 1}") for i, d in enumerate(data.get("layers") or [])]
    steps = parse_steps(data, patch, pal, name) if kind == "steps" else None
    if not layers and steps is None:
        raise LookError(f"{name}: no layers")
    sc = Scene(data.get("name", name), layers, steps=steps, generated="generated" in data)
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
        self, scene: Scene, rig: Rig, start: float, timebase: Callable[[float], float] | None = None,
        first_step: int = 0, only_step: int | None = None,
        darkness: Callable[[float], float] | None = None, edge: float = 0.0,
    ) -> None:
        self.scene = scene
        self.rig = rig
        # v6: Autopilot darkness (0-1 at clock time `now`): lit = the layer's lit x (1 - darkness), except
        # exempt lights (the kick light), which keep the look's own lit. None = play as authored.
        self.darkness = darkness
        self.edge = edge  # soft black edges (the look's fade), 0 = hard cut
        self.timebase = timebase or (lambda now: now)  # tap tempo: effect time vs real time
        self.start = self.timebase(start)
        # haze machines are never part of a look (rule 5), nor of where an effect runs across the stage
        present = {f for f in rig.present if rig.patch.fixtures[f].type.kind != Kind.HAZE}
        self._layers: list[tuple[Layer, list[str]]] = []
        for ly in scene.layers:
            fids = [f for f in ly.fixtures if f in present]
            if not fids:  # shows adapt: move the layer to what's there
                fids = [f for f in ly.fallback if f in present]
            self._layers.append((ly, fids))
        self._units: dict[tuple[int, bool], list[Unit]] = {}
        self._cells: dict[str, list[tuple[float, float]]] | None = None
        self._centre: tuple[float, float] | None = None
        self.runner: Any = None
        if scene.steps is not None:
            from .steps import StepRunner

            tempo = getattr(self.timebase, "__self__", None)  # tempo.eff: the show's TempoClock

            def beat_s() -> float:
                bpm = getattr(tempo, "bpm", None)
                return 60.0 / bpm if bpm else BEAT_S

            self.runner = StepRunner(scene.steps, rig, self._step_look, start, beat_s, first_step, only_step)

    def _step_look(self, i: int) -> Look:
        """Step i with tracking: every step up to it laid in order (each only sets what changes)."""
        layers = [ly for st in self.scene.steps.steps[: i + 1] for ly in st.layers]
        sub = ScenePlayer(Scene(self.scene.name, layers, self.scene.show_colour), self.rig, 0.0)
        return sub(0.0)

    def __call__(self, now: float) -> Look:
        t = self.timebase(now) - self.start
        if self.runner is not None:
            from .steps import set_active

            set_active(self.runner)
            base = self.runner(now)
            look = Look(show_colour=dict(base.show_colour),
                        fixtures={k: replace(v, colour=dict(v.colour), pixels=[dict(p) for p in v.pixels] if v.pixels else None)
                                  for k, v in base.fixtures.items()})
            top_dark: set[str] = set()
            for i, (layer, fids) in enumerate(self._layers):
                if fids and not layer.mute:
                    self._apply(i, layer, fids, t, look, top_dark, now)
            for f in top_dark:
                fl = look.fixtures.get(f)
                if fl:
                    fl.colour, fl.pixels = {}, None
            return look
        look = Look(show_colour=self.scene.show_colour)
        dark: set[str] = set()
        for i, (layer, fids) in enumerate(self._layers):
            if fids and not layer.mute:
                self._apply(i, layer, fids, t, look, dark, now)
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

    def _rig_centre(self) -> tuple[float, float]:
        c = self._centre
        if c is None:
            c = self._centre = self.rig.layout_centre()
        return c

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
                only = layer.pixel_mask.get(f)
                if only is not None:  # a pixel selection: the effect runs over just those pixels
                    for px in sorted(only):
                        units.append(Unit(f, px, len(units)))
                        raw.append(where[px] if px < len(where) else where[0])
                elif per_pixel and n:
                    for px in range(n):
                        units.append(Unit(f, px, len(units)))
                        raw.append(where[px] if px < len(where) else where[0])
                else:
                    units.append(Unit(f, None, len(units)))
                    raw.append((sum(x for x, _ in where) / len(where), sum(y for _, y in where) / len(where)))
            if raw:  # one scale both ways so angles stay true
                xs, ys = [x for x, _ in raw], [y for _, y in raw]
                span = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
                rcx, rcy = self._rig_centre()  # v8: centre_out / sides use the rig's stage centrelines
                cx, cy = (rcx - min(xs)) / span, (rcy - min(ys)) / span
                for un, (x, y) in zip(units, raw):
                    un.x, un.y = (x - min(xs)) / span, (y - min(ys)) / span
                    un.cx, un.cy = cx, cy
            place_units(units, layer.params, f"{self.scene.name}|{i}")
            self._units[key] = units
        return self._units[key]

    def _apply(self, i: int, ly: Layer, fids: list[str], t: float, look: Look, dark: set[str], now: float = 0.0) -> None:
        p = ly.params
        if ly.shift:
            t += ly.shift * (ly.period() or 0.0)
        d = max(0.0, min(1.0, self.darkness(now))) if self.darkness is not None else 0.0
        eff = effects.REGISTRY[ly.effect] if ly.effect is not None else None
        run = Run(t, fids, look, dark, self._pixels, lambda per_pixel: self._units_for(i, per_pixel),
                  ly.blend, ly.level, f"{self.scene.name}|{i}", now, mask=ly.pixel_mask,
                  lit=ly.lit * (1 - d * ly.dark.get("*", 1.0)), lit_exempt=ly.lit, exempt=self.rig.exempt,
                  lit_by={f: ly.lit * (1 - d * s) for f, s in ly.dark.items() if f != "*"},
                  edge=self.edge or (1.0 if p.get("fade") is True else 0.0), shift=ly.shift,
                  auto_gate=eff is not None and not eff.lit_aware and not eff.movement)
        plain = ly.blend == "replace" and ly.level >= 1
        static_lit = run.gating() and "colour" in p and (ly.effect is None or "colour" not in EFFECTS[ly.effect])
        # static attributes (also allowed alongside an effect's own settings)
        for f in fids:
            fl = self._fl(look, f)
            if static_lit:
                pass  # below: a regular black pattern across the lights / pixels
            elif "colour" in p and (ly.effect is None or "colour" not in EFFECTS[ly.effect]):
                if plain and f not in ly.pixel_mask:
                    fl.colour, fl.pixels = dict(p["colour"]), None
                else:
                    run.set_colour(f, p["colour"])  # also a pixel selection: only those pixels
            if "pixels" in p:
                if plain and f not in ly.pixel_mask:
                    fl.pixels = [dict(c) for c in p["pixels"]]
                else:
                    run.set_pixels(f, [dict(c) for c in p["pixels"]])
            if "position" in p and f in p["position"]:
                fl.pan, fl.tilt = p["position"][f]
            if "gobo" in p and p["gobo"].get(f) is not None:
                fl.gobo = p["gobo"][f]
            if "colour_wheel" in p and p["colour_wheel"].get(f) is not None:
                fl.colour_wheel = p["colour_wheel"][f]
            if "strobe" in p:
                fl.strobe = p["strobe"]
            for k in ("zoom", "focus", "frost", "prism"):
                if k in p:
                    setattr(fl, k, p[k])
            if "speed" in p:
                fl.speed = p["speed"]
            if "intensity" in p:
                fl.intensity = p["intensity"]
        if static_lit:  # v6: a still colour with lit < 1 -> alternate / every third ... black, moving with shift
            units = self._units_for(i, True)
            off = round(ly.shift * len(units))
            for un in units:
                on = static_on(un.index, run.lit_of(un.fid), off)
                run.put(un, p["colour"] if on else run.black(un.fid, un.pixel))
            run.flush()
        if eff is not None:
            eff.render(p, run)
        for f, px in run.unlit:  # drum flash leaves these black (MASTER off)
            ul = look.fixtures.get(f)
            if ul is not None:
                ul.unlit = ul.unlit | {-1 if px is None else px}


def static_source(look: Look) -> Callable[[float], Look]:
    return lambda now: look


__all__ = ["Scene", "Layer", "ScenePlayer", "parse_scene", "load_scenes", "EFFECTS", "EMITTERS"]
