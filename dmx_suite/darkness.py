"""Autopilot Darkness (v6): black put into the Autopilot's effects. Not a dimmer.

Each Autopilot look renders at effective_lit = look lit x (1 - darkness), so at 0 the looks play as
programmed and at 100 % the rig is black except the exempt kick light, which keeps its look's own lit.
Black is colour off; dimmers, MASTER, haze and Override are untouched. Hand-programmed scenes and shows
play as authored (darkness is only handed to the Autopilot's scene player).

Manual (v6): the value comes from the rig's `autopilot: darkness:` at load, the LOW / MID / HIGH set's
`set_darkness` when the mood changes, then the slider or a MIDI CC (FCB1010 expression pedal) until the
next set change. Every change eases in over the look's fade, so the pedal never steps.

Auto (v7): two markers, Min and Max. On each change of the Darkness layer (A4: its own clock when
staggered, every look when together) it goes to Max while the time spent at Max so far is below
`time_at_max` %, else to Min (a deficit counter, so the share comes out exact over time). It stays at a
marker at least `hold_s` (default: the Darkness layer's interval), so it never flips on consecutive ticks.
Touching the slider, the pedal or Claude's set_autopilot in Auto drops back to Manual (shown on the page).
Each set can carry its own mode, value, markers and time at Max.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

MOODS = ("low", "mid", "high")
MIN_EASE_S = 0.15  # even at fade 0 a pedal sweep mustn't step
MAX_EASE_S = 2.0
LIVE = ("slider", "cc", "claude")  # hands on: Auto drops to Manual


def ease_s(fade: float) -> float:
    return MIN_EASE_S + (MAX_EASE_S - MIN_EASE_S) * max(0.0, min(1.0, fade))


def _auto(d: dict[str, Any] | None) -> dict[str, Any]:
    d = d or {}
    return {"min": float(d.get("min", 0)) / 100, "max": float(d.get("max", 60)) / 100,
            "time_at_max": float(d.get("time_at_max", 30)) / 100,
            "hold_s": None if d.get("hold_s") is None else float(d["hold_s"])}


class Darkness:
    """Callable(now) -> darkness 0-1 as it should render now (eased)."""

    def __init__(self, clock: Callable[[], float], mood: Callable[[], str],
                 interval: Callable[[], float] | None = None) -> None:
        self.clock, self.mood = clock, mood
        self.interval = interval or (lambda: 40.0)  # the Darkness layer's interval (the hold default)
        self._lock = threading.Lock()
        self.default = 0.0
        self.sets: dict[str, float | None] = {m: None for m in MOODS}
        self.set_cfg: dict[str, dict[str, Any] | None] = {m: None for m in MOODS}  # v7: a set's mode / markers
        self.target = 0.0
        self.source = "default"  # default / set / slider / cc / claude / auto
        self.fade = 0.5  # the playing look's feel fade (0-1): soft edges and easing
        self._from, self._at, self._dur = 0.0, -1e9, MIN_EASE_S
        self._mood: str | None = None
        self.cc: dict[str, Any] | None = None  # the input mapped to it (for status)
        # v7 Auto
        self.rig_mode = "manual"
        self.rig_auto = _auto(None)
        self.mode = "manual"
        self.auto = _auto(None)
        self.dropped = False  # Auto just dropped to Manual because someone moved the slider / pedal
        self._marker: str | None = None  # "min" / "max" while in Auto
        self._since = 0.0  # when the current marker was chosen
        self._acct = 0.0  # last time the marker totals were brought up to date
        self._at_max = 0.0  # seconds spent at Max / at either marker, since Auto started
        self._total = 0.0

    def configure(self, cfg: dict[str, Any]) -> None:
        """The rig's autopilot block (darkness and set_darkness in %, v7 darkness_mode / darkness_auto)."""
        with self._lock:
            self.default = float(cfg.get("darkness", 0)) / 100
            sd = cfg.get("set_darkness") or {}
            self.sets, self.set_cfg = {}, {}
            for m in MOODS:
                v = sd.get(m)
                if isinstance(v, dict):
                    self.sets[m] = None if v.get("value") is None else float(v["value"]) / 100
                    self.set_cfg[m] = v
                else:
                    self.sets[m] = None if v is None else float(v) / 100
                    self.set_cfg[m] = None
            mode, auto = str(cfg.get("darkness_mode", "manual")), _auto(cfg.get("darkness_auto"))
            changed = (mode, auto) != (self.rig_mode, self.rig_auto)
            self.rig_mode, self.rig_auto = mode, auto
            now = self.clock()
            if changed and self.source in ("default", "auto"):
                self._mode(mode, auto, now)
            if self.source == "default" and self.mode == "manual":
                self._go(self.default, "default", now)

    # ------------------------------------------------------------------ easing

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

    # ------------------------------------------------------------------ v7 Auto

    def _mode(self, mode: str, auto: dict[str, Any], now: float) -> None:
        self.mode, self.auto = mode, auto
        if mode == "auto":
            self._marker, self._since, self._acct, self._at_max, self._total = "min", now, now, 0.0, 0.0
            self._go(auto["min"], "auto", now)
        else:
            self._marker = None

    def _account(self, now: float) -> None:
        dt = max(0.0, now - self._acct)
        self._acct = now
        self._total += dt
        if self._marker == "max":
            self._at_max += dt

    def hold_s(self) -> float:
        h = self.auto.get("hold_s")
        return float(self.interval()) if h is None else float(h)

    def step(self, now: float | None = None, why: str = "") -> str | None:
        """The Darkness layer changed (A4): in Auto, maybe move to the other marker. Returns the marker."""
        with self._lock:
            now = self.clock() if now is None else now
            self._sync_mood(now)
            if self.mode != "auto":
                return None
            self._account(now)
            if now - self._since < self.hold_s() - 1e-6:
                return self._marker  # minimum hold at a marker
            share = self._at_max / self._total if self._total > 0 else 0.0
            want = "max" if share < self.auto["time_at_max"] else "min"
            if self.auto["time_at_max"] <= 0:
                want = "min"
            elif self.auto["time_at_max"] >= 1:
                want = "max"
            if want != self._marker:
                self._marker, self._since = want, now
                self._go(self.auto[want], "auto", now)
            return self._marker

    def set_auto(self, mode: str | None = None, mn: float | None = None, mx: float | None = None,
                 time_at_max: float | None = None, hold_s: float | None = None, source: str = "claude") -> None:
        """Live mode / markers (0-1, time_at_max 0-1); held until the next set change, like a slider move."""
        with self._lock:
            now = self.clock()
            auto = dict(self.auto)
            for k, v in (("min", mn), ("max", mx), ("time_at_max", time_at_max)):
                if v is not None:
                    auto[k] = max(0.0, min(1.0, float(v)))
            if hold_s is not None:
                auto["hold_s"] = float(hold_s)
            if auto["min"] > auto["max"]:
                raise ValueError("darkness min is above max")
            mode = mode or self.mode
            if mode not in ("manual", "auto"):
                raise ValueError("darkness mode is manual or auto")
            self.dropped = False
            if mode == "auto" and (self.mode != "auto" or auto != self.auto):
                was = self._marker
                self._mode("auto", auto, now)
                if was == "max":  # markers moved while at Max: stay there
                    self._marker = "max"
                    self._go(auto["max"], "auto", now)
            elif mode == "manual" and self.mode == "auto":
                self._mode("manual", auto, now)
                self.source = source
            else:
                self.auto = auto

    # ------------------------------------------------------------------ live value

    def set(self, v: float, source: str = "slider") -> float:
        with self._lock:
            now = self.clock()
            if self.mode == "auto" and source in LIVE:  # hands on: back to Manual, shown on the page
                self._mode("manual", self.auto, now)
                self.dropped = True
            self._go(v, source, now)
            return self.target

    def _sync_mood(self, now: float) -> None:
        mood = self.mood()
        if mood == self._mood:
            return
        first = self._mood is None
        self._mood = mood
        sc = self.set_cfg.get(mood)
        if sc is not None and sc.get("mode") is not None:  # v7: the set brings its own mode and markers
            auto = _auto({**{k: v * 100 if k != "hold_s" and v is not None else v for k, v in self.rig_auto.items()},
                          **{k: v for k, v in sc.items() if k in ("min", "max", "time_at_max", "hold_s")}})
            self.dropped = False
            if sc["mode"] == "auto":
                self._mode("auto", auto, now)
                return
            self._mode("manual", auto, now)
        elif first and self.rig_mode == "auto" and self.mode != "auto":
            self._mode("auto", self.rig_auto, now)
            return
        v = self.sets.get(mood)
        if v is not None:
            self.dropped = False
            if self.mode == "auto":
                self._mode("manual", self.auto, now)
            self._go(v, "set", now)
        elif not first and self.source in LIVE:
            pass  # no default stored for this set: the live value carries on

    def __call__(self, now: float) -> float:
        with self._lock:
            self._sync_mood(now)
            return self._value(now)

    def status(self, now: float | None = None) -> dict[str, Any]:
        now = self.clock() if now is None else now
        with self._lock:
            share = None
            if self.mode == "auto":
                total = self._total + max(0.0, now - self._acct)
                at_max = self._at_max + (max(0.0, now - self._acct) if self._marker == "max" else 0.0)
                share = round(100 * at_max / total, 1) if total > 0 else 0.0
            return {"darkness": round(self.target * 100, 1), "now": round(self._value(now) * 100, 1),
                    "source": self.source, "set_darkness": {m: (None if v is None else round(v * 100, 1))
                                                            for m, v in self.sets.items()},
                    "default": round(self.default * 100, 1), "cc": self.cc,
                    "mode": self.mode, "min": round(self.auto["min"] * 100, 1), "max": round(self.auto["max"] * 100, 1),
                    "time_at_max": round(self.auto["time_at_max"] * 100, 1), "hold_s": round(self.hold_s(), 1),
                    "marker": self._marker, "share_at_max": share, "dropped": self.dropped}
