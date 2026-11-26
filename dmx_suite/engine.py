"""Show engine: owns control state, runs the 40 Hz output loop, sends immediately on drum hits."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from .faders import Masters
from .fixtures import DMX_CHANNELS, Kind
from .haze import Haze, HazeMode
from .look import Colour, FixtureLook, Look
from .output import OutputDriver
from .rig import Rig
from .rules import ControlState, Flash, RuleLayer
from .scenes import Scene, ScenePlayer

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
        self.look = look or Look()  # static look (or last look a scene produced)
        self.source: Callable[[float], Look] | None = None  # scene player
        self.scene: Scene | None = None
        # setup/test page: find one fixture, raw channel tester
        self.find: str | None = None
        self.channel_test: dict[tuple[int, int], int] = {}  # (universe, 1-based channel) -> value
        # position picker: hold a head at a spot over whatever the show does (limits still apply)
        self.position_override: dict[str, tuple[float, float]] = {}
        # preview: play something for a while, then put back what was running
        self._preview: tuple[float, Callable[[float], Look] | None, Scene | None, Look] | None = None
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
            if self._preview is not None and now >= self._preview[0]:
                _, self.source, self.scene, self.look = self._preview
                self._preview = None
            if self.source is not None:
                self.look = self.source(now)
            if self.position_override:
                self.look = self._with_positions(self.look)
            if self.find is not None:
                self.frames = self._render_find(now)
            else:
                self.frames = self.rules.render(self.look, self._state(now), self.masters)
            for (uni, ch), val in self.channel_test.items():
                if uni in self.frames:
                    self.frames[uni][ch - 1] = val
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
            self._preview = None
            self.source, self.scene = None, None
            self.look = look
        self._changed()

    def _with_positions(self, look: Look) -> Look:
        fixtures = dict(look.fixtures)
        for fid, (pan, tilt) in self.position_override.items():
            base = fixtures.get(fid, FixtureLook())
            fixtures[fid] = FixtureLook(**{**base.__dict__, "pan": pan, "tilt": tilt})
        return Look(fixtures=fixtures, show_colour=look.show_colour)

    def override_position(self, fid: str, pan: float | None = None, tilt: float | None = None) -> None:
        """Hold a moving head at pan/tilt (0-1); call with pan=None to release."""
        with self.lock:
            if pan is None or tilt is None:
                self.position_override.pop(fid, None)
            else:
                fx = self.rig.patch.fixtures.get(fid)
                if fx is None or fid not in self.rig.present:
                    raise ValueError(f"{fid} is not in this rig")
                if fx.type.colour_only or not fx.type.has("pan"):
                    raise ValueError(f"{fid} can't move (rule 7)")
                if not (0 <= pan <= 1 and 0 <= tilt <= 1):
                    raise ValueError("pan and tilt are 0-1")
                self.position_override[fid] = (pan, tilt)
        self._changed()

    def preview(self, source: Callable[[float], Look], seconds: float, scene: Scene | None = None) -> None:
        """Play `source` for `seconds`, then go back to what was running. Rules still apply."""
        if not 0 < seconds <= 300:
            raise ValueError("preview 0-300 s")
        with self.lock:
            prev = self._preview[1:] if self._preview else (self.source, self.scene, self.look)
            self._preview = (self.clock() + seconds, *prev)
            self.source, self.scene = source, scene
        self._changed()

    @property
    def previewing(self) -> float | None:
        """Seconds of preview left, or None."""
        with self.lock:
            return max(0.0, self._preview[0] - self.clock()) if self._preview else None

    def end_preview(self) -> None:
        with self.lock:
            if self._preview:
                _, self.source, self.scene, self.look = self._preview
                self._preview = None
        self._changed()

    def set_source(self, source: Callable[[float], Look], scene: Scene | None = None) -> None:
        """Play any look source (a show, a scene with tap tempo). The rule layer still applies."""
        with self.lock:
            self._preview = None  # a real selection ends any preview
            self.source, self.scene = source, scene
        self._changed()

    def set_scene(self, scene: Scene) -> None:
        """Play a scene from its start. The rule layer still applies to every frame."""
        with self.lock:
            self.scene = scene
            self.source = ScenePlayer(scene, self.rig, self.clock())
        self._changed()

    # ------------------------------------------------------------------ setup / test page
    # Operator tools, not show output: `find` lights one fixture regardless of MASTER and the
    # masters; the channel tester sets raw values. Neither can drive a haze channel (rule 5),
    # and head limits still apply to `find`.

    def _render_find(self, now: float) -> dict[int, bytearray]:
        full = Masters(1.0, {}, 1.0, 0.0)
        white = {e: 1.0 for e in ("red", "green", "blue", "white")}
        look = Look(fixtures={self.find: FixtureLook(colour=white)})
        state = ControlState(True, False, {}, self.haze.tick(now))
        frames = self.rules.render(look, state, full)
        for fx in self.rig.fixtures:  # the kick light ignores MASTER, so dark it explicitly
            if fx.kind == Kind.KICK and fx.id != self.find:
                for ch in fx.type.channels:
                    frames[fx.universe][fx.slot(ch)] = 0
        return frames

    def find_fixture(self, fid: str | None) -> None:
        with self.lock:
            if fid is not None and fid not in self.rig.present:
                raise ValueError(f"{fid} is not in this rig")
            if fid is not None and self.rig.patch.fixtures[fid].kind == Kind.HAZE:
                raise ValueError("haze is only run from the Haze controls (rule 5)")
            self.find = fid
        self._changed()

    def haze_slots(self) -> set[tuple[int, int]]:
        out = set()
        for fx in self.rig.patch.fixtures.values():
            for ch in fx.type.channels:
                if ch.role == "haze":
                    out.add((fx.universe, fx.slot(ch) + 1))
        return out

    def test_channel(self, channel: int, value: int | None, universe: int = 0) -> None:
        if not 1 <= channel <= DMX_CHANNELS:
            raise ValueError("channel 1-512")
        if (universe, channel) in self.haze_slots():
            raise ValueError("that's the haze channel: use the Haze controls (rule 5)")
        with self.lock:
            if value is None:
                self.channel_test.pop((universe, channel), None)
            else:
                if not 0 <= value <= 255:
                    raise ValueError("value 0-255")
                self.channel_test[(universe, channel)] = value
        self._changed()

    def clear_setup(self) -> None:
        with self.lock:
            self.find = None
            self.channel_test.clear()
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
