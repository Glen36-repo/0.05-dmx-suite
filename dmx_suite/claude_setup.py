"""Add the 0.05 tools (MCP server) to Claude Desktop's config.

Claude Desktop keeps `claude_desktop_config.json` in `%APPDATA%/Claude` (standard install) or under
`%LOCALAPPDATA%/Packages/Claude_*/LocalCache/Roaming/Claude` (Microsoft Store install). Every config
found is updated; if there is none, the standard one is created. Other settings and MCP servers are
kept, and the previous file is saved next to it as `.bak`.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

SERVER_NAME = "dmx-suite"
CONFIG_NAME = "claude_desktop_config.json"


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


def server_entry(shows: Path) -> dict:
    """How Claude Desktop should start the 0.05 tools."""
    if getattr(sys, "frozen", False):
        return {"command": sys.executable, "args": ["--shows", str(shows), "mcp"]}
    return {"command": sys.executable, "args": ["-m", "dmx_suite.cli", "--shows", str(shows), "mcp"]}


def add_server(config: Path, entry: dict) -> bool:
    """Write the dmx-suite entry into one config. Returns True if the file changed."""
    data: dict = {}
    if config.is_file():
        text = config.read_text(encoding="utf-8").strip()
        data = json.loads(text) if text else {}
        if not isinstance(data, dict):
            raise ValueError(f"{config} is not a JSON object")
    servers = data.setdefault("mcpServers", {})
    if servers.get(SERVER_NAME) == entry:
        return False
    if config.is_file():
        shutil.copy2(config, config.with_name(config.name + ".bak"))
    servers[SERVER_NAME] = entry
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


def setup(shows: Path, configs: list[Path] | None = None) -> list[tuple[Path, bool]]:
    entry = server_entry(shows)
    return [(c, add_server(c, entry)) for c in (configs or config_paths())]
