"""MIDI monitor: what came in, from where, and what it triggered (or 'unmapped')."""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable


@dataclass
class MonitorEntry:
    time: float  # wall clock
    port: str
    channel: int  # 1-16
    type: str  # note / note_off / program_change / control_change / other
    number: int
    value: int  # velocity / CC value / 0
    result: str  # what it triggered, or "unmapped"
    seq: int = 0  # set by the monitor; lets the UI ask for "everything after N"

    def format(self) -> str:
        t = time.strftime("%H:%M:%S", time.localtime(self.time)) + f".{int(self.time * 1000) % 1000:03d}"
        return f"{t}  {self.port[:20]:20}  ch{self.channel:<2}  {self.type:14}  {self.number:3}  {self.value:3}  {self.result}"


class MidiMonitor:
    def __init__(self, size: int = 1000) -> None:
        self.entries: deque[MonitorEntry] = deque(maxlen=size)
        self.paused = False
        self.listeners: list[Callable[[MonitorEntry], None]] = []
        self._lock = threading.Lock()
        self.seq = 0

    def add(self, e: MonitorEntry) -> None:
        if self.paused:
            return
        with self._lock:
            self.seq += 1
            e.seq = self.seq
            self.entries.append(e)
        for fn in self.listeners:
            fn(e)

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
