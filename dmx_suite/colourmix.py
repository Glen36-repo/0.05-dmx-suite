"""Colour mixing (R7): turn a look's colour into what one fixture can actually make.

Looks and palettes give colours as red/green/blue (0-1), optionally with explicit white, amber or
UV. A fixture type with `colour_mix: auto` gets:

- RGBW: the white part taken out of RGB into the white channel (unless the colour sets white)
- RGBA: the orange part into amber (unless the colour sets amber)
- white only (no RGB): white at the colour's brightness
- no emitters (dimmer only, colour wheel): the colour's brightness, and the nearest wheel slot
UV is only ever what the colour asks for. `colour_mix: off` (types from before R7) sends the colour
exactly as given, so older shows look the same.
"""

from __future__ import annotations

from .fixtures import FixtureType, WheelSlot

Colour = dict[str, float]
RGB = ("red", "green", "blue")


def brightness(c: Colour) -> float:
    return max((v for v in c.values()), default=0.0)


def mix(c: Colour, t: FixtureType) -> Colour:
    """The colour for this fixture type's emitters."""
    if t.colour_mix == "off" or not c:
        return c
    em = t.emitters
    rgb = all(r in em for r in RGB)
    out = dict(c)
    r, g, b = (c.get(k, 0.0) for k in RGB)
    if "white" in em and "white" not in c:
        if rgb:
            w = min(r, g, b)
            if w > 0:
                out.update(red=r - w, green=g - w, blue=b - w, white=w)
                r, g, b = r - w, g - w, b - w
        else:
            out["white"] = max(r, g, b)
    if "amber" in em and "amber" not in c and rgb:
        a = max(0.0, min(r, 2 * g) - b)  # amber ~ (1, 0.5, 0)
        if a > 0:
            out.update(red=r - a, green=max(0.0, g - a / 2), amber=a)
    return out


def nearest_slot(c: Colour, t: FixtureType) -> WheelSlot | None:
    """The wheel slot whose colour is closest (by hue and mix, not brightness) to `c`."""
    slots = [s for s in t.wheel.values() if s.colour]
    level = brightness(c)
    if not slots or level <= 0:
        return None
    want = [c.get(k, 0.0) / level for k in RGB]
    white = c.get("white", 0.0) / level
    want = [min(1.0, x + white) for x in want]

    def dist(s: WheelSlot) -> float:
        have = [(s.colour or {}).get(k, 0.0) for k in RGB]
        top = max(have) or 1.0
        return sum((x - y / top) ** 2 for x, y in zip(want, have, strict=True))

    return min(slots, key=dist)
