"""Synthetic drum grooves for the beat tracker tests: (time, roles, velocity) hits."""

from __future__ import annotations

import random


def groove(bpm: float, bars: int, start: float = 0.0, hats: str = "8ths", feel: str = "rock", seed: int = 1,
           jitter_ms: float = 8.0, drift: float = 0.0) -> list[tuple[float, tuple[str, ...], int]]:
    """A groove from `start`: kick 1 and 3 (plus an irregular extra), snare 2 and 4 (half time: snare on
    3 only), hats in eighths or sixteenths. `drift` = fractional tempo change per bar (0.01 = +1 % a bar)."""
    rnd = random.Random(seed)
    out = []
    t = start
    b = bpm
    for _ in range(bars):
        beat = 60.0 / b
        for i in range(4):
            tb = t + i * beat
            j = lambda: rnd.uniform(-jitter_ms, jitter_ms) / 1000  # noqa: E731
            if feel == "half":
                if i == 0:
                    out.append((tb + j(), ("kick",), 110))
                if i == 2:
                    out.append((tb + j(), ("snare",), 115))
            else:
                if i in (0, 2):
                    out.append((tb + j(), ("kick",), 120 if i == 0 else 100))  # the 1 is harder
                if i in (1, 3):
                    out.append((tb + j(), ("snare",), 115))
                if i == 2 and rnd.random() < 0.5:  # an irregular extra kick on the "and" of 3
                    out.append((tb + beat / 2 + j(), ("kick",), 95))
            subs = 2 if hats == "8ths" else 4
            for s in range(subs):
                out.append((tb + s * beat / subs + j(), ("hat",), 80))
        t += 4 * beat
        b *= 1 + drift
    out.sort()
    return out


def fill(bpm: float, bars: int, start: float) -> list[tuple[float, tuple[str, ...], int]]:
    """Sixteenth-note tom fill."""
    beat = 60.0 / bpm
    return [(start + k * beat / 4, ("tom",), 100) for k in range(bars * 16)]


def run(tracker, hits, until: float, step: float = 0.025, t0: float | None = None, probe=None):
    """Feed hits in time order with the tracker updated at 40 Hz; probe(t) called each step."""
    i = 0
    t = hits[0][0] if t0 is None else t0
    hits = sorted(hits)
    while t <= until:
        while i < len(hits) and hits[i][0] <= t:
            ht, roles, vel = hits[i]
            tracker.hit(roles, vel, ht)
            i += 1
        tracker.update(t)
        if probe:
            probe(t)
        t += step
