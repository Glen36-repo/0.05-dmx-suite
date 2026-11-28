"""Autopilot Darkness (v6): black put into the Autopilot's effects. Not a dimmer.

Each Autopilot look renders at effective_lit = look lit x (1 - darkness), so at 0 the looks play as
programmed and at 100 % the rig is black except the exempt kick light, which keeps its look's own lit.
Black is colour off; dimmers, MASTER, haze and Override are untouched. Hand-programmed scenes and shows
play as authored (darkness is only handed to the Autopilot's scene player).

Where the value comes from: the rig's `autopilot: darkness:` at load, the LOW / MID / HIGH set's
`set_darkness` when the mood changes, then the slider or a MIDI CC (FCB1010 expression pedal) until the
next set change. Every change eases in over the look's fade, so the pedal never steps.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

MOODS = ("low", "mid", "high")
MIN_EASE_S = 0.15  # even at fade 0 a pedal sweep mustn't step
MAX_EASE_S = 2.0


def ease_s(fade: float) -> float:
    return MIN_EASE_S + (MAX_EASE_S - MIN_EASE_S) * max(0.0, min(1.0, fade))


class Darkness:
    """Callable(now) -> darkness 0-1 as it should render now (eased)."""

    def __init__(self, clock: Callable[[], float], mood: Callable[[], str]) -> None:
        self.clock, self.mood = clock, mood
        self._lock = threading.Lock()
        self.default = 0.0
        self.sets: dict[str, float | None] = {m: None for m in MOODS}
        self.target = 0.0
        self.source = "default"  # default / set / slider / cc / claude
        self.fade = 0.5  # the playing look's feel fade (0-1): soft edges and easing
        self._from, self._at, self._dur = 0.0, -1e9, MIN_EASE_S
        self._mood: str | None = None
        self.cc: dict[str, Any] | None = None  # the input mapped to it (for status)

    def configure(self, cfg: dict[str, Any]) -> None:
        """The rig's autopilot block (darkness and set_darkness in %)."""
        with self._lock:
            self.default = float(cfg.get("darkness", 0)) / 100
            sd = cfg.get("set_darkness") or {}
            self.sets = {m: (float(sd[m]) / 100 if sd.get(m) is not None else None) for m in MOODS}
            if self.source == "default":
                self._go(self.default, "default", self.clock())

    def _value(self, now: float) -> float:
        k = (now - self._at) / self._dur if self._dur > 0 else 1.0
        if k >= 1.0:
            return self.target
        k = max(0.0, k)
        k = k * k * (3 - 2 * k)  # smoothstep
        return self._from + (self.target - self._from) * k

    def _go(self, v: float, source: str, now: float) -> None:
        self._from = self._value(now)
        self.target = max(0.0, min(1.0, v))
        self._at, self._dur, self.source = now, ease_s(self.fade), source

    def set(self, v: float, source: str = "slider") -> float:
        with self._lock:
            self._go(v, source, self.clock())
            return self.target

    def __call__(self, now: float) -> float:
        with self._lock:
            mood = self.mood()
            if mood != self._mood:  # set change: that set's stored darkness (a live move holds until now)
                first = self._mood is None
                self._mood = mood
                v = self.sets.get(mood)
                if v is not None:
                    self._go(v, "set", now)
                elif not first and self.source in ("slider", "cc", "claude"):
                    pass  # no default stored for this set: the live value carries on
            return self._value(now)

    def status(self, now: float | None = None) -> dict[str, Any]:
        now = self.clock() if now is None else now
        with self._lock:
            return {"darkness": round(self.target * 100, 1), "now": round(self._value(now) * 100, 1),
                    "source": self.source, "set_darkness": {m: (None if v is None else round(v * 100, 1))
                                                            for m, v in self.sets.items()},
                    "default": round(self.default * 100, 1), "cc": self.cc}
