"""Step scenes (v3.2): a scene made of steps programmed by hand, Daslight style.

    name: Intro hits
    type: steps
    step_s: 2            # default step time (seconds the step lasts, its fade included)
    fade_s: 0.5          # default fade into a step (0 = cut)
    playback: loop       # loop | once | bounce
    advance: timer       # timer | manual | {input: snare} (a named input hit = next step)
    move: dark           # dark | lit; default from the rule profile (0.05 band dark, generic lit)
    steps:
      - {name: red bars, set: {bars: {colour: red}}}
      - {name: blue heads, set: {heads: {colour: blue, position: drum_kit}}, fade_s: 0}
      - {name: heads to crowd, set: {heads: {position: audience_l}}, move: lit, step_s: 4, fade_s: 4}
      - {name: all white, set: {all: {colour: white}}, step_beats: 8, fade_s: 2}
    layers:              # optional effect layers over the steps (e.g. a sparkle)
      - {fixtures: [bars], effect: sparkle, colour: white, level: 0.4, blend: max}

Tracking: each step starts as a copy of the one before, so a step only lists what changes.
`set` takes, per light or group, what a layer can set: colour, pixels, position, gobo,
colour_wheel, strobe, zoom, focus, frost, prism, speed (and intensity where the profile allows).

Fades follow the rules: colour fades; wheels, gobos and strobe snap halfway; lights the new step
doesn't use fade to 0 (rule 4); haze is never part of a step (rule 5). A head that changes
position moves either:
- dark: it dims out where it was, moves, then fades in (at least `dark_s`, default 0.3 s, even on
  a cut, so the motor has time to get there in the dark), or
- lit: pan/tilt glide from the old spot to the new over the fade time, 16-bit where the head has
  fine channels, with its speed channel held at fastest so the motor doesn't add lag. The glide is
  checked against the head limits: head limits are a box, so a straight glide between two points
  inside them stays inside; an end outside them (a point stored before the limits changed) is
  rerouted along the limit edge. A head without a known start position moves dark.

Live: `speed` (0.25-4) scales step and fade times; `fade_scale` (0-4) scales fades only.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from .effects.base import num
from .fade import _colours, _moved
from .look import FixtureLook, Look, LookError
from .rig import Rig

PLAYBACK = ("loop", "once", "bounce")
MOVES = ("dark", "lit")
STEP_KEYS = {"name", "set", "step_s", "step_beats", "fade_s", "move"}
SCENE_KEYS = {"type", "step_s", "step_beats", "fade_s", "playback", "advance", "move", "dark_s", "steps"}
SET_KEYS = {"colour", "pixels", "position", "gobo", "colour_wheel", "strobe", "zoom", "focus", "frost", "prism", "speed",
            "intensity", "lit"}  # v6 lit: % of the colour lit, the rest a regular black pattern


@dataclass
class Step:
    name: str
    layers: list[Any]  # this step's own static layers (scenes.Layer), in order
    step_s: float | None = None  # None = the scene's
    step_beats: float | None = None
    fade_s: float | None = None
    move: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)  # as written (the editor round-trips it)


@dataclass
class Steps:
    steps: list[Step]
    step_s: float = 2.0
    step_beats: float | None = None
    fade_s: float = 0.0
    playback: str = "loop"
    advance: str = "timer"  # timer | manual | input
    advance_input: str | None = None
    move: str | None = None  # None = from the profile
    dark_s: float = 0.3

    def hold(self, i: int, beat_s: float) -> float:
        st = self.steps[i]
        if st.step_beats is not None:
            return st.step_beats * beat_s
        if st.step_s is not None:
            return st.step_s
        if self.step_beats is not None:
            return self.step_beats * beat_s
        return self.step_s

    def fade(self, i: int) -> float:
        st = self.steps[i]
        return self.fade_s if st.fade_s is None else st.fade_s

    def move_for(self, i: int, rig: Rig) -> str:
        st = self.steps[i]
        if st.move is not None:
            return st.move
        if self.move is not None:
            return self.move
        return "dark" if rig.profile.master_gate else "lit"

    @property
    def length(self) -> float | None:
        """One pass through the steps (timer-driven only); used when a show repeats the scene."""
        if self.advance != "timer":
            return None
        return sum(self.hold(i, 0.5) for i in range(len(self.steps)))


def parse_steps(data: dict[str, Any], patch: Any, pal: Any, name: str) -> Steps:
    from .scenes import parse_layer

    bad = set(data) - SCENE_KEYS - {"name", "show_colour", "layers", "length_s", "generated"}
    if bad:
        raise LookError(f"{name}: unknown keys {sorted(bad)}")
    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise LookError(f"{name}: a step scene needs steps")
    out = Steps([])
    if "step_s" in data:
        out.step_s = num(data["step_s"], f"{name} step_s", 0.05)
    if "step_beats" in data:
        out.step_beats = num(data["step_beats"], f"{name} step_beats", 0.25, 256)
    if "fade_s" in data:
        out.fade_s = num(data["fade_s"], f"{name} fade_s", 0)
    if "dark_s" in data:
        out.dark_s = num(data["dark_s"], f"{name} dark_s", 0, 5)
    pb = data.get("playback", "loop")
    if pb not in PLAYBACK:
        raise LookError(f"{name}: playback is {', '.join(PLAYBACK)}")
    out.playback = pb
    adv = data.get("advance", "timer")
    if isinstance(adv, dict):
        if set(adv) != {"input"} or not isinstance(adv["input"], str):
            raise LookError(f"{name}: advance is timer, manual or {{input: <named input>}}")
        out.advance, out.advance_input = "input", adv["input"]
    elif adv in ("timer", "manual"):
        out.advance = adv
    else:
        raise LookError(f"{name}: advance is timer, manual or {{input: <named input>}}")
    if "move" in data:
        if data["move"] not in MOVES:
            raise LookError(f"{name}: move is dark or lit")
        out.move = data["move"]
    for i, d in enumerate(raw_steps):
        what = f"{name} step {i + 1}"
        if not isinstance(d, dict):
            raise LookError(f"{what}: needs set: {{lights: {{colour, position, ...}}}}")
        bad = set(d) - STEP_KEYS
        if bad:
            raise LookError(f"{what}: unknown keys {sorted(bad)}")
        sets = d.get("set") or {}
        if not isinstance(sets, dict):
            raise LookError(f"{what}: set is {{lights or group: {{colour, position, ...}}}}")
        layers = []
        for target, attrs in sets.items():
            if not isinstance(attrs, dict) or not attrs:
                raise LookError(f"{what} {target}: what to set, e.g. {{colour: red}}")
            extra = set(attrs) - SET_KEYS
            if extra:
                raise LookError(f"{what} {target}: can't set {sorted(extra)} (dimmer is MASTER's, haze its own controls)")
            layers.append(parse_layer({"fixtures": [target], **attrs}, patch, pal, f"{what} {target}"))
        st = Step(str(d.get("name") or f"Step {i + 1}"), layers, raw=dict(d))
        if "step_s" in d:
            st.step_s = num(d["step_s"], f"{what} step_s", 0.05)
        if "step_beats" in d:
            st.step_beats = num(d["step_beats"], f"{what} step_beats", 0.25, 256)
        if "fade_s" in d:
            st.fade_s = num(d["fade_s"], f"{what} fade_s", 0)
        if "move" in d:
            if d["move"] not in MOVES:
                raise LookError(f"{what}: move is dark or lit")
            st.move = d["move"]
        out.steps.append(st)
    return out


# ---------------------------------------------------------------------- tracking view (v4 step editor)


def track_view(data: dict[str, Any], index: int, patch: Any) -> dict[str, Any]:
    """What each light shows at step `index` (0-based) and where it comes from: set in this step, or
    tracked from an earlier one. Works on unsaved scene data (the editor's). Keyed by fixture id; a
    pixel selection adds `pixels` (1-based numbers). Unknown targets are skipped (validation says so)."""
    steps = data.get("steps") or []
    if not 0 <= index < len(steps):
        raise LookError(f"no step {index + 1}; the scene has {len(steps)}")
    out: dict[str, dict[str, Any]] = {}
    for i, st in enumerate(steps[: index + 1]):
        for target, attrs in ((st or {}).get("set") or {}).items():
            try:
                sel = patch.resolve_targets([target])
            except Exception:  # noqa: BLE001 - shown by validation, not here
                continue
            for fid, px in sel.items():
                slot = out.setdefault(fid, {})
                for k, v in (attrs or {}).items():
                    entry: dict[str, Any] = {"value": v, "from_step": i, "via": target,
                                             "source": "set" if i == index else "tracked"}
                    if px is not None:
                        entry["pixels"] = sorted(n + 1 for n in px)
                        key = f"{k}@px" + ",".join(str(n + 1) for n in sorted(px))
                    else:
                        key = k
                        for old in [x for x in slot if x.startswith(f"{k}@px")]:  # a whole-light value covers the pixels
                            del slot[old]
                    slot[key] = entry
    return {"step": index, "name": (steps[index] or {}).get("name") or f"Step {index + 1}", "fixtures": out}


# ---------------------------------------------------------------------- playback


def glide_path(rig: Rig, fid: str, a: tuple[float, float], b: tuple[float, float], f: float) -> tuple[float, float]:
    """Pan/tilt f of the way from a to b, kept inside the head limits (rerouted along their edge)."""
    lim = rig.limit(fid)
    pan = a[0] + (b[0] - a[0]) * f
    tilt = a[1] + (b[1] - a[1]) * f
    return lim.clamp("pan", pan), lim.clamp("tilt", tilt)


def path_ok(rig: Rig, fid: str, a: tuple[float, float], b: tuple[float, float], samples: int = 16) -> bool:
    """True when the straight glide stays inside the head limits all the way."""
    lim = rig.limit(fid)
    for i in range(samples + 1):
        f = i / samples
        p, t = a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
        if not (lim.pan[0] - 1e-9 <= p <= lim.pan[1] + 1e-9 and lim.tilt[0] - 1e-9 <= t <= lim.tilt[1] + 1e-9):
            return False
    return True


def _ease(f: float) -> float:
    return 0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, f)))


class StepRunner:
    """Plays a step scene: which step, how far through, the look. Thread-safe controls."""

    def __init__(self, steps: Steps, rig: Rig, render_step: Callable[[int], Look], start: float,
                 beat_s: Callable[[], float] | None = None, first: int = 0, only: int | None = None) -> None:
        self.s, self.rig = steps, rig
        self.render_step = render_step  # step index -> its (tracked) look
        self.beat_s = beat_s or (lambda: 0.5)
        self.only = only  # preview one step: stay on it
        self.speed = 1.0
        self.fade_scale = 1.0
        self.index = first if 0 <= first < len(steps.steps) else 0
        self.prev: int | None = None
        self.direction = 1
        self.finished = False
        self._tau = 0.0  # step clock (seconds x speed) since the step began
        self._last = start
        self._lock = threading.Lock()
        self._cache: dict[int, Look] = {}
        self._from_look: Look | None = None  # what was showing when the step changed (mid-fade too)
        self._last_look: Look | None = None

    # ------------------------------------------------------------------ controls (any thread)

    def next(self) -> None:
        with self._lock:
            self._go(self._after(self.index, 1))

    def back(self) -> None:
        with self._lock:
            self._go(self._after(self.index, -1))

    def go(self, index: int) -> None:
        with self._lock:
            if 0 <= index < len(self.s.steps):
                self._go(index)

    def set_speed(self, speed: float) -> None:
        self.speed = max(0.05, min(8.0, float(speed)))

    def set_fade_scale(self, scale: float) -> None:
        self.fade_scale = max(0.0, min(8.0, float(scale)))

    # ------------------------------------------------------------------ internals

    def _after(self, i: int, way: int) -> int | None:
        n = len(self.s.steps)
        if n == 1:
            return 0
        if self.s.playback == "loop":
            return (i + way) % n
        if self.s.playback == "once":
            j = i + way
            return j if 0 <= j < n else None
        # bounce: forward then back
        step = way * self.direction
        j = i + step
        if not 0 <= j < n:
            self.direction = -self.direction
            j = i - step
        return j

    def _go(self, j: int | None) -> None:
        if j is None:
            self.finished = True
            return
        self._from_look = self._last_look  # fade from what's on the rig now
        self.prev, self.index = self.index, j
        self._tau = 0.0
        self.finished = False

    def look(self, i: int) -> Look:
        if i not in self._cache:
            self._cache[i] = self.render_step(i)
        return self._cache[i]

    def hold(self) -> float:
        return self.s.hold(self.index, self.beat_s())

    def fade_len(self) -> float:
        return min(self.s.fade(self.index) * self.fade_scale, self.hold()) if self.prev is not None else 0.0

    def time_left(self) -> float:
        return max(0.0, (self.hold() - self._tau) / self.speed)

    def __call__(self, now: float) -> Look:
        with self._lock:
            dt = max(0.0, now - self._last)
            self._last = now
            self._tau += dt * self.speed
            if self.only is None and self.s.advance == "timer" and not self.finished:
                # a long gap (laptop asleep) may pass several steps: step through them
                for _ in range(len(self.s.steps) + 1):
                    hold = self.hold()
                    if self._tau < hold:
                        break
                    over = self._tau - hold
                    self._last_look = self.look(self.index)
                    self._go(self._after(self.index, 1))
                    if self.finished:
                        break
                    self._tau = over
            out = self._frame()
            self._last_look = out
            return out

    def _frame(self) -> Look:
        new = self.look(self.index)
        if self.prev is None or self._from_look is None:
            return new
        fade = self.fade_len()
        old = self._from_look
        move = self.s.move_for(self.index, self.rig)
        dark = min(self.s.dark_s, self.hold() / 2) if move == "dark" else 0.0
        span = max(fade, dark)
        if span <= 0 or self._tau >= span:
            if self._tau >= span:
                self._from_look = None  # settled: no need to keep the old look
            return new
        return self._mix(old, new, self._tau, fade, move, dark)

    def _mix(self, a: Look, b: Look, tau: float, fade: float, move: str, dark: float) -> Look:
        """The step fade at `tau` seconds in: colours over `fade`, heads per `move`."""
        f = 1.0 if fade <= 0 else min(1.0, tau / fade)
        out = Look(show_colour={k: a.show_colour.get(k, 0.0) * (1 - f) + b.show_colour.get(k, 0.0) * f
                                for k in set(a.show_colour) | set(b.show_colour)})
        for fid in set(a.fixtures) | set(b.fixtures):
            fa, fb = a.fixtures.get(fid, FixtureLook()), b.fixtures.get(fid, FixtureLook())
            o = replace(fb if f >= 0.5 else fa)  # slots (wheel, gobo, strobe, speed) snap halfway
            moved = _moved(fa, fb)
            if moved and (move == "dark" or fa.pan is None):
                span = max(fade, dark)
                g = tau / span if span > 0 else 1.0
                if g < 0.5:  # dim out where it was
                    _colours(fa, fb, 1 - 2 * g, 0.0, o)
                    o.pan, o.tilt = fa.pan, fa.tilt
                else:  # move dark, fade in where it's going
                    _colours(fa, fb, 0.0, 2 * g - 1, o)
                    o.pan, o.tilt = fb.pan, fb.tilt
            elif moved:  # lit glide, inside the head limits, motor at fastest
                assert fa.pan is not None and fa.tilt is not None and fb.pan is not None and fb.tilt is not None
                _colours(fa, fb, 1 - f, f, o)
                o.pan, o.tilt = glide_path(self.rig, fid, (fa.pan, fa.tilt), (fb.pan, fb.tilt), _ease(f) if fade > 0 else 1.0)
                o.speed = 1.0
            else:
                _colours(fa, fb, 1 - f, f, o)
                o.pan = fb.pan if fb.pan is not None else fa.pan
                o.tilt = fb.tilt if fb.tilt is not None else fa.tilt
            if fa.intensity is not None or fb.intensity is not None:
                ia = fa.intensity if fa.intensity is not None else 1.0
                ib = fb.intensity if fb.intensity is not None else 1.0
                o.intensity = ia * (1 - f) + ib * f
            out.fixtures[fid] = o
        return out


# The step scene the engine drew last (the newest one: a crossfade draws old then new). Pedals,
# faders and named inputs reach it through here.
_active: list[StepRunner | None] = [None]


def active() -> StepRunner | None:
    return _active[0]


def set_active(r: StepRunner | None) -> None:
    _active[0] = r
