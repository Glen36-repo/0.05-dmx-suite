"""Show file format versions.

Every show file carries `version: N` (the format, not the app version). A file with no `version:`
is format 1 (written before versions existed). Loading:

- older files are upgraded in memory step by step, so the app always parses the current format;
- `ShowStore.upgrade()` also writes them back at start-up, original backed up first, comments kept;
- a file from a newer format is refused with a clear message rather than half-read.

To change a format: bump FORMAT and add a step to STEPS[kind][old_format] that turns the old data
into the new shape. Steps get a copy and return the new data; they never see `version:`.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from .fixtures import ConfigError

FORMAT = 7

# show folder layout: single files, then one folder per kind
FILES = {"fixtures.yaml": "fixtures", "palettes.yaml": "palettes", "panels.yaml": "panels", "inputs.yaml": "inputs",
         "quality.yaml": "quality", "presets.yaml": "presets", "ratings.yaml": "ratings"}
FOLDERS = {"rigs": "rig", "looks": "look", "scenes": "scene", "shows": "show", "setlists": "setlist", "midi": "midi",
           "devices": "device"}


class FormatError(ConfigError):
    pass


def _rig_1_to_2(d: dict[str, Any]) -> dict[str, Any]:
    # rule profiles: a v1 rig ran the 0.05 band rules, so say so explicitly
    d.setdefault("profile", "0.05_band")
    return d


CELLS_PER_M = 4  # layout grid: 25 cm cells


def _rig_2_to_3(d: dict[str, Any]) -> dict[str, Any]:
    # stage plan in metres (x from stage left, y from the front) -> layout grid cells (y down from
    # the back of the stage); the stage size goes, the grid fits what's on it
    stage = d.pop("stage", None) or {}
    try:
        depth = float(stage.get("depth", 4.0))
    except (TypeError, ValueError, AttributeError):
        depth = 4.0
    layout = d.get("layout")
    if isinstance(layout, dict):
        out = {}
        for fid, p in layout.items():
            try:
                x = round(float(p["x"]) * CELLS_PER_M * 2) / 2 + 1  # one cell of margin
                y = round((depth - float(p["y"])) * CELLS_PER_M * 2) / 2 + 1
                out[fid] = {"x": max(0.0, x), "y": max(0.0, y), "rot": p.get("rot", 0)}
            except (KeyError, TypeError, ValueError):
                out[fid] = p  # left for the loader to report
        d["layout"] = out
    return d


def _fixtures_3_to_4(d: dict[str, Any]) -> dict[str, Any]:
    # colour mixing (R7): types written before it keep sending colours exactly as given
    for t in (d.get("types") or {}).values():
        if isinstance(t, dict):
            t.setdefault("colour_mix", "off")
    return d


# Format 4 -> 5 (v3.1) needs no change inside a single file: named inputs (inputs.yaml), head points
# in rig files and `palettes:` are all new and optional, and raw MIDI mappings still load. The moves
# across files (raw mappings -> named inputs, palette positions -> rig points) are made once by
# ShowStore.upgrade (migrate.py), with backups.

# Format 5 -> 6 (v4): the Ride page is the Autopilot page and busking is Override. Pick keys
# `ride` / `bank_ride` become `feel` / `bank_feel`, MIDI actions get their new names, driver ids say
# what the interface does (enttec_open -> usb_dmx_open). Outputs get no `universe:` here on purpose:
# the loader assumes 0 and warns until the routing is confirmed on the Layout page.

def _feel(p: Any) -> Any:
    from .fxbanks import FEEL_KEYS

    if isinstance(p, dict):
        for old, new in FEEL_KEYS.items():
            if old in p and new not in p:
                p[new] = p.pop(old)
    return p


def _rig_5_to_6(d: dict[str, Any]) -> dict[str, Any]:
    from .output import driver_id

    ap = d.get("autopilot")
    if isinstance(ap, dict):
        for k in ("talking", "walk_on", "walk_off"):
            _feel(ap.get(k))
    for o in d.get("outputs") or []:
        if isinstance(o, dict) and "driver" in o:
            o["driver"] = driver_id(o["driver"])
    return d


def _presets_5_to_6(d: dict[str, Any]) -> dict[str, Any]:
    for v in (d.get("presets") or {}).values():
        if isinstance(v, dict):
            _feel(v.get("pick"))
    return d


def _midi_5_to_6(d: dict[str, Any]) -> dict[str, Any]:
    from .midi.map import canonical

    for m in d.get("mappings") or []:
        if isinstance(m, dict) and "action" in m:
            m["action"] = canonical(m["action"])
    return d


# Format 6 -> 7 (v7): between songs gets its own block. Rig `autopilot:` gap_s / count_in / talking
# move into `autopilot: between:` (talking is its `look`). Part D adds the flash steps here.

def _rig_6_to_7(d: dict[str, Any]) -> dict[str, Any]:
    from .autopilot import fold_between

    ap = d.get("autopilot")
    if isinstance(ap, dict):
        d["autopilot"] = fold_between(ap)
    return d


STEPS: dict[str, dict[int, Callable[[dict[str, Any]], dict[str, Any]]]] = {
    "rig": {1: _rig_1_to_2, 2: _rig_2_to_3, 5: _rig_5_to_6, 6: _rig_6_to_7},
    "fixtures": {3: _fixtures_3_to_4},
    "presets": {5: _presets_5_to_6},
    "midi": {5: _midi_5_to_6},
}


def kind_of(path: Path) -> str | None:
    path = Path(path)
    if path.name in FILES:
        return FILES[path.name]
    return FOLDERS.get(path.parent.name)


def format_of(data: dict[str, Any], where: str = "file") -> int:
    v = data.get("version", 1)
    if isinstance(v, bool) or not isinstance(v, int) or v < 1:
        raise FormatError(f"{where}: version must be a whole number (the file format), not {v!r}")
    if v > FORMAT:
        raise FormatError(f"{where} is file format {v}, made by a newer 0.05 DMX Suite; this one reads up to "
                          f"format {FORMAT}. Update the app (or restore the file from .backups)")
    return v


def upgrade(data: Any, kind: str | None, where: str = "file") -> dict[str, Any]:
    """Current-format data without `version:` (what the parsers take)."""
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{where}: expected a mapping (key: value lines) at the top")
    v = format_of(data, where)
    out = {k: x for k, x in data.items() if k != "version"}
    if v < FORMAT and kind is not None:
        out = copy.deepcopy(out)
        for step in range(v, FORMAT):
            fn = STEPS.get(kind, {}).get(step)
            if fn is not None:
                out = fn(out)
    return out


def stamped(data: dict[str, Any]) -> dict[str, Any]:
    """Data as written to disk: `version:` first."""
    return {"version": FORMAT, **{k: v for k, v in data.items() if k != "version"}}


def read_doc(path: str | Path, kind: str | None = None) -> dict[str, Any]:
    """Load a show file the way every loader should: checked, upgraded, without `version:`."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ConfigError(f"{path.name}: not valid YAML: {e}") from e
    return upgrade(data, kind or kind_of(path), path.name)


def needs_upgrade(path: Path) -> bool:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return False  # loading will report it
    return isinstance(data, dict) and format_of(data, path.name) < FORMAT


def show_files(root: Path) -> list[Path]:
    root = Path(root)
    out = [root / f for f in FILES if (root / f).exists()]
    for folder in FOLDERS:
        out += sorted((root / folder).glob("*.yaml"))
    return out
