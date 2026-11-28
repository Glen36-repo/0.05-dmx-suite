"""Per-rig FX settings (v8 item 14): overrides on the FX bank items and variants (duplicates).

Rig config (format 8):
    autopilot:
      fx:                                   # bank item id -> only the changed values
        fan:
          priority: 4                       # 0-5 pick weight; 0 = excluded (default 3)
          restore: 4                        # excluded: the priority it goes back to (written by Exclude mode)
          darkness: exempt                  # follow | exempt | 0-1 (Reduced: share of the Darkness value)
          moods: [mid, high]
          min_s: 20                         # time on screen (s), within the mood timer
          max_s: 60
          params: {phase: 0.25, size: 0.8}  # the effect's own settings (its Param list)
      variants:                             # duplicates, picked as their own types
        fan_v1: {of: fan, name: "Fan slow wide", priority: 3, params: {period_s: 12}}
      palette_settings:                     # palette tiles: priority and darkness only
        ice: {priority: 0}

`autopilot: palettes:` is the v3 list of allowed palettes, so palette tiles use `palette_settings`.
Flash FX take no overrides (they're played by hand). A variant shares no-repeat with its original.
"""

from __future__ import annotations

import copy
import math
import re
from dataclasses import replace
from typing import Any

from .fixtures import ConfigError

KEYS = ("priority", "restore", "darkness", "moods", "min_s", "max_s", "params")
VARIANT_KEYS = ("of", "name", *KEYS)
PALETTE_KEYS = ("priority", "restore", "darkness")
DARKNESS = ("follow", "exempt")
DEFAULT_PRIORITY = 3
MOODS = ("low", "mid", "high")
# settings the panel doesn't offer: colours come from the playing palette, fixtures from the bank; free text
# (tags, seed) and positions (points come with v8 Part B's Position / Point tour) aren't per-look settings
FIXED_PARAMS = {"colour", "colours", "background", "fixtures", "blend", "tags", "seed"}
FIXED_KINDS = {"colour", "colours", "position", "text"}
VARIANT_ID = re.compile(r"^(?P<of>[a-z0-9_]+)_v(?P<n>\d+)$")


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


def editable_params(item: Any) -> list[Any]:
    """The effect's Params the panel offers for this item (Flash FX: none)."""
    from .effects import get

    if item.bank == "flash":
        return []
    eff = get(str(item.layer.get("effect", "")))
    if eff is None:
        return []
    fixed = FIXED_PARAMS | ({"pattern"} if item.bank == "move" else set())  # a Move FX's pattern is what it is
    return [p for p in eff.params if p.key not in fixed and p.kind not in FIXED_KINDS]


def check_params(item: Any, params: Any, where: str) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise ConfigError(f"{where} params: {{setting: value}}")
    by_key = {p.key: p for p in editable_params(item)}
    out: dict[str, Any] = {}
    for k, v in params.items():
        p = by_key.get(str(k))
        if p is None:
            raise ConfigError(f"{where} params: {item.label} has no setting {k!r}"
                              + (f" (settings: {', '.join(sorted(by_key))})" if by_key else ""))
        if p.kind in ("number", "int", "angle"):
            f = _num(v)
            if f is None or (p.lo is not None and f < p.lo) or (p.hi is not None and f > p.hi):
                lo = "" if p.lo is None else f"{p.lo:g}"
                hi = "" if p.hi is None else f"{p.hi:g}"
                raise ConfigError(f"{where} params {k}: a number {lo}-{hi}".rstrip("-"))
            v = int(f) if p.kind == "int" else v
        elif p.kind == "bool":
            if not isinstance(v, bool):
                raise ConfigError(f"{where} params {k}: true or false")
        elif p.kind == "choice":
            if p.choices and v not in p.choices:
                raise ConfigError(f"{where} params {k}: one of {', '.join(p.choices)}")
        out[str(k)] = v
    return out


def check(item: Any, d: Any, where: str, keys: tuple[str, ...] = KEYS) -> dict[str, Any]:
    """One item's overrides, checked; only the keys given are kept."""
    if not isinstance(d, dict) or set(d) - set(keys):
        raise ConfigError(f"{where}: settings are {', '.join(keys)}")
    out: dict[str, Any] = {}
    if "priority" in d:
        p = d["priority"]
        if isinstance(p, bool) or not isinstance(p, int) or not 0 <= p <= 5:
            raise ConfigError(f"{where} priority: a whole number 0-5 (0 = excluded)")
        out["priority"] = p
    if "restore" in d:  # the priority an excluded tile goes back to when it's put back
        r = d["restore"]
        if isinstance(r, bool) or not isinstance(r, int) or not 1 <= r <= 5:
            raise ConfigError(f"{where} restore: a whole number 1-5")
        out["restore"] = r
    if "darkness" in d:
        v = d["darkness"]
        if v not in DARKNESS and (_num(v) is None or not 0 <= v <= 1):
            raise ConfigError(f"{where} darkness: follow, exempt or 0-1 (share of the Darkness value)")
        out["darkness"] = v
    if "moods" in d:
        m = d["moods"]
        if not isinstance(m, list) or not m or set(m) - set(MOODS):
            raise ConfigError(f"{where} moods: one or more of low, mid, high")
        out["moods"] = [x for x in MOODS if x in m]
    for k in ("min_s", "max_s"):
        if k in d and d[k] is not None:
            f = _num(d[k])
            if f is None or not 2 <= f <= 3600:
                raise ConfigError(f"{where} {k}: 2-3600 s")
            out[k] = d[k]
    if "min_s" in out and "max_s" in out and out["min_s"] > out["max_s"]:
        raise ConfigError(f"{where}: min_s is more than max_s")
    if "params" in d:
        out["params"] = check_params(item, d["params"], where)
    return out


def apply(item: Any, ov: dict[str, Any], *, id_: str | None = None, label: str | None = None,
          of: str | None = None) -> Any:
    """The bank item with its overrides (a new Item; the bank is never changed)."""
    layer = copy.deepcopy(item.layer)
    layer.update(copy.deepcopy(ov.get("params") or {}))
    return replace(item, id=id_ or item.id, label=label or item.label, layer=layer,
                   moods=tuple(ov.get("moods") or item.moods),
                   priority=int(ov.get("priority", DEFAULT_PRIORITY)), darkness=ov.get("darkness", "follow"),
                   min_s=ov.get("min_s"), max_s=ov.get("max_s"), of=of or item.of,
                   overridden=bool(ov) or of is not None)


def parse(fx: Any, variants: Any, palette_settings: Any = None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Checked `autopilot: fx`, `variants` and `palette_settings` blocks."""
    from .fxbanks import BY_ID

    fx = {} if fx is None else fx
    variants = {} if variants is None else variants
    palette_settings = {} if palette_settings is None else palette_settings
    if not isinstance(fx, dict):
        raise ConfigError("autopilot fx: {FX type: {priority, darkness, moods, min_s, max_s, params}}")
    out_fx: dict[str, Any] = {}
    for k, v in fx.items():
        item = BY_ID.get(str(k))
        if item is None:
            raise ConfigError(f"autopilot fx: unknown FX type {k!r}")
        if item.bank == "flash":
            raise ConfigError(f"autopilot fx: {k} is a Flash FX (played by hand, never by the autopilot)")
        out_fx[str(k)] = check(item, v, f"autopilot fx {k}")
    if not isinstance(variants, dict):
        raise ConfigError("autopilot variants: {id: {of: FX type, name, ...settings}}")
    out_var: dict[str, Any] = {}
    for k, v in variants.items():
        k = str(k)
        if not isinstance(v, dict) or "of" not in v:
            raise ConfigError(f"autopilot variants {k}: needs of: <FX type> (the item it copies)")
        item = BY_ID.get(str(v["of"]))
        if item is None or item.bank == "flash":
            raise ConfigError(f"autopilot variants {k}: of {v['of']!r} is not a Move, Colour or Drum FX type")
        if k in BY_ID or not re.fullmatch(r"[a-z0-9_]+", k):
            raise ConfigError(f"autopilot variants {k}: an id of lower-case letters, digits and _ that isn't an FX type")
        name = v.get("name")
        if name is not None and (not isinstance(name, str) or not name.strip()):
            raise ConfigError(f"autopilot variants {k} name: some text")
        rest = check(item, {x: y for x, y in v.items() if x not in ("of", "name")}, f"autopilot variants {k}")
        out_var[k] = {"of": item.id, **({"name": name.strip()} if name else {}), **rest}
    if not isinstance(palette_settings, dict):
        raise ConfigError("autopilot palette_settings: {palette: {priority, darkness}}")
    out_pal: dict[str, Any] = {}
    for k, v in palette_settings.items():
        out_pal[str(k)] = check(None, v, f"autopilot palette_settings {k}", PALETTE_KEYS)
    return out_fx, out_var, out_pal


def rig_items(cfg: dict[str, Any] | None) -> dict[str, Any]:
    """Every bank item for this rig: overrides applied, variants added next to their originals."""
    from .fxbanks import BY_ID, FLASH_ITEMS, ITEMS

    cfg = cfg or {}
    fx = cfg.get("fx") or {}
    variants = cfg.get("variants") or {}
    out: dict[str, Any] = {}
    by_of: dict[str, list[str]] = {}
    for vid, v in variants.items():
        by_of.setdefault(v["of"], []).append(vid)
    for it in ITEMS:
        out[it.id] = apply(it, fx[it.id]) if it.id in fx else it
        for vid in by_of.get(it.id, []):
            v = variants[vid]
            out[vid] = apply(it, v, id_=vid, label=v.get("name") or variant_name(it.label, vid), of=it.id)
    for it in FLASH_ITEMS:
        out[it.id] = it
    assert all(k in out or k in BY_ID for k in out)
    return out


def variant_name(label: str, vid: str) -> str:
    m = VARIANT_ID.match(vid)
    return f"{label} {int(m['n']) + 1}" if m else label


def new_variant_id(of: str, taken: set[str]) -> str:
    n = 1
    while f"{of}_v{n}" in taken:
        n += 1
    return f"{of}_v{n}"


def family(item: Any) -> str:
    """No-repeat key: a variant counts as its original."""
    return item.of or item.id


def darkness_share(item: Any) -> float:
    """How much of the Darkness value applies to this item: 1 follow, 0 exempt, else the Reduced share."""
    return share(getattr(item, "darkness", "follow"))


def share(d: Any) -> float:
    """A Darkness setting as a share: follow 1, exempt 0, Reduced its number."""
    if d == "exempt":
        return 0.0
    if d == "follow" or d is None:
        return 1.0
    return float(d)


def from_exclude_lists(auto: dict[str, Any], autopilot: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Format 7 -> 8: `auto: exclude_fx / exclude_palettes` become priority 0 under `autopilot:`."""
    auto = dict(auto)
    ap = dict(autopilot)
    xfx = auto.pop("exclude_fx", None) or []
    xpal = auto.pop("exclude_palettes", None) or []
    if xfx:
        fx = dict(ap.get("fx") or {})
        for k in xfx:
            k = RENAMED.get(str(k), str(k))
            fx[k] = {**(fx.get(k) or {}), "priority": 0}
        ap["fx"] = fx
    if xpal:
        ps = dict(ap.get("palette_settings") or {})
        for k in xpal:
            ps[str(k)] = {**(ps.get(str(k)) or {}), "priority": 0}
        ap["palette_settings"] = ps
    return auto, ap


RENAMED = {"sweep": "dir_wave", "sweep_dark": "dir_wave_dark"}  # v8 item 6
FLASH_REMOVED = {"chase_hit": "colour_hit", "split_hit": "colour_hit"}  # v8 item 9


def exclude(ov: dict[str, Any], excluded: bool) -> dict[str, Any]:
    """Exclude mode / the switch: priority 0 keeping the old one to restore; putting back restores it."""
    ov = dict(ov)
    if excluded:
        old = int(ov.get("priority", DEFAULT_PRIORITY))
        if old:
            ov["priority"] = 0
            if old != DEFAULT_PRIORITY:
                ov["restore"] = old
    elif ov.get("priority") == 0:
        back = int(ov.pop("restore", DEFAULT_PRIORITY))
        ov.pop("priority")
        if back != DEFAULT_PRIORITY:
            ov["priority"] = back
    return ov


def set_priority(ov: dict[str, Any], priority: int) -> dict[str, Any]:
    ov = {k: v for k, v in ov.items() if k != "restore"}
    if priority == DEFAULT_PRIORITY:
        ov.pop("priority", None)
    else:
        ov["priority"] = priority
    return ov


def next_badge(priority: int) -> int:
    """Tapping the badge: 1 -> 2 -> ... -> 5 -> 1 (never 0: excluding is a deliberate action)."""
    return 1 if priority >= 5 or priority < 1 else priority + 1
