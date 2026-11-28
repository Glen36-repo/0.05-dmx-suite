"""Tempo. Effects are written in seconds at a reference tempo of 120 BPM; when a tempo is set,
effect time runs faster or slower so every chase follows the band. Fixed timers stay the
default: with no tempo, effect time is real time.

Where the tempo comes from (rig file `tempo: {source: ...}`):
    drums        v6: the drummer's playing, every drum weighted (beat.py), seeded by a tap, a tap
                 pad or a count-in; freewheels at the last tempo through fills and stops, never
                 back to timers. `kick` (v3) means drums
    tap          a pedal, key or button tapped on the beat (median of the last few taps) only
    midi_clock   MIDI clock from any input (24 ticks a beat); start lines the beat up
    off          the tempo stays where it is (120 BPM if none was ever set)
A MIDI clock that goes quiet keeps its last tempo for `timeout_s`, then effects go back to fixed
timers. `speed` (0.25-4) multiplies whatever the tempo is, e.g. from a busk fader.

Tempo changes never make effect time jump: the clock is piecewise linear and continuous.
"""

from __future__ import annotations

import statistics
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from .beat import BeatParams, BeatTracker

REFERENCE_BPM = 120.0
BEAT_S = 60.0 / REFERENCE_BPM  # one beat in effect time
MIN_BPM, MAX_BPM = 40.0, 240.0
MAX_GAP_S = 60.0 / MIN_BPM  # longer gap starts a new tap sequence
SOURCES = ("drums", "tap", "midi_clock", "off")
SOURCE_ALIASES = {"kick": "drums"}  # v3 name
PPQN = 24  # MIDI clock ticks a beat


@dataclass
class TempoConfig:
    source: str = "tap"
    kick_note: int = 36  # General MIDI kick; the TD-25 sends 36 (only without a kick-role input)
    timeout_s: float = 30.0  # MIDI clock gone quiet this long: back to fixed timers
    beat: BeatParams = field(default_factory=BeatParams)  # v6 drums tracker settings


class TempoClock:
    """Maps real time to effect time."""

    def __init__(self, now: float, config: TempoConfig | None = None) -> None:
        self._lock = threading.Lock()
        self._anchor_real = now
        self._anchor_eff = now
        self.rate = 1.0
        self.bpm: float | None = None
        self.speed = 1.0
        self.tracker = BeatTracker(now)
        self._drum_anchor: tuple[float, float] | None = None  # (tracker beats, effect time) while following drums
        self.config = config or TempoConfig()
        self.last_input: float | None = None
        self.lost = False  # the kick / clock stopped and timers took over
        self._taps: list[float] = []
        self._kicks: deque[float] = deque(maxlen=9)
        self._ticks: deque[float] = deque(maxlen=PPQN * 2 + 1)

    @property
    def config(self) -> TempoConfig:
        return self._config

    @config.setter
    def config(self, c: TempoConfig) -> None:
        self._config = c
        self.tracker.p = c.beat

    @property
    def source(self) -> str:
        return SOURCE_ALIASES.get(self.config.source, self.config.source)

    # ---------------------------------------------------------------- drums (v6)

    def _drums_on(self) -> bool:
        return self.source == "drums" and self.tracker.out_bpm is not None

    def _drum_eff(self, now: float) -> float:
        """Effect time while following the drums: the tracker's beat clock (continuous, rate-nudged)."""
        self.tracker.update(now)
        b = self.tracker.beats(now)
        if self._drum_anchor is None:
            self._drum_anchor = (b, self._anchor_eff + (now - self._anchor_real) * self.rate)
        b0, e0 = self._drum_anchor
        bpm = self.tracker.out_bpm
        self.bpm = bpm
        return e0 + (b - b0) * BEAT_S * self.speed

    def _leave_drums(self, now: float) -> None:
        """Hand effect time back to the linear clock where the drums left it (no jump)."""
        if self._drum_anchor is not None:
            eff = self._drum_eff(now)
            self._drum_anchor = None
            self._anchor_real, self._anchor_eff = now, eff
            self.rate = ((self.bpm or REFERENCE_BPM) / REFERENCE_BPM) * self.speed

    def hit(self, roles: list[str] | tuple[str, ...], velocity: int, now: float) -> None:
        """A drum hit (named input with roles): onset for the tracker; a tap pad taps; count-in pads count in."""
        with self._lock:
            if self.source != "drums":
                return
            if "count_in" in roles:
                bpm = self.tracker.count_in_hit(now)
                if bpm is not None:
                    self._seeded(now, bpm)
            if "tap" in roles:
                self._tap(now)
                return
            self.tracker.hit(roles, velocity, now)

    def _seeded(self, now: float, bpm: float) -> None:
        """The tracker was seeded: effect time carries on from here at the new tempo."""
        eff = self._drum_eff(now) if self._drum_anchor is not None else self._anchor_eff + (now - self._anchor_real) * self.rate
        self._drum_anchor = (self.tracker.beats(now), eff)
        self.bpm = bpm
        self.last_input, self.lost = now, False

    def set_source(self, source: str, now: float) -> None:
        source = SOURCE_ALIASES.get(source, source)
        if source not in SOURCES:
            raise ValueError(f"tempo source: {', '.join(SOURCES)}")
        with self._lock:
            if self.source == "drums" and source != "drums":
                self._leave_drums(now)
            self._config = TempoConfig(source, self.config.kick_note, self.config.timeout_s, self.config.beat)
            self.tracker.p = self.config.beat
            if source == "drums" and self.bpm:  # start from the tempo we have
                self.tracker.seed(self.bpm, now, "previous")
                self._drum_anchor = None
            if source == "off" and self.bpm is None:
                self._set(now, REFERENCE_BPM)

    def set_params(self, changes: dict[str, Any]) -> BeatParams:
        with self._lock:
            p = self.config.beat.update(changes)
            self._config = TempoConfig(self.config.source, self.config.kick_note, self.config.timeout_s, p)
            self.tracker.p = p
            return p

    # ---------------------------------------------------------------- effect time

    def eff(self, now: float) -> float:
        with self._lock:
            if self._drums_on():
                return self._drum_eff(now)
            self._check_lost(now)
            return self._anchor_eff + (now - self._anchor_real) * self.rate

    def _check_lost(self, now: float) -> None:
        if (self.source == "midi_clock" and self.bpm is not None and self.last_input is not None
                and now - self.last_input > self.config.timeout_s):
            self._set(now, None)
            self.lost = True

    def _rebase(self, now: float, rate: float, snap: bool = False) -> None:
        eff = self._anchor_eff + (now - self._anchor_real) * self.rate
        if snap:  # line the beat up with now
            eff = round(eff / BEAT_S) * BEAT_S
        self._anchor_real, self._anchor_eff, self.rate = now, eff, rate

    def _set(self, now: float, bpm: float | None, snap: bool = False) -> None:
        self.bpm = bpm
        self._rebase(now, (bpm / REFERENCE_BPM if bpm else 1.0) * self.speed, snap)

    # ---------------------------------------------------------------- sources

    def tap(self, now: float) -> float | None:
        """A tap (pedal, key, button). Returns the BPM once two taps are in. Following the drums, a tap
        seeds the tracker (BPM straight away, history cleared)."""
        with self._lock:
            return self._tap(now)

    def _tap(self, now: float) -> float | None:
        if self.source == "off":
            return self.bpm
        if self._taps and now - self._taps[-1] > MAX_GAP_S:
            self._taps = []
        self._taps = (self._taps + [now])[-5:]
        if len(self._taps) < 2:
            return self.bpm
        intervals = [b - a for a, b in zip(self._taps, self._taps[1:])]
        bpm = 60.0 / statistics.median(intervals)
        if not MIN_BPM <= bpm <= MAX_BPM:
            return self.bpm
        self.last_input, self.lost = now, False
        if self.source == "drums":
            if self._drum_anchor is None and self.tracker.out_bpm is None:
                self._set(now, bpm, snap=True)  # first seed: the linear clock lines the beat up
            self.tracker.seed(bpm, now, "tap", beat_at=now)
            self._seeded(now, bpm)
            return bpm
        self._set(now, bpm, snap=True)
        return bpm

    def kick(self, now: float) -> float | None:
        """A kick-drum hit (tempo source `kick`): the tempo is the average of the last 4 beat
        gaps that fit together; double kicks and long gaps are left out."""
        with self._lock:
            if self._kicks and now - self._kicks[-1] > MAX_GAP_S:
                self._kicks.clear()
            self._kicks.append(now)
            gaps = [b - a for a, b in zip(self._kicks, list(self._kicks)[1:])]
            gaps = [g for g in gaps if 60 / MAX_BPM <= g <= 60 / MIN_BPM]
            if len(gaps) < 2:
                return self.bpm
            mid = statistics.median(gaps)
            fit = [g for g in gaps if abs(g - mid) <= 0.2 * mid][-4:]  # fills and doubles don't count
            if len(fit) < 2:
                return self.bpm
            bpm = 60.0 / (sum(fit) / len(fit))
            self.last_input, self.lost = now, False
            if self.bpm is None or abs(bpm - self.bpm) > 0.5:  # don't wobble on every hit
                self._set(now, bpm)
            return self.bpm

    def clock_tick(self, now: float) -> float | None:
        """One MIDI clock tick (tempo source `midi_clock`)."""
        with self._lock:
            if self._ticks and now - self._ticks[-1] > 1.0:  # clock stopped and started again
                self._ticks.clear()
            self._ticks.append(now)
            self.last_input, self.lost = now, False
            if len(self._ticks) <= PPQN:
                return self.bpm
            per_tick = (self._ticks[-1] - self._ticks[0]) / (len(self._ticks) - 1)
            bpm = 60.0 / (per_tick * PPQN)
            if MIN_BPM <= bpm <= MAX_BPM and (self.bpm is None or abs(bpm - self.bpm) > 0.3):
                self._set(now, bpm)
            return self.bpm

    def clock_start(self, now: float) -> None:
        """MIDI start / continue: the beat starts now."""
        with self._lock:
            self._ticks.clear()
            self.last_input, self.lost = now, False
            self._rebase(now, self.rate, snap=True)

    def set_bpm(self, bpm: float | None, now: float) -> None:
        with self._lock:
            if bpm is not None and not MIN_BPM <= bpm <= MAX_BPM:
                raise ValueError(f"tempo {MIN_BPM:.0f}-{MAX_BPM:.0f} BPM")
            if self.source == "drums" and bpm is not None:
                self.tracker.seed(bpm, now, "set")
                self._seeded(now, bpm)
                return
            self._leave_drums(now)
            self._taps = []
            self.lost = False
            self.last_input = now if bpm else None
            self._set(now, bpm)

    def set_speed(self, speed: float, now: float) -> None:
        """Multiply whatever the tempo is (0.25-4; 1 = as set)."""
        with self._lock:
            if not 0.25 <= speed <= 4:
                raise ValueError("speed 0.25-4")
            if self._drum_anchor is not None:  # re-anchor so effect time doesn't jump
                eff = self._drum_eff(now)
                self._drum_anchor = (self.tracker.beats(now), eff)
                self.speed = speed
                return
            self.speed = speed
            self._set(now, self.bpm)

    def status(self, now: float) -> dict[str, object]:
        e = self.eff(now)
        out: dict[str, object] = {"bpm": round(self.bpm, 1) if self.bpm else None, "source": self.source,
                                  "speed": self.speed, "beat": int(e // BEAT_S), "lost": self.lost}
        if self.source == "drums":  # v6: beat in the bar, bar, confidence, freewheel, where the seed came from
            t = self.tracker.status(now)
            out.update(bar_beat=t["beat"], bar=t["bar"], confidence=t["confidence"], freewheel=t["freewheel"],
                       raw_bpm=t["raw_bpm"], seed_source=t["seed_source"])
        return out
