"""Tap tempo (optional). Effects are written in seconds at a reference tempo of 120 BPM; when a
tempo is tapped, effect time runs faster or slower so every chase follows the band. Fixed timers
stay the default: with no tempo set, effect time is real time. Set step times are never stretched.
"""

from __future__ import annotations

import statistics
import threading

REFERENCE_BPM = 120.0
BEAT_S = 60.0 / REFERENCE_BPM  # one beat in effect time
MIN_BPM, MAX_BPM = 40.0, 240.0
MAX_GAP_S = 60.0 / MIN_BPM  # longer gap starts a new tap sequence


class TempoClock:
    """Maps real time to effect time: piecewise linear and continuous, so changing tempo never jumps."""

    def __init__(self, now: float) -> None:
        self._lock = threading.Lock()
        self._anchor_real = now
        self._anchor_eff = now
        self.rate = 1.0
        self.bpm: float | None = None
        self._taps: list[float] = []

    def eff(self, now: float) -> float:
        with self._lock:
            return self._anchor_eff + (now - self._anchor_real) * self.rate

    def _rebase(self, now: float, rate: float, snap: bool = False) -> None:
        eff = self._anchor_eff + (now - self._anchor_real) * self.rate
        if snap:  # line the beat up with this tap
            eff = round(eff / BEAT_S) * BEAT_S
        self._anchor_real, self._anchor_eff, self.rate = now, eff, rate

    def tap(self, now: float) -> float | None:
        """Register a tap (pedal or kick drum). Returns the BPM once two taps are in."""
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
            self.bpm = bpm
            self._rebase(now, bpm / REFERENCE_BPM, snap=True)
            return bpm

    def set_bpm(self, bpm: float | None, now: float) -> None:
        with self._lock:
            if bpm is not None and not MIN_BPM <= bpm <= MAX_BPM:
                raise ValueError(f"tempo {MIN_BPM:.0f}-{MAX_BPM:.0f} BPM")
            self.bpm = bpm
            self._taps = []
            self._rebase(now, (bpm / REFERENCE_BPM) if bpm else 1.0)
