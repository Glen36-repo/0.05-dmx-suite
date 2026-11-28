"""Tempo. Effects are written in seconds at a reference tempo of 120 BPM; when a tempo is set,
effect time runs faster or slower so every chase follows the band. Fixed timers stay the
default: with no tempo, effect time is real time.

Where the tempo comes from (rig file `tempo: {source: ...}`):
    tap          a pedal, key or button tapped on the beat (median of the last few taps)
    kick         the drummer's kick note (average of the last 4 beats; double kicks, fills and
                 gaps that don't fit are ignored)
    midi_clock   MIDI clock from any input (24 ticks a beat); start lines the beat up
A kick or clock that goes quiet keeps its last tempo for `timeout_s`, then effects go back to
fixed timers. `speed` (0.25-4) multiplies whatever the tempo is, e.g. from a busk fader.

Tempo changes never make effect time jump: the clock is piecewise linear and continuous.
"""

from __future__ import annotations

import statistics
import threading
from collections import deque
from dataclasses import dataclass

REFERENCE_BPM = 120.0
BEAT_S = 60.0 / REFERENCE_BPM  # one beat in effect time
MIN_BPM, MAX_BPM = 40.0, 240.0
MAX_GAP_S = 60.0 / MIN_BPM  # longer gap starts a new tap sequence
SOURCES = ("tap", "kick", "midi_clock")
PPQN = 24  # MIDI clock ticks a beat


@dataclass
class TempoConfig:
    source: str = "tap"
    kick_note: int = 36  # General MIDI kick; the TD-25 sends 36
    timeout_s: float = 30.0  # kick / clock gone quiet this long: back to fixed timers


class TempoClock:
    """Maps real time to effect time."""

    def __init__(self, now: float, config: TempoConfig | None = None) -> None:
        self._lock = threading.Lock()
        self._anchor_real = now
        self._anchor_eff = now
        self.rate = 1.0
        self.bpm: float | None = None
        self.speed = 1.0
        self.config = config or TempoConfig()
        self.last_input: float | None = None
        self.lost = False  # the kick / clock stopped and timers took over
        self._taps: list[float] = []
        self._kicks: deque[float] = deque(maxlen=9)
        self._ticks: deque[float] = deque(maxlen=PPQN * 2 + 1)

    @property
    def source(self) -> str:
        return self.config.source

    # ---------------------------------------------------------------- effect time

    def eff(self, now: float) -> float:
        with self._lock:
            self._check_lost(now)
            return self._anchor_eff + (now - self._anchor_real) * self.rate

    def _check_lost(self, now: float) -> None:
        if (self.source != "tap" and self.bpm is not None and self.last_input is not None
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
        """A tap (pedal, key, button). Returns the BPM once two taps are in."""
        with self._lock:
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
            self._taps = []
            self.lost = False
            self.last_input = now if bpm else None
            self._set(now, bpm)

    def set_speed(self, speed: float, now: float) -> None:
        """Multiply whatever the tempo is (0.25-4; 1 = as set)."""
        with self._lock:
            if not 0.25 <= speed <= 4:
                raise ValueError("speed 0.25-4")
            self.speed = speed
            self._set(now, self.bpm)

    def status(self, now: float) -> dict[str, object]:
        e = self.eff(now)
        return {"bpm": round(self.bpm, 1) if self.bpm else None, "source": self.source, "speed": self.speed,
                "beat": int(e // BEAT_S), "lost": self.lost}
