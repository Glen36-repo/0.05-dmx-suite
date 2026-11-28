"""Drum bus (v3.3): recent hits on named inputs, by role, for the drum-reactive effects and (V3.4)
the autopilot's energy. MIDI only: the band's own pads and pedals, no audio.

The router feeds every named input hit in (App); effects read it with the engine's clock time.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Hit:
    time: float
    input: str
    roles: tuple[str, ...]
    strength: float  # 0-1 after the input's velocity curve


class DrumBus:
    def __init__(self, keep_s: float = 30.0, size: int = 4000) -> None:
        self.hits: deque[Hit] = deque(maxlen=size)
        self.keep_s = keep_s
        self._lock = threading.Lock()

    def add(self, input_id: str, roles: list[str] | tuple[str, ...], strength: float, now: float) -> None:
        with self._lock:
            self.hits.append(Hit(now, input_id, tuple(roles), max(0.0, min(1.0, strength))))
            while self.hits and now - self.hits[0].time > self.keep_s:
                self.hits.popleft()

    def recent(self, role: str | None, now: float, window_s: float) -> list[Hit]:
        """Hits with this role (any role when None) in the last `window_s` seconds, oldest first."""
        with self._lock:
            return [h for h in self.hits if now - window_s <= h.time <= now and (role is None or role in h.roles)]

    def last(self, role: str | None, now: float) -> Hit | None:
        with self._lock:
            for h in reversed(self.hits):
                if h.time <= now and (role is None or role in h.roles):
                    return h
        return None

    def count(self, role: str | None, now: float, window_s: float) -> int:
        return len(self.recent(role, now, window_s))

    def clear(self) -> None:
        with self._lock:
            self.hits.clear()


BUS = DrumBus()  # the running app's; tests make their own or clear it
