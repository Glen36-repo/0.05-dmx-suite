"""Look quality rules (v3.3): what makes a good-looking auto show, as data so it can be tuned
without code and read by Claude. Defaults below; `quality.yaml` in the show folder overrides any
part of them (same shape).

    busy:           an item's busy score (0-1) overrides; items default to their bank table value
    max_busy:       the move + colour + drum busy scores together may not go over this
    lead_busy:      above this an item "leads"; never two leads at once (one leads, the other supports)
    mood_speeds:    which item speeds suit each mood
    speed_gap:      move and colour speeds at most this many steps apart (slow, mid, fast)
    contrast:       consecutive looks must change noticeably: a palette hue change of at least
                    min_hue (0-0.5 round the wheel), or a different move or colour item
    (an item whose speed is "still", e.g. a static palette or holding a point, suits any mood)
    palettes:       generated palettes follow colour theory (schemes) and avoid muddy colours
    weights:        how the autopilot and generator score candidates (higher = more likely)
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from .colourtheory import hue_distance, muddy, scheme_of, to_hsv
from .fxbanks import BY_ID, Item, Pick, lookup

SPEEDS = ("slow", "mid", "fast")

DEFAULTS: dict[str, Any] = {
    "busy": {},
    "max_busy": 1.3,
    "lead_busy": 0.55,
    "mood_speeds": {"low": ["slow", "mid"], "mid": ["slow", "mid", "fast"], "high": ["mid", "fast"]},
    "speed_gap": 1,
    "contrast": {"min_hue": 0.1, "move_change": True, "colour_change": True},
    "palettes": {"no_muddy": True, "schemes": ["analogous", "complementary", "triadic", "split", "mono"]},
    "weights": {"mood_match": 3.0, "busy_fit": 2.0, "liked": 2.5, "disliked": -4.0, "repeat": -6.0, "contrast": 1.5},
}


def merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = v
    return out


def check_rules(d: dict[str, Any]) -> None:
    from .fixtures import ConfigError

    if not isinstance(d, dict) or set(d) - set(DEFAULTS):
        raise ConfigError(f"quality.yaml: sections are {', '.join(DEFAULTS)}")
    for k, v in (d.get("busy") or {}).items():
        if k not in BY_ID:
            raise ConfigError(f"quality.yaml busy: unknown FX item {k!r}")
        if not isinstance(v, (int, float)) or not 0 <= v <= 1:
            raise ConfigError(f"quality.yaml busy {k}: 0-1")
    for k in ("max_busy", "lead_busy"):
        if k in d and (not isinstance(d[k], (int, float)) or not 0 <= d[k] <= 4):
            raise ConfigError(f"quality.yaml {k}: a number 0-4")
    for mood, speeds in (d.get("mood_speeds") or {}).items():
        if mood not in ("low", "mid", "high") or not set(speeds) <= set(SPEEDS):
            raise ConfigError("quality.yaml mood_speeds: {low|mid|high: [slow, mid, fast]}")


def load_rules(root: Path | None) -> dict[str, Any]:
    if root is None or not (Path(root) / "quality.yaml").exists():
        return copy.deepcopy(DEFAULTS)
    from .versions import read_doc

    data = read_doc(Path(root) / "quality.yaml", "quality")
    check_rules(data)
    return merge(DEFAULTS, data)


class Quality:
    def __init__(self, rules: dict[str, Any] | None = None) -> None:
        self.r = rules or copy.deepcopy(DEFAULTS)

    def busy(self, item: Item | None) -> float:
        if item is None:
            return 0.0
        return float(self.r["busy"].get(item.id, self.r["busy"].get(item.of or item.id, item.busy)))

    def combo_issues(self, pick: Pick, mood: str) -> list[str]:
        """Why this combination breaks the rules (empty = fine)."""
        items: list[Item] = [i for x in (pick.move, pick.colour, pick.drum) if x and (i := lookup(x)) is not None]
        out = []
        total = sum(self.busy(i) for i in items)
        if total > self.r["max_busy"] + 1e-9:
            out.append(f"too busy together ({total:.2f} > {self.r['max_busy']})")
        leads = [i.id for i in items if i.bank in ("move", "colour") and self.busy(i) > self.r["lead_busy"]]
        if len(leads) > 1:
            out.append(f"two busy effects at once ({' + '.join(leads)}): one leads, the other supports")
        allowed = self.r["mood_speeds"].get(mood, list(SPEEDS))
        for i in items:
            if i.bank in ("move", "colour") and i.speed != "still" and i.speed not in allowed:
                out.append(f"{i.id} is {i.speed}: too {'slow' if SPEEDS.index(i.speed) < 1 else 'fast'} for {mood}")
        mv, cv = lookup(pick.move), lookup(pick.colour)
        if (mv and cv and "still" not in (mv.speed, cv.speed)
                and abs(SPEEDS.index(mv.speed) - SPEEDS.index(cv.speed)) > self.r["speed_gap"]):
            out.append(f"movement ({mv.speed}) and colour ({cv.speed}) speeds don't match")
        return out

    def contrast_ok(self, prev: Pick | None, pick: Pick, palettes: dict[str, list[Any]]) -> bool:
        """Consecutive looks change noticeably: colour, movement or the colour effect."""
        if prev is None:
            return True
        c = self.r["contrast"]
        if c.get("move_change") and prev.move != pick.move:
            return True
        if c.get("colour_change") and prev.colour != pick.colour:
            return True
        a, b = palettes.get(prev.palette) or [], palettes.get(pick.palette) or []
        return palette_hue_change(a, b) >= c.get("min_hue", 0.08)

    def palette_issues(self, colours: list[dict[str, float]]) -> list[str]:
        p = self.r["palettes"]
        out = []
        if p.get("no_muddy") and any(muddy(c) for c in colours):
            out.append("has a muddy colour (mid saturation, low brightness)")
        if len(colours) > 1 and scheme_of(colours) not in p.get("schemes", []):
            out.append("doesn't follow a colour-theory scheme")
        return out


def palette_hue_change(a: list[dict[str, float]], b: list[dict[str, float]]) -> float:
    """How far apart two palettes are round the colour wheel (0-0.5), by their main colours."""
    def main(cols: list[dict[str, float]]) -> float | None:
        sat = [to_hsv(c) for c in cols if to_hsv(c)[1] > 0.15]
        return sat[0][0] if sat else None

    ha, hb = main(a), main(b)
    if ha is None or hb is None:
        return 0.5 if (ha is None) != (hb is None) else 0.0
    return hue_distance(ha, hb)
