"""Shows (sets of scenes on fixed-timer steps) and setlists.

shows/shows/band.yaml:
    name: Main band show
    default_set: mid
    sets:
      low:  {step_s: 60, auto: {colours: [blue, purple], energy: low}}
      mid:  {step_s: 40, auto: {colours: [blue, purple, amber], energy: mid}}
      high: {step_s: 20, auto: {colours: [red, blue, white], energy: high, flash: true}}
      intro: {step_s: 30, scenes: [blue_chase, red_movers], order: random}

A set has either `scenes` (ordered or random, never the same twice in a row) or `auto` (a fresh
generated scene every step). Step times are fixed timers; tap tempo only changes effect speed.

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


from .auto import AutoStyle, generate, parse_style
from .fixtures import ConfigError
from .look import Look
from .palettes import Palettes
from .rig import Rig
from .scenes import Scene, ScenePlayer
from .tempo import TempoClock


@dataclass
class ShowSet:
    name: str
    step_s: float
    scenes: list[str] = field(default_factory=list)
    order: str = "sequence"  # sequence | random
    auto: AutoStyle | None = None


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
        bad = set(sd) - {"step_s", "scenes", "order", "auto"}
        if bad:
            raise ConfigError(f"{what}: unknown keys {sorted(bad)}")
        step = float(sd.get("step_s", 40))
        if step < 1:
            raise ConfigError(f"{what}: step_s must be >= 1")
        has_scenes, has_auto = bool(sd.get("scenes")), "auto" in sd
        if has_scenes == has_auto:
            raise ConfigError(f"{what}: give either scenes or auto")
        for sc in sd.get("scenes") or []:
            if sc not in scenes:
                raise ConfigError(f"{what}: unknown scene {sc!r}")
        order = sd.get("order", "sequence")
        if order not in ("sequence", "random"):
            raise ConfigError(f"{what}: order must be sequence or random")
        sets[sname] = ShowSet(sname, step, list(sd.get("scenes") or []), order,
                              parse_style(sd["auto"], pal, what) if has_auto else None)
    if not sets:
        raise ConfigError(f"show {key}: no sets")
    default = d.get("default_set", next(iter(sets)))
    if default not in sets:
        raise ConfigError(f"show {key}: default_set {default!r} isn't a set")
    return Show(key, d.get("name", key), sets, default)


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
    """Callable(now) -> Look. Steps through a set on its fixed timer."""

    def __init__(self, show: Show, set_name: str, rig: Rig, pal: Palettes, scenes: dict[str, Scene],
                 tempo: TempoClock, now: float, seed: str | None = None) -> None:
        if set_name not in show.sets:
            raise ConfigError(f"show {show.key} has no set {set_name!r}")
        self.show, self.set = show, show.sets[set_name]
        self.rig, self.pal, self.scenes, self.tempo = rig, pal, scenes, tempo
        self.seed = seed if seed is not None else f"{show.key}-{set_name}-{now}"
        self.step = -1
        self._last_scene: str | None = None
        self._rng = random.Random(zlib.crc32(self.seed.encode()))
        self.scene: Scene | None = None
        self._player: ScenePlayer | None = None
        self.step_start = now
        self.next_step(now)

    def _pick(self) -> Scene:
        st = self.set
        if st.auto is not None:
            return generate(st.auto, self.rig, self.pal, self.step, self.seed, self.show.name)
        if st.order == "sequence":
            key = st.scenes[self.step % len(st.scenes)]
        else:
            choices = [s for s in st.scenes if s != self._last_scene] or st.scenes
            key = self._rng.choice(choices)
        self._last_scene = key
        return self.scenes[key]

    def next_step(self, now: float) -> None:
        self.step += 1
        self.step_start = now
        self.scene = self._pick()
        self._player = ScenePlayer(self.scene, self.rig, now, self.tempo.eff)

    def __call__(self, now: float) -> Look:
        if now - self.step_start >= self.set.step_s:
            self.next_step(now)
        assert self._player is not None
        return self._player(now)

    def time_left(self, now: float) -> float:
        return max(0.0, self.set.step_s - (now - self.step_start))
