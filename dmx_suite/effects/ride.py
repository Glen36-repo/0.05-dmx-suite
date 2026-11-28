"""Effects added for the auto show (v3.3): the Move FX, Colour FX and drum-reactive banks.

Move FX are one effect, `move`, with a pattern; heads always stay inside the head limits (the
rule layer clamps) and jump between positions dark. Colour FX work per pixel where it helps.
Drum-reactive effects read named input hits by role (drums.BUS) at the engine's clock (run.now).
"""

from __future__ import annotations

import math
import random
from typing import Any

from ..look import Colour
from .base import BLACK, SPREAD_PARAMS, Effect, Param, ParseCtx, Run, Unit, mix, scale, seed, static_on, wave, with_black

# ---------------------------------------------------------------------- Move FX

MOVE_PATTERNS = ("pan_sweep", "tilt_sweep", "circle", "figure8", "fan", "swim", "float", "point", "random_points",
                 "crossfire", "audience", "ballyhoo")


def _tagged(ctx: ParseCtx, tags: list[str]) -> list[str]:
    """Point names whose tags include any of `tags` (all points when none given)."""
    info = getattr(ctx.pal, "point_info", {}) or {}
    names = sorted(ctx.pal.positions)
    if not tags:
        return names
    return [n for n in names if set(tags) & set((info.get(n) or {}).get("tags") or [])]


class Move(Effect):
    name = "move"
    label = "Move FX"
    help = ("Moving heads: pan or tilt sweep, circle, figure 8, fan out and in, swim, float, hold a point, jump "
            "between points (dark), crossfire, audience sweep, ballyhoo. Head limits still apply.")
    movement = True
    params = [
        Param("pattern", "choice", "pan_sweep", choices=MOVE_PATTERNS),
        Param("centre", "position", help="palette position or point the move goes round (default: the middle)"),
        Param("size", "number", 0.2, lo=0, hi=0.5, help="how far it moves, share of the pan/tilt range"),
        Param("period_s", "number", 8.0, lo=0.2, label="period (s)"),
        Param("spread", "number", 0.0, lo=0, hi=1, help="how far apart the heads are in the cycle"),
        Param("mirror", "bool", False, help="heads on the right mirror the left"),
        Param("tags", "text", "", help="points to use, by tag (e.g. band,safe): point, random_points, crossfire"),
        Param("dark_move_s", "number", 0.6, lo=0, label="dark move (s)", help="random_points: dark while moving"),
        Param("seed", "text", lambda ctx: ctx.what),
        *SPREAD_PARAMS,
    ]

    def check(self, p: dict[str, Any], ctx: ParseCtx) -> None:
        tags = [x.strip() for x in str(p.get("tags") or "").split(",") if x.strip()]
        p["_points"] = {}
        if p["pattern"] in ("point", "random_points", "crossfire"):
            for names in (_tagged(ctx, tags), _tagged(ctx, [])):  # by tag; else any point (a rig not tagged yet)
                pts = {n: ctx.pal.positions_for(n, ctx.targets, ctx.what) for n in names}
                p["_points"] = {n: v for n, v in pts.items() if v}
                if p["_points"]:
                    break
            if p["pattern"] in ("point", "random_points") and not p["_points"]:
                # no head points on this rig yet: the heads stay where they are (store points on the Heads page)
                ctx.pal.warnings.add(f"{ctx.what}: no head points for these heads yet; they stay where they are")

    def _centre(self, p: dict[str, Any], fid: str) -> tuple[float, float]:
        c = p.get("centre")
        if c and fid in c:
            return c[fid]
        return (0.5, 0.5)

    def render(self, p: dict[str, Any], run: Run) -> None:
        pat, r, period = p["pattern"], p["size"], p["period_s"]
        units = run.units(False)
        n = max(1, len(units))
        for un in units:
            ph = run.t / period + p["spread"] * un.u
            a = 2 * math.pi * ph
            cp, ct = self._centre(p, un.fid)
            side = -1.0 if p["mirror"] and un.x > 0.5 else 1.0
            dp = dt = 0.0
            if pat == "pan_sweep":
                dp = math.sin(a)
            elif pat == "tilt_sweep":
                dt = math.sin(a)
            elif pat == "circle":
                dp, dt = math.cos(a), math.sin(a)
            elif pat == "figure8":
                dp, dt = math.sin(a), math.sin(2 * a) / 2
            elif pat == "fan":  # spread out from the centre and back in
                k = 0.5 - 0.5 * math.cos(a)
                dp = (2 * un.index / max(1, n - 1) - 1 if n > 1 else 0.0) * k
            elif pat in ("swim", "float"):  # slow organic drift: two sines out of step
                k = 1.0 if pat == "swim" else 0.35
                off = (seed(p["seed"], un.fid) % 1000) / 1000
                dp = k * (math.sin(a + 6.28 * off) * 0.7 + math.sin(2.3 * a + 1.7) * 0.3)
                dt = k * (math.cos(0.7 * a + 3.1 * off) * 0.6 + math.sin(1.9 * a) * 0.4)
            elif pat == "ballyhoo":  # big fast sweep
                dp, dt = math.sin(a), math.sin(2 * a + 1.3) * 0.8
            elif pat == "audience":  # side to side across the audience, held low (limits still clamp)
                dp, dt = math.sin(a), -0.6
            elif pat == "crossfire":  # beams cross: left heads sweep right, right heads sweep left
                dp = math.sin(a) * (1.0 if un.x <= 0.5 else -1.0)
            elif pat in ("point", "random_points"):
                self._points(p, run, un)
                continue
            fl = run.fl(un.fid)
            fl.pan = min(1.0, max(0.0, cp + side * r * dp))
            fl.tilt = min(1.0, max(0.0, ct + r * dt))

    def _points(self, p: dict[str, Any], run: Run, un: Unit) -> None:
        names = [n for n, v in p["_points"].items() if un.fid in v]
        if not names:
            return  # a head no tagged point covers stays where it is
        fl = run.fl(un.fid)
        if p["pattern"] == "point":
            fl.pan, fl.tilt = p["_points"][names[0]][un.fid]
            return
        period = p["period_s"]
        slot = math.floor(run.t / period)
        rng = random.Random(seed(p["seed"], un.fid if p["spread"] else "", slot))
        fl.pan, fl.tilt = p["_points"][rng.choice(names)][un.fid]
        if slot > 0 and run.t - slot * period < p["dark_move_s"]:  # heads move between points dark
            run.dark.add(un.fid)


# ---------------------------------------------------------------------- Colour FX


def _cols(p: dict[str, Any]) -> list[Colour]:
    return list(p.get("colours") or [p.get("colour") or {"red": 1.0, "green": 1.0, "blue": 1.0}])


class Palette(Effect):
    name = "palette"
    label = "Static palette"
    help = "Each light (or pixel) takes the next colour of a palette; optionally drifting slowly along."
    per_pixel = True
    params = [
        Param("colours", "colours", ["white", "off"], min_items=1),
        Param("period_s", "number", 0.0, lo=0, label="drift (s)", help="0 = still; else once along the palette"),
        *SPREAD_PARAMS,
    ]

    def period(self, p: dict[str, Any]) -> float | None:
        return p["period_s"] or None

    lit_aware = True

    def render(self, p: dict[str, Any], run: Run) -> None:
        base = _cols(p)
        units = run.units(True)
        drift = run.t / p["period_s"] if p["period_s"] else 0.0
        off = round(run.shift * len(units))
        for un in units:
            lit = run.lit_of(un.fid)
            if lit < 1.0 and not p["period_s"]:  # still: a regular black pattern across the lights, moving with shift
                c = base[int(un.u * len(units)) % len(base)]
                run.put(un, c if static_on(un.index, lit, off) else run.black(un.fid, un.pixel))
                continue
            cols = with_black(base, lit) if lit < 1.0 else base  # drifting: black slots between the colours
            c = cols[int(un.u * len(units) + drift * len(cols)) % len(cols)]
            run.put(un, run.black(un.fid, un.pixel) if lit < 1.0 and c is BLACK else c)
        run.flush()


class ColourFade(Effect):
    name = "colour_fade"
    label = "Colour fade"
    help = "The whole rig crossfades slowly through a palette."
    per_pixel = True
    params = [
        Param("colours", "colours", ["white", "off"], min_items=2),
        Param("period_s", "number", 8.0, lo=0.5, label="per colour (s)"),
        Param("spread", "number", 0.0, lo=0, hi=1),
        *SPREAD_PARAMS,
    ]

    def period(self, p: dict[str, Any]) -> float | None:
        return p["period_s"] * len(p["colours"])

    lit_aware = True

    def render(self, p: dict[str, Any], run: Run) -> None:
        for un in run.units(True):
            lit = run.lit_of(un.fid)
            cols = with_black(p["colours"], lit) if lit < 1.0 else p["colours"]  # fades through black too
            n = len(cols)
            x = (run.t / p["period_s"] * n / len(p["colours"]) + p["spread"] * un.u * n) % n
            i = int(x)
            c = mix(cols[i], cols[(i + 1) % n], x - i)
            run.put(un, run.black(un.fid, un.pixel) if lit < 1.0 and not any(c.values()) else c)
        run.flush()


class Split(Effect):
    name = "split"
    label = "Split"
    help = "Two colours: left and right halves, or alternating lights; optionally swapping."
    per_pixel = True
    params = [
        Param("colours", "colours", ["white", "off"], min_items=2),
        Param("mode", "choice", "sides", choices=("sides", "alternate")),
        Param("period_s", "number", 0.0, lo=0, label="swap every (s)", help="0 = never"),
        *SPREAD_PARAMS,
    ]

    def period(self, p: dict[str, Any]) -> float | None:
        return 2 * p["period_s"] if p["period_s"] else None

    lit_aware = True

    def render(self, p: dict[str, Any], run: Run) -> None:
        a, b = p["colours"][0], p["colours"][1]
        swap = int(run.t / p["period_s"]) % 2 if p["period_s"] else 0
        units = run.units(p["mode"] == "alternate")
        off = round(run.shift * len(units))
        for un in units:
            # v8: sides split at the rig's vertical centreline (a light on the line goes right, as before)
            first = (un.x < (0.5 if un.cx is None else un.cx)) if p["mode"] == "sides" else (un.index % 2 == 0)
            lit = run.lit_of(un.fid)
            on = lit >= 1.0 or static_on(un.index, lit, off)  # a regular black pattern across the lights
            run.put(un, (a if first != bool(swap) else b) if on else run.black(un.fid, un.pixel))
        run.flush()


class Pulse(Effect):
    name = "pulse"
    label = "Pulse"
    help = "The whole rig breathes: its colour swells and fades."
    params = [
        Param("colour", "colour", "white"),
        Param("period_s", "number", 4.0, lo=0.1, label="period (s)"),
        Param("floor", "number", 0.15, lo=0, hi=1, help="lowest level"),
        Param("spread", "number", 0.0, lo=0, hi=1),
        *SPREAD_PARAMS,
    ]

    def render(self, p: dict[str, Any], run: Run) -> None:
        for un in run.units(False):
            lv = p["floor"] + (1 - p["floor"]) * wave("sine", run.t / p["period_s"] + p["spread"] * un.u)
            run.put(un, scale(p["colour"], lv))
        run.flush()


class Twinkle(Effect):
    name = "twinkle"
    label = "Twinkle"
    help = "Softer sparkle: lights fade in and out at random."
    per_pixel = True
    params = [
        Param("colour", "colour", "white"),
        Param("background", "colour", "off"),
        Param("period_s", "number", 3.0, lo=0.2, label="twinkle (s)"),
        Param("density", "number", 0.3, lo=0, hi=1),
        Param("seed", "text", lambda ctx: ctx.what),
    ]

    def render(self, p: dict[str, Any], run: Run) -> None:
        for un in run.units(True):
            off = (seed(p["seed"], un.fid, un.pixel) % 1000) / 1000
            x = run.t / p["period_s"] + off
            cycle = math.floor(x)
            lit = random.Random(seed(p["seed"], un.fid, un.pixel, cycle)).random() < p["density"]
            run.put(un, mix(p["background"], p["colour"], wave("sine", x) if lit else 0.0))
        run.flush()


class Comet(Effect):
    name = "comet"
    label = "Comet"
    help = "A dot runs along the pixels with a fading tail."
    per_pixel = True
    params = [
        Param("colour", "colour", "white"),
        Param("background", "colour", "off"),
        Param("period_s", "number", 1.5, lo=0.1, label="period (s)"),
        Param("tail", "number", 0.3, lo=0.01, hi=1, help="tail length, share of the run"),
        *SPREAD_PARAMS,
    ]

    def render(self, p: dict[str, Any], run: Run) -> None:
        head = (run.t / p["period_s"]) % 1.0
        for un in run.units(True):
            behind = (head - un.u) % 1.0
            lv = max(0.0, 1 - behind / p["tail"]) if behind <= p["tail"] else 0.0
            run.put(un, mix(p["background"], p["colour"], lv))
        run.flush()


class Bounce(Effect):
    name = "bounce"
    label = "Bounce"
    help = "A dot bounces from end to end along the pixels."
    per_pixel = True
    params = [
        Param("colour", "colour", "white"),
        Param("background", "colour", "off"),
        Param("period_s", "number", 2.0, lo=0.1, label="there and back (s)"),
        Param("width", "number", 0.12, lo=0.01, hi=1),
        *SPREAD_PARAMS,
    ]

    def render(self, p: dict[str, Any], run: Run) -> None:
        pos = wave("triangle", run.t / p["period_s"])
        for un in run.units(True):
            run.put(un, mix(p["background"], p["colour"], max(0.0, 1 - abs(un.u - pos) / p["width"])))
        run.flush()


class Fill(Effect):
    name = "fill"
    label = "Fill / unfill"
    help = "The pixels fill up one by one, then empty again."
    per_pixel = True
    params = [
        Param("colour", "colour", "white"),
        Param("background", "colour", "off"),
        Param("period_s", "number", 3.0, lo=0.1, label="fill and empty (s)"),
        *SPREAD_PARAMS,
    ]

    def render(self, p: dict[str, Any], run: Run) -> None:
        level = wave("triangle", run.t / p["period_s"])
        for un in run.units(True):
            run.put(un, p["colour"] if un.u < level else p["background"])
        run.flush()


class Fire(Effect):
    name = "fire"
    label = "Fire"
    help = "Flickering reds and oranges."
    per_pixel = True
    params = [
        Param("colours", "colours", ["#ff1000", "#ff5a00", "#ffa000"], min_items=2),
        Param("rate_hz", "number", 6.0, lo=0.5, hi=25, label="flicker (Hz)"),
        Param("seed", "text", lambda ctx: ctx.what),
    ]

    def render(self, p: dict[str, Any], run: Run) -> None:
        cols = p["colours"]
        for un in run.units(True):
            x = run.t * p["rate_hz"]
            i = math.floor(x)

            def at(k: int) -> float:
                return random.Random(seed(p["seed"], un.fid, un.pixel, k)).random()

            a, b = at(i), at(i + 1)
            v = a + (b - a) * (x - i)
            pos = v * (len(cols) - 1)
            j = min(len(cols) - 2, int(pos))
            run.put(un, scale(mix(cols[j], cols[j + 1], pos - j), 0.55 + 0.45 * v))
        run.flush()


class Lightning(Effect):
    name = "lightning"
    label = "Lightning"
    help = "Sparse white bursts with a quick fade, now and then (no rate limit: it's as set)."
    params = [
        Param("colour", "colour", "white"),
        Param("rate_hz", "number", 0.6, lo=0.05, hi=10, label="bursts a second"),
        Param("decay_s", "number", 0.25, lo=0.02, hi=2),
        Param("seed", "text", lambda ctx: ctx.what),
    ]

    def render(self, p: dict[str, Any], run: Run) -> None:
        slot_len = 0.1
        level = 0.0
        k = math.floor(run.t / slot_len)
        chance = p["rate_hz"] * slot_len
        for back in range(int(p["decay_s"] / slot_len) + 2):
            if random.Random(seed(p["seed"], k - back)).random() < chance:
                level = max(level, math.exp(-(run.t - (k - back) * slot_len) / max(0.02, p["decay_s"] / 3)))
        for f in run.fids:
            run.set_colour(f, scale(p["colour"], min(1.0, level)))


class Police(Effect):
    name = "police"
    label = "Police"
    help = "Red and blue sides swapping."
    params = [
        Param("colours", "colours", ["#ff0000", "#0020ff"], min_items=2),
        Param("rate_hz", "number", 2.0, lo=0.2, hi=20, label="swaps a second"),
    ]

    def render(self, p: dict[str, Any], run: Run) -> None:
        a, b = p["colours"][0], p["colours"][1]
        flip = int(run.t * p["rate_hz"]) % 2
        for un in run.units(False):
            left = un.x < 0.5 if len(run.fids) > 1 else True
            run.put(un, a if left != bool(flip) else b)
        run.flush()


# ---------------------------------------------------------------------- drum-reactive


def _bus(run: Run) -> Any:
    from ..drums import BUS

    return getattr(run, "bus", None) or BUS


class KickPump(Effect):
    name = "kick_pump"
    label = "Kick pump"
    help = "Every kick bumps the brightness up, then it settles (inputs with the kick role)."
    params = [
        Param("colour", "colour", "white"),
        Param("floor", "number", 0.35, lo=0, hi=1, help="level between kicks"),
        Param("decay_s", "number", 0.25, lo=0.02, hi=3),
        Param("role", "choice", "kick", choices=("kick", "snare", "tom", "cymbal", "activity")),
    ]

    def render(self, p: dict[str, Any], run: Run) -> None:
        h = _bus(run).last(p["role"], run.now)
        bump = h.strength * math.exp(-(run.now - h.time) / p["decay_s"]) if h else 0.0
        lv = min(1.0, p["floor"] + (1 - p["floor"]) * bump)
        for f in run.fids:
            run.set_colour(f, scale(p["colour"], lv))


class SnareHit(Effect):
    name = "snare_hit"
    label = "Snare hit"
    help = "Every snare hit flashes the lights, then they fade."
    params = [
        Param("colour", "colour", "white"),
        Param("decay_s", "number", 0.2, lo=0.02, hi=3),
        Param("role", "choice", "snare", choices=("kick", "snare", "tom", "cymbal", "activity")),
    ]

    def render(self, p: dict[str, Any], run: Run) -> None:
        h = _bus(run).last(p["role"], run.now)
        lv = h.strength * math.exp(-(run.now - h.time) / p["decay_s"]) if h else 0.0
        for f in run.fids:
            run.set_colour(f, scale(p["colour"], lv) if lv > 0.01 else {})


class TomRoll(Effect):
    name = "tom_roll"
    label = "Tom roll"
    help = "Each tom hit lights the next light along, so a roll walks across the rig."
    params = [
        Param("colour", "colour", "white"),
        Param("decay_s", "number", 0.3, lo=0.02, hi=3),
        *SPREAD_PARAMS,
    ]

    def render(self, p: dict[str, Any], run: Run) -> None:
        units = sorted(run.units(False), key=lambda u: u.u)
        hits = _bus(run).recent("tom", run.now, 4.0)
        lit: dict[int, float] = {}
        for k, h in enumerate(hits):
            lv = h.strength * math.exp(-(run.now - h.time) / p["decay_s"])
            i = k % max(1, len(units))
            lit[i] = max(lit.get(i, 0.0), lv)
        for i, un in enumerate(units):
            lv = lit.get(i, 0.0)
            run.put(un, scale(p["colour"], lv) if lv > 0.01 else {})
        run.flush()


class CymbalShimmer(Effect):
    name = "cymbal_shimmer"
    label = "Cymbal shimmer"
    help = "A crash or ride sets off a burst of sparkle that dies away."
    per_pixel = True
    params = [
        Param("colour", "colour", "white"),
        Param("length_s", "number", 1.2, lo=0.1, hi=6),
        Param("rate_hz", "number", 14.0, lo=1, hi=25),
        Param("seed", "text", lambda ctx: ctx.what),
    ]

    def render(self, p: dict[str, Any], run: Run) -> None:
        h = _bus(run).last("cymbal", run.now)
        age = run.now - h.time if h else 1e9
        density = max(0.0, 1 - age / p["length_s"]) * (h.strength if h else 0.0) * 0.6
        slot = math.floor(run.t * p["rate_hz"])
        for un in run.units(True):
            on = random.Random(seed(p["seed"], un.fid, un.pixel, slot)).random() < density
            run.put(un, p["colour"] if on else {})
        run.flush()


class FillBuild(Effect):
    name = "fill_build"
    label = "Fill build"
    help = "During a drum fill (many hits close together) a wave speeds up and grows."
    per_pixel = True
    params = [
        Param("colour", "colour", "white"),
        Param("background", "colour", "off"),
        Param("period_s", "number", 2.0, lo=0.1, label="calm period (s)"),
        Param("window_s", "number", 1.5, lo=0.2, hi=6, help="how far back hits count"),
        Param("full_hits", "int", 10, lo=2, hi=60, help="hits in the window for full build"),
        *SPREAD_PARAMS,
    ]

    def render(self, p: dict[str, Any], run: Run) -> None:
        n = _bus(run).count("activity", run.now, p["window_s"])
        build = min(1.0, n / p["full_hits"])
        period = p["period_s"] / (1 + 3 * build)
        width = 0.15 + 0.6 * build
        for un in run.units(True):
            lv = wave("pulse", run.t / period - un.u, width)
            run.put(un, mix(p["background"], p["colour"], lv * (0.3 + 0.7 * build)))
        run.flush()


class VelocityColour(Effect):
    name = "velocity_colour"
    label = "Velocity colour"
    help = "How hard the last hit was picks the colour (soft to hard along the list)."
    params = [
        Param("colours", "colours", ["#0030ff", "#ff00a0", "white"], min_items=2),
        Param("role", "choice", "activity", choices=("kick", "snare", "tom", "cymbal", "activity")),
        Param("decay_s", "number", 0.0, lo=0, hi=5, help="0 = hold the colour until the next hit"),
    ]

    def render(self, p: dict[str, Any], run: Run) -> None:
        h = _bus(run).last(p["role"], run.now)
        cols = p["colours"]
        if h is None:
            c = cols[0]
            lv = 1.0
        else:
            x = h.strength * (len(cols) - 1)
            i = min(len(cols) - 2, int(x))
            c = mix(cols[i], cols[i + 1], x - i)
            lv = math.exp(-(run.now - h.time) / p["decay_s"]) if p["decay_s"] else 1.0
        for f in run.fids:
            run.set_colour(f, scale(c, lv))


SWEEP_ORDERS = {"cycle": ("right", "left", "down", "up"), "left_right": ("right", "left"), "up_down": ("down", "up"),
                "right": ("right",), "left": ("left",), "down": ("down",), "up": ("up",)}


class DirSweep(Effect):
    lit_aware = True
    name = "dir_sweep"
    label = "Directional sweep"
    help = ("A band of colour crosses the rig by where the lights are, one direction per pass: left to right, "
            "right to left, top to bottom (back to front), bottom to top. With a gap, the rig is dark between passes.")
    per_pixel = True
    params = [
        Param("colour", "colour", "white"),
        Param("background", "colour", "off"),
        Param("period_s", "number", 2.5, lo=0.2, label="pass (s)", help="one pass across the rig, gap included"),
        Param("width", "number", 0.25, lo=0.02, hi=1, help="the band, as a share of the rig"),
        Param("gap", "number", 0.0, lo=0, hi=0.9, help="share of each pass with the rig dark (background) after the band"),
        Param("directions", "choice", "cycle", choices=tuple(SWEEP_ORDERS),
              help="cycle: right, left, down, up in turn; or one axis, or one direction"),
    ]

    @staticmethod
    def position(units: list[Unit], direction: str) -> list[float]:
        """0-1 across the lights in the direction of travel (by where they are on the layout)."""
        horizontal = direction in ("right", "left")
        vals = [un.x if horizontal else un.y for un in units]
        lo, hi = (min(vals), max(vals)) if vals else (0.0, 0.0)
        out = [(v - lo) / (hi - lo) if hi > lo else 0.5 for v in vals]
        return [1 - v for v in out] if direction in ("left", "up") else out

    def render(self, p: dict[str, Any], run: Run) -> None:
        units = run.units(True)
        x = run.t / p["period_s"]
        order = SWEEP_ORDERS[p["directions"]]
        direction = order[math.floor(x) % len(order)]
        f = x % 1.0
        lit_part = 1.0 - p["gap"]
        for un, pos in zip(units, self.position(units, direction)):
            lit = run.lit_of(un.fid)
            w = max(0.01, p["width"] * min(1.0, lit)) / 2  # lit narrows the band
            centre = -w + (f / lit_part) * (1 + 2 * w) if f < lit_part else None  # None: the dark gap
            d = abs(pos - centre) if centre is not None else w
            lv = 0.5 * (1 + math.cos(math.pi * d / w)) if d < w else 0.0
            if lit < 1.0:  # the rest of the rig black, not the background
                run.put(un, mix(BLACK, p["colour"], lv) if lv > 0 else run.black(un.fid, un.pixel))
            else:
                run.put(un, mix(p["background"], p["colour"], lv))
        run.flush()


class RandomFlash(Effect):
    name = "random_flash"
    label = "Random flash"
    help = ("Pulses of light through random bits of the rig, several at once, each fading out with a tail. "
            "On a pixel bar a flash is a few pixels; anything not flashing is the background (off by default).")
    per_pixel = True
    params = [
        Param("colour", "colour", "white"),
        Param("background", "colour", "off"),
        Param("rate_hz", "number", 6.0, lo=0.2, hi=25, label="flashes (/s)"),
        Param("count", "int", 1, lo=1, hi=8, help="flashes started at a time"),
        Param("tail_s", "number", 0.8, lo=0.05, hi=4, label="tail (s)", help="how long a flash takes to fade out"),
        Param("bit", "int", 3, lo=1, hi=64, help="pixels in one flash on a pixel bar"),
        Param("seed", "text", lambda ctx: ctx.what),
    ]

    def period(self, p: dict[str, Any]) -> float | None:
        return 1.0 / float(p["rate_hz"])

    def render(self, p: dict[str, Any], run: Run) -> None:
        units = run.units(True)
        fids = list(dict.fromkeys(un.fid for un in units))
        if not fids:
            return
        dt = 1.0 / p["rate_hz"]
        now = math.floor(run.t / dt)
        back = math.ceil(p["tail_s"] / dt) + 1
        lit: dict[tuple[str, int | None], float] = {}
        for k in range(max(0, now - back), now + 1):
            age = run.t - k * dt
            if age < 0 or age > p["tail_s"]:
                continue
            lv = (1 - age / p["tail_s"]) ** 2  # bright at once, then a soft tail
            for j in range(p["count"]):
                rng = random.Random(seed(p["seed"], k, j))
                fid = fids[rng.randrange(len(fids))]
                n = run.pixels(fid)
                if n > 1:
                    b = min(p["bit"], n)
                    start = rng.randrange(n - b + 1)
                    keys: list[tuple[str, int | None]] = [(fid, i) for i in range(start, start + b)]
                else:
                    keys = [(fid, None)]
                for key in keys:
                    lit[key] = max(lit.get(key, 0.0), lv)
        for un in units:
            lv = lit.get((un.fid, un.pixel), lit.get((un.fid, None), 0.0))
            run.put(un, mix(p["background"], p["colour"], lv))
        run.flush()


RIDE = [Move, Palette, ColourFade, Split, Pulse, Twinkle, Comet, Bounce, Fill, Fire, Lightning, Police,
        KickPump, SnareHit, TomRoll, CymbalShimmer, FillBuild, VelocityColour, DirSweep, RandomFlash]
