"""The rig from the v4 brief's screenshot (27/11/2026, after the Daslight import): the real U0
patch with channel counts as Daslight has them, and the layout that drew badly - par_1 on mh_a,
par_4 on mh_b, four 8-pixel bars end to end, the smoke machine among the washes and U'Kings.

`make(root)` turns a copy of the shipped `shows/` folder into that rig."""

from __future__ import annotations

from pathlib import Path

import yaml


def _pad(n: int) -> list:
    return [{"role": "fixed", "default": 0}] * n


TYPES = {
    "mhl36": {"name": "MHL36 16ch", "kind": "head", "colour_mix": "off", "home": {"pan": 0.5, "tilt": 0.5},
             "channels": ["pan", "pan_fine", "tilt", "tilt_fine", {"role": "pt_speed", "invert": True}, "dimmer",
                          {"role": "strobe", "default": 0}, "red", "green", "blue", "white", "gobo", *_pad(4)]},
    "uking_mini": {"name": "U'King 14ch", "kind": "head", "colour_mix": "off", "colour_only": True,
                "home": {"pan": 0.5, "tilt": 0.5},
                "channels": ["pan", "tilt", {"role": "pt_speed", "invert": True}, "dimmer", "red", "green", "blue",
                             "white", {"role": "strobe", "default": 0}, *_pad(5)]},
    # 48ch: per segment dimmer, R, G, B, strobe, fixed (each segment's dimmer/strobe owned by MASTER)
    "lcb803": {"name": "LCB803 48ch", "kind": "bar", "colour_mix": "off",
                  "channels": [c for px in range(8) for c in ("dimmer", {"role": "red", "pixel": px},
                               {"role": "green", "pixel": px}, {"role": "blue", "pixel": px},
                               {"role": "strobe", "default": 0}, {"role": "fixed", "default": 0})]},
    "starcolor72": {"name": "Wash 10ch", "kind": "wash", "colour_mix": "off",
               "channels": ["dimmer", "red", "green", "blue", "white", {"role": "strobe", "default": 0}, *_pad(4)]},
    "par7": {"name": "Par 7ch", "kind": "wash", "colour_mix": "off",
             "channels": ["dimmer", "red", "green", "blue", "white", {"role": "strobe", "default": 0}, *_pad(1)]},
    "kick_rgb": {"name": "Kick-drum RGB light", "kind": "kick", "colour_mix": "off", "channels": ["red", "green", "blue"]},
    "smoke": {"name": "Smoke machine", "kind": "haze", "colour_mix": "off", "channels": ["haze"]},
}

PATCH = [  # (id, type, address, groups) - the brief's U0 table
    ("smoke", "smoke", 1, []),
    ("uking_r", "uking_mini", 27, ["heads", "ukings"]),
    ("uking_l", "uking_mini", 67, ["heads", "ukings"]),
    ("bar_3", "lcb803", 81, ["bars"]),
    ("bar_1", "lcb803", 129, ["bars"]),
    ("bar_2", "lcb803", 183, ["bars"]),
    ("bar_4", "lcb803", 231, ["bars"]),
    ("kick", "kick_rgb", 279, []),
    ("wash_l", "starcolor72", 300, ["washes"]),
    ("wash_r", "starcolor72", 310, ["washes"]),
    ("mh_a", "mhl36", 321, ["heads", "movers"]),
    ("mh_b", "mhl36", 337, ["heads", "movers"]),
    ("par_2", "par7", 385, ["pars"]),
    ("par_1", "par7", 392, ["pars"]),
    ("par_3", "par7", 399, ["pars"]),
    ("par_4", "par7", 406, ["pars"]),
]

LAYOUT = {  # what the import left: stacked and crowded
    "mh_a": {"x": 6, "y": 2, "rot": 0}, "par_1": {"x": 6, "y": 2, "rot": 0},
    "mh_b": {"x": 30, "y": 2, "rot": 0}, "par_4": {"x": 30, "y": 2, "rot": 0},
    "par_2": {"x": 14, "y": 2, "rot": 0}, "par_3": {"x": 22, "y": 2, "rot": 0},
    "bar_1": {"x": 4.5, "y": 6, "rot": 0}, "bar_2": {"x": 12.5, "y": 6, "rot": 0},
    "bar_3": {"x": 20.5, "y": 6, "rot": 0}, "bar_4": {"x": 28.5, "y": 6, "rot": 0},
    "wash_l": {"x": 16, "y": 10, "rot": 0}, "uking_l": {"x": 17, "y": 10, "rot": 0},
    "uking_r": {"x": 18, "y": 10, "rot": 0}, "wash_r": {"x": 19, "y": 10, "rot": 0},
    "smoke": {"x": 17.5, "y": 10, "rot": 0}, "kick": {"x": 17.5, "y": 13, "rot": 0},
}


def make(root: Path) -> Path:
    fx = {"version": 6, "types": TYPES,
          "fixtures": [{"id": i, "type": t, "address": a, **({"groups": g} if g else {})} for i, t, a, g in PATCH]}
    (root / "fixtures.yaml").write_text(yaml.safe_dump(fx, sort_keys=False), encoding="utf-8")
    for name in ("full", "small"):
        p = root / "rigs" / f"{name}.yaml"
        rig = yaml.safe_load(p.read_text(encoding="utf-8"))
        rig["fixtures"] = ["all"]
        rig["layout"] = LAYOUT
        rig.pop("sub_masters", None)
        p.write_text(yaml.safe_dump(rig, sort_keys=False), encoding="utf-8")
    return root
