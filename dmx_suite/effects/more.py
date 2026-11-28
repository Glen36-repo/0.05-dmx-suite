"""Effects added in v2: rainbow, sparkle, wave, strobe, and circle / figure-8 head movement.
Colour effects work per pixel, so a bar's pixels are separate lights to them."""

from __future__ import annotations

import math
import random
from typing import Any

from ..look import LookError
from .base import SPREAD_PARAMS, WAVEFORMS, Effect, Param, ParseCtx, Run, gapped, hue, mix, seed, wave


class Rainbow(Effect):
    name = "rainbow"
    label = "Rainbow"
    help = "Colours go round the colour wheel; spread lays the rainbow across the lights."
    per_pixel = True
    params = [
        Param("period_s", "number", 8.0, lo=0.05, label="period (s)", help="once round the wheel"),
        Param("spread", "number", 1.0, lo=0, hi=4, help="how much of the rainbow is across the lights at once"),
        Param("saturation", "number", 1.0, lo=0, hi=1, help="1 = full colour, lower = paler"),
        *SPREAD_PARAMS,
    ]

    lit_aware = True
    SEGMENTS = 6  # with lit < 1: red, yellow, green, cyan, blue, magenta with black gaps between

    def render(self, p: dict[str, Any], run: Run) -> None:
        for un in run.units(True):
            x = run.t / p["period_s"] - p["spread"] * un.u
            lit = run.lit_of(un.fid)
            if lit >= 1.0:
                run.put(un, hue(x, p["saturation"]))
                continue
            seg = gapped(x, self.SEGMENTS, lit)
            run.put(un, run.black(un.fid, un.pixel) if seg is None
                    else hue((seg[0] + seg[1]) / self.SEGMENTS, p["saturation"]))
        run.flush()


class Sparkle(Effect):
    name = "sparkle"
    label = "Sparkle"
    help = "Random lights or pixels light up, a new pattern several times a second."
    per_pixel = True
    params = [
        Param("colour", "colour", "white"),
        Param("background", "colour", "off"),
        Param("density", "number", 0.15, lo=0, hi=1, help="share of lights lit at once"),
        Param("rate_hz", "number", 8.0, lo=0.1, hi=25, label="rate (Hz)", help="new patterns a second"),
        Param("seed", "text", lambda ctx: ctx.what),
    ]

    def render(self, p: dict[str, Any], run: Run) -> None:
        slot = math.floor(run.t * p["rate_hz"])
        for un in run.units(True):
            lit = random.Random(seed(p["seed"], un.fid, un.pixel, slot)).random() < p["density"]
            run.put(un, p["colour"] if lit else p["background"])
        run.flush()


class Wave(Effect):
    name = "wave"
    label = "Wave"
    help = "Brightness rolls across the lights in a wave between two colours."
    per_pixel = True
    params = [
        Param("colour", "colour", "white"),
        Param("background", "colour", "off"),
        Param("period_s", "number", 2.0, lo=0.05, label="period (s)"),
        Param("spread", "number", 1.0, lo=0, hi=4, help="waves across the lights at once"),
        Param("waveform", "choice", "sine", choices=WAVEFORMS),
        Param("width", "number", 0.5, lo=0.01, hi=1, help="lit part of each wave (square, pulse)"),
        *SPREAD_PARAMS,
    ]

    def render(self, p: dict[str, Any], run: Run) -> None:
        for un in run.units(True):
            level = wave(p["waveform"], run.t / p["period_s"] - p["spread"] * un.u, p["width"])
            run.put(un, mix(p["background"], p["colour"], level))
        run.flush()


class Strobe(Effect):
    name = "strobe"
    label = "Strobe"
    help = "All the lights flash together, fast. Done with colour, so MASTER still owns on/off."
    params = [
        Param("colour", "colour", "white"),
        Param("rate_hz", "number", 10.0, lo=0.5, hi=25, label="rate (Hz)"),
        Param("duty", "number", 0.2, lo=0.01, hi=0.99, help="part of each flash that's lit"),
    ]

    def render(self, p: dict[str, Any], run: Run) -> None:
        on = (run.t * p["rate_hz"]) % 1.0 < p["duty"]
        for f in run.fids:
            run.set_colour(f, dict(p["colour"]) if on else {})


class Circle(Effect):
    name = "circle"
    label = "Circle"
    help = "Moving heads draw a circle round a palette position (head limits still apply)."
    movement = True
    shape = "circle"
    params = [
        Param("centre", "position", help="palette position the circle goes round"),
        Param("size", "number", 0.12, lo=0, hi=0.5, help="radius, share of the pan/tilt range"),
        Param("period_s", "number", 6.0, lo=0.2, label="period (s)"),
        Param("spread", "number", 0.0, lo=0, hi=1),
        *SPREAD_PARAMS,
    ]

    def check(self, p: dict[str, Any], ctx: ParseCtx) -> None:
        if "centre" not in p:
            raise LookError(f"{ctx.what}: {self.name} needs a centre position")

    def render(self, p: dict[str, Any], run: Run) -> None:
        r = p["size"]
        for un in run.units(False):
            a = 2 * math.pi * (run.t / p["period_s"] + p["spread"] * un.u)
            cp, ct = p["centre"][un.fid]
            if self.shape == "figure8":
                dp, dt = math.sin(a), math.sin(2 * a) / 2
            else:
                dp, dt = math.cos(a), math.sin(a)
            fl = run.fl(un.fid)
            fl.pan = min(1.0, max(0.0, cp + r * dp))
            fl.tilt = min(1.0, max(0.0, ct + r * dt))


class FigureEight(Circle):
    name = "figure8"
    label = "Figure eight"
    help = "Moving heads draw a figure 8 round a palette position (head limits still apply)."
    shape = "figure8"


MORE = [Rainbow, Sparkle, Wave, Strobe, Circle, FigureEight]
