"""Presets and look ratings (v3.5).

A preset is a saved Ride look (FX + palette + ride settings) with a name, in presets.yaml:

    presets:
      verse_blues: {name: Verse blues, tags: [low], pick: {move: swim, colour: colour_fade, palette: cool,
                                                           ride: {speed: 0.8}}}

Presets go on the Ride page's grid, can limit the autopilot ("only these looks for this song"), and
are used in shows and setlists like scenes: a show step `{preset: verse_blues, hold_s: 30}`, a song
`{name: Intro, preset: verse_blues}`, or a song run by the autopilot with only some presets
`{name: Encore, presets: [verse_blues, chorus_fire], mood: high}`. A preset is composed for the
running rig when the show loads, so the same preset works on any rig.

Starter presets ship built in (a preset in the file with the same id replaces one).

Ratings (ratings.yaml) are thumbs up (1), down (-1) or ban (-2) per look, from the look review
page; the autopilot and the generator favour liked looks and skip banned ones:

    looks: {"pan_sweep|colour_chase|-|cool": 1, "ballyhoo|police|-|neon": -2}
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .fixtures import ConfigError

ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
PRESET_PREFIX = "preset:"

STARTERS: dict[str, dict[str, Any]] = {
    "calm_warm": {"name": "Calm warm", "tags": ["low"], "pick": {"colour": "colour_fade", "palette": "warm", "move": "float",
                                                               "ride": {"speed": 0.7}}},
    "cool_drift": {"name": "Cool drift", "tags": ["low"], "pick": {"colour": "twinkle", "palette": "cool", "move": "swim"}},
    "band_groove": {"name": "Band groove", "tags": ["mid"], "pick": {"colour": "colour_chase", "palette": "band",
                                                                  "move": "pan_sweep", "drum": "kick_pump"}},
    "fire_wave": {"name": "Fire wave", "tags": ["mid"], "pick": {"colour": "wave", "palette": "fire", "move": "figure8"}},
    "neon_hits": {"name": "Neon hits", "tags": ["high"], "pick": {"colour": "static", "palette": "neon", "move": "ballyhoo",
                                                               "drum": "snare_hit", "ride": {"speed": 1.3}}},
    "white_lights": {"name": "White", "tags": ["low", "mid"], "pick": {"colour": "static", "palette": "white", "move": "kit"}},
}


def look_key(pick: dict[str, Any]) -> str:
    """The rating key of a look: move|colour|drum|palette."""
    return f"{pick.get('move') or '-'}|{pick.get('colour') or '-'}|{pick.get('drum') or '-'}|{pick.get('palette') or 'warm'}"


def check_pick(pick: Any, palettes: set[str] | None, what: str) -> dict[str, Any]:
    from .fxbanks import BY_ID, RANGES

    if not isinstance(pick, dict) or set(pick) - {"move", "colour", "drum", "palette", "ride", "bank_ride"}:
        raise ConfigError(f"{what}: pick is {{move, colour, drum, palette, ride, bank_ride}}")
    for bank in ("move", "colour", "drum"):
        v = pick.get(bank)
        if v is not None and (v not in BY_ID or BY_ID[v].bank != bank):
            raise ConfigError(f"{what}: {bank} {v!r} isn't a {bank} FX item")
    if palettes is not None and pick.get("palette", "warm") not in palettes:
        raise ConfigError(f"{what}: unknown palette {pick.get('palette')!r}")
    for r in [pick.get("ride") or {}, *((pick.get("bank_ride") or {}).values())]:
        if not isinstance(r, dict) or set(r) - set(RANGES):
            raise ConfigError(f"{what}: ride settings are {', '.join(RANGES)}")
        for k, v in r.items():
            lo, hi = RANGES[k]
            if not isinstance(v, (int, float)) or not lo <= v <= hi:
                raise ConfigError(f"{what}: ride {k} {lo:g}-{hi:g}")
    return pick


def parse_presets(data: dict[str, Any] | None, palettes: set[str] | None = None) -> dict[str, dict[str, Any]]:
    data = data or {}
    if set(data) - {"presets"}:
        raise ConfigError("presets.yaml: presets only")
    out: dict[str, dict[str, Any]] = {}
    for k, v in STARTERS.items():
        out[k] = {**v, "builtin": True}
    for k, v in (data.get("presets") or {}).items():
        what = f"preset {k}"
        if not ID.match(str(k)):
            raise ConfigError(f"{what}: names use lower case letters, digits, _ or -")
        if not isinstance(v, dict) or set(v) - {"name", "tags", "pick"} or "pick" not in v:
            raise ConfigError(f"{what}: name, tags and pick")
        tags = v.get("tags") or []
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            raise ConfigError(f"{what}: tags is a list of words")
        out[str(k)] = {"name": str(v.get("name") or k), "tags": list(tags), "pick": check_pick(v["pick"], palettes, what),
                       "builtin": False}
    return out


def load_presets(root: Path, palettes: set[str] | None = None) -> dict[str, dict[str, Any]]:
    p = Path(root) / "presets.yaml"
    if not p.exists():
        return parse_presets({}, palettes)
    from .versions import read_doc

    return parse_presets(read_doc(p, "presets"), palettes)


def load_ratings(root: Path) -> dict[str, int]:
    p = Path(root) / "ratings.yaml"
    if not p.exists():
        return {}
    from .versions import read_doc

    d = read_doc(p, "ratings")
    looks = d.get("looks") or {}
    if set(d) - {"looks"} or not isinstance(looks, dict) or any(v not in (1, -1, -2) for v in looks.values()):
        raise ConfigError("ratings.yaml: looks {look: 1 (liked), -1 (disliked) or -2 (banned)}")
    return {str(k): int(v) for k, v in looks.items()}


def preset_scenes(presets: dict[str, dict[str, Any]], rig: Any, pal: Any, patch: Any) -> dict[str, Any]:
    """Each preset as a scene for this rig ("preset:<id>"), for show steps and setlist songs."""
    from .classify import auto_rig
    from .fxbanks import Pick, compose
    from .scenes import parse_scene

    ar = auto_rig(rig)
    out = {}
    for k, v in presets.items():
        pick = Pick.from_dict(v["pick"])
        key = pick.palette if pick.palette in pal.sets else next(iter(pal.sets))
        data = compose(pick, ar, list(pal.sets[key]["colours"]), v["name"])
        out[PRESET_PREFIX + k] = parse_scene(data, patch, pal, v["name"])
    return out
