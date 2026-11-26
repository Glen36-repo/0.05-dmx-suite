"""Colour theory (v3.1): hue maths, palettes generated from a base colour, white temperature.

Shared by the palette editor, the colour wheel (kelvin presets) and, from V3.3, the look quality
rules, so a palette made by hand and one picked by the auto show follow the same rules.

Colours here are RGB 0-1 dicts like the rest of the app ({red, green, blue}).
"""

from __future__ import annotations

import colorsys
import math
from typing import Any

Colour = dict[str, float]

SCHEMES = ("analogous", "complementary", "triadic", "split", "mono")

# White temperature presets for the colour wheel (warm incandescent to cool daylight)
KELVIN_PRESETS: list[tuple[str, int]] = [
    ("Candle", 1900), ("Incandescent", 2700), ("Warm white", 3000), ("Halogen", 3200), ("Neutral", 4000),
    ("Cool white", 5000), ("Daylight", 5600), ("Overcast", 6500), ("Blue sky", 9000),
]


def to_hsv(c: Colour) -> tuple[float, float, float]:
    return colorsys.rgb_to_hsv(c.get("red", 0.0), c.get("green", 0.0), c.get("blue", 0.0))


def from_hsv(h: float, s: float, v: float) -> Colour:
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, max(0.0, min(1.0, s)), max(0.0, min(1.0, v)))
    return {"red": round(r, 4), "green": round(g, 4), "blue": round(b, 4)}


def hex_of(c: Colour) -> str:
    return "#" + "".join(f"{round(max(0.0, min(1.0, c.get(k, 0.0))) * 255):02x}" for k in ("red", "green", "blue"))


def hue_distance(a: float, b: float) -> float:
    """0-0.5: how far apart two hues are round the wheel."""
    d = abs(a - b) % 1.0
    return min(d, 1.0 - d)


def kelvin(k: float) -> Colour:
    """RGB for a white temperature (Tanner Helland's fit to the black-body curve, 1,000-40,000 K)."""
    t = max(1000.0, min(40000.0, float(k))) / 100
    if t <= 66:
        r = 255.0
        g = 99.4708025861 * math.log(t) - 161.1195681661
        b = 0.0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307
    else:
        r = 329.698727446 * (t - 60) ** -0.1332047592
        g = 288.1221695283 * (t - 60) ** -0.0755148492
        b = 255.0
    return {k2: round(max(0.0, min(255.0, x)) / 255, 4) for k2, x in (("red", r), ("green", g), ("blue", b))}


def generate(base: Colour, scheme: str, count: int = 4) -> list[Colour]:
    """A palette of `count` colours from `base`, by a colour-theory scheme:

    analogous     neighbours on the wheel (±30° steps)
    complementary base and its opposite, with lighter/darker versions
    triadic       three hues 120° apart
    split         base and the two hues either side of its opposite (±150°)
    mono          one hue, stepped saturation and brightness
    The base colour always comes first."""
    if scheme not in SCHEMES:
        raise ValueError(f"scheme is one of {', '.join(SCHEMES)}")
    count = max(2, min(12, int(count)))
    h, s, v = to_hsv(base)
    s = s if s > 0.05 else 1.0  # a white or grey base: theory needs a hue, so use a full colour of it
    v = v or 1.0
    hues: list[tuple[float, float, float]]
    if scheme == "analogous":
        offs = [0, 1, -1, 2, -2, 3, -3, 4, -4, 5, -5, 6]
        hues = [(h + o / 12, s, v) for o in offs]
    elif scheme == "complementary":
        hues = [(h, s, v), (h + 0.5, s, v), (h, s * 0.55, v), (h + 0.5, s * 0.55, v), (h, s, v * 0.6), (h + 0.5, s, v * 0.6)]
    elif scheme == "triadic":
        hues = [(h + i / 3, s, v) for i in range(3)] + [(h + i / 3, s * 0.55, v) for i in range(3)]
    elif scheme == "split":
        hues = [(h, s, v), (h + 5 / 12, s, v), (h + 7 / 12, s, v), (h, s * 0.55, v), (h + 5 / 12, s * 0.55, v),
                (h + 7 / 12, s * 0.55, v)]
    else:  # mono
        hues = [(h, s * (1 - i * 0.18), v * (1 - (i % 2) * 0.25)) for i in range(12)]
    out: list[Colour] = []
    i = 0
    while len(out) < count:
        hh, ss, vv = hues[i % len(hues)]
        if i >= len(hues):  # more than the scheme has: step brightness down
            vv *= max(0.3, 1 - 0.2 * (i // len(hues)))
        c = from_hsv(hh, ss, vv)
        if c not in out:
            out.append(c)
        i += 1
        if i > 60:
            break
    return out


def muddy(c: Colour) -> bool:
    """A colour that reads as brown/grey mud on stage: mid saturation at low-mid brightness."""
    _, s, v = to_hsv(c)
    return 0.15 < s < 0.55 and 0.1 < v < 0.5


def scheme_of(colours: list[Colour]) -> str | None:
    """Which theory scheme a palette follows, if any (for tags and the quality rules)."""
    hs = [to_hsv(c) for c in colours if to_hsv(c)[1] > 0.15]
    if len(hs) < 2:
        return "mono"
    hues = [h for h, _, _ in hs]
    spread = max(hue_distance(a, b) for a in hues for b in hues)
    if spread <= 1 / 24:
        return "mono"
    if spread <= 0.25 + 1e-6 and all(min(hue_distance(a, b) for b in hues if b is not a) <= 1 / 12 + 1e-6 for a in hues):
        return "analogous"
    groups = _clusters(hues)
    if len(groups) == 2 and abs(hue_distance(groups[0], groups[1]) - 0.5) <= 1 / 24:
        return "complementary"
    if len(groups) == 3 and all(abs(hue_distance(a, b) - 1 / 3) <= 1 / 24 for i, a in enumerate(groups) for b in groups[i + 1:]):
        return "triadic"
    if len(groups) == 3:
        return "split"
    return None


def _clusters(hues: list[float], tol: float = 1 / 24) -> list[float]:
    out: list[float] = []
    for h in hues:
        if all(hue_distance(h, g) > tol for g in out):
            out.append(h)
    return out


def describe(c: Colour) -> dict[str, Any]:
    h, s, v = to_hsv(c)
    return {"hex": hex_of(c), "hue": round(h * 360), "saturation": round(s, 3), "brightness": round(v, 3)}
