"""Show folder store: every edit from the browser UI or Claude (MCP) goes through here.

A change is staged in a scratch copy of the show folder and the whole folder is validated
(`check_all`: rules, references, auto shows on every rig). Only if that passes is the file
written, after the previous version is copied to `.backups/<date-time>/` so any change can be undone.
Saves keep the file's comments and layout (yamlio.update_text): only what changed is rewritten.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import yaml

from .fixtures import ConfigError
from .showfiles import check_all
from .yamlio import plain_dump, update_text

NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
FOLDERS = {"scene": "scenes", "show": "shows", "setlist": "setlists", "rig": "rigs", "look": "looks", "midi": "midi"}
BACKUPS = ".backups"


class StoreError(ConfigError):
    pass


class LockedError(StoreError):
    pass


_dump = plain_dump  # new files


class ShowStore:
    def __init__(self, root: str | Path, locked: Any = None) -> None:
        self.root = Path(root)
        self._lock = threading.Lock()
        self._locked = locked or (lambda: False)  # gig lock check (callable)

    # ------------------------------------------------------------------ paths

    def _check_name(self, name: str) -> None:
        if not NAME.match(name):
            raise StoreError(f"bad name {name!r}: use lower case letters, digits, _ or -, up to 40 characters")

    def path(self, kind: str, name: str) -> Path:
        if kind == "palettes":
            return self.root / "palettes.yaml"
        if kind == "fixtures":
            return self.root / "fixtures.yaml"
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
        p = self.path(kind, name)
        if not p.exists():
            if kind == "palettes":
                return {}
            raise StoreError(f"no {kind} {name!r}")
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}

    def read_text(self, kind: str, name: str = "") -> str:
        p = self.path(kind, name)
        if not p.exists():
            raise StoreError(f"no {kind} {name!r}")
        return p.read_text(encoding="utf-8")

    # ------------------------------------------------------------------ write (validated, backed up)

    def text_for(self, path: Path, data: Any) -> str:
        """What to write so `path` holds `data`, keeping the comments already in the file."""
        return update_text(path.read_text(encoding="utf-8") if path.exists() else None, data)

    def _guard(self) -> None:
        if self._locked():
            raise LockedError("gig lock is on: show files can't be changed")

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
                tmp.write_text(text, encoding="utf-8")
                tmp.replace(path)
        return bdir.name

    def apply(self, changes: dict[Path, str | None], note: str) -> str:
        """Validate then write. Returns the backup id."""
        with self._lock:
            self._guard()
            self._validate(changes)
            return self._commit(changes, note)

    def put(self, kind: str, name: str, data: Any, note: str = "") -> str:
        if isinstance(data, str):
            try:
                data = yaml.safe_load(data)
            except yaml.YAMLError as e:
                raise StoreError(f"not valid YAML: {e}") from e
        if not isinstance(data, dict):
            raise StoreError(f"{kind} must be a mapping")
        p = self.path(kind, name)
        return self.apply({p: self.text_for(p, data)}, note or f"put {kind} {name}")

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

    # ------------------------------------------------------------------ backups

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
