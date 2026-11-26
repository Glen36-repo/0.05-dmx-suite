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
from .versions import FORMAT, FormatError, kind_of, needs_upgrade, show_files, stamped, upgrade
from .yamlio import plain_dump, update_text

log = logging.getLogger(__name__)

NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
FOLDERS = {"scene": "scenes", "show": "shows", "setlist": "setlists", "rig": "rigs", "look": "looks", "midi": "midi"}
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
            if kind in ("palettes", "panels"):
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
            for p in show_files(self.root):
                try:
                    if needs_upgrade(p):
                        text = p.read_text(encoding="utf-8")
                        data = upgrade(yaml.safe_load(text), kind_of(p), p.name)  # no version: = format 1
                        changes[p] = update_text(text, stamped(data))
                except (FormatError, ConfigError, OSError, yaml.YAMLError):
                    continue  # newer format or broken: loading reports it
            if not changes:
                return None, []
            names = [str(p.relative_to(self.root)) for p in changes]
            return self._commit(changes, f"upgrade to file format {FORMAT}: {', '.join(names)}"), names

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
        sections = {"palettes": ("colours", "positions", "gobos"), "fixtures": ("types",)}
        if section not in sections.get(kind, ()):
            raise StoreError(f"{kind} sections: {sections.get(kind)}")
        self._check_name(name)
        data = self.read(kind)
        data.setdefault(section, {})
        if value is None:
            if name not in (data[section] or {}):
                raise StoreError(f"no {section} entry {name!r}")
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
