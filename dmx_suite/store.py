"""Show folder store: every edit from the browser UI or Claude (MCP) goes through here.

A change is staged in a scratch copy of the show folder and the whole folder is validated
(`check_all`: rules, references, auto shows on every rig). Only if that passes is the file
written, after the previous version is copied to `.backups/<date-time>/` so any change can be undone.
Saves keep the file's comments and layout (yamlio.update_text): only what changed is rewritten.

Undo/redo (R6): every change made while the app runs is remembered with the files' text before
and after, so it can be undone and redone, unlimited, until the app closes. An undo is refused if
the files have changed since in some other way (use the backups then). Each change records who
made it ("ui" or "claude"), so Claude can undo its own last change without touching yours.
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .fixtures import ConfigError, Kind
from .showfiles import check_all
from .versions import FORMAT, FormatError, format_of, kind_of, needs_upgrade, show_files, stamped, upgrade
from .yamlio import plain_dump, update_text

log = logging.getLogger(__name__)

NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
FOLDERS = {"scene": "scenes", "show": "shows", "setlist": "setlists", "rig": "rigs", "look": "looks", "midi": "midi",
           "device": "devices"}
BACKUPS = ".backups"


class StoreError(ConfigError):
    pass


class LockedError(StoreError):
    pass


_dump = plain_dump  # new files


@dataclass
class Change:
    """One remembered change: each file's text before and after (None = no file)."""

    id: int
    note: str
    who: str
    at: float
    before: dict[Path, str | None]
    after: dict[Path, str | None]

    def info(self, root: Path) -> dict[str, Any]:
        return {"id": self.id, "note": self.note, "who": self.who, "at": self.at,
                "files": sorted(str(p.relative_to(root)) for p in self.after)}


class ShowStore:
    def __init__(self, root: str | Path, locked: Any = None) -> None:
        self.root = Path(root)
        self._lock = threading.Lock()
        self._locked = locked or (lambda: False)  # gig lock check (callable)
        self.undo_stack: list[Change] = []
        self.redo_stack: list[Change] = []
        self._next_id = 1
        self._actor = threading.local()
        self.after_commit: Callable[[], None] | None = None  # e.g. pack the working copy into its .dms

    @contextmanager
    def acting(self, who: str) -> Iterator[None]:
        """Changes made inside are recorded as made by `who` (the web server sets it per request)."""
        old = getattr(self._actor, "who", None)
        self._actor.who = who
        try:
            yield
        finally:
            self._actor.who = old

    # ------------------------------------------------------------------ paths

    def _check_name(self, name: str) -> None:
        if not NAME.match(name):
            raise StoreError(f"bad name {name!r}: use lower case letters, digits, _ or -, up to 40 characters")

    def path(self, kind: str, name: str) -> Path:
        if kind == "palettes":
            return self.root / "palettes.yaml"
        if kind == "fixtures":
            return self.root / "fixtures.yaml"
        if kind == "panels":
            return self.root / "panels.yaml"
        if kind == "inputs":
            return self.root / "inputs.yaml"
        if kind in ("quality", "presets", "ratings"):
            return self.root / f"{kind}.yaml"
        if kind not in FOLDERS:
            raise StoreError(f"unknown kind {kind!r}")
        self._check_name(name)
        return self.root / FOLDERS[kind] / f"{name}.yaml"

    # ------------------------------------------------------------------ read

    def names(self, kind: str) -> list[str]:
        if kind not in FOLDERS:
            raise StoreError(f"unknown kind {kind!r}")
        return sorted(p.stem for p in (self.root / FOLDERS[kind]).glob("*.yaml"))

    def read(self, kind: str, name: str = "") -> dict:
        """Current-format data, without `version:` (writes add it back)."""
        p = self.path(kind, name)
        if not p.exists():
            if kind in ("palettes", "panels", "inputs", "quality", "presets", "ratings"):
                return {}
            raise StoreError(f"no {kind} {name!r}")
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            raise StoreError(f"{p.name}: not valid YAML: {e}") from e
        return upgrade(data, kind_of(p), p.name)

    def read_text(self, kind: str, name: str = "") -> str:
        p = self.path(kind, name)
        if not p.exists():
            raise StoreError(f"no {kind} {name!r}")
        return p.read_text(encoding="utf-8")

    # ------------------------------------------------------------------ write (validated, backed up)

    def text_for(self, path: Path, data: Any) -> str:
        """What to write so `path` holds `data` (stamped with the current file format), keeping the
        comments already in the file. Data is taken as the current format (what `read` returns and
        the UI and Claude write) unless it carries an older `version:`, which is upgraded."""
        if isinstance(data, dict) and "version" in data:
            data = upgrade(data, kind_of(path), path.name)
        return update_text(path.read_text(encoding="utf-8") if path.exists() else None, stamped(data))

    def upgrade(self) -> tuple[str | None, list[str]]:
        """Write every older-format show file in the current format (start-up). The originals are
        backed up first and comments are kept. Not validated: an upgrade only changes the format,
        and a file with other problems is reported by loading/check as usual. Gig lock doesn't
        apply: it's the app catching up, not an edit. Returns (backup id, files upgraded)."""
        with self._lock:
            changes: dict[Path, str | None] = {}
            before_v5 = False
            for p in show_files(self.root):
                try:
                    if needs_upgrade(p):
                        text = p.read_text(encoding="utf-8")
                        raw = yaml.safe_load(text)
                        before_v5 = before_v5 or format_of(raw if isinstance(raw, dict) else {}, p.name) < 5
                        data = upgrade(raw, kind_of(p), p.name)  # no version: = format 1
                        changes[p] = update_text(text, stamped(data))
                except (FormatError, ConfigError, OSError, yaml.YAMLError):
                    continue  # newer format or broken: loading reports it
            if before_v5:
                try:
                    changes.update(self._migrate_v5(changes))
                except (FormatError, ConfigError, OSError, yaml.YAMLError, KeyError, TypeError, ValueError):
                    log.exception("moving MIDI mappings / positions for file format 5 failed; files upgraded as they are")
            if not changes:
                return None, []
            names = [str(p.relative_to(self.root)) for p in changes]
            return self._commit(changes, f"upgrade to file format {FORMAT}: {', '.join(names)}"), names

    def _migrate_v5(self, staged: dict[Path, str | None]) -> dict[Path, str | None]:
        """Format 5 moves across files (migrate.py): raw MIDI mappings -> named inputs, the kick
        tempo note -> an input with the kick role, palette positions -> head points in each rig."""
        from .fixtures import parse_patch
        from .migrate import mappings_to_inputs, positions_to_points
        from .rig import parse_rig

        def current(p: Path) -> dict[str, Any]:
            text = staged.get(p)
            if text is None:
                text = p.read_text(encoding="utf-8") if p.exists() else ""
            return upgrade(yaml.safe_load(text) if text else {}, kind_of(p), p.name)

        out: dict[Path, str | None] = {}
        maps = {p: current(p) for p in sorted((self.root / "midi").glob("*.yaml"))}
        rigs = {p: current(p) for p in sorted((self.root / "rigs").glob("*.yaml"))}
        kicks = [int(r["tempo"]["kick_note"]) for r in rigs.values()
                 if isinstance(r.get("tempo"), dict) and r["tempo"].get("source") == "kick" and "kick_note" in r["tempo"]]
        raw = any("input" not in m for d in maps.values() for m in d.get("mappings") or [] if isinstance(m, dict))
        ip = self.root / "inputs.yaml"
        if raw or kicks:
            inputs, new_maps = mappings_to_inputs(current(ip) if ip.exists() else {}, {str(p): d for p, d in maps.items()},
                                                  kicks)
            for p, d in maps.items():
                if new_maps[str(p)] != d:
                    out[p] = update_text(staged.get(p) or p.read_text(encoding="utf-8"), stamped(new_maps[str(p)]))
            if inputs.get("devices"):
                out[ip] = update_text(ip.read_text(encoding="utf-8") if ip.exists() else None, stamped(inputs))
        pp = self.root / "palettes.yaml"
        pal = current(pp) if pp.exists() else {}
        if pal.get("positions"):
            patch = parse_patch(current(self.root / "fixtures.yaml"))
            heads_of: dict[str, list[str]] = {}
            for p, r in rigs.items():
                try:
                    present = parse_rig(r, patch).present
                except (ConfigError, KeyError, TypeError, ValueError):
                    present = list(patch.fixtures)
                heads_of[str(p)] = [f for f in present if patch.fixtures[f].type.has("pan")
                                    and not patch.fixtures[f].type.colour_only]
            new_pal, new_rigs = positions_to_points(pal, {str(p): r for p, r in rigs.items()}, heads_of)
            out[pp] = update_text(staged.get(pp) or pp.read_text(encoding="utf-8"), stamped(new_pal))
            for p, r in rigs.items():
                if new_rigs[str(p)] != r:
                    out[p] = update_text(staged.get(p) or p.read_text(encoding="utf-8"), stamped(new_rigs[str(p)]))
        return out

    # ------------------------------------------------------------------ named inputs (v3)

    def input_users(self, name: str) -> list[str]:
        """Show files that name input `name` (`input: name` anywhere)."""
        from .midi.named import refs

        out = []
        for p in show_files(self.root):
            if p.name == "inputs.yaml":
                continue
            try:
                data = upgrade(yaml.safe_load(p.read_text(encoding="utf-8")), kind_of(p), p.name)
            except (FormatError, ConfigError, OSError, yaml.YAMLError):
                continue
            n = refs(data, name)
            if n:
                out.append(f"{p.relative_to(self.root).as_posix()} ({n})")
        return out

    def put_input(self, device: str, name: str, value: dict[str, Any], device_info: dict[str, Any] | None = None) -> str:
        """Add or replace input `name` in `device` (made if new, with `device_info` name/port/channel).
        An input moving device is taken out of its old one."""
        self._check_name(device)
        self._check_name(name)
        if not isinstance(value, dict):
            raise StoreError("an input is a mapping: type, notes/number or address, roles...")
        data = self.read("inputs")
        devices = data.setdefault("devices", {}) or {}
        data["devices"] = devices
        for did, d in devices.items():
            if did != device and name in ((d or {}).get("inputs") or {}):
                del d["inputs"][name]
        dev = devices.setdefault(device, {"name": (device_info or {}).get("name") or device.replace("_", " ").title(),
                                          "inputs": {}})
        for k in ("name", "port", "channel"):
            if device_info and device_info.get(k) not in (None, ""):
                dev[k] = device_info[k]
        dev.setdefault("inputs", {})
        if dev["inputs"] is None:
            dev["inputs"] = {}
        dev["inputs"][name] = value
        p = self.path("inputs", "")
        return self.apply({p: self.text_for(p, data)}, f"put input {device}.{name}")

    def put_device(self, device: str, value: dict[str, Any]) -> str:
        """Replace a whole device (name, port, channel, inputs). Inputs it no longer has must be unused."""
        self._check_name(device)
        if not isinstance(value, dict):
            raise StoreError("a device is a mapping: name, port, channel, inputs")
        data = self.read("inputs")
        devices = data.setdefault("devices", {}) or {}
        data["devices"] = devices
        gone = set((devices.get(device) or {}).get("inputs") or {}) - set(value.get("inputs") or {})
        self._refuse_used(gone)
        devices[device] = value
        p = self.path("inputs", "")
        return self.apply({p: self.text_for(p, data)}, f"put device {device}")

    def _refuse_used(self, names: Any) -> None:
        for n in sorted(names):
            users = self.input_users(n)
            if users:
                raise StoreError(f"input {n} is still used: {', '.join(users)}")

    def export_device(self, device: str) -> str:
        """Save a device as a profile in the show's devices/ folder, to load into other shows or share."""
        devices = self.read("inputs").get("devices") or {}
        if device not in devices:
            raise StoreError(f"no device {device!r}")
        return self.put("device", device, dict(devices[device]), f"save device profile {device}")

    def delete_input(self, name: str) -> str:
        data = self.read("inputs")
        for d in (data.get("devices") or {}).values():
            if name in ((d or {}).get("inputs") or {}):
                self._refuse_used([name])
                del d["inputs"][name]
                p = self.path("inputs", "")
                return self.apply({p: self.text_for(p, data)}, f"delete input {name}")
        raise StoreError(f"no input {name!r}")

    def delete_device(self, device: str) -> str:
        data = self.read("inputs")
        devices = data.get("devices") or {}
        if device not in devices:
            raise StoreError(f"no device {device!r}")
        self._refuse_used((devices[device] or {}).get("inputs") or {})
        del devices[device]
        p = self.path("inputs", "")
        return self.apply({p: self.text_for(p, data)}, f"delete device {device}")

    def rename_input(self, old: str, new: str) -> str:
        """Rename an input and every show file that names it, in one change."""
        from .midi.named import refs, rename_refs

        self._check_name(new)
        data = self.read("inputs")
        devs = data.get("devices") or {}
        owner = next((d for d in devs.values() if old in ((d or {}).get("inputs") or {})), None)
        if owner is None:
            raise StoreError(f"no input {old!r}")
        if any(new in ((d or {}).get("inputs") or {}) for d in devs.values()):
            raise StoreError(f"there's already an input {new!r}")
        owner["inputs"] = {(new if k == old else k): v for k, v in owner["inputs"].items()}
        p = self.path("inputs", "")
        changes: dict[Path, str | None] = {p: self.text_for(p, data)}
        for f in show_files(self.root):
            if f == p:
                continue
            try:
                d = upgrade(yaml.safe_load(f.read_text(encoding="utf-8")), kind_of(f), f.name)
            except (FormatError, ConfigError, OSError, yaml.YAMLError):
                continue
            if refs(d, old):
                changes[f] = self.text_for(f, rename_refs(d, old, new))
        return self.apply(changes, f"rename input {old} -> {new}")

    # ------------------------------------------------------------------ named colours and palettes (v3)

    COLOUR_KEYS = ("colour", "colours", "pixels", "show_colour", "background", "colour_b")

    def _colour_refs(self, data: Any, name: str, new: str | None = None, keys: tuple[str, ...] = COLOUR_KEYS) -> tuple[int, Any]:
        """(times `data` names colour `name` under a colour key, the data with it renamed `new`)."""
        def swap(v: Any) -> tuple[int, Any]:
            if v == name:
                return 1, (new if new is not None else v)
            if isinstance(v, list):
                n, out = 0, []
                for x in v:
                    c, y = swap(x) if not isinstance(x, (dict, list)) else self._colour_refs(x, name, new, keys)
                    n += c
                    out.append(y)
                return n, out
            if isinstance(v, dict):
                return self._colour_refs(v, name, new, keys)
            return 0, v

        if isinstance(data, dict):
            n, out = 0, {}
            for k, v in data.items():
                if k in keys:
                    c, out[k] = swap(v)
                else:
                    c, out[k] = self._colour_refs(v, name, new, keys)
                n += c
            return n, out
        if isinstance(data, list):
            n, items = 0, []
            for x in data:
                c, y = self._colour_refs(x, name, new, keys)
                n += c
                items.append(y)
            return n, items
        return 0, data

    def _files_using(self, fn: Any) -> list[str]:
        out = []
        for kind in ("scene", "look", "show", "setlist", "rig", "midi"):
            for n in self.names(kind):
                c = fn(self.read(kind, n))
                if c:
                    out.append(f"{FOLDERS[kind]}/{n}.yaml ({c})")
        for kind, fname in (("panels", "panels.yaml"), ("palettes", "palettes.yaml")):
            c = fn(self.read(kind))
            if c:
                out.append(f"{fname} ({c})")
        return out

    def colour_users(self, name: str) -> list[str]:
        """Show files that use named colour `name` (scenes, looks, busk panels, palettes...)."""
        def count(d: Any) -> int:
            if isinstance(d, dict) and "colours" in d and isinstance(d.get("colours"), dict):
                d = {k: v for k, v in d.items() if k != "colours"}  # palettes.yaml's own definitions
            return self._colour_refs(d, name)[0]
        return self._files_using(count)

    def palette_users(self, name: str) -> list[str]:
        """Files that pick palette `name` (`palette: name`, e.g. Ride presets and the auto show)."""
        def count(d: Any) -> int:
            if isinstance(d, dict) and isinstance(d.get("palettes"), dict):
                d = {k: v for k, v in d.items() if k != "palettes"}
            return self._colour_refs(d, name, keys=("palette", "palettes"))[0]
        return self._files_using(count)

    def rename_colour(self, old: str, new: str) -> str:
        """Rename a named colour, and every scene, look, panel and palette that uses it."""
        from .palettes import BUILTIN_COLOURS

        self._check_name(new)
        if old in BUILTIN_COLOURS:
            raise StoreError(f"{old} is built in and can't be renamed")
        pal = self.read("palettes")
        cols = pal.get("colours") or {}
        if old not in cols:
            raise StoreError(f"no colour {old!r}")
        if new in cols or new in BUILTIN_COLOURS:
            raise StoreError(f"there's already a colour {new!r}")
        pal["colours"] = {(new if k == old else k): v for k, v in cols.items()}
        sets = pal.get("palettes") or {}
        for v in sets.values():
            if isinstance(v, dict) and isinstance(v.get("colours"), list):
                v["colours"] = [new if c == old else c for c in v["colours"]]
        pp = self.path("palettes", "")
        changes: dict[Path, str | None] = {pp: self.text_for(pp, pal)}
        for kind in ("scene", "look", "show", "setlist"):
            for n in self.names(kind):
                c, d = self._colour_refs(self.read(kind, n), old, new)
                if c:
                    p = self.path(kind, n)
                    changes[p] = self.text_for(p, d)
        c, d = self._colour_refs(self.read("panels"), old, new)
        if c:
            p = self.root / "panels.yaml"
            changes[p] = self.text_for(p, d)
        return self.apply(changes, f"rename colour {old} -> {new}")

    def rename_palette(self, old: str, new: str) -> str:
        self._check_name(new)
        pal = self.read("palettes")
        sets = pal.get("palettes") or {}
        if old not in sets:
            raise StoreError(f"no palette {old!r}")
        if new in sets:
            raise StoreError(f"there's already a palette {new!r}")
        pal["palettes"] = {(new if k == old else k): v for k, v in sets.items()}
        pp = self.path("palettes", "")
        changes: dict[Path, str | None] = {pp: self.text_for(pp, pal)}
        for kind in ("scene", "look", "show", "setlist", "rig"):
            for n in self.names(kind):
                c, d = self._colour_refs(self.read(kind, n), old, new, keys=("palette", "palettes"))
                if c:
                    p = self.path(kind, n)
                    changes[p] = self.text_for(p, d)
        return self.apply(changes, f"rename palette {old} -> {new}")

    def import_palette(self, data: dict[str, Any], overwrite: bool = False) -> str:
        """A palette exported from another show: {palette: {key: {...}}, colours: {...}} (its named
        colours come with it). Names already here are refused unless overwrite."""
        if not isinstance(data, dict) or not isinstance(data.get("palette"), dict) or len(data["palette"]) != 1:
            raise StoreError("a palette file has palette: {name: {name, tags, colours}} and its colours")
        pal = self.read("palettes")
        key, value = next(iter(data["palette"].items()))
        sets = pal.setdefault("palettes", {}) or {}
        pal["palettes"] = sets
        cols = pal.setdefault("colours", {}) or {}
        pal["colours"] = cols
        clash = ([key] if key in sets else []) + [c for c, v in (data.get("colours") or {}).items() if c in cols and cols[c] != v]
        if clash and not overwrite:
            raise StoreError(f"already here: {', '.join(clash)} (import again with overwrite to replace)")
        cols.update(data.get("colours") or {})
        sets[key] = value
        pp = self.path("palettes", "")
        return self.apply({pp: self.text_for(pp, pal)}, f"import palette {key}")

    def export_palette(self, key: str) -> dict[str, Any]:
        pal = self.read("palettes")
        sets = pal.get("palettes") or {}
        if key not in sets:
            raise StoreError(f"no palette {key!r}")
        have = pal.get("colours") or {}
        named = {c: have[c] for c in sets[key].get("colours") or [] if isinstance(c, str) and c in have}
        return {"version": FORMAT, "palette": {key: sets[key]}, "colours": named}

    # ------------------------------------------------------------------ head points (v3)

    POINT_KEYS = ("position", "from", "to")

    def _point_refs(self, data: Any, name: str, new: str | None = None) -> tuple[int, Any]:
        """(how many times data names point `name` as a position, the data with it renamed `new`)."""
        if isinstance(data, dict):
            n, out = 0, {}
            for k, v in data.items():
                if k in self.POINT_KEYS and v == name:
                    n += 1
                    out[k] = new if new is not None else v
                else:
                    c, out[k] = self._point_refs(v, name, new)
                    n += c
            return n, out
        if isinstance(data, list):
            n, items = 0, []
            for x in data:
                c, y = self._point_refs(x, name, new)
                n += c
                items.append(y)
            return n, items
        return 0, data

    def point_users(self, name: str) -> list[str]:
        out = []
        for kind in ("scene", "look", "show"):
            for n in self.names(kind):
                c, _ = self._point_refs(self.read(kind, n), name)
                if c:
                    out.append(f"{FOLDERS[kind]}/{n}.yaml ({c})")
        c, _ = self._point_refs(self.read("panels"), name)
        if c:
            out.append(f"panels.yaml ({c})")
        return out

    def put_point(self, rig: str, name: str, value: dict[str, Any], merge: bool = False) -> str:
        """Add or replace head point `name` in a rig. merge=True keeps heads not in `value` (store
        the heads just aimed). A head outside the rig's head limits is refused (rule 8)."""
        from .fixtures import load_patch
        from .rig import parse_rig

        self._check_name(name)
        if not isinstance(value, dict):
            raise StoreError("a point is {description, tags, stage, heads: {head: {pan, tilt}}}")
        data = self.read("rig", rig)
        points = data.get("positions") or {}
        data["positions"] = points
        old = dict(points.get(name) or {})
        if merge:
            heads = {**(old.get("heads") or {}), **(value.get("heads") or {})}
            new = {**old, **{k: v for k, v in value.items() if k != "heads"}, "heads": heads}
        else:
            new = dict(value)
        new["heads"] = {f: {"pan": round(float(pv["pan"]), 5), "tilt": round(float(pv["tilt"]), 5)}
                        for f, pv in (new.get("heads") or {}).items() if isinstance(pv, dict) and "pan" in pv and "tilt" in pv}
        for k in ("description", "tags", "stage"):
            if new.get(k) in (None, "", [], {}):
                new.pop(k, None)
        points[name] = new
        r = parse_rig(data, load_patch(self.root / "fixtures.yaml"))
        bad = [w for w in r.point_problems() if w.startswith(f"point {name}:")
               and any(f" {f} is outside" in w for f in (value.get("heads") or {}))]
        if bad:
            raise StoreError(f"can't store inside the head limits' no-go zone (rule 8): {'; '.join(bad)}")
        p = self.path("rig", rig)
        return self.apply({p: self.text_for(p, data)}, f"point {name} on rig {rig}")

    def delete_point(self, rig: str, name: str) -> str:
        data = self.read("rig", rig)
        points = data.get("positions") or {}
        if name not in points:
            raise StoreError(f"rig {rig} has no point {name!r}")
        others = [r for r in self.names("rig") if r != rig and name in (self.read("rig", r).get("positions") or {})]
        if not others:
            users = self.point_users(name)
            if users:
                raise StoreError(f"point {name} is still used: {', '.join(users)}")
        del points[name]
        if not points:
            data.pop("positions")
        p = self.path("rig", rig)
        return self.apply({p: self.text_for(p, data)}, f"delete point {name} from rig {rig}")

    def rename_point(self, old: str, new: str) -> str:
        """Rename a point in every rig and every scene, look, show and busk panel that names it."""
        self._check_name(new)
        changes: dict[Path, str | None] = {}
        found = False
        for r in self.names("rig"):
            data = self.read("rig", r)
            points = data.get("positions") or {}
            if old in points:
                if new in points:
                    raise StoreError(f"rig {r} already has a point {new!r}")
                data["positions"] = {(new if k == old else k): v for k, v in points.items()}
                p = self.path("rig", r)
                changes[p] = self.text_for(p, data)
                found = True
        if not found:
            raise StoreError(f"no point {old!r}")
        for kind in ("scene", "look", "show"):
            for n in self.names(kind):
                c, d = self._point_refs(self.read(kind, n), old, new)
                if c:
                    p = self.path(kind, n)
                    changes[p] = self.text_for(p, d)
        c, d = self._point_refs(self.read("panels"), old, new)
        if c:
            p = self.root / "panels.yaml"
            changes[p] = self.text_for(p, d)
        return self.apply(changes, f"rename point {old} -> {new}")

    def _guard(self) -> None:
        why = self._locked()  # True (gig lock) or a reason, e.g. the show file is open elsewhere
        if why:
            raise LockedError(why if isinstance(why, str) else "gig lock is on: show files can't be changed")

    def _validate(self, changes: dict[Path, str | None]) -> None:
        """Apply changes to a scratch copy and check the whole folder. Raises with every problem."""
        with tempfile.TemporaryDirectory() as tmp:
            scratch = Path(tmp) / "shows"
            shutil.copytree(self.root, scratch, ignore=shutil.ignore_patterns(BACKUPS, ".state.json"))
            for path, text in changes.items():
                target = scratch / path.relative_to(self.root)
                if text is None:
                    target.unlink(missing_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(text, encoding="utf-8")
            problems = [p for p in check_all(scratch) if not p.startswith("warning")]
            if problems:
                raise StoreError("rejected: " + "; ".join(problems))

    def _commit(self, changes: dict[Path, str | None], note: str) -> str:
        stamp = time.strftime("%Y-%m-%d_%H%M%S")
        bdir = self.root / BACKUPS / stamp
        n = 0
        while bdir.exists():  # two writes in the same second
            n += 1
            bdir = self.root / BACKUPS / f"{stamp}-{n}"
        for path in changes:
            if path.exists():
                dest = bdir / path.relative_to(self.root)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dest)
        bdir.mkdir(parents=True, exist_ok=True)
        (bdir / "NOTE.txt").write_text(note + "\n", encoding="utf-8")
        for path, text in changes.items():
            if text is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".tmp")
                tmp.write_text(text, encoding="utf-8", newline="")  # as given: no \r\n added on Windows
                tmp.replace(path)
        if self.after_commit is not None:
            try:
                self.after_commit()
            except Exception:  # the change is made; the owner reports the failed save (e.g. a .dms)
                log.exception("after-save step failed")
        return bdir.name

    def apply(self, changes: dict[Path, str | None], note: str) -> str:
        """Validate then write. Returns the backup id."""
        with self._lock:
            self._guard()
            self._validate(changes)
            before = {p: self._text(p) for p in changes}
            bid = self._commit(changes, note)
            self.undo_stack.append(Change(self._next_id, note, getattr(self._actor, "who", None) or "ui",
                                          time.time(), before, dict(changes)))
            self._next_id += 1
            self.redo_stack.clear()
            return bid

    # ------------------------------------------------------------------ undo / redo

    @staticmethod
    def _text(p: Path) -> str | None:
        return p.read_bytes().decode("utf-8") if p.exists() else None  # exact, line endings too

    def _unchanged(self, files: dict[Path, str | None]) -> None:
        moved = [str(p.relative_to(self.root)) for p, text in files.items() if self._text(p) != text]
        if moved:
            raise StoreError(f"{', '.join(moved)} changed since (another edit); put it back from the backups instead")

    def history(self) -> dict[str, list[dict[str, Any]]]:
        return {"undo": [c.info(self.root) for c in reversed(self.undo_stack)],
                "redo": [c.info(self.root) for c in reversed(self.redo_stack)]}

    def undo(self, who: str | None = None) -> dict[str, Any]:
        """Undo the last change (or `who`'s last change). Returns what was undone."""
        with self._lock:
            self._guard()
            mine = [c for c in self.undo_stack if who is None or c.who == who]
            if not mine:
                raise StoreError("nothing to undo" if who is None else f"no change by {who} to undo")
            c = mine[-1]
            self._unchanged(c.after)
            self._validate(c.before)
            self._commit(c.before, f"undo: {c.note}")
            self.undo_stack.remove(c)
            self.redo_stack.append(c)
            return c.info(self.root)

    def redo(self) -> dict[str, Any]:
        with self._lock:
            self._guard()
            if not self.redo_stack:
                raise StoreError("nothing to redo")
            c = self.redo_stack[-1]
            self._unchanged(c.before)
            self._validate(c.after)
            self._commit(c.after, f"redo: {c.note}")
            self.redo_stack.pop()
            self.undo_stack.append(c)
            return c.info(self.root)

    def put(self, kind: str, name: str, data: Any, note: str = "") -> str:
        if isinstance(data, str):
            try:
                data = yaml.safe_load(data)
            except yaml.YAMLError as e:
                raise StoreError(f"not valid YAML: {e}") from e
        if not isinstance(data, dict):
            raise StoreError(f"{kind} must be a mapping")
        p = self.path(kind, name) if kind != "panels" else self.root / "panels.yaml"
        return self.apply({p: self.text_for(p, data)}, note or f"put {kind} {name}".strip())

    def delete(self, kind: str, name: str) -> str:
        p = self.path(kind, name)
        if not p.exists():
            raise StoreError(f"no {kind} {name!r}")
        if kind == "rig" and len(self.names("rig")) == 1:
            raise StoreError("can't delete the only rig")
        return self.apply({p: None}, f"delete {kind} {name}")  # references are caught by validation

    def duplicate(self, kind: str, src: str, dst: str) -> str:
        if self.path(kind, dst).exists():
            raise StoreError(f"{kind} {dst!r} already exists")
        data = self.read(kind, src)
        if "name" in data:
            data["name"] = f"{data['name']} (copy)"
        return self.put(kind, dst, data, f"duplicate {kind} {src} -> {dst}")

    # palettes and fixtures are single files with named entries

    def put_entry(self, kind: str, section: str, name: str, value: Any) -> str:
        """kind 'palettes' (section colours/positions/gobos) or 'fixtures' (section types)."""
        sections = {"palettes": ("colours", "positions", "gobos", "palettes"), "fixtures": ("types",)}
        if section not in sections.get(kind, ()):
            raise StoreError(f"{kind} sections: {sections.get(kind)}")
        self._check_name(name)
        data = self.read(kind)
        data.setdefault(section, {})
        if value is None:
            if name not in (data[section] or {}):
                raise StoreError(f"no {section} entry {name!r}")
            if kind == "palettes" and section in ("colours", "palettes"):
                users = self.colour_users(name) if section == "colours" else self.palette_users(name)
                if users:
                    raise StoreError(f"{section[:-1]} {name} is still used: {', '.join(users)}")
            del data[section][name]
        else:
            data[section][name] = value
        p = self.path(kind, "")
        return self.apply({p: self.text_for(p, data)}, f"{'delete' if value is None else 'put'} {kind} {section}.{name}")

    def put_fixture(self, entry: dict) -> str:
        """Add or replace one patched fixture (by id) in fixtures.yaml."""
        if not isinstance(entry, dict) or "id" not in entry:
            raise StoreError("fixture needs an id")
        data = self.read("fixtures")
        fx = list(data.get("fixtures") or [])
        at = next((i for i, f in enumerate(fx) if f.get("id") == entry["id"]), None)
        if at is None:
            fx.append(entry)
        else:
            fx[at] = entry  # replace in place: the patch keeps its order (and the file its layout)
        data["fixtures"] = fx
        p = self.path("fixtures", "")
        return self.apply({p: self.text_for(p, data)}, f"put fixture {entry['id']}")

    def put_patch(self, fixtures: Any) -> str:
        """Replace the whole patch list (Fixtures page: addresses, universes, groups, sub-masters)."""
        if not isinstance(fixtures, list) or not all(isinstance(f, dict) and f.get("id") for f in fixtures):
            raise StoreError("the patch is a list of fixtures, each with an id")
        data = self.read("fixtures")
        data["fixtures"] = fixtures
        p = self.path("fixtures", "")
        return self.apply({p: self.text_for(p, data)}, f"patch: {len(fixtures)} fixtures")

    def remove_fixture(self, fid: str) -> str:
        """Take a fixture out of the patch and every rig (layout, head limits, fixture lists) in one
        change. Scenes or looks that name it directly are reported and refuse the change."""
        data = self.read("fixtures")
        fx = [f for f in data.get("fixtures") or [] if f.get("id") != fid]
        if len(fx) == len(data.get("fixtures") or []):
            raise StoreError(f"no fixture {fid!r}")
        data["fixtures"] = fx
        p = self.path("fixtures", "")
        changes: dict[Path, str | None] = {p: self.text_for(p, data)}
        for name in self.names("rig"):
            rig = self.read("rig", name)
            touched = False
            for key in ("layout", "head_limits"):
                if isinstance(rig.get(key), dict) and fid in rig[key]:
                    del rig[key][fid]
                    touched = True
            if isinstance(rig.get("fixtures"), list) and fid in rig["fixtures"]:
                rig["fixtures"] = [x for x in rig["fixtures"] if x != fid]
                touched = True
            if touched:
                rp = self.path("rig", name)
                changes[rp] = self.text_for(rp, rig)
        return self.apply(changes, f"remove fixture {fid}")

    # ------------------------------------------------------------------ groups

    def edit_group(self, action: str, name: str, fixtures: list[str] | None = None, new_name: str | None = None) -> str:
        """Groups live on the fixture entries in fixtures.yaml (`groups: [...]`).

        set:    the group is exactly `fixtures` (made if new; empty list = delete)
        rename: to `new_name`, and every scene, look, rig and MIDI map that names it follows
        delete: refused (by validation) while anything still uses it
        """
        if action not in ("set", "rename", "delete"):
            raise StoreError("group action must be set, rename or delete")
        data = self.read("fixtures")
        entries = data.get("fixtures") or []
        ids = {e.get("id") for e in entries}
        have = {g for e in entries for g in e.get("groups") or []}
        self._check_group_name(name, ids)
        if action != "set" and name not in have:
            raise StoreError(f"no group {name!r}")
        changes: dict[Path, str | None] = {}
        if action == "set":
            want = set(fixtures or [])
            unknown = want - ids
            if unknown:
                raise StoreError(f"unknown fixtures {sorted(unknown)}")
            for e in entries:
                gs = [g for g in e.get("groups") or [] if g != name]
                if e["id"] in want:
                    gs.append(name)
                self._set_groups(e, gs)
            note = f"group {name}: {', '.join(sorted(want)) or 'deleted'}"
        elif action == "delete":
            for e in entries:
                self._set_groups(e, [g for g in e.get("groups") or [] if g != name])
            note = f"delete group {name}"
        else:
            if not new_name:
                raise StoreError("rename needs new_name")
            self._check_group_name(new_name, ids)
            if new_name in have:
                raise StoreError(f"there's already a group {new_name!r}")
            for e in entries:
                self._set_groups(e, [new_name if g == name else g for g in e.get("groups") or []])
            changes.update(self._rename_refs(name, new_name))
            note = f"rename group {name} -> {new_name}"
        p = self.path("fixtures", "")
        changes[p] = self.text_for(p, data)
        return self.apply(changes, note)

    @staticmethod
    def _set_groups(entry: dict[str, Any], groups: list[str]) -> None:
        if groups:
            entry["groups"] = groups
        else:
            entry.pop("groups", None)

    def _check_group_name(self, name: str, ids: set[str]) -> None:
        self._check_name(name)
        if name == "all" or name in ids or name in {k.value for k in Kind}:
            raise StoreError(f"{name!r} can't be a group name: it's a fixture, a fixture kind or 'all'")

    def _rename_refs(self, old: str, new: str) -> dict[Path, str | None]:
        """Files whose fixture lists name group `old`, rewritten to name `new`."""

        def swap(names: Any) -> Any:
            if isinstance(names, list):
                return [new if n == old else n for n in names]
            return new if names == old else names

        out: dict[Path, str | None] = {}
        for kind, folder in FOLDERS.items():
            for p in sorted((self.root / folder).glob("*.yaml")):
                data = self.read(kind, p.stem)
                before = repr(data)
                if kind == "scene":
                    for ly in data.get("layers") or []:
                        for k in ("fixtures", "fallback"):
                            if isinstance(ly, dict) and k in ly:
                                ly[k] = swap(ly[k])
                elif kind == "rig":
                    if "fixtures" in data:
                        data["fixtures"] = swap(data["fixtures"])
                    prof = data.get("profile")
                    if isinstance(prof, dict) and "master_exempt" in prof:
                        prof["master_exempt"] = swap(prof["master_exempt"])
                elif kind == "look" and isinstance(data.get("fixtures"), dict):
                    data["fixtures"] = {(new if k == old else k): v for k, v in data["fixtures"].items()}
                elif kind == "midi":
                    for m in data.get("mappings") or []:
                        if isinstance(m, dict) and "fixtures" in m:
                            m["fixtures"] = swap(m["fixtures"])
                if repr(data) != before:
                    out[p] = self.text_for(p, data)
        return out

    # ------------------------------------------------------------------ backups

    def last_good(self, load: Callable[[Path], Any], scratch: Path) -> tuple[Any, str] | None:
        """When the show folder won't load: the newest earlier version of it that does.

        Works on a copy in `scratch` (the show folder is never touched): backups are laid over the
        copy newest first, each putting back the files as they were before that change, until
        `load(copy)` succeeds. Returns (whatever load returned, backup id) or None."""
        backups = sorted((p for p in (self.root / BACKUPS).glob("*") if p.is_dir()), reverse=True)
        if not backups:
            return None
        shutil.rmtree(scratch, ignore_errors=True)
        shutil.copytree(self.root, scratch, ignore=shutil.ignore_patterns(BACKUPS, ".state.json", ".giglock"))
        for b in backups:
            for f in b.rglob("*.yaml"):
                dest = scratch / f.relative_to(b)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dest)
            try:
                return load(scratch), b.name
            except ConfigError:
                continue
        return None

    def backups(self, limit: int = 50) -> list[dict[str, Any]]:
        bdir = self.root / BACKUPS
        out = []
        for d in sorted(bdir.glob("*"), reverse=True)[:limit]:
            note = (d / "NOTE.txt").read_text(encoding="utf-8").strip() if (d / "NOTE.txt").exists() else ""
            files = sorted(str(p.relative_to(d)) for p in d.rglob("*.yaml"))
            out.append({"id": d.name, "note": note, "files": files})
        return out

    def restore(self, backup_id: str, file: str) -> str:
        """Put one file back as it was before that change (validated like any write)."""
        if "/" in backup_id or ".." in backup_id:
            raise StoreError("bad backup id")
        if not file.endswith(".yaml"):
            raise StoreError("only show files (.yaml) can be restored")
        src = (self.root / BACKUPS / backup_id / file).resolve()
        if not src.is_relative_to((self.root / BACKUPS / backup_id).resolve()) or not src.exists():
            raise StoreError(f"no {file} in backup {backup_id}")
        dest = self.root / file
        return self.apply({dest: src.read_text(encoding="utf-8")}, f"restore {file} from {backup_id}")
