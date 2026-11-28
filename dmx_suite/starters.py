"""Starter shows (R7): a working show for any rig, built from generic effects, so a new user has
something lit straight after adding their lights.

The scenes only use what each light can do: colour on every light, effects that run across the
whole rig (laid out on the light layout), and movement only on heads that move. Colours are
written as #rrggbb so no palette entries are needed. Nothing sets intensity or haze, so the
scenes pass under every rule profile.
"""

from __future__ import annotations

from typing import Any

from .fixtures import Kind
from .rig import Rig

PREFIX = "starter_"


def _scene(name: str, layers: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {"name": name, **extra, "layers": layers}


def starter(rig: Rig, show_key: str = "starter") -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """(scenes by file name, the show) for this rig."""
    lights = [f.id for f in rig.fixtures if f.kind != Kind.HAZE]
    if not lights:
        raise ValueError("add some lights to the rig first")
    movers = [f.id for f in rig.fixtures if f.type.has("pan") and not f.type.colour_only]
    still = [f for f in lights if f not in movers]
    scenes: dict[str, dict[str, Any]] = {
        "warm": _scene("Starter: warm", [{"fixtures": lights, "colour": "#ffb070"}], show_colour="#ffb070"),
        "blue": _scene("Starter: deep blue", [{"fixtures": lights, "colour": "#1a3cff"}], show_colour="#1a3cff"),
        "rainbow": _scene("Starter: rainbow", [{"fixtures": lights, "effect": "rainbow", "period_s": 10, "spread": 1}]),
        "chase": _scene("Starter: colour chase", [{"fixtures": lights, "effect": "colour_chase",
                                                   "colours": ["#ff2020", "#2040ff", "#ffffff"], "period_s": 3, "spread": 1}],
                        show_colour="#ff2020"),
        "wave": _scene("Starter: wave", [{"fixtures": lights, "colour": "#102060"},
                                         {"fixtures": lights, "effect": "linear_wave", "colour": "#00c0ff",
                                          "period_s": 3, "blend": "max"}], show_colour="#00c0ff"),
        "sparkle": _scene("Starter: sparkle", [{"fixtures": lights, "effect": "sparkle", "colour": "#ffffff",
                                                "background": "#200040", "density": 0.2}]),
    }
    if movers:  # heads that move draw slow circles; everything else stays in colour
        layers: list[dict[str, Any]] = [{"fixtures": lights, "colour": "#8020ff"},
                                        {"fixtures": movers, "effect": "circle", "centre": {"pan": 0.5, "tilt": 0.4},
                                         "size": 0.1, "period_s": 8, "spread": 0.5}]
        scenes["circles"] = _scene("Starter: circles", layers, show_colour="#8020ff")
    if still and movers:
        scenes["wave"]["layers"].append({"fixtures": movers, "colour": "#00c0ff"})
    calm = [{"scene": PREFIX + "warm", "hold_s": 20}, {"scene": PREFIX + "blue", "hold_s": 20},
            {"scene": PREFIX + "wave", "repeats": 4}]
    if movers:
        calm.append({"scene": PREFIX + "circles", "repeats": 2})
    show = {
        "name": "Starter show",
        "sets": {
            "calm": {"fade_s": 2, "loop": True, "steps": calm},
            "lively": {"fade_s": 0.5, "loop": True, "steps": [
                {"scene": PREFIX + "chase", "repeats": 4},
                {"scene": PREFIX + "rainbow", "hold_bars": 8},
                {"scene": PREFIX + "sparkle", "hold_s": 10},
            ]},
        },
    }
    return {PREFIX + k: v for k, v in scenes.items()}, show
