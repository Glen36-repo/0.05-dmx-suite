"""`.dms` show files: the whole show folder in one file, like a Daslight project file.

A `.dms` is a zip holding the show's `.yaml` files and `dms.json` (container version, show file
format, app version, when saved). Backups, resume state and gig lock stay on the laptop.

The app never edits inside the zip: opening `x.dms` unpacks it into a working copy in app data
(`open/<key>/`), everything runs on that folder as before, and every saved change packs the
working copy back into `x.dms` (temp file, then an atomic replace, so a crash can't leave half a
file). If the working copy holds changes that never made it into the `.dms` (a crash between the
edit and the pack), opening keeps them as "<name> (recovered DD-MM-YYYY).dms" next to it.

`<name>.dms.lock` (process, computer) next to the file stops two copies of the app writing the
same show: the second one opens it read-only.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

from . import __version__
from .fixtures import ConfigError
from .paths import data_dir
from .versions import FORMAT

DMS_VERSION = 1
MANIFEST = "dms.json"
SUFFIX = ".dms"
MAX_ENTRIES = 2000
MAX_BYTES = 50 * 1024 * 1024
STALE_LOCK_S = 12 * 3600  # a lock from another computer this old is taken to be left over
SKIP_DIRS = {".backups"}
_ZIP_DATE = (1980, 1, 1, 0, 0, 0)  # fixed, so the same show packs to the same bytes


class DmsError(ConfigError):
    pass


def is_dms(path: str | Path | None) -> bool:
    return path is not None and Path(path).suffix.lower() == SUFFIX


def show_files(folder: Path) -> list[Path]:
    """The show's .yaml files, relative to the folder (no backups or other hidden folders)."""
    out = []
    for p in sorted(folder.rglob("*.yaml")):
        rel = p.relative_to(folder)
        if any(part.startswith(".") for part in rel.parts) or not p.is_file():
            continue
        out.append(rel)
    return out


def content_hash(folder: Path) -> str:
    h = hashlib.sha256()
    for rel in show_files(folder):
        h.update(rel.as_posix().encode() + b"\0" + (folder / rel).read_bytes() + b"\0")
    return h.hexdigest()


# ---------------------------------------------------------------- pack / unpack


def pack(folder: Path, dms: Path) -> None:
    """Write the folder's show files to `dms` (atomic: a crash leaves the old file as it was)."""
    folder, dms = Path(folder), Path(dms)
    files = show_files(folder)
    if not files:
        raise DmsError(f"{folder} has no show files to save")
    dms.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{dms.stem}.", suffix=".tmp", dir=dms.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        manifest = {"dms": DMS_VERSION, "format": FORMAT, "app": __version__,
                    "saved": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(zipfile.ZipInfo(MANIFEST, _ZIP_DATE), json.dumps(manifest, indent=1))
            for rel in files:
                info = zipfile.ZipInfo(rel.as_posix(), _ZIP_DATE)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                z.writestr(info, (folder / rel).read_bytes())
        _replace(tmp, dms)
    finally:
        tmp.unlink(missing_ok=True)


def _replace(src: Path, dst: Path, tries: int = 8) -> None:
    """os.replace, retried for a moment: on Windows something else (OneDrive syncing, the indexer, an
    antivirus scan) can hold the show file for a fraction of a second, and the replace is then refused."""
    for n in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if n == tries - 1:
                raise
            time.sleep(0.05 * (n + 1))


def _safe_name(name: str) -> bool:
    if not name or name.startswith(("/", "\\")) or "\\" in name or ":" in name:
        return False
    parts = name.split("/")
    return all(p not in ("", ".", "..") and not p.startswith(".") for p in parts)


def read_manifest(dms: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(dms) as z:
            return _manifest(z, dms)
    except (zipfile.BadZipFile, OSError) as e:
        raise DmsError(f"{Path(dms).name} isn't a show file (.dms): {e}") from e


def _manifest(z: zipfile.ZipFile, dms: Path) -> dict[str, Any]:
    try:
        m = json.loads(z.read(MANIFEST))
    except (KeyError, ValueError) as e:
        raise DmsError(f"{Path(dms).name} isn't a show file (.dms): no {MANIFEST}") from e
    if not isinstance(m, dict) or not isinstance(m.get("dms"), int) or not isinstance(m.get("format"), int):
        raise DmsError(f"{Path(dms).name}: {MANIFEST} is damaged")
    if m["dms"] > DMS_VERSION or m["format"] > FORMAT:
        raise DmsError(f"{Path(dms).name} was saved by a newer version of the app ({m.get('app', '?')}): "
                       "update the app to open it")
    return m


def unpack(dms: Path, folder: Path) -> dict[str, Any]:
    """Unpack `dms` into `folder` (its existing show files are replaced). Returns the manifest.
    Only .yaml files and the manifest are taken; anything unsafe refuses the whole file."""
    dms, folder = Path(dms), Path(folder)
    try:
        z = zipfile.ZipFile(dms)
    except (zipfile.BadZipFile, OSError) as e:
        raise DmsError(f"{dms.name} isn't a show file (.dms): {e}") from e
    with z:
        infos = z.infolist()
        if len(infos) > MAX_ENTRIES:
            raise DmsError(f"{dms.name} holds too many files ({len(infos)})")
        manifest = _manifest(z, dms)
        take = []
        total = 0
        for info in infos:
            if info.filename == MANIFEST or info.is_dir():
                continue
            if not _safe_name(info.filename) or not info.filename.endswith(".yaml"):
                raise DmsError(f"{dms.name}: unexpected file {info.filename!r} in it")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise DmsError(f"{dms.name}: {info.filename!r} is a link")
            total += info.file_size
            if total > MAX_BYTES:
                raise DmsError(f"{dms.name} is too big unpacked (over {MAX_BYTES // 1024 // 1024} MB)")
            take.append(info)
        if not take:
            raise DmsError(f"{dms.name} has no show files in it")
        data = {}
        read = 0
        for info in take:
            with z.open(info) as f:
                b = f.read(MAX_BYTES - read + 1)
            read += len(b)
            if read > MAX_BYTES:
                raise DmsError(f"{dms.name} is too big unpacked")
            data[info.filename] = b
    folder.mkdir(parents=True, exist_ok=True)
    for rel in show_files(folder):  # replace: files gone from the .dms go from the folder too
        (folder / rel).unlink()
    for name, b in data.items():
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b)
    return manifest


def create(dms: Path, source: Path) -> None:
    """A new .dms from a show folder (e.g. the starter shows)."""
    if Path(dms).exists():
        raise DmsError(f"{Path(dms).name} already exists")
    pack(source, dms)


# ---------------------------------------------------------------- lock


def _host() -> str:
    return platform.node() or "this computer"


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        kernel32 = getattr(ctypes, "windll").kernel32  # noqa: B009 - windll only exists on Windows
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def lock_path(dms: Path) -> Path:
    return Path(dms).with_name(Path(dms).name + ".lock")


def read_lock(dms: Path) -> dict[str, Any] | None:
    try:
        d = json.loads(lock_path(dms).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def lock_holder(dms: Path) -> dict[str, Any] | None:
    """Who else has this file open (None if nobody, or the lock is left over)."""
    d = read_lock(dms)
    if d is None:
        return None
    pid, host, at = d.get("pid"), d.get("host"), d.get("at", 0)
    if host == _host() and pid == os.getpid():
        return None  # ours
    if host == _host():
        return d if isinstance(pid, int) and pid_alive(pid) else None
    return d if isinstance(at, (int, float)) and time.time() - at < STALE_LOCK_S else None


def take_lock(dms: Path) -> dict[str, Any] | None:
    """Lock the file for this process. Returns the other holder instead if someone has it."""
    other = lock_holder(dms)
    if other is not None:
        return other
    tmp = lock_path(dms).with_suffix(".tmp")
    tmp.write_text(json.dumps({"pid": os.getpid(), "host": _host(), "at": time.time()}), encoding="utf-8")
    os.replace(tmp, lock_path(dms))
    return None


def drop_lock(dms: Path) -> None:
    d = read_lock(dms)
    if d and d.get("pid") == os.getpid() and d.get("host") == _host():
        lock_path(dms).unlink(missing_ok=True)


# ---------------------------------------------------------------- an open .dms


def work_dir(dms: Path, tag: str = "") -> Path:
    key = hashlib.sha1(str(Path(dms).resolve()).lower().encode()).hexdigest()[:12]
    return data_dir() / "open" / f"{Path(dms).stem}-{key}{tag}"


def recovered_name(dms: Path) -> Path:
    base = f"{dms.stem} (recovered {time.strftime('%d-%m-%Y')})"
    p = dms.with_name(base + SUFFIX)
    n = 2
    while p.exists():
        p = dms.with_name(f"{base} {n}{SUFFIX}")
        n += 1
    return p


class DmsProject:
    """A .dms file opened through a working copy (see the module notes)."""

    STATE = ".dms-state.json"

    def __init__(self, dms: str | Path, work: Path | None = None, lock: bool = True) -> None:
        self.dms = Path(dms).resolve()
        self.work = work or work_dir(self.dms)
        self.lock = lock
        self.read_only = False
        self.holder: dict[str, Any] | None = None
        self.notes: list[str] = []
        self.recovered: Path | None = None
        self.save_error: str | None = None
        self.dirty = False  # v7 Manual save: changes in the working copy not yet packed into the .dms

    @property
    def name(self) -> str:
        return self.dms.name

    def _state(self) -> dict[str, Any]:
        try:
            return dict(json.loads((self.work / self.STATE).read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            return {}

    def _remember(self) -> None:
        st = self.dms.stat()
        (self.work / self.STATE).write_text(json.dumps({
            "dms": str(self.dms), "content": content_hash(self.work), "mtime": st.st_mtime, "size": st.st_size}),
            encoding="utf-8")

    def open(self) -> list[str]:
        if not self.dms.exists():
            raise DmsError(f"no show file {self.dms}")
        read_manifest(self.dms)  # refuse a bad or newer file before touching anything
        if self.lock:
            self.holder = take_lock(self.dms)
            if self.holder is not None:
                self.read_only = True
                self.notes.append(f"{self.name} is open on {self.holder.get('host', '?')}: opened read-only")
        self.work.mkdir(parents=True, exist_ok=True)
        st = self._state()
        if show_files(self.work) and st.get("content") and content_hash(self.work) != st["content"] and not self.read_only:
            self.recovered = recovered_name(self.dms)
            pack(self.work, self.recovered)
            self.notes.append(f"changes that weren't saved into {self.name} were kept as {self.recovered.name}")
        unpack(self.dms, self.work)
        self._remember()
        return self.notes

    def save(self) -> None:
        """Pack the working copy into the .dms (after every saved change, or v7 Manual save: on Save)."""
        if self.read_only:
            raise DmsError(f"{self.name} is open read-only")
        try:
            pack(self.work, self.dms)
            self._remember()
            self.save_error = None
            self.dirty = False
        except (OSError, DmsError) as e:
            self.save_error = f"couldn't save {self.name}: {e}"
            raise

    def changed_outside(self) -> bool:
        """The .dms was replaced since it was unpacked (another program, OneDrive)."""
        st = self._state()
        try:
            s = self.dms.stat()
        except OSError:
            return False
        return (s.st_mtime, s.st_size) != (st.get("mtime"), st.get("size"))

    def refresh(self) -> None:
        if self.changed_outside():
            unpack(self.dms, self.work)
            self._remember()

    def save_as(self, new: Path) -> None:
        """Save under a new name and carry on with that file."""
        new = Path(new).resolve()
        if not is_dms(new):
            new = new.with_suffix(SUFFIX)
        if self.lock and new != self.dms:
            other = take_lock(new)
            if other is not None:
                raise DmsError(f"{new.name} is open on {other.get('host', '?')}")
        pack(self.work, new)
        if self.lock and new != self.dms and not self.read_only:
            drop_lock(self.dms)
        self.dms, self.read_only, self.holder, self.dirty = new, False, None, False
        self._remember()

    def close(self) -> None:
        if self.lock and not self.read_only:
            drop_lock(self.dms)


def unpack_to_temp(dms: Path) -> Path:
    """For one-off reads (check, addresses): a throw-away folder."""
    folder = Path(tempfile.mkdtemp(prefix="dmx-suite-")) / "shows"
    unpack(dms, folder)
    return folder


def remove_temp(folder: Path) -> None:
    shutil.rmtree(folder.parent, ignore_errors=True)
