"""Connect the 0.05 tools (MCP server) to Claude Desktop and Claude Code, check it, or take it out.

Claude Desktop keeps `claude_desktop_config.json` in `%APPDATA%/Claude` (standard install) or under
`%LOCALAPPDATA%/Packages/Claude_*/LocalCache/Roaming/Claude` (Microsoft Store install). Claude Code
keeps its user settings in `~/.claude.json`. Every config found is updated; other settings and MCP
servers are kept, and the previous file is saved next to it as `.bak`. Nothing is written until
Connect (the Setup page, `dmx-suite claude-setup`, or the installer option).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SERVER_NAME = "dmx-suite"
CONFIG_NAME = "claude_desktop_config.json"


# ---------------------------------------------------------------------- where the configs are


def config_paths() -> list[Path]:
    """Existing Claude Desktop configs, or the standard location if none exist yet."""
    found: list[Path] = []
    appdata = os.environ.get("APPDATA")
    standard = Path(appdata) / "Claude" / CONFIG_NAME if appdata else None
    if standard and standard.is_file():
        found.append(standard)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        found += sorted(Path(local, "Packages").glob(f"Claude_*/LocalCache/Roaming/Claude/{CONFIG_NAME}"))
    if not found and standard:
        found.append(standard)
    return found


def code_config() -> Path:
    """Claude Code's user settings (`~/.claude.json`)."""
    home = os.environ.get("USERPROFILE") or os.environ.get("HOME") or str(Path.home())
    return Path(home) / ".claude.json"


@dataclass
class Target:
    kind: str  # desktop | code
    label: str
    config: Path
    installed: bool  # the Claude app has been run on this computer (its folder or settings exist)


def targets() -> list[Target]:
    """Every Claude app found on this computer, with the config the 0.05 tools go in."""
    out: list[Target] = []
    store = [p for p in config_paths() if "Packages" in p.parts]
    for cfg in config_paths():
        label = "Claude Desktop (Microsoft Store)" if cfg in store else "Claude Desktop"
        out.append(Target("desktop", label, cfg, cfg.is_file() or cfg.parent.is_dir()))
    code = code_config()
    home = code.parent
    out.append(Target("code", "Claude Code", code, code.is_file() or (home / ".claude").is_dir()))
    return out


# ---------------------------------------------------------------------- the entry


def program() -> str:
    """The program Claude starts. The installed app's console exe (`dmx-suite.exe`) when it's next to
    the windowed one, so the tools talk over a console; else this Python."""
    exe = Path(sys.executable)
    if getattr(sys, "frozen", False):
        console = exe.with_name("dmx-suite.exe")
        return str(console if console.is_file() else exe)
    return sys.executable


def server_entry(shows: Path) -> dict:
    """How Claude should start the 0.05 tools for this show (folder or .dms file)."""
    if getattr(sys, "frozen", False):
        return {"command": program(), "args": ["--shows", str(shows), "mcp"]}
    return {"command": sys.executable, "args": ["-m", "dmx_suite.cli", "--shows", str(shows), "mcp"]}


def _read(config: Path) -> dict:
    if not config.is_file():
        return {}
    text = config.read_text(encoding="utf-8").strip()
    data = json.loads(text) if text else {}
    if not isinstance(data, dict):
        raise ValueError(f"{config} is not a JSON object")
    return data


def _write(config: Path, data: dict) -> None:
    if config.is_file():
        shutil.copy2(config, config.with_name(config.name + ".bak"))
    config.parent.mkdir(parents=True, exist_ok=True)
    tmp = config.with_name(config.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(config)


def add_server(config: Path, entry: dict) -> bool:
    """Write the dmx-suite entry into one config. Returns True if the file changed."""
    data = _read(config)
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError(f"{config}: mcpServers is not a JSON object")
    if servers.get(SERVER_NAME) == entry:
        return False
    servers[SERVER_NAME] = entry
    _write(config, data)
    return True


def remove_server(config: Path) -> bool:
    """Take the dmx-suite entry out of one config (everything else kept). True if it was there."""
    data = _read(config)
    servers = data.get("mcpServers")
    if not isinstance(servers, dict) or SERVER_NAME not in servers:
        return False
    del servers[SERVER_NAME]
    _write(config, data)
    return True


def setup(shows: Path, configs: list[Path] | None = None) -> list[tuple[Path, bool]]:
    entry = server_entry(shows)
    return [(c, add_server(c, entry)) for c in (configs or config_paths())]


# ---------------------------------------------------------------------- status, connect, disconnect (Setup page)


def _registered(t: Target, entry: dict) -> tuple[str, dict | None, str | None]:
    """('no' | 'current' | 'other', the entry found, an error)."""
    try:
        servers = _read(t.config).get("mcpServers") or {}
    except (OSError, ValueError) as e:
        return "no", None, str(e)
    found = servers.get(SERVER_NAME) if isinstance(servers, dict) else None
    if not found:
        return "no", None, None
    return ("current" if found == entry else "other"), found, None


def status(shows: Path) -> dict[str, Any]:
    """What the Setup page shows: each Claude app found, whether it has the 0.05 tools for this show."""
    entry = server_entry(shows)
    rows = []
    for t in targets():
        reg, found, err = _registered(t, entry)
        found_shows = None
        if found:
            args = list(found.get("args") or [])
            found_shows = args[args.index("--shows") + 1] if "--shows" in args[:-1] else None
        rows.append({**asdict(t), "config": str(t.config), "registered": reg, "error": err,
                     "entry_command": (found or {}).get("command"), "entry_shows": found_shows})
    return {"program": entry["command"], "program_ok": Path(entry["command"]).is_file(), "shows": str(shows),
            "targets": rows}


def connect(shows: Path, only: list[str] | None = None) -> list[str]:
    """Add the 0.05 tools for this show to every Claude app found (or only those kinds). Returns the files changed."""
    entry = server_entry(shows)
    changed = []
    for t in targets():
        if (only and t.kind not in only) or not t.installed:
            continue
        if add_server(t.config, entry):
            changed.append(str(t.config))
    return changed


def disconnect() -> list[str]:
    """Take the 0.05 tools out of every Claude config. Returns the files changed."""
    return [str(t.config) for t in targets() if t.config.is_file() and remove_server(t.config)]
