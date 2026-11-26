"""Show engine: owns control state, runs the 40 Hz output loop, sends immediately on drum hits."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from .faders import Masters
from .fixtures import Kind
from .haze import Haze, HazeMode
from .look import Colour, Look
from .output import OutputDriver
from .rig import Rig
from .rules import ControlState, Flash, RuleLayer

log = logging.getLogger(__name__)

FRAME_HZ = 40
WHITE: Colour = {"red": 1.0, "green": 1.0, "blue": 1.0, "white": 1.0}


class Engine:
    def __init__(
        self,
        rig: Rig,
        drivers: list[OutputDriver],
        look: Look | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.rig = rig
        self.drivers = drivers
        self.clock = clock
        self.lock = threading.RLock()
        now = clock()
        self.master = rig.startup_master  # safe default on (re)start
        self.blackout = False
        self.look = look or Look()
        self.flashes: dict[str, Flash] = {}
        self.masters = Masters(rig.grand_master, rig.sub_masters, rig.flash_level, rig.fade_s)
        self.haze = Haze(rig.haze, now)
        self.rules = RuleLayer(rig)
        self.frames: dict[int, bytearray] = {}
        self.frames_sent = 0
        self.driver_errors = 0
        self.on_frame: list[Callable[[dict[int, bytearray]], None]] = []
        self._last_tick = now
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ output

    def _state(self, now: float) -> ControlState:
        return ControlState(self.master, self.blackout, self.flashes, self.haze.tick(now))

    def output(self) -> dict[int, bytearray]:
        """Render and send now. Called by the loop and directly by anything that must not wait."""
        with self.lock:
            now = self.clock()
            for fid in [f for f, fl in self.flashes.items() if fl.until <= now]:
                del self.flashes[fid]
            self.frames = self.rules.render(self.look, self._state(now), self.masters)
            for drv in self.drivers:
                for uni, frame in self.frames.items():
                    try:
                        drv.send(uni, bytes(frame))
                    except Exception:
                        self.driver_errors += 1
                        log.exception("output driver %s failed", drv.name)
            self.frames_sent += 1
            for fn in self.on_frame:
                fn(self.frames)
            return self.frames

    def tick(self) -> None:
        """One loop step: advance fades, then render and send."""
        with self.lock:
            now = self.clock()
            self.masters.tick(max(0.0, now - self._last_tick))
            self._last_tick = now
            self.output()

    def flash_deadline(self) -> float:
        """When the earliest running flash ends (inf if none), so the loop can cut it exactly."""
        with self.lock:
            return min((f.until for f in self.flashes.values()), default=float("inf"))

    # ------------------------------------------------------------------ loop thread

    def start(self) -> None:
        if self._thread:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="engine", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        next_tick = self.clock()
        while not self._stop.is_set():
            self._wake.clear()  # before tick, so a control change during it isn't missed
            self.tick()
            now = self.clock()
            next_tick = max(next_tick + 1 / FRAME_HZ, now)
            deadline = min(next_tick, self.flash_deadline())
            self._wake.wait(max(0.0, deadline - now))

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=1)
            self._thread = None
        for d in self.drivers:
            d.close()

    def _changed(self) -> None:
        """Control change: send now rather than on the next tick."""
        self.output()
        self._wake.set()

    # ------------------------------------------------------------------ controls

    def set_look(self, look: Look) -> None:
        with self.lock:
            self.look = look
        self._changed()

    def set_master(self, on: bool) -> None:
        with self.lock:
            self.master = on
            if on:
                self.flashes.clear()
        self._changed()

    def toggle_master(self) -> None:
        self.set_master(not self.master)

    def set_blackout(self, on: bool) -> None:
        with self.lock:
            self.blackout = on
        self._changed()

    def toggle_blackout(self) -> None:
        self.set_blackout(not self.blackout)

    def flash(
        self,
        fixtures: list[str],
        velocity: int = 127,
        colour: str | Colour = "show",
        length_ms: int = 100,
        min_level: float = 0.0,
    ) -> bool:
        """Drum hit. Only with MASTER off (rule 2). Sends a frame immediately; the loop wakes to
        cut back to black exactly when the flash ends. Returns False if ignored."""
        with self.lock:
            if self.master or self.blackout:
                return False
            if colour == "show":
                col = self.look.show_colour
            elif colour == "white":
                col = WHITE
            else:
                col = colour  # type: ignore[assignment]
            level = max(min_level, min(1.0, velocity / 127))
            until = self.clock() + length_ms / 1000
            for fid in fixtures:
                if fid in self.rig.present and self.rig.patch.fixtures[fid].kind != Kind.KICK:
                    self.flashes[fid] = Flash(col, level, until)
        self._changed()
        return True

    def set_grand(self, level: float, instant: bool = False) -> None:
        with self.lock:
            self.masters.grand.set(level, instant)
        self._wake.set()

    def set_sub(self, kind: Kind | str, level: float, instant: bool = False) -> None:
        with self.lock:
            self.masters.subs[Kind(kind)].set(level, instant)
        self._wake.set()

    def set_flash_level(self, level: float) -> None:
        with self.lock:
            self.masters.flash.set(level)

    # haze: separate controls (rule 5)

    def haze_mode(self, mode: HazeMode | str) -> None:
        with self.lock:
            self.haze.set_mode(mode, self.clock())
        self._changed()

    def haze_toggle_manual(self) -> None:
        with self.lock:
            self.haze.toggle_manual(self.clock())
        self._changed()

    def haze_boost(self, pressed: bool) -> bool:
        with self.lock:
            now = self.clock()
            ok = self.haze.boost_press(now) if pressed else (self.haze.boost_release(now) or True)
        self._changed()
        return ok

    def haze_stop(self) -> None:
        with self.lock:
            self.haze.stop(self.clock())
        self._changed()
