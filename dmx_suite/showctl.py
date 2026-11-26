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
    time_left_s: float | None = None
    setlist: str | None = None
    song: int | None = None  # 0-based
    song_name: str | None = None
    bpm: float | None = None



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
        self.tempo = TempoClock(engine.clock())
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
        self.mode, self.show, self.set_name, self.scene_key, self.player = "look", None, None, None, None
        self.e.set_look(self.files.look)
        self._save()

    @_locked
    def select_scene(self, key: str) -> None:
        if key not in self.files.scenes:
            raise ConfigError(f"no scene {key!r}")
        sc = self.files.scenes[key]
        self.mode, self.scene_key, self.show, self.set_name, self.player = "scene", key, None, None, None
        self.e.set_source(ScenePlayer(sc, self.e.rig, self.e.clock(), self.tempo.eff), sc)
        self._save()

    @_locked
    def select_show(self, key: str, set_name: str | None = None) -> None:
        if key not in self.files.shows:
            raise ConfigError(f"no show {key!r}")
        show = self.files.shows[key]
        set_name = set_name or show.default_set
        self.player = ShowPlayer(show, set_name, self.e.rig, self.files.palettes, self.files.scenes, self.tempo, self.e.clock())
        self.mode, self.show, self.set_name, self.scene_key = "show", show, set_name, None
        self.e.set_source(self.player, self.player.scene)
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

    # ------------------------------------------------------------------ status

    @_locked
    def now(self) -> Now:
        n = Now(self.mode, "static look", bpm=self.tempo.bpm)
        if self.mode == "scene" and self.scene_key:
            n.scene, n.label = self.scene_key, self.files.scenes[self.scene_key].name
        elif self.mode == "show" and self.player and self.show:
            n.show, n.set, n.step = self.show.key, self.set_name, self.player.step + 1
            n.scene = self.player.scene.name if self.player.scene else None
            n.time_left_s = self.player.time_left(self.e.clock())
            n.label = f"{self.show.name} / {self.set_name}"
        if self.setlist and self.song is not None:
            n.setlist, n.song, n.song_name = self.setlist.key, self.song, self.setlist.songs[self.song].name
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
