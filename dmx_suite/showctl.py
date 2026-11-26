"""Show control: what's playing (look / scene / show+set / setlist song), tap tempo, and resuming
after a laptop restart mid-gig. Driven by the FCB1010 (MIDI map), the console, and later the UI/MCP.
"""

from __future__ import annotations

import functools
import json
import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .engine import Engine
from .fixtures import ConfigError
from .scenes import ScenePlayer
from .shows import Setlist, Show, ShowPlayer
from .tempo import TempoClock

log = logging.getLogger(__name__)

RESUME_MAX_AGE_S = 12 * 3600  # older saved state is treated as a fresh start


@dataclass
class Now:
    mode: str  # look | scene | show
    label: str
    show: str | None = None
    set: str | None = None
    scene: str | None = None
    step: int | None = None
    step_index: int | None = None  # which of the set's steps (0-based), for the step list
    repeat: tuple[int, int] | None = None  # (repeat playing, of how many)
    time_left_s: float | None = None
    setlist: str | None = None
    song: int | None = None  # 0-based
    song_name: str | None = None
    bpm: float | None = None
    steps: dict[str, Any] | None = None  # a step scene playing (v3.2): step, of, name, time left, speeds



def _locked(fn: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(fn)
    def run(self: Any, *a: Any, **k: Any) -> Any:
        with self._lock:
            return fn(self, *a, **k)

    return run

class ShowController:
    def __init__(self, engine: Engine, files: Any, state_path: Path | None = None) -> None:
        # MIDI, OSC, the web page, Claude and the console can all pick shows at once
        self._lock = threading.RLock()
        self.e = engine
        self.files = files  # ShowFiles (with shows/setlists)
        self.tempo = TempoClock(engine.clock(), engine.rig.tempo)
        self.state_path = state_path
        self.mode = "look"
        self.show: Show | None = None
        self.set_name: str | None = None
        self.scene_key: str | None = None
        self.player: ShowPlayer | None = None
        self.setlist: Setlist | None = None
        self.song: int | None = None

    # ------------------------------------------------------------------ selection

    @_locked
    def select_look(self) -> None:
        from . import steps

        steps.set_active(None)
        self.mode, self.show, self.set_name, self.scene_key, self.player = "look", None, None, None, None
        self.e.set_look(self.files.look)
        self._save()

    @_locked
    def select_scene(self, key: str, step: int = 0) -> None:
        from . import steps

        if key not in self.files.scenes:
            raise ConfigError(f"no scene {key!r}")
        sc = self.files.scenes[key]
        self.mode, self.scene_key, self.show, self.set_name, self.player = "scene", key, None, None, None
        player = ScenePlayer(sc, self.e.rig, self.e.clock(), self.tempo.eff, first_step=step)
        steps.set_active(player.runner)
        self.e.set_source(player, sc, self.e.rig.change_fade_s)
        self._save()

    @_locked
    def select_show(self, key: str, set_name: str | None = None) -> None:
        if key not in self.files.shows:
            raise ConfigError(f"no show {key!r}")
        show = self.files.shows[key]
        set_name = set_name or show.default_set
        from . import steps

        steps.set_active(None)  # a step scene in the show takes over when it's drawn
        self.player = ShowPlayer(show, set_name, self.e.rig, self.files.palettes, self.files.scenes, self.tempo, self.e.clock())
        self.mode, self.show, self.set_name, self.scene_key = "show", show, set_name, None
        self.e.set_source(self.player, self.player.scene, self.e.rig.change_fade_s)
        self._save()

    @_locked
    def select_set(self, set_name: str) -> None:
        """Switch LOW / MID / HIGH: in the current show if it has that set, otherwise in the first
        show that does (so the LOW pedal during Opera goes to the band show's LOW set)."""
        if self.show is not None and set_name in self.show.sets:
            return self.select_show(self.show.key, set_name)
        for show in self.files.shows.values():
            if set_name in show.sets:
                return self.select_show(show.key, set_name)
        raise ConfigError(f"no show has a set {set_name!r}")

    @_locked
    def next_step(self) -> None:
        if self.player is None:
            raise ConfigError("no show playing")
        with self.e.lock:  # the engine thread is reading this player
            self.player.next_step(self.e.clock())
        self.e.set_source(self.player, self.player.scene)

    @_locked
    def go_step(self, index: int) -> None:
        """Jump to one of the playing set's steps (tap a step on the Live page)."""
        if self.player is None:
            raise ConfigError("no show playing")
        with self.e.lock:
            self.player.go(index, self.e.clock())
        self.e.set_source(self.player, self.player.scene)

    @_locked
    def select_ride(self, label: str, player: Any, scene: Any, fade_s: float = 0.0) -> None:
        """The Ride page or the autopilot is playing a look (v3.3)."""
        from . import steps

        steps.set_active(None)
        self.mode, self.show, self.set_name, self.scene_key, self.player = "ride", None, None, None, None
        self.ride_label = label
        self.e.set_source(player, scene, fade_s)
        self._save()

    # ------------------------------------------------------------------ step scenes (v3.2)

    def step_runner(self) -> Any:
        from . import steps

        return steps.active()

    def _runner(self) -> Any:
        r = self.step_runner()
        if r is None:
            raise ConfigError("no step scene playing")
        return r

    def step_scene(self, action: str, value: float | None = None) -> str:
        """Pedals, buttons and faders for the step scene playing: next, back, go (value = step,
        0-based), speed (0.25-4) and fade (scale 0-4)."""
        r = self._runner()
        with self.e.lock:
            if action == "next":
                r.next()
            elif action == "back":
                r.back()
            elif action == "go":
                r.go(int(value or 0))
            elif action == "speed":
                r.set_speed(float(value if value is not None else 1.0))
            elif action == "fade":
                r.set_fade_scale(float(value if value is not None else 1.0))
            else:
                raise ConfigError("step action: next, back, go, speed or fade")
        self.e._changed()
        return f"step {r.index + 1}: {r.s.steps[r.index].name}"

    def step_input(self, input_id: str) -> bool:
        """A named input was hit: the step scene playing moves on if it waits for that input."""
        r = self.step_runner()
        if r is None or r.s.advance != "input" or r.s.advance_input != input_id:
            return False
        with self.e.lock:
            r.next()
        self.e._changed()
        return True

    # ------------------------------------------------------------------ setlist

    @_locked
    def load_setlist(self, key: str, song: int = 0) -> None:
        if key not in self.files.setlists:
            raise ConfigError(f"no setlist {key!r}")
        self.setlist = self.files.setlists[key]
        self.go_song(song)

    @_locked
    def go_song(self, index: int) -> None:
        if self.setlist is None:
            raise ConfigError("no setlist loaded")
        index = max(0, min(index, len(self.setlist.songs) - 1))
        self.song = index
        s = self.setlist.songs[index]
        if s.master is not None:
            self.e.set_master(s.master)
        if s.show:
            self.select_show(s.show, s.set)
        else:
            assert s.scene is not None
            self.select_scene(s.scene)

    @_locked
    def next_song(self) -> None:
        self.go_song((self.song if self.song is not None else -1) + 1)

    @_locked
    def prev_song(self) -> None:
        self.go_song((self.song or 0) - 1)

    @_locked
    def clear_setlist(self) -> None:
        self.setlist, self.song = None, None
        self._save()

    # ------------------------------------------------------------------ tempo

    @_locked
    def tap(self) -> float | None:
        return self.tempo.tap(self.e.clock())

    @_locked
    def set_tempo(self, bpm: float | None) -> None:
        self.tempo.set_bpm(bpm, self.e.clock())

    def set_speed(self, speed: float) -> None:
        self.tempo.set_speed(speed, self.e.clock())

    # ------------------------------------------------------------------ status

    @_locked
    def now(self) -> Now:
        n = Now(self.mode, "static look", bpm=self.tempo.bpm)
        if self.mode == "ride":
            n.label = getattr(self, "ride_label", "Ride")
        if self.mode == "scene" and self.scene_key:
            n.scene, n.label = self.scene_key, self.files.scenes[self.scene_key].name
        elif self.mode == "show" and self.player and self.show:
            n.show, n.set, n.step = self.show.key, self.set_name, self.player.step + 1
            n.scene = self.player.scene.name if self.player.scene else None
            n.time_left_s = self.player.time_left(self.e.clock())
            n.step_index = self.player.index if self.player.set.auto is None else None
            n.repeat = self.player.repeat(self.e.clock())
            n.label = f"{self.show.name} / {self.set_name}"
        if self.setlist and self.song is not None:
            n.setlist, n.song, n.song_name = self.setlist.key, self.song, self.setlist.songs[self.song].name
        r = self.step_runner()
        if r is not None and self.mode in ("scene", "show"):
            n.steps = {"index": r.index, "of": len(r.s.steps), "name": r.s.steps[r.index].name,
                       "names": [st.name for st in r.s.steps], "time_left_s": round(r.time_left(), 2),
                       "advance": r.s.advance, "input": r.s.advance_input, "playback": r.s.playback,
                       "speed": r.speed, "fade_scale": r.fade_scale, "finished": r.finished}
        return n

    @_locked
    def describe(self) -> str:
        n = self.now()
        parts = [n.label]
        if n.mode == "show":
            parts.append(f"step {n.step}: {n.scene} ({n.time_left_s:.0f}s left)")
        if n.setlist and self.setlist and n.song is not None:
            parts.append(f"song {n.song + 1}/{len(self.setlist.songs)}: {n.song_name}")
        parts.append(f"tempo {n.bpm:.0f} BPM" if n.bpm else "fixed timers")
        return "  |  ".join(parts)

    # ------------------------------------------------------------------ resume after restart

    def _save(self) -> None:
        if not self.state_path:
            return
        state = {
            "saved": time.time(),
            "mode": self.mode,
            "show": self.show.key if self.show else None,
            "set": self.set_name,
            "scene": self.scene_key,
            "setlist": self.setlist.key if self.setlist else None,
            "song": self.song,
            "master": self.e.master,
        }
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(state), encoding="utf-8")
            os.replace(tmp, self.state_path)  # atomic: a crash mid-write can't corrupt it
        except OSError:
            log.exception("couldn't save show state")

    @_locked
    def replay(self) -> None:
        """After the rig or patch changed: build what's playing again on the new rig (same show and
        set, scene or static look; the setlist and song stay)."""
        self.tempo.config = self.e.rig.tempo
        if self.mode == "show" and self.show and self.show.key in self.files.shows:
            show = self.files.shows[self.show.key]
            self.select_show(show.key, self.set_name if self.set_name in show.sets else None)
        elif self.mode == "scene" and self.scene_key in self.files.scenes:
            self.select_scene(self.scene_key)
        else:
            self.select_look()

    @_locked
    def save(self) -> None:
        """Call after MASTER changes so a restart comes back the same way."""
        self._save()

    @_locked
    def restore(self) -> bool:
        """Pick up where we were if the laptop restarted mid-gig. Returns True if resumed."""
        if not self.state_path or not self.state_path.exists():
            return False
        try:
            st = json.loads(self.state_path.read_text(encoding="utf-8"))
            if time.time() - float(st.get("saved", 0)) > RESUME_MAX_AGE_S:
                return False
            if st.get("setlist") in self.files.setlists:
                self.load_setlist(st["setlist"], int(st.get("song") or 0))
            elif st.get("mode") == "show" and st.get("show") in self.files.shows:
                show = self.files.shows[st["show"]]
                self.select_show(show.key, st.get("set") if st.get("set") in show.sets else None)
            elif st.get("mode") == "scene" and st.get("scene") in self.files.scenes:
                self.select_scene(st["scene"])
            else:
                return False
            if isinstance(st.get("master"), bool):
                self.e.set_master(st["master"])
            return True
        except (OSError, ValueError, TypeError, ConfigError):
            log.exception("couldn't restore show state; starting fresh")
            return False
