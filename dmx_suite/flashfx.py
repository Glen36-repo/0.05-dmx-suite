"""Flash FX (v3.3): momentary hits from a button, pedal or drum pad, laid over whatever is running
(control priority level 3, under blackout and MASTER-off drum flash, over the running show).

    blinder      full white on every light
    colour_hit   every light the colour, fading out
    strobe       every light flashing at a rate (as fast as set: there's no rate limit)
    blackout     every light dark while held / for the length (not the BLACKOUT button: haze runs on)
    freeze       hold the look as it is now
    flash_decay  a white hit that fades out
    chase_hit    one quick chase across the rig
    split_hit    the left or right half

They only touch colour (and freeze also holds head positions): no dimmer, so MASTER still owns
on/off (rule 1); never haze (rule 5); never the MASTER-exempt lights such as the kick light
(rule 3). Each is an engine override: held while the button is down, or for `length_ms`.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from .busk import Override
from .look import Colour, FixtureLook, Look

KINDS = ("blinder", "colour_hit", "strobe", "blackout", "freeze", "flash_decay", "chase_hit", "split_hit")
WHITE: Colour = {"red": 1.0, "green": 1.0, "blue": 1.0, "white": 1.0}


def make(kind: str, lights: list[str], start: float, colour: Colour | None = None, length_s: float = 0.4,
         rate_hz: float = 12.0, side: str = "left", left: list[str] | None = None,
         frozen: Look | None = None) -> Callable[[Look, float], Look]:
    """A function that turns the look under it into the look with this flash laid over."""
    if kind not in KINDS:
        raise ValueError(f"flash FX is one of {', '.join(KINDS)}")
    col = dict(colour or WHITE)
    order = list(lights)
    left_set = set(left or order[: len(order) // 2])

    def paint(look: Look, ids: list[str], c: Colour) -> Look:
        fx = dict(look.fixtures)
        for f in ids:
            base = fx.get(f, FixtureLook())
            fx[f] = replace(base, colour=dict(c), pixels=None)
        return Look(fixtures=fx, show_colour=look.show_colour)

    def scaled(c: Colour, k: float) -> Colour:
        return {a: v * max(0.0, min(1.0, k)) for a, v in c.items()}

    def fn(look: Look, now: float) -> Look:
        t = max(0.0, now - start)
        if kind == "blinder":
            return paint(look, order, WHITE)
        if kind == "colour_hit":
            return paint(look, order, scaled(col, 1 - t / max(0.05, length_s) * 0.6))
        if kind == "flash_decay":
            return paint(look, order, scaled(WHITE, math.exp(-t / max(0.02, length_s / 3))))
        if kind == "strobe":
            on = (t * rate_hz) % 1.0 < 0.25
            return paint(look, order, col if on else {})
        if kind == "blackout":
            return paint(look, order, {})
        if kind == "freeze":
            if frozen is None:
                return look
            fx = dict(look.fixtures)
            for f in order:
                if f in frozen.fixtures:
                    fx[f] = frozen.fixtures[f]
            return Look(fixtures=fx, show_colour=look.show_colour)
        if kind == "chase_hit":
            n = max(1, len(order))
            pos = t / max(0.05, length_s) * n
            fx = dict(look.fixtures)
            for i, f in enumerate(order):
                k = max(0.0, 1 - abs(i - pos) / 1.5)
                if k > 0:
                    base = fx.get(f, FixtureLook())
                    fx[f] = replace(base, colour=scaled(col, k), pixels=None)
            return Look(fixtures=fx, show_colour=look.show_colour)
        # split_hit
        ids = [f for f in order if (f in left_set) == (side == "left")]
        return paint(look, ids, scaled(col, 1 - t / max(0.05, length_s) * 0.6))

    return fn


def override(key: str, fn: Callable[[Look, float], Look], now: float, length_s: float | None, fade_s: float) -> Override:
    """Held until released when length_s is None; otherwise ends by itself after length_s."""
    o = Override(key, "fn", fn=fn)
    if length_s is not None:
        o.released_at = now + length_s
        o.fade_s = fade_s
    return o


def lights_for(app: Any) -> tuple[list[str], list[str]]:
    """Every light a flash may touch (not haze, not MASTER-exempt), in layout order, and the left half."""
    from .classify import auto_rig

    ar = auto_rig(app.engine.rig)
    ids = [f for c, v in ar.classes.items() if c != "kick" for f in v]
    return ids, [f for f in ar.left if f in ids]
