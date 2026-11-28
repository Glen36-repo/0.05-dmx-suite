"""Matrix effects: drawn across the layout as one picture (mapping: spatial by default), so a wave
crosses the whole rig whatever order the lights are listed in, and each pixel of a bar is lit
where it really is. Lights missing from a smaller rig simply drop out of the picture."""

from __future__ import annotations

import math
from typing import Any

from .base import DIRECTIONS, MAPPINGS, WAVEFORMS, Effect, Param, Run, gapped, mix, scale, wave, window

SPATIAL = [
    Param("mapping", "choice", "spatial", choices=MAPPINGS,
          help="spatial: by where the lights are on the layout; order: as listed"),
    Param("direction", "choice", "angle", choices=DIRECTIONS),
    Param("angle", "angle", 0.0, help="degrees, 0 = left to right, 90 = top to bottom"),
    Param("groups_of", "int", 1, lo=1, hi=64, label="groups of"),
]


def _cycle(cols: list[dict[str, float]], pos: float) -> dict[str, float]:
    """Smoothly round a list of colours (pos 0-1 = once round)."""
    k = len(cols)
    x = (pos % 1.0) * k
    i = int(x) % k
    return mix(cols[i], cols[(i + 1) % k], x - int(x))


class LinearWave(Effect):
    name = "linear_wave"
    label = "Linear wave"
    help = "A wave of colour crosses the layout at any angle."
    per_pixel = True
    params = [
        Param("colour", "colour", "white"),
        Param("background", "colour", "off"),
        Param("period_s", "number", 2.0, lo=0.05, label="period (s)"),
        Param("count", "number", 1.0, lo=0.1, hi=16, help="waves across the layout at once"),
        Param("waveform", "choice", "sine", choices=WAVEFORMS),
        Param("width", "number", 0.5, lo=0.01, hi=1, help="lit part of each wave (square, pulse)"),
        *SPATIAL,
    ]

    lit_aware = True

    @staticmethod
    def peak(p: dict[str, Any]) -> float:
        """Where in a cycle the wave is brightest (the lit band's centre when lit < 1)."""
        return {"sine": 0.5, "triangle": 0.5, "saw": 0.875, "pulse": 0.0}.get(p["waveform"], p["width"] / 2)

    def render(self, p: dict[str, Any], run: Run) -> None:
        gate, pk = run.gating(), self.peak(p)
        for un in run.units(True):
            x = run.t / p["period_s"] - p["count"] * un.u
            c = mix(p["background"], p["colour"], wave(p["waveform"], x, p["width"]))
            if gate:  # lit: the band is `lit` of each cycle round the peak, the rest black
                g = window(x - pk, run.lit_of(un.fid), run.edge)
                c = scale(c, g) if g > 0 else run.black(un.fid, un.pixel)
            run.put(un, c)
        run.flush()


class Radial(LinearWave):
    name = "radial"
    label = "Radial"
    help = "Rings of colour spread out from the middle of the lights (or close in on it)."
    params = [prm for prm in LinearWave.params if prm.key not in ("direction", "angle")] + [
        Param("inward", "bool", False, help="close in towards the middle instead of spreading out"),
    ]

    def parse(self, d: dict[str, Any], ctx: Any) -> dict[str, Any]:
        p = super().parse(d, ctx)
        p["direction"] = "out_centre" if p["inward"] else "centre_out"
        return p


class Gradient(Effect):
    name = "gradient"
    label = "Gradient sweep"
    help = "A blend of colours laid across the layout, scrolling."
    per_pixel = True
    params = [
        Param("colours", "colours", min_items=2),
        Param("period_s", "number", 8.0, lo=0.05, label="period (s)", help="one scroll through the colours"),
        Param("count", "number", 1.0, lo=0.1, hi=16, help="times the colours repeat across the layout"),
        *SPATIAL,
    ]

    def check(self, p: dict[str, Any], ctx: Any) -> None:
        if "colours" not in p:
            from ..look import LookError

            raise LookError(f"{ctx.what}: gradient needs at least 2 colours")

    lit_aware = True

    def render(self, p: dict[str, Any], run: Run) -> None:
        cols, k = p["colours"], len(p["colours"])
        for un in run.units(True):
            pos = p["count"] * un.u - run.t / p["period_s"]
            lit = run.lit_of(un.fid)
            if lit >= 1.0:
                run.put(un, _cycle(cols, pos))
                continue
            seg = gapped(pos, k, lit)  # gaps of black between the colour segments
            run.put(un, run.black(un.fid, un.pixel) if seg is None
                    else mix(cols[seg[0]], cols[(seg[0] + 1) % k], seg[1]))
        run.flush()


class Bars(LinearWave):
    name = "bars"
    label = "Bars"
    help = "Hard-edged bands of colour moving across the layout."
    params = [prm if prm.key != "count" else Param("count", "number", 3.0, lo=0.1, hi=16, help="bands across the layout")
              for prm in LinearWave.params if prm.key != "waveform"]

    def parse(self, d: dict[str, Any], ctx: Any) -> dict[str, Any]:
        p = super().parse(d, ctx)
        p["waveform"] = "square"
        return p


class Noise(Effect):
    name = "noise"
    label = "Noise / plasma"
    help = "Slowly drifting blobs of colour over the layout."
    per_pixel = True
    params = [
        Param("colours", "colours", min_items=2),
        Param("scale", "number", 1.5, lo=0.2, hi=8, help="bigger = smaller blobs"),
        Param("period_s", "number", 6.0, lo=0.2, label="period (s)", help="how fast it drifts"),
        *SPATIAL,
    ]

    def check(self, p: dict[str, Any], ctx: Any) -> None:
        if "colours" not in p:
            from ..look import LookError

            raise LookError(f"{ctx.what}: noise needs at least 2 colours")

    def render(self, p: dict[str, Any], run: Run) -> None:
        w = 2 * math.pi / p["period_s"]
        s = p["scale"] * 2 * math.pi
        t = run.t
        for un in run.units(True):
            x, y = un.x, un.y
            v = (math.sin(s * x + t * w) + math.sin(s * y * 1.3 - t * w * 0.8)
                 + math.sin(s * (x + y) * 0.7 + t * w * 0.6) + math.sin(s * math.hypot(x - 0.5, y - 0.5) * 1.6 - t * w))
            run.put(un, _cycle(p["colours"], (v / 4 + 1) / 2 * 0.999))
        run.flush()


MATRIX = [LinearWave, Radial, Gradient, Bars, Noise]
