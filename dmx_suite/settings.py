"""Per-laptop settings (app data `settings.json`), as opposed to the show folder, which may be
shared through OneDrive: things like the UI theme, which differ from one screen to another."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from .paths import data_dir

log = logging.getLogger(__name__)

THEMES = Path(__file__).parent / "web" / "static" / "themes"
DEFAULTS: dict[str, Any] = {"theme": "neutral", "recent": [], "wizard": "", "density": "compact"}  # wizard: "", "done", "skipped"
RECENT = 8
DENSITIES = ("compact", "comfortable")  # v4: button size, per laptop


def path() -> Path:
    return data_dir() / "settings.json"


def load() -> dict[str, Any]:
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(DEFAULTS)
    return {**DEFAULTS, **(data if isinstance(data, dict) else {})}


def save(changes: dict[str, Any]) -> dict[str, Any]:
    unknown = set(changes) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"unknown settings {sorted(unknown)}")
    if "wizard" in changes and changes["wizard"] not in ("", "done", "skipped"):
        raise ValueError("wizard is done or skipped")
    if "density" in changes and changes["density"] not in DENSITIES:
        raise ValueError(f"density is {' or '.join(DENSITIES)}")
    if "theme" in changes and changes["theme"] not in themes():
        raise ValueError(f"no theme {changes['theme']!r}; have {', '.join(themes())}")
    data = {**load(), **changes}
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, p)
    return data


def first_run() -> bool:
    """A new laptop: the setup wizard hasn't been finished or skipped here."""
    return load().get("wizard") not in ("done", "skipped")


def add_recent(path: str) -> list[str]:
    """Remember a show file opened on this laptop (newest first)."""
    recent = [p for p in load().get("recent", []) if isinstance(p, str) and p.lower() != path.lower()]
    recent = [path, *recent][:RECENT]
    save({"recent": recent})
    return recent


def themes() -> dict[str, dict[str, str]]:
    """Theme folders under web/static/themes: key -> {name, app_name}."""
    out = {}
    for d in sorted(THEMES.iterdir()):
        try:
            meta = json.loads((d / "theme.json").read_text(encoding="utf-8"))
            out[d.name] = {"name": str(meta["name"]), "app_name": str(meta.get("app_name", "DMX Suite"))}
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return out


def theme() -> tuple[str, dict[str, str]]:
    """The theme in use (falls back to neutral if the saved one has gone)."""
    have = themes()
    key = load().get("theme", "neutral")
    if key not in have:
        key = "neutral"
    return key, have[key]
