"""Crossfades between looks: scene changes, show steps, busk releases.

A fade mixes colour (and intensity) only: no dimmer, so MASTER still owns on/off (rule 1).
Colour wheel, gobo and strobe values snap over halfway through (they're slots, not levels). A
moving head whose position changes doesn't sweep across the room lit: it dims out over the
first half at its old spot, then moves and fades in at the new one (heads move dark). Lights in
neither look stay fully off (rule 4); haze isn't part of a look, so fades never touch it (rule 5).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from .look import Colour, FixtureLook, Look

EPS = 1e-6


def _mix(a: Colour, b: Colour, f: float) -> Colour:
    return {k: a.get(k, 0.0) * (1 - f) + b.get(k, 0.0) * f for k in set(a) | set(b)}


def _scale(c: Colour, f: float) -> Colour:
    return {k: v * f for k, v in c.items()}


def _pixels(fl: FixtureLook, n: int) -> list[Colour]:
    if fl.pixels:
        return [fl.pixels[i] if i < len(fl.pixels) else {} for i in range(n)]
    return [dict(fl.colour) for _ in range(n)]


def _moved(a: FixtureLook, b: FixtureLook) -> bool:
    if a.pan is None or b.pan is None or a.tilt is None or b.tilt is None:
        return False
    return abs(a.pan - b.pan) > EPS or abs(a.tilt - b.tilt) > EPS


def _colours(a: FixtureLook, b: FixtureLook, fa: float, fb: float, out: FixtureLook) -> None:
    """out gets a's colour x fa plus b's x fb (pixels if either side has them)."""
    if a.pixels or b.pixels:
        n = max(len(a.pixels or []), len(b.pixels or []))
        out.pixels = [{k: pa.get(k, 0.0) * fa + pb.get(k, 0.0) * fb for k in set(pa) | set(pb)}
                      for pa, pb in zip(_pixels(a, n), _pixels(b, n))]
        out.colour = {}
    else:
        out.colour = {k: a.colour.get(k, 0.0) * fa + b.colour.get(k, 0.0) * fb for k in set(a.colour) | set(b.colour)}
        out.pixels = None


def mix_looks(a: Look, b: Look, f: float) -> Look:
    """The look f (0-1) of the way from a to b."""
    if f <= 0:
        return a
    if f >= 1:
        return b
    out = Look(show_colour=_mix(a.show_colour, b.show_colour, f))
    for fid in set(a.fixtures) | set(b.fixtures):
        fa, fb = a.fixtures.get(fid, FixtureLook()), b.fixtures.get(fid, FixtureLook())
        late = f >= 0.5
        o = replace(fb if late else fa)  # slots (wheel, gobo, strobe, speed) snap halfway
        if _moved(fa, fb):  # dim out where it was, move dark, fade in where it's going
            if late:
                _colours(fa, fb, 0.0, 2 * f - 1, o)
                o.pan, o.tilt = fb.pan, fb.tilt
            else:
                _colours(fa, fb, 1 - 2 * f, 0.0, o)
                o.pan, o.tilt = fa.pan, fa.tilt
        else:
            _colours(fa, fb, 1 - f, f, o)
            o.pan = fb.pan if fb.pan is not None else fa.pan
            o.tilt = fb.tilt if fb.tilt is not None else fa.tilt
        if fa.intensity is not None or fb.intensity is not None:
            ia = fa.intensity if fa.intensity is not None else 1.0
            ib = fb.intensity if fb.intensity is not None else 1.0
            o.intensity = ia * (1 - f) + ib * f
        out.fixtures[fid] = o
    return out


class Crossfade:
    """Callable(now) -> Look: `old` fading into `new` over `seconds`, both still running."""

    def __init__(self, old: Callable[[float], Look], new: Callable[[float], Look], start: float, seconds: float) -> None:
        self.old, self.new, self.start, self.seconds = old, new, start, max(0.0, seconds)

    def done(self, now: float) -> bool:
        return self.seconds <= 0 or now - self.start >= self.seconds

    def __call__(self, now: float) -> Look:
        if self.done(now):
            return self.new(now)
        return mix_looks(self.old(now), self.new(now), (now - self.start) / self.seconds)
