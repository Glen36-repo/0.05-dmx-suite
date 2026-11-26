"""MIDI router: incoming message -> mapping -> engine action. Also MIDI learn."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from ..engine import Engine
from .map import ACTIONS, Mapping, MidiMap, validate
from .monitor import MidiMonitor, MonitorEntry

PHASE4 = {"select_show", "select_set", "next_song"}


@dataclass
class Incoming:
    """A MIDI message, normalised. `pressed` is False for note-off / velocity 0 / CC < 64."""

    type: str  # note / program_change / control_change / other
    channel: int  # 1-16
    number: int
    value: int
    pressed: bool
    raw_type: str

    @classmethod
    def from_mido(cls, msg: Any) -> "Incoming":
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
        return cls("other", ch, 0, 0, False, t)


class MidiRouter:
    def __init__(self, engine: Engine, midimap: MidiMap, monitor: MidiMonitor | None = None) -> None:
        self.engine = engine
        self.map = midimap
        self.monitor = monitor or MidiMonitor()
        self._learn: tuple[str, dict[str, Any], Callable[[Mapping], None] | None] | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ learn

    def learn(self, action: str, params: dict[str, Any] | None = None, on_learned: Callable[[Mapping], None] | None = None) -> None:
        """Arm learn: the next note-on / PC / CC becomes the input for `action`."""
        if action not in ACTIONS:
            raise ValueError(f"unknown action {action!r}")
        # validate params now with a dummy input so a bad learn fails before the pedal press
        dummy_type = "control_change" if action in ("grand_master", "sub_master", "flash_level") else "note"
        validate(Mapping(dummy_type, 1, 0, action, dict(params or {})))
        with self._lock:
            self._learn = (action, dict(params or {}), on_learned)

    def cancel_learn(self) -> None:
        with self._lock:
            self._learn = None

    @property
    def learning(self) -> str | None:
        return self._learn[0] if self._learn else None

    # ------------------------------------------------------------------ handling

    def handle_mido(self, msg: Any, port: str = "") -> str:
        return self.handle(Incoming.from_mido(msg), port)

    def handle(self, m: Incoming, port: str = "") -> str:
        result = self._route(m)
        self.monitor.add(
            MonitorEntry(time.time(), port, m.channel, m.raw_type, m.number, m.value, result)
        )
        return result

    def _route(self, m: Incoming) -> str:
        if m.type == "other":
            return "ignored"
        # learn takes any CC value (a pedal may start low), note-ons and program changes
        learnable = m.pressed or m.type == "control_change"
        with self._lock:
            learn = self._learn
            if learn and learnable:
                action, params, cb = learn
                if action in ("grand_master", "sub_master", "flash_level") and m.type != "control_change":
                    return "learn: needs a CC (move a pedal or knob)"
                mapping = Mapping(m.type, m.channel, m.number, action, params)
                self.map.add(mapping)
                self._learn = None
        if learn and learnable:
            if cb:
                cb(mapping)
            return f"learned: {mapping.describe()}"

        mp = self.map.get(m.type, m.channel, m.number)
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
        if a in ("grand_master", "sub_master", "flash_level"):
            level = m.value / 127
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
        if a in PHASE4:
            return f"{mp.describe()} (not available until phase 4)"
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
        if a == "master_toggle":
            return f"MASTER {'on' if e.master else 'off'}"
        if a == "blackout_toggle":
            return f"blackout {'on' if e.blackout else 'off'}"
        return a
