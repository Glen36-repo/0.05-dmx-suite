"""The v1 effects, moved into the registry unchanged: with the new spread settings at their
defaults they draw exactly the frames they always did (tests/golden checks every shipped scene)."""

from __future__ import annotations

import math
import random
from typing import Any

from ..look import LookError
from .base import SPREAD_PARAMS, Effect, Param, ParseCtx, Run, mix, seed


def _plain(p: dict[str, Any]) -> bool:
    """Spread settings at their defaults: use the v1 formula, so old scenes don't change a bit."""
    return p.get("mapping", "order") == "order" and p.get("direction", "forward") == "forward" and p.get("groups_of", 1) == 1


def _offsets(p: dict[str, Any], run: Run) -> list[float]:
    n = len(run.fids)
    if _plain(p):
        return [p["spread"] * i / n for i in range(n)]
    return [p["spread"] * un.u for un in run.units(False)]


class ColourChase(Effect):
    name = "colour_chase"
    label = "Colour chase"
    help = "Steps (or fades) through a list of colours; spread staggers the lights."
    params = [
        Param("colours", "colours", min_items=2, help="two or more colours"),
        Param("period_s", "number", 4.0, lo=0.05, label="period (s)", help="one time through all the colours"),
        Param("spread", "number", 0.0, lo=0, hi=1, help="0 = all lights together, 1 = spread round the whole cycle"),
        Param("fade", "bool", False, help="fade between colours instead of stepping"),
        *SPREAD_PARAMS,
    ]

    def check(self, p: dict[str, Any], ctx: ParseCtx) -> None:
        if "colours" not in p:
            raise LookError(f"{ctx.what}: colour_chase needs at least 2 colours")

    def render(self, p: dict[str, Any], run: Run) -> None:
        cols, k = p["colours"], len(p["colours"])
        for f, off in zip(run.fids, _offsets(p, run)):
            phase = (run.t / p["period_s"] + off) % 1.0
            pos = phase * k
            idx, frac = int(pos) % k, pos - int(pos)
            c = mix(cols[idx], cols[(idx + 1) % k], frac) if p["fade"] else cols[idx]
            run.set_colour(f, c)


class PixelChase(Effect):
    name = "pixel_chase"
    label = "Pixel chase"
    help = "A block of lit pixels runs along every pixel of the lights in order, with an optional fading tail."
    per_pixel = True
    params = [
        Param("colour", "colour", "white"),
        Param("background", "colour", "off"),
        Param("width", "int", 1, lo=1, help="pixels lit at once"),
        Param("tail", "int", 0, lo=0, help="pixels fading out behind"),
        Param("period_s", "number", 2.0, lo=0.05, label="period (s)", help="one run along the strip"),
        Param("bounce", "bool", False, help="back and forth instead of round and round"),
        Param("reverse", "bool", False),
    ]

    def render(self, p: dict[str, Any], run: Run) -> None:
        strip: list[tuple[str, int]] = []  # every light's pixels in layer order (bars: 8 each)
        for f in run.fids:
            strip += [(f, i) for i in range(run.pixels(f) or 1)]
        total = len(strip)
        phase = (run.t / p["period_s"]) % 1.0
        head = (1 - abs(1 - 2 * phase)) * (total - 1) if p["bounce"] else phase * total
        width, tail = p["width"], p["tail"]
        values = []
        for j in range(total):
            d = head - j  # distance behind the head
            if not p["bounce"]:
                d %= total
            if 0 <= d < width:
                values.append(dict(p["colour"]))
            elif tail and width <= d < width + tail:
                fade = 1 - (d - width + 1) / (tail + 1)
                values.append(mix(p["background"], p["colour"], max(0.0, fade)))
            else:
                values.append(dict(p["background"]))
        if p["reverse"]:
            values.reverse()
        for f in run.fids:
            mine = [values[j] for j, (ff, _) in enumerate(strip) if ff == f]
            if run.pixels(f):
                run.set_pixels(f, mine)
            else:
                run.set_colour(f, mine[0])


class Flash(Effect):
    name = "flash"
    label = "Flash"
    help = "Lights flash on and off at a rate; spread staggers them."
    params = [
        Param("colour", "colour", "white"),
        Param("rate_hz", "number", 4.0, lo=0.1, hi=25, label="rate (Hz)", help="flashes a second"),
        Param("duty", "number", 0.5, lo=0.01, hi=0.99, help="part of each flash that's lit"),
        Param("spread", "number", 0.0, lo=0, hi=1),
        *SPREAD_PARAMS,
    ]

    def render(self, p: dict[str, Any], run: Run) -> None:
        for f, off in zip(run.fids, _offsets(p, run)):
            phase = (run.t * p["rate_hz"] + off) % 1.0
            run.set_colour(f, dict(p["colour"]) if phase < p["duty"] else {})


class Sweep(Effect):
    name = "sweep"
    label = "Sweep"
    help = "Moving heads swing smoothly between two positions and back."
    movement = True
    params = [
        Param("from", "position", help="palette position"),
        Param("to", "position", help="palette position"),
        Param("period_s", "number", 8.0, lo=0.2, label="period (s)", help="there and back"),
        Param("spread", "number", 0.0, lo=0, hi=1),
        *SPREAD_PARAMS,
    ]

    def check(self, p: dict[str, Any], ctx: ParseCtx) -> None:
        if "from" not in p or "to" not in p:
            raise LookError(f"{ctx.what}: sweep needs from and to positions")

    def render(self, p: dict[str, Any], run: Run) -> None:
        for f, off in zip(run.fids, _offsets(p, run)):
            phase = (run.t / p["period_s"] + off) % 1.0
            x = 0.5 - 0.5 * math.cos(2 * math.pi * phase)  # smooth there and back
            (p0, t0), (p1, t1) = p["from"][f], p["to"][f]
            fl = run.fl(f)
            fl.pan, fl.tilt = p0 + (p1 - p0) * x, t0 + (t1 - t0) * x


class RandomMove(Effect):
    name = "random_move"
    label = "Random move"
    help = "Each head jumps to a random spot (inside the head limits) every period, optionally dark while it moves."
    movement = True
    params = [
        Param("period_s", "number", 6.0, lo=0.5, label="period (s)"),
        Param("pan", "range", (0.0, 1.0), help="[min, max] 0-1"),
        Param("tilt", "range", (0.0, 1.0), help="[min, max] 0-1"),
        Param("dark_move_s", "number", 0.0, lo=0, label="dark move (s)", help="blacked out this long after each move"),
        Param("stagger", "bool", True, help="each head on its own timing"),
        Param("seed", "text", lambda ctx: ctx.what, help="change it for a different random pattern"),
    ]

    def check(self, p: dict[str, Any], ctx: ParseCtx) -> None:
        if p["dark_move_s"] >= p["period_s"]:
            raise LookError(f"{ctx.what}: dark_move_s must be shorter than period_s")

    def render(self, p: dict[str, Any], run: Run) -> None:
        period = p["period_s"]
        for f in run.fids:
            offset = (seed(p["seed"], f, "offset") % 1000) / 1000 * period if p["stagger"] else 0.0
            slot = math.floor((run.t + offset) / period)
            first = math.floor(offset / period)
            rng = random.Random(seed(p["seed"], f, slot))
            fl = run.fl(f)
            fl.pan = rng.uniform(*p["pan"])
            fl.tilt = rng.uniform(*p["tilt"])
            # dark for dark_move_s after each new position (not at scene start)
            if p["dark_move_s"] and slot > first and (run.t + offset) - slot * period < p["dark_move_s"]:
                run.dark.add(f)


CLASSIC = [ColourChase, PixelChase, Flash, Sweep, RandomMove]
