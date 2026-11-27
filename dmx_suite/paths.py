"""Where the show folder lives.

From a source checkout the show folder is the repo's `shows/`. The installed Windows app is read-only
under Program Files, so its show folder is the one picked in the installer (default
`OneDrive/Music/0.05 DMX Suite/shows`, saved as the DMX_SUITE_SHOWS user environment variable), or
`Documents/0.05 DMX Suite/shows` if none was set. A missing folder is created from the bundled starter
shows on first run; an existing one is never overwritten, so upgrades keep the band's edits.

Order: `--shows` on the command line, then the DMX_SUITE_SHOWS environment variable, then the default.

What the app writes for itself (resume state, logs) lives in per-user app data, not in the show
folder, so it doesn't sync through OneDrive: `%LOCALAPPDATA%/0.05 DMX Suite` on Windows,
`~/.local/state/0.05 DMX Suite` elsewhere, or DMX_SUITE_DATA if set.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
from pathlib import Path

APP_DIR_NAME = "0.05 DMX Suite"
ENV_VAR = "DMX_SUITE_SHOWS"
DATA_ENV_VAR = "DMX_SUITE_DATA"


def frozen() -> bool:
    """True when running from the packaged app (PyInstaller)."""
    return bool(getattr(sys, "frozen", False))


def bundled_shows() -> Path:
    """Starter shows shipped with the app (or the repo's shows/ from source)."""
    if frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "shows"
    return Path(__file__).resolve().parents[1] / "shows"


def manual_dir() -> Path:
    """The user manual (docs/manual), bundled with the packaged app."""
    if frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "docs" / "manual"
    return Path(__file__).resolve().parents[1] / "docs" / "manual"


def documents_dir() -> Path:
    """The user's Documents folder (falls back to the home folder)."""
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    docs = home / "Documents"
    return docs if docs.is_dir() else home


def user_shows() -> Path:
    return documents_dir() / APP_DIR_NAME / "shows"


def seed_shows(target: Path, source: Path | None = None) -> bool:
    """Copy the starter shows into `target` if it doesn't exist yet. Returns True if copied."""
    if target.exists():
        return False
    src = source or bundled_shows()
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, target, ignore=shutil.ignore_patterns(".backups", ".state.json", ".giglock"))
    return True


def prepare(shows: Path) -> Path:
    """Installed app: a new show folder or .dms show file starts from the starter shows. From
    source: leave it."""
    if frozen():
        if Path(shows).suffix.lower() == ".dms":
            if not Path(shows).exists():
                from .package import create

                create(Path(shows), bundled_shows())
        else:
            seed_shows(shows)
    return shows


def app_token_file() -> Path:
    """The running app's token for its own other copies (a second launch hands over a show file)."""
    return data_dir() / "run" / "app_token"


def default_shows() -> Path:
    """Show folder to use when --shows isn't given."""
    env = os.environ.get(ENV_VAR)
    if env:
        return prepare(Path(env))
    # installed app without a folder picked in the installer: Documents
    return prepare(user_shows()) if frozen() else bundled_shows()


def data_dir() -> Path:
    """Per-user app data (resume state, logs), outside the show folder."""
    env = os.environ.get(DATA_ENV_VAR)
    if env:
        return Path(env)
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / APP_DIR_NAME
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / APP_DIR_NAME


def state_file(shows: Path) -> Path:
    """Resume state for one show folder (several show folders don't share it)."""
    key = hashlib.sha1(str(Path(shows).resolve()).lower().encode()).hexdigest()[:10]
    return data_dir() / "state" / f"{Path(shows).name}-{key}.json"


def giglock_file() -> Path:
    """Gig lock on this laptop (the running app writes it; Claude's tools read it when the app is off)."""
    return data_dir() / "state" / ".giglock"


def giglock_on() -> bool:
    try:
        return giglock_file().read_text(encoding="utf-8").strip() == "on"
    except OSError:
        return False


def log_dir() -> Path:
    return data_dir() / "logs"


def move_old_state(shows: Path) -> Path:
    """v1 kept resume state in the show folder: move it once, so an upgrade mid-gig still resumes."""
    new = state_file(shows)
    old = Path(shows) / ".state.json"
    if old.exists() and not new.exists():
        try:
            new.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old), str(new))
        except OSError:
            pass
    return new
