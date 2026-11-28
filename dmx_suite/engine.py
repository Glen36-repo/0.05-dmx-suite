"""Show engine: owns control state, runs the 40 Hz output loop, sends immediately on drum hits.

The show must go on: an error while rendering (a bad value in a show file, a bug in an effect)
never stops output. The engine logs it, drops to the static look, and if even that can't render
keeps sending the last good frame. `fault` says what happened for the status bar.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable
from typing import Any

from . import testpattern
from .busk import Override, apply_with_releases
from .fade import Crossfade
from .faders import Masters
from .fixtures import DMX_CHANNELS, Kind
from .haze import Haze, HazeMode
from .look import Colour, FixtureLook, Look
from .output import NodeSerialDriver, OutputDriver
from .output.timer import high_res
from .rig import HazeConfig, Rig
from .rules import ControlState, Flash, RuleLayer
from .scenes import Scene, ScenePlayer
from .testpattern import TestPattern

log = logging.getLogger(__name__)

FRAME_HZ = 40
WHITE: Colour = {"red": 1.0, "green": 1.0, "blue": 1.0, "white": 1.0}


FLASH_MIN_LEVEL = 0.6  # v7: a soft drum hit still opens the light this far


def flash_level(velocity: int, min_level: float = FLASH_MIN_LEVEL) -> float:
    """v7 drum flash level: velocity 1 = the pad's min level, 127 = full, in a straight line between."""
    lo = max(0.0, min(1.0, float(min_level)))
    v = max(1, min(127, int(velocity)))
    return lo + (1 - lo) * (v - 1) / 126


class Engine:
    def __init__(
        self,
        rig: Rig,
        drivers: list[OutputDriver],
        look: Look | None = None,
        clock: Callable[[], float] = time.perf_counter,  # high resolution on Windows too
    ) -> None:
        self.rig = rig
        self.drivers = drivers
        self.hint_drivers()
        self.clock = clock
        self.lock = threading.RLock()
        now = clock()
        self.master = rig.startup_master  # safe default on (re)start
        self.blackout = False
        self.look = look or Look()  # what's on the rig: the base look with positions and busking laid over
        self.base_look = self.look  # the static look playing when no scene or show is
        self.static_look = self.look  # what the engine falls back to after a fault
        self.source: Callable[[float], Look] | None = None  # scene player
        self.scene: Scene | None = None
        # setup/test page: find one fixture, raw channel tester
        self.find: str | None = None
        self.channel_test: dict[tuple[int, int], int] = {}  # (universe, 1-based channel) -> value
        self.test: TestPattern | None = None  # v5 test pattern, straight to the interface(s)
        self.test_log: list[dict[str, Any]] = []  # started / stopped, for the Monitor DMX pane
        # position picker: hold a head at a spot over whatever the show does (limits still apply)
        self.position_override: dict[str, tuple[float, float]] = {}
        # preview: play something for a while, then put back what was running
        self._preview: tuple[float, Callable[[float], Look] | None, Scene | None, Look] | None = None
        self.flashes: dict[str, Flash] = {}
        self.overrides: list[Override] = []  # busking: laid over the show, under the rules
        self.masters = Masters(rig.grand_master, rig.sub_masters, rig.flash_level, rig.fade_s)
        self.haze = Haze(rig.haze, now)
        self.rules = RuleLayer(rig)
        self.frames: dict[int, bytearray] = {}
        self.frames_sent = 0
        self.driver_errors = 0
        self.fault: str | None = None  # last render error, for the status bar
        self.fault_at: float | None = None
        self.faults = 0
        self._logged: dict[str, float] = {}  # message -> when last logged (rate limit)
        self.on_frame: list[Callable[[dict[int, bytearray]], None]] = []
        self._last_tick = now
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ live rig changes (R7)

    def swap_rig(self, rig: Rig, look: Look) -> None:
        """Run on a changed patch or rig from the next frame: new rule layer (heads keep where they
        are), static look, haze settings; MASTER, masters and what's playing stay. Anything aimed at
        a fixture that's gone (flash, find, held position) is dropped."""
        with self.lock:
            old = self.rig
            self.rig = rig
            held = self.rules.position
            self.rules = RuleLayer(rig)
            for fid in self.rules.position:
                if fid in held and fid in old.present:
                    self.rules.position[fid] = held[fid]
            if rig.haze != old.haze:
                self.haze.reconfigure(rig.haze, self.clock())  # the mode the band picked carries on
            if self.source is None:  # the static look is what's playing
                self.base_look = look
            self.static_look = look
            present = set(rig.present)
            self.flashes = {f: v for f, v in self.flashes.items() if f in present}
            self.position_override = {f: v for f, v in self.position_override.items() if f in present}
            if self.find not in present:
                self.find = None
            self.frames = {}
            for d in self.drivers:
                if isinstance(d, NodeSerialDriver):
                    d.link.health.expect(rig.nodes)
            self.hint_drivers()
        self._wake.set()

    def hint_drivers(self) -> None:
        """Tell drivers that can send short frames (`channels: patched`) the last patched channel per universe."""
        last: dict[int, int] = {}
        for fx in self.rig.fixtures:
            last[fx.universe] = max(last.get(fx.universe, 0), fx.address + fx.type.footprint - 1)
        for d in self.drivers:
            if hasattr(d, "patched_slots"):
                d.patched_slots = dict(last)

    # ------------------------------------------------------------------ output

    def _state(self, now: float) -> ControlState:
        gate, gate_all = 1.0, False
        start = getattr(self, "_gate_start", None)
        fade = self.rig.release_fade_s
        if start is not None and fade > 0 and now - start < fade:
            gate, gate_all = max(0.0, (now - start) / fade), self._gate_all
        return ControlState(self.master, self.blackout, self.flashes, self.haze.tick(now), now, gate, gate_all)

    def output(self) -> dict[int, bytearray]:
        """Render and send now. Called by the loop and directly by anything that must not wait."""
        with self.lock:
            now = self.clock()
            for fid in [f for f, fl in self.flashes.items() if fl.until <= now]:
                del self.flashes[fid]
            if self._preview is not None and now >= self._preview[0]:
                _, self.source, self.scene, self.base_look = self._preview
                self._preview = None
            if isinstance(self.source, Crossfade) and self.source.done(now):
                self.source = self.source.new  # fade finished: drop the old look
            # start from the clean base every frame: overrides are laid over it, never baked in
            look = self.source(now) if self.source is not None else self.base_look
            if self.position_override:
                look = self._with_positions(look)
            if self.overrides:
                look, self.overrides = apply_with_releases(look, self.overrides, now)
            self.look = look
            if self.find is not None:
                frames = self._render_find(now)
            else:
                frames = self.rules.render(self.look, self._state(now), self.masters)
            for (uni, ch), val in self.channel_test.items():
                if uni in frames:
                    frames[uni][ch - 1] = val
            self.frames = frames  # only a frame that rendered completely replaces the last good one
            self._send(frames, self._test_frame(now))
            return frames

    def _test_frame(self, now: float) -> tuple[int, int | None, bytearray] | None:
        tp = self.test
        if tp is None:
            return None
        if now >= tp.until():
            self._end_test("timed out")
            return None
        return tp.universe, tp.output, testpattern.render(self.rig, tp, self.rules.out_position, now)

    def _send(self, frames: dict[int, bytearray], test: tuple[int, int | None, bytearray] | None = None) -> None:
        for i, drv in enumerate(self.drivers):
            out = frames
            if test is not None and (test[1] is None or test[1] == i):  # the test replaces its universe there
                out = {**frames, test[0]: test[2]}
            for uni, frame in out.items():
                try:
                    drv.send(uni, bytes(frame))
                except Exception:
                    self.driver_errors += 1
                    self._log_once(f"output driver {drv.name} failed", exc=True)
        self.frames_sent += 1
        for fn in self.on_frame:
            try:
                fn(frames)
            except Exception:
                self._log_once(f"frame listener {getattr(fn, '__name__', fn)} failed", exc=True)

    def _log_once(self, msg: str, exc: bool = False, every_s: float = 60.0) -> None:
        """Log a repeating problem once a minute, not 40 times a second."""
        now = self.clock()
        if now - self._logged.get(msg, -math.inf) >= every_s:
            self._logged[msg] = now
            (log.exception if exc else log.error)(msg)

    def _safe_output(self) -> None:
        """Render and send, and never let an error stop the show."""
        try:
            self.output()
        except Exception as e:  # noqa: BLE001 - anything at all: the lights must keep going
            self._fault(e)

    def _fault(self, e: Exception) -> None:
        with self.lock:
            self.faults += 1
            self.fault = f"{type(e).__name__}: {e}"
            self.fault_at = self.clock()
            self._log_once(f"render failed, back to the static look: {self.fault}", exc=True)
            # drop whatever was playing and fall back to the static look
            self._preview = None
            self.source, self.scene = None, None
            self.look = self.base_look = self.static_look
            try:
                self.output()
            except Exception as e2:  # noqa: BLE001
                self.fault = f"{type(e2).__name__}: {e2} (holding the last good frame)"
                self._log_once(f"static look failed too, holding the last good frame: {e2}", exc=True)
                if self.frames:
                    self._send(self.frames)

    def tick(self) -> None:
        """One loop step: advance fades, then render and send. Never raises (see _fault)."""
        with self.lock:
            now = self.clock()
            self.masters.tick(max(0.0, now - self._last_tick))
            self._last_tick = now
            self._safe_output()

    def flash_deadline(self) -> float:
        """When the earliest running flash ends (inf if none), so the loop can cut it exactly."""
        with self.lock:
            return min((f.until for f in self.flashes.values()), default=float("inf"))

    # ------------------------------------------------------------------ loop thread

    def start(self) -> None:
        if self._thread:
            return
        self._stop.clear()
        self._end_timer = high_res()  # 1 ms timer on Windows while running
        self._thread = threading.Thread(target=self._run, name="engine", daemon=True)
        self._thread.start()

    def loop_step(self, next_tick: float) -> tuple[float, float]:
        """One pass of the loop: tick if a frame is due (the 40 Hz grid) or a flash has just ended.
        Returns (next grid time, how long to wait). Early wakes (control changes, fader moves)
        never move the grid, so a burst of changes can't push frames into the future."""
        now = self.clock()
        due = now >= next_tick
        if due or self.flash_deadline() <= now:
            self.tick()
        if due:
            period = 1 / FRAME_HZ
            next_tick += period * (math.floor((now - next_tick) / period) + 1)  # next grid point after now
        return next_tick, max(0.0, min(next_tick, self.flash_deadline()) - self.clock())

    def _run(self) -> None:
        next_tick = self.clock()
        while not self._stop.is_set():
            self._wake.clear()  # before looking, so a change made meanwhile wakes the wait at once
            try:
                next_tick, wait = self.loop_step(next_tick)
            except Exception as e:  # noqa: BLE001 - tick never raises; this is the last line of defence
                self._fault(e)
                next_tick, wait = self.clock() + 1 / FRAME_HZ, 1 / FRAME_HZ
            self._wake.wait(wait)

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=1)
            self._thread = None
        getattr(self, "_end_timer", lambda: None)()
        self._end_timer = lambda: None
        for d in self.drivers:
            d.close()

    def _changed(self) -> None:
        """Control change: send now rather than on the next tick. The loop only re-plans its wait
        (a new flash end), it doesn't render the same frame again."""
        self._safe_output()
        self._wake.set()

    # ------------------------------------------------------------------ controls

    def set_look(self, look: Look) -> None:
        with self.lock:
            self._preview = None
            self.source, self.scene = None, None
            self.look = self.base_look = look
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
            prev = self._preview[1:] if self._preview else (self.source, self.scene, self.base_look)
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
                _, src, self.scene, look = self._preview
                self._preview = None
                back = src if src is not None else (lambda now, lk=look: lk)
                fade = self.rig.change_fade_s
                self.source = Crossfade(self.source, back, self.clock(), fade) if fade and self.source else back
                self.look = self.base_look = look
        self._changed()

    def set_source(self, source: Callable[[float], Look], scene: Scene | None = None, fade_s: float = 0.0) -> None:
        """Play any look source (a show, a scene with tap tempo), crossfading from what's on now
        over `fade_s` seconds (0 = cut). The rule layer still applies."""
        with self.lock:
            self._preview = None  # a real selection ends any preview
            if fade_s > 0:
                old = self.source if self.source is not None else (lambda now, lk=self.base_look: lk)
                source = Crossfade(old, source, self.clock(), fade_s)
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
        look = Look(fixtures={self.find: FixtureLook(colour=white)} if self.find else {})
        state = ControlState(True, False, {}, self.haze.tick(now), now)
        frames = self.rules.render(look, state, full)
        for fx in self.rig.fixtures:  # exempt fixtures (kick light) ignore MASTER: dark them explicitly
            if fx.id in self.rig.exempt and fx.id != self.find:
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

    # ------------------------------------------------------------------ test patterns (v5)

    def run_test(self, tp: TestPattern) -> dict[str, Any]:
        """Start a test pattern (replacing one running). Bypasses scenes, autopilot, Override, the grand
        master and MASTER on that universe / interface; head limits still apply, haze stays 0."""
        with self.lock:
            testpattern.check(self.rig, tp, self.haze_slots())
            if tp.output is not None:
                if not 0 <= tp.output < len(self.drivers):
                    raise ValueError(f"no output {tp.output}")
                drv = self.drivers[tp.output]
                if drv.universe is not None:
                    tp.universe = drv.universe
            tp.started = self.clock()
            self.test = tp
            self._log_test("start", tp)
        self._changed()
        return tp.view(self.clock())

    def stop_test(self, why: str = "stopped") -> bool:
        with self.lock:
            had = self.test is not None
            self._end_test(why)
        if had:
            self._changed()
        return had

    def _end_test(self, why: str) -> None:
        if self.test is not None:
            self._log_test(why, self.test)
            self.test = None

    def _log_test(self, what: str, tp: TestPattern) -> None:
        self.test_log = (self.test_log + [{"time": time.time(), "what": what, "pattern": tp.pattern,
                                            "universe": tp.universe, "output": tp.output, "by": tp.by}])[-50:]
        log.info("TEST %s: %s on U%s%s", what, testpattern.NAMES[tp.pattern], tp.universe,
                 f" output {tp.output}" if tp.output is not None else "")

    def test_status(self) -> dict[str, Any] | None:
        with self.lock:
            return self.test.view(self.clock()) if self.test is not None else None

    def clear_setup(self) -> None:
        with self.lock:
            self.find = None
            self.channel_test.clear()
        self._changed()

    # ------------------------------------------------------------------ busking

    def hold(self, o: Override) -> None:
        """Lay an override over the show (replacing one with the same key)."""
        with self.lock:
            self.overrides = [x for x in self.overrides if x.key != o.key] + [o]
        self._changed()

    def release(self, key: str, fade_s: float = 0.0) -> bool:
        with self.lock:
            found = False
            for o in self.overrides:
                if o.key == key and o.released_at is None:
                    o.released_at, o.fade_s, found = self.clock(), fade_s, True
            if fade_s <= 0:
                self.overrides = [o for o in self.overrides if o.key != key]
        self._changed()
        return found

    def release_all(self, fade_s: float = 0.0) -> None:
        with self.lock:
            now = self.clock()
            for o in self.overrides:
                if o.released_at is None:
                    o.released_at, o.fade_s = now, fade_s
            if fade_s <= 0:
                self.overrides = []
        self._changed()

    def held(self) -> list[Override]:
        with self.lock:
            return [o for o in self.overrides if o.released_at is None]

    def set_master(self, on: bool) -> None:
        with self.lock:
            if on and not self.master:  # control priority: MASTER back on fades the show in (release_fade_s)
                self._gate_start, self._gate_all = self.clock(), False
            self.master = on
            if on:
                self.flashes.clear()
        self._changed()

    def toggle_master(self) -> None:
        self.set_master(not self.master)

    def set_blackout(self, on: bool) -> None:
        with self.lock:
            if self.blackout and not on:  # blackout released: everything fades back in (release_fade_s)
                self._gate_start, self._gate_all = self.clock(), True
            self.blackout = on
        self._changed()

    def toggle_blackout(self) -> None:
        self.set_blackout(not self.blackout)

    def flash(
        self,
        fixtures: list[str],
        velocity: int = 127,
        length_ms: int = 100,
        min_level: float = FLASH_MIN_LEVEL,
    ) -> bool:
        """Drum hit (v7: a gate). Only with MASTER off, and only if the rig's profile has drum flash
        (rule 2): the ticked lights open for the hit and show what the playing look has on them right
        now (colour, pixels, wheel, gobo, shutter), at a level from the pad's min level (soft hit) to
        full (hardest). Nothing is added: a light the look leaves dark stays dark. Sends a frame
        immediately; the loop wakes to cut back to black exactly when the flash ends. Returns False if
        ignored."""
        with self.lock:
            if not self.rig.profile.drum_flash or self.master or self.blackout:
                return False
            level = flash_level(velocity, min_level)
            until = self.clock() + length_ms / 1000
            for fid in fixtures:
                if fid in self.rig.present and fid not in self.rig.exempt:  # rule 3
                    self.flashes[fid] = Flash(level, until)
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
            if pressed:
                ok = self.haze.boost_press(now)
            else:
                self.haze.boost_release(now)
                ok = True
        self._changed()
        return ok

    def haze_preset(self, name: str) -> None:
        with self.lock:
            self.haze.apply_preset(name, self.clock())
        self._changed()

    def haze_test(self, mode: str) -> float:
        with self.lock:
            span = self.haze.test(mode, self.clock())
        self._changed()
        return span

    def haze_settings(self, cfg: HazeConfig) -> None:
        """Try haze settings live (the Haze settings panel) without saving them."""
        with self.lock:
            self.haze.reconfigure(cfg, self.clock())
        self._changed()

    def haze_stop(self) -> None:
        with self.lock:
            self.haze.stop(self.clock())
        self._changed()
