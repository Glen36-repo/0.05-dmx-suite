"""MIDI router: incoming message -> mapping -> engine action. Also MIDI learn."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..engine import Engine
from .map import ACTIONS, Mapping, MidiMap, validate
from .monitor import MidiMonitor, MonitorEntry

SHOW_ACTIONS = {"select_show", "select_set", "select_scene", "next_step", "next_song", "prev_song", "tap_tempo"}


@dataclass
class Incoming:
    """A MIDI message, normalised. `pressed` is False for note-off / velocity 0 / CC < 64."""

    type: str  # note / program_change / control_change / osc / other
    channel: int  # 1-16 (0 for OSC)
    number: int
    value: int
    pressed: bool
    raw_type: str
    address: str = ""  # OSC
    level: float | None = None  # OSC fader value 0-1 (MIDI: value / 127)

    @classmethod
    def from_osc(cls, address: str, args: list[Any]) -> Incoming:
        from ..osc import level_of

        lv = level_of(args)
        pressed = True if lv is None else lv >= 0.5
        return cls("osc", 0, 0, round((1.0 if lv is None else lv) * 127), pressed, "osc", address, lv)

    @classmethod
    def from_mido(cls, msg: Any) -> Incoming:
        t = msg.type
        ch = getattr(msg, "channel", 0) + 1
        if t == "note_on":
            return cls("note", ch, msg.note, msg.velocity, msg.velocity > 0, t if msg.velocity else "note_off")
        if t == "note_off":
            return cls("note", ch, msg.note, msg.velocity, False, t)
        if t == "program_change":
            return cls("program_change", ch, msg.program, 0, True, t)
        if t == "control_change":
            return cls("control_change", ch, msg.control, msg.value, msg.value >= 64, t)
        if t in ("clock", "start", "continue", "stop"):
            return cls(t, 0, 0, 0, False, t)
        return cls("other", ch, 0, 0, False, t)


class MidiRouter:
    def __init__(self, engine: Engine, midimap: MidiMap, monitor: MidiMonitor | None = None, shows: Any = None) -> None:
        self.engine = engine
        self.shows = shows  # ShowController
        self.map = midimap
        self.monitor = monitor or MidiMonitor()
        self.busk: Callable[[str, str, bool, float | None], str] | None = None  # App.busk
        # (action, params, callback, port fragment the mapping is tied to)
        self._learn: tuple[str, dict[str, Any], Callable[[Mapping], None] | None, str | None] | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ learn

    def learn(self, action: str, params: dict[str, Any] | None = None,
              on_learned: Callable[[Mapping], None] | None = None) -> None:
        """Arm learn: the next note-on / PC / CC becomes the input for `action`.
        params may include port: "this" (tie the mapping to whichever port the message comes from)
        or a port-name fragment such as "H2MIDI"."""
        if action not in ACTIONS:
            raise ValueError(f"unknown action {action!r}")
        params = dict(params or {})
        port = params.pop("port", None)
        # validate params now with a dummy input so a bad learn fails before the pedal press
        dummy_type = "control_change" if action in ("grand_master", "sub_master", "flash_level", "speed") else "note"
        validate(Mapping(dummy_type, 1, 0, action, dict(params or {})))
        with self._lock:
            self._learn = (action, params, on_learned, port)

    def cancel_learn(self) -> None:
        with self._lock:
            self._learn = None

    @property
    def learning(self) -> str | None:
        return self._learn[0] if self._learn else None

    # ------------------------------------------------------------------ handling

    def handle_mido(self, msg: Any, port: str = "") -> str:
        return self.handle(Incoming.from_mido(msg), port)

    def handle_osc(self, address: str, args: list[Any], source: str = "") -> str:
        return self.handle(Incoming.from_osc(address, args), f"OSC {source}".strip())

    def handle(self, m: Incoming, port: str = "") -> str:
        if m.type in ("clock", "start", "continue", "stop"):  # 24 a beat: not worth a monitor row each
            return self._clock(m)
        result = self._route(m, port)
        kind = f"osc {m.address}" if m.type == "osc" else m.raw_type
        self.monitor.add(
            MonitorEntry(time.time(), port, m.channel, kind, m.number, m.value, result)
        )
        return result

    def _clock(self, m: Incoming) -> str:
        tempo = self.shows.tempo if self.shows is not None else None
        if tempo is None or tempo.source != "midi_clock":
            return "ignored"
        now = self.engine.clock()
        if m.type == "clock":
            tempo.clock_tick(now)
        elif m.type in ("start", "continue"):
            tempo.clock_start(now)
        return m.type

    def _route(self, m: Incoming, port: str = "") -> str:
        if m.type == "other":
            return "ignored"
        tempo = self.shows.tempo if self.shows is not None else None
        if (tempo is not None and tempo.source == "kick" and m.type == "note" and m.pressed
                and m.number == tempo.config.kick_note):
            tempo.kick(self.engine.clock())  # and on to whatever the kick is mapped to
        # learn takes any CC or OSC value (a pedal or fader may start low), note-ons and program changes
        learnable = m.pressed or m.type in ("control_change", "osc")
        with self._lock:
            learn = self._learn
            if learn and learnable:
                action, params, cb, want_port = learn
                if action in ("grand_master", "sub_master", "flash_level", "speed") and m.type not in ("control_change", "osc"):
                    return "learn: needs a CC or OSC fader (move a pedal, knob or fader)"
                if m.type == "osc":
                    mapping = Mapping("osc", 0, 0, action, params, address=m.address)
                else:
                    bind = port if want_port == "this" else want_port
                    mapping = Mapping(m.type, m.channel, m.number, action, params, port=bind or None)
                self.map.add(mapping)
                self._learn = None
        if learn and learnable:
            if cb:
                cb(mapping)
            return f"learned: {mapping.describe()}"

        mp = self.map.get_osc(m.address) if m.type == "osc" else self.map.get(m.type, m.channel, m.number, port)
        if mp is None:
            return "unmapped"
        return self._act(mp, m)

    def _act(self, mp: Mapping, m: Incoming) -> str:
        e, a, p = self.engine, mp.action, mp.params
        if a == "haze_boost":
            ok = e.haze_boost(m.pressed if m.type != "program_change" else True)
            if m.pressed and not ok:
                return "haze boost refused (disabled or cooling down)"
            return "haze boost on" if m.pressed else "haze boost release"
        if a == "busk":
            if self.busk is None:
                return "busk: not running"
            level = m.level if m.level is not None else (m.value / 127 if m.type == "control_change" else None)
            try:
                return self.busk(p["panel"], p["widget"], m.pressed, level)
            except Exception as err:  # a bad press must never stop the show
                return f"busk failed: {err}"
        if a == "speed":
            level = m.level if m.level is not None else m.value / 127
            speed = 4 ** (2 * level - 1)  # fader bottom = quarter speed, middle = as set, top = 4x
            if self.shows is not None:
                self.shows.set_speed(speed)
            return f"speed x{speed:.2f}"
        if a in ("grand_master", "sub_master", "flash_level"):
            level = m.level if m.level is not None else m.value / 127
            if a == "grand_master":
                e.set_grand(level)
            elif a == "sub_master":
                e.set_sub(p["kind"], level)
            else:
                e.set_flash_level(level)
            return f"{mp.describe()} {round(level * 100)}%"
        if not m.pressed:
            return "release"  # note-off / CC up: only boost cares
        if a == "flash":
            fixtures = e.rig.patch.resolve(p["fixtures"])
            vel = m.value if m.type == "note" else 127
            ok = e.flash(fixtures, vel, p.get("colour", "show"), int(p.get("length_ms", 100)), float(p.get("min_level", 0)))
            return f"flash {','.join(p['fixtures'])} vel {vel}" if ok else "flash ignored (MASTER on)"
        if a in SHOW_ACTIONS:
            return self._show_action(a, p)
        simple = {
            "master_on": lambda: e.set_master(True),
            "master_off": lambda: e.set_master(False),
            "master_toggle": e.toggle_master,
            "blackout_on": lambda: e.set_blackout(True),
            "blackout_off": lambda: e.set_blackout(False),
            "blackout_toggle": e.toggle_blackout,
            "haze_off": e.haze_stop,
            "haze_manual": e.haze_toggle_manual,
            "haze_pulse": lambda: e.haze_mode("pulse"),
        }
        simple[a]()
        if a.startswith("master") and self.shows is not None:
            self.shows.save()  # a restart comes back with the same MASTER state
        if a == "master_toggle":
            return f"MASTER {'on' if e.master else 'off'}"
        if a == "blackout_toggle":
            return f"blackout {'on' if e.blackout else 'off'}"
        return a

    def _show_action(self, a: str, p: dict[str, Any]) -> str:
        c = self.shows
        if c is None:
            return f"{a}: no show control running"
        try:
            if a == "tap_tempo":
                bpm = c.tap()
                return f"tap: {bpm:.0f} BPM" if bpm else "tap"
            if a == "select_show":
                c.select_show(p["show"], p.get("set"))
            elif a == "select_set":
                c.select_set(p["set"])
            elif a == "select_scene":
                c.select_scene(p["scene"])
            elif a == "next_step":
                c.next_step()
            elif a == "next_song":
                c.next_song()
            elif a == "prev_song":
                c.prev_song()
        except Exception as e:  # a bad pedal press must never stop the show
            return f"{a} failed: {e}"
        return c.describe()
