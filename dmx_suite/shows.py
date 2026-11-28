"""Shows (sets of scenes on fixed-timer steps) and setlists.

shows/shows/band.yaml:
    name: Main band show
    default_set: mid
    sets:
      low:  {step_s: 60, auto: {colours: [blue, purple], energy: low}}
      mid:  {step_s: 40, auto: {colours: [blue, purple, amber], energy: mid}}
      high: {step_s: 20, auto: {colours: [red, blue, white], energy: high, flash: true}}
      intro: {step_s: 30, scenes: [blue_chase, red_movers], order: random}

A set has `steps`, `scenes` (the v1 way: each held for `step_s`) or `auto` (a fresh generated
scene every step). Steps work like Daslight's super scenes: each plays a scene for a number of
`repeats` (cycles of the scene, see Scene.length), or `hold_s` seconds, or `hold_beats` /
`hold_bars` (4 beats) at the current tempo, then `fade_s` into the next (the set's `fade_s` is
the default). `order: random` never plays the same scene twice in a row; `loop: false` stays on
the last step.

    sets:
      verse:
        fade_s: 2
        steps:
          - {scene: blue_chase, repeats: 4}
          - {scene: red_movers, hold_s: 30, fade_s: 0}
          - {scene: strobe_hit, hold_bars: 2}

Repeats and beats run in effect time, so they follow a tapped or clocked tempo; hold_s is real time.

shows/setlists/gig.yaml:
    name: Gig 26/11/2026
    songs:
      - {name: Opener, show: band, set: high}
      - {name: Ballad, show: band, set: low}
      - {name: Aria, show: opera}
      - {name: Intro cue, scene: blue_chase}
"""

from __future__ import annotations

import random
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .auto import AutoStyle, generate, parse_style
from .fade import Crossfade
from .fixtures import ConfigError
from .look import Look
from .palettes import Palettes
from .rig import Rig
from .scenes import Scene, ScenePlayer
from .tempo import BEAT_S, TempoClock

DEFAULT_STEP_S = 40.0


@dataclass
class Step:
    scene: str  # scene key ("" for auto sets: generated each time)
    repeats: int | None = None  # cycles of the scene
    hold_s: float | None = None  # real seconds
    hold_beats: float | None = None  # beats at the current tempo (bars x 4)
    fade_s: float | None = None  # into this step; None = the set's

    def effect_length(self, scene: Scene | None) -> float | None:
        """How long in effect time (repeats, beats), or None when it's a real-time hold."""
        if self.repeats is not None and scene is not None and scene.length:
            return self.repeats * scene.length
        if self.hold_beats is not None:
            return self.hold_beats * BEAT_S
        return None


@dataclass
class ShowSet:
    name: str
    step_s: float  # hold for steps that don't say (and every auto step)
    scenes: list[str] = field(default_factory=list)
    order: str = "sequence"  # sequence | random
    auto: AutoStyle | None = None
    steps: list[Step] = field(default_factory=list)
    fade_s: float = 0.0  # between steps, unless a step says
    loop: bool = True  # False: stay on the last step


@dataclass
class Show:
    key: str
    name: str
    sets: dict[str, ShowSet]
    default_set: str


@dataclass
class Song:
    name: str
    show: str | None = None
    set: str | None = None
    scene: str | None = None
    master: bool | None = None  # optionally force MASTER on/off for this song


@dataclass
class Setlist:
    key: str
    name: str
    songs: list[Song]


def parse_show(key: str, d: dict, pal: Palettes, scenes: dict[str, Scene]) -> Show:
    sets = {}
    for sname, sd in (d.get("sets") or {}).items():
        what = f"show {key} set {sname}"
        sd = sd or {}
        bad = set(sd) - {"step_s", "scenes", "steps", "order", "auto", "fade_s", "loop"}
        if bad:
            raise ConfigError(f"{what}: unknown keys {sorted(bad)}")
        step = _secs(sd.get("step_s", DEFAULT_STEP_S), f"{what} step_s", 1)
        kinds = [k for k in ("scenes", "steps", "auto") if sd.get(k) or (k == "auto" and k in sd)]
        if len(kinds) != 1:
            raise ConfigError(f"{what}: give one of steps, scenes or auto")
        order = sd.get("order", "sequence")
        if order not in ("sequence", "random"):
            raise ConfigError(f"{what}: order must be sequence or random")
        if "scenes" in kinds:  # v1: each scene held for step_s
            steps = [Step(_scene_key(sc, scenes, what), hold_s=step) for sc in sd["scenes"]]
        elif "steps" in kinds:
            steps = [_parse_step(x, scenes, f"{what} step {i + 1}") for i, x in enumerate(sd["steps"])]
        else:
            steps = []
        sets[sname] = ShowSet(sname, step, [s.scene for s in steps], order,
                              parse_style(sd["auto"], pal, what) if "auto" in kinds else None,
                              steps, _secs(sd.get("fade_s", 0), f"{what} fade_s"), bool(sd.get("loop", True)))
    if not sets:
        raise ConfigError(f"show {key}: no sets")
    default = d.get("default_set", next(iter(sets)))
    if default not in sets:
        raise ConfigError(f"show {key}: default_set {default!r} isn't a set")
    return Show(key, d.get("name", key), sets, default)


def _secs(v: object, what: str, lo: float = 0.0) -> float:
    try:
        f = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError) as e:
        raise ConfigError(f"{what} must be a number of seconds") from e
    if f < lo:
        raise ConfigError(f"{what} must be >= {lo:g}")
    return f


def _scene_key(sc: object, scenes: dict[str, Scene], what: str) -> str:
    if sc not in scenes:
        raise ConfigError(f"{what}: unknown scene {sc!r}")
    return str(sc)


def _parse_step(d: object, scenes: dict[str, Scene], what: str) -> Step:
    if isinstance(d, str):
        d = {"scene": d}
    if not isinstance(d, dict) or "scene" not in d:
        raise ConfigError(f"{what}: needs a scene")
    bad = set(d) - {"scene", "repeats", "hold_s", "hold_beats", "hold_bars", "fade_s"}
    if bad:
        raise ConfigError(f"{what}: unknown keys {sorted(bad)}")
    key = _scene_key(d["scene"], scenes, what)
    holds = [k for k in ("repeats", "hold_s", "hold_beats", "hold_bars") if k in d]
    if len(holds) > 1:
        raise ConfigError(f"{what}: give one of repeats, hold_s, hold_beats or hold_bars")
    st = Step(key, fade_s=_secs(d["fade_s"], f"{what} fade_s") if "fade_s" in d else None)
    if "repeats" in d:
        try:
            st.repeats = int(d["repeats"])
        except (TypeError, ValueError) as e:
            raise ConfigError(f"{what}: repeats must be a whole number") from e
        if st.repeats < 1:
            raise ConfigError(f"{what}: repeats must be 1 or more")
        if not scenes[key].length:
            raise ConfigError(f"{what}: scene {key} has no moving effect to repeat; use hold_s")
    elif "hold_s" in d:
        st.hold_s = _secs(d["hold_s"], f"{what} hold_s", 0.1)
    elif "hold_beats" in d or "hold_bars" in d:
        beats = _secs(d.get("hold_beats", d.get("hold_bars")), f"{what} hold_beats/bars", 0.25)
        st.hold_beats = beats * (4 if "hold_bars" in d else 1)
    return st


def parse_setlist(key: str, d: dict, shows: dict[str, Show], scenes: dict[str, Scene]) -> Setlist:
    songs = []
    for i, sd in enumerate(d.get("songs") or []):
        what = f"setlist {key} song {i + 1}"
        bad = set(sd) - {"name", "show", "set", "scene", "master"}
        if bad:
            raise ConfigError(f"{what}: unknown keys {sorted(bad)}")
        song = Song(sd.get("name", f"Song {i + 1}"), sd.get("show"), sd.get("set"), sd.get("scene"), sd.get("master"))
        if (song.show is None) == (song.scene is None):
            raise ConfigError(f"{what}: give either show or scene")
        if song.show is not None:
            if song.show not in shows:
                raise ConfigError(f"{what}: unknown show {song.show!r}")
            if song.set is not None and song.set not in shows[song.show].sets:
                raise ConfigError(f"{what}: show {song.show} has no set {song.set!r}")
        elif song.scene not in scenes:
            raise ConfigError(f"{what}: unknown scene {song.scene!r}")
        songs.append(song)
    if not songs:
        raise ConfigError(f"setlist {key}: no songs")
    return Setlist(key, d.get("name", key), songs)


def _load_dir(folder: Path) -> dict[str, dict]:
    from .versions import read_doc

    return {p.stem: read_doc(p) for p in sorted(folder.glob("*.yaml"))}


def load_shows(folder: Path, pal: Palettes, scenes: dict[str, Scene]) -> dict[str, Show]:
    return {k: parse_show(k, d, pal, scenes) for k, d in _load_dir(folder).items()}


def load_setlists(folder: Path, shows: dict[str, Show], scenes: dict[str, Scene]) -> dict[str, Setlist]:
    return {k: parse_setlist(k, d, shows, scenes) for k, d in _load_dir(folder).items()}


# --------------------------------------------------------------------------- playback


class ShowPlayer:
    """Callable(now) -> Look. Plays a set's steps: each for its repeats, hold or beats, then
    (crossfading if the step or set says so) on to the next."""

    def __init__(self, show: Show, set_name: str, rig: Rig, pal: Palettes, scenes: dict[str, Scene],
                 tempo: TempoClock, now: float, seed: str | None = None) -> None:
        if set_name not in show.sets:
            raise ConfigError(f"show {show.key} has no set {set_name!r}")
        self.show, self.set = show, show.sets[set_name]
        self.rig, self.pal, self.scenes, self.tempo = rig, pal, scenes, tempo
        self.seed = seed if seed is not None else f"{show.key}-{set_name}-{now}"
        self.step = -1  # steps played so far - 1 (counts up for ever; auto shows seed from it)
        self.index = 0  # which of the set's steps is playing
        self.current: Step | None = None
        self._last_scene: str | None = None
        self._rng = random.Random(zlib.crc32(self.seed.encode()))
        self.scene: Scene | None = None
        self._player: Any = None
        self.step_start = now
        self._eff_start = tempo.eff(now)
        self.next_step(now, fade=False)

    def _pick(self) -> tuple[Scene, Step | None]:
        st = self.set
        if st.auto is not None:
            return generate(st.auto, self.rig, self.pal, self.step, self.seed, self.show.name), None
        n = len(st.steps)
        if st.order == "sequence":
            self.index = self.step % n if st.loop else min(self.step, n - 1)
            step = st.steps[self.index]
        else:
            choices = [x for x in st.steps if x.scene != self._last_scene] or st.steps
            step = self._rng.choice(choices)
            self.index = st.steps.index(step)
        self._last_scene = step.scene
        return self.scenes[step.scene], step

    def next_step(self, now: float, fade: bool = True) -> None:
        old = self._player
        self.step += 1
        self.step_start = now
        self._eff_start = self.tempo.eff(now)
        self.scene, self.current = self._pick()
        new = ScenePlayer(self.scene, self.rig, now, self.tempo.eff)
        fade_s = self.current.fade_s if self.current and self.current.fade_s is not None else self.set.fade_s
        self._player = Crossfade(old, new, now, fade_s) if fade and old is not None and fade_s > 0 else new

    def go(self, index: int, now: float) -> None:
        """Jump to one of the set's steps."""
        if self.set.auto is not None or not 0 <= index < len(self.set.steps):
            raise ConfigError("no such step")
        self.step = index - 1 if self.set.order == "sequence" else self.step
        if self.set.order == "random":  # play exactly that one next
            self._last_scene = None
            self.step += 1
            self.step_start, self._eff_start = now, self.tempo.eff(now)
            self.index, self.current = index, self.set.steps[index]
            self.scene = self.scenes[self.current.scene]
            self._player = ScenePlayer(self.scene, self.rig, now, self.tempo.eff)
            self._last_scene = self.current.scene
            return
        self.next_step(now)

    def _length(self) -> tuple[float, bool]:
        """(how long this step lasts, whether that's effect time)."""
        st = self.current
        if st is not None:
            eff = st.effect_length(self.scene)
            if eff is not None:
                return eff, True
            if st.hold_s is not None:
                return st.hold_s, False
        return self.set.step_s, False

    def _at_end(self) -> bool:
        return not self.set.loop and self.set.auto is None and self.set.order == "sequence" \
            and self.step >= len(self.set.steps) - 1

    def __call__(self, now: float) -> Look:
        length, eff = self._length()
        elapsed = self.tempo.eff(now) - self._eff_start if eff else now - self.step_start
        if elapsed >= length and not self._at_end():
            self.next_step(now)
        if isinstance(self._player, Crossfade) and self._player.done(now):
            self._player = self._player.new
        return self._player(now)

    def time_left(self, now: float) -> float:
        length, eff = self._length()
        if eff:
            return max(0.0, (length - (self.tempo.eff(now) - self._eff_start)) / (self.tempo.rate or 1.0))
        return max(0.0, length - (now - self.step_start))

    def repeat(self, now: float) -> tuple[int, int] | None:
        """(which repeat is playing, of how many), for steps counted in repeats."""
        st = self.current
        if st is None or st.repeats is None or not self.scene or not self.scene.length:
            return None
        done = int((self.tempo.eff(now) - self._eff_start) // self.scene.length)
        return min(done + 1, st.repeats), st.repeats
