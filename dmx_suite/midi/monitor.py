"""MIDI monitor: what came in, from where, and what it triggered (or 'unmapped')."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

NOTES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def note_name(n: int) -> str:
    """MIDI note number as a name, middle C (60) = C4."""
    return f"{NOTES[n % 12]}{n // 12 - 1}" if 0 <= n <= 127 else ""


@dataclass
class MonitorEntry:
    time: float  # wall clock
    port: str
    channel: int  # 1-16
    type: str  # note / note_off / program_change / control_change / other
    number: int
    value: int  # velocity / CC value / 0
    result: str  # what it triggered, or "unmapped"
    input: str = ""  # named input(s) it was, e.g. "Kick" (v3)
    seq: int = 0  # set by the monitor; lets the UI ask for "everything after N"
    note: str = ""  # v4: note name (C4) for notes
    roles: str = ""  # v4: the named input's roles (kick, snare ...)
    direction: str = "in"  # v4: in (from gear) / out (sent by the app)
    since_start: float = 0.0  # v4: seconds since the monitor started (engine start)

    def format(self) -> str:
        t = time.strftime("%H:%M:%S", time.localtime(self.time)) + f".{int(self.time * 1000) % 1000:03d}"
        who = ""
        if self.input:
            who = f"{self.input}, vel {self.value}  " if self.type == "note_on" else f"{self.input}  "
        return (f"{t}  {self.port[:20]:20}  ch{self.channel:<2}  {self.type:14}  {self.number:3}  {self.value:3}  "
                f"{who}{self.result}")


class MidiMonitor:
    def __init__(self, size: int = 5000) -> None:
        self.entries: deque[MonitorEntry] = deque(maxlen=size)
        self.started = time.time()
        self.clock_times: deque[float] = deque(maxlen=200)  # MIDI clock: counted, not logged row by row
        self.paused = False
        self.listeners: list[Callable[[MonitorEntry], None]] = []
        self._lock = threading.Lock()
        self.seq = 0

    def add(self, e: MonitorEntry) -> None:
        with self._lock:
            if self.paused:
                return
            self.seq += 1
            e.seq = self.seq
            e.since_start = round(e.time - self.started, 3)
            self.entries.append(e)
            listeners = list(self.listeners)
        for fn in listeners:  # outside the lock: a listener may read the monitor
            fn(e)

    def since(self, seq: int) -> list[MonitorEntry]:
        """Entries after `seq`, copied under the lock (MIDI and OSC threads keep adding)."""
        with self._lock:
            return [e for e in self.entries if e.seq > seq]

    def clock(self, now: float | None = None) -> None:
        self.clock_times.append(time.time() if now is None else now)

    def rates(self, window_s: float = 4.0, now: float | None = None) -> dict[str, float]:
        """Hits a second (note-ons) and MIDI clock ticks a second over the last few seconds."""
        now = time.time() if now is None else now
        with self._lock:
            hits = sum(1 for e in self.entries if e.type == "note_on" and e.value > 0 and now - e.time <= window_s)
            clocks = sum(1 for t in self.clock_times if now - t <= window_s)
        return {"hits_per_s": round(hits / window_s, 2), "clock_per_s": round(clocks / window_s, 1)}

    def query(self, n: int = 50, port: str | None = None, channel: int | None = None, kind: str | None = None,
              unmapped: bool = False, since: int = 0) -> list[MonitorEntry]:
        """The last n entries matching the filters (Monitor page, Claude)."""
        with self._lock:
            out = [e for e in self.entries if e.seq > since
                   and (not port or port.lower() in e.port.lower()) and (not channel or e.channel == channel)
                   and (not kind or e.type.startswith(kind)) and (not unmapped or e.result == "unmapped")]
        return out[-n:] if n else out

    def clear(self) -> None:
        with self._lock:
            self.entries.clear()

    def filtered(self, port: str | None = None, channel: int | None = None) -> list[MonitorEntry]:
        with self._lock:
            return [
                e
                for e in self.entries
                if (port is None or e.port == port) and (channel is None or e.channel == channel)
            ]
