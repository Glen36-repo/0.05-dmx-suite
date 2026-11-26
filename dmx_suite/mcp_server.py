"""MCP server so Claude (Desktop) can read, build, check and preview shows in plain words.

Run by Claude Desktop over stdio: `dmx-suite mcp`. Needs the `mcp` package (pip install -e .[claude]).
"""

from __future__ import annotations

import functools
import threading
import time

from .claude_tools import DmxTools

PING_S = 20  # how often Claude Desktop tells the engine the 0.05 tools are loaded

KINDS = "scene, show, setlist, rig, look or midi"


def build_server(tools: DmxTools | None = None):  # -> MCPServer
    from mcp.server.mcpserver import MCPServer

    t = tools or DmxTools()
    server = MCPServer(
        name="0.05 DMX Suite",
        instructions=(
            "Lighting for the band 0.05. Call get_guide first: it explains scenes, shows, palettes and the hard "
            "rules every change is checked against. Use validate_scene or preview_scene before saving. Writes "
            "are refused while the band has gig lock on."
        ),
    )

    def tool(fn):  # register, and label each call so the status bar can show what Claude is doing
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            t.call_label = fn.__name__
            try:
                return fn(*args, **kwargs)
            finally:
                t.call_label = None

        return server.tool()(wrapper)

    @tool
    def get_guide() -> str:
        """How scenes, shows, setlists and palettes are written, the effects available, and the hard rules."""
        return t.get_guide()

    @tool
    def list_fixtures() -> str:
        """Fixtures in the patch: ids, kinds, groups, which can move, pixels, and fixture type channel maps."""
        return t.list_fixtures()

    @tool
    def get_palettes() -> str:
        """Named colours, positions and gobos (palettes.yaml)."""
        return t.get_palettes()

    @tool
    def list_items(kind: str) -> str:
        """List saved items of one kind: scene, show, setlist, rig, look or midi."""
        return t.list(kind)

    @tool
    def get_item(kind: str, name: str) -> str:
        """Read one saved item as YAML. kind: scene, show, setlist, rig, look or midi."""
        return t.get(kind, name)

    @tool
    def get_midi_map() -> str:
        """The MIDI map(s): which FCB1010 program change / drum note / CC does what."""
        return t.get_midi_map()

    @tool
    def validate_scene(scene_yaml: str) -> str:
        """Check a scene (YAML) against the fixtures, palettes and hard rules without saving it."""
        return t.validate_scene(scene_yaml)

    @tool
    def save_item(kind: str, name: str, yaml_text: str) -> str:
        """Create or replace a scene, show, setlist, rig, look or MIDI map from YAML. The whole show folder is
        re-checked first; anything that breaks a rule or a reference is rejected with the reason. The old file
        is kept in backups. name: lower case letters, digits, _ or -."""
        return t.save(kind, name, yaml_text)

    @tool
    def duplicate_item(kind: str, source: str, new_name: str) -> str:
        """Copy a scene/show/setlist/rig to a new name."""
        return t.duplicate(kind, source, new_name)

    @tool
    def delete_item(kind: str, name: str) -> str:
        """Delete a scene/show/setlist/rig/look. Refused if something still uses it (a show, setlist or MIDI map)."""
        return t.delete(kind, name)

    @tool
    def save_palette_entry(section: str, name: str, value_yaml: str) -> str:
        """Add or change one palette entry. section: colours, positions or gobos. value_yaml e.g. '"#ff3300"',
        '{pan: 0.4, tilt: 0.3}', or per head '{mh_a: {pan: 0.4, tilt: 0.3}, mh_b: {pan: 0.6, tilt: 0.3}}'."""
        return t.save_entry("palettes", section, name, value_yaml)

    @tool
    def delete_palette_entry(section: str, name: str) -> str:
        """Remove a palette entry (refused if a scene or show still uses it)."""
        return t.save_entry("palettes", section, name, None)

    @tool
    def save_fixture_type(key: str, yaml_text: str) -> str:
        """Add or change a fixture type (channel map), e.g. from a fixture manual. Channel roles: dimmer, red,
        green, blue, white, amber, uv, pan, pan_fine, tilt, tilt_fine, pt_speed (invert: true if 0 = fastest),
        colour_wheel, gobo, strobe (default = shutter open value), haze, fixed (default value). Set
        verified: false until it's checked on the real fixture. Patch changes need an engine restart."""
        return t.save_entry("fixtures", "types", key, yaml_text)

    @tool
    def save_fixture(yaml_text: str) -> str:
        """Add or replace one patched fixture: {id, type, address, universe, groups}. Needs an engine restart."""
        return t.save_fixture(yaml_text)

    @tool
    def list_backups() -> str:
        """Recent changes with the files each one backed up."""
        return t.list_backups()

    @tool
    def restore_backup(backup: str, file: str) -> str:
        """Put one file back as it was before a change (e.g. backup '2026-11-26_201500', file 'scenes/opera.yaml')."""
        return t.restore_backup(backup, file)

    @tool
    def now_playing() -> str:
        """What's running: show/set/song, MASTER, blackout, masters, haze, gig lock. Engine must be running."""
        return t.now_playing()

    @tool
    def preview_scene(scene: str, seconds: float = 10) -> str:
        """Play a scene on the rig for a few seconds, then go back to what was running. `scene` is a saved
        scene name or a whole scene as YAML (to try before saving). Not allowed during gig lock."""
        return t.preview_scene(scene, seconds)

    @tool
    def set_haze(action: str) -> str:
        """Haze mode: off, manual or pulse. Not allowed during gig lock. Haze settings live in the rig file."""
        return t.set_haze(action)

    @tool
    def node_health() -> str:
        """0.05 nodes and receivers: state, signal, packet loss, last data, recent drop-outs."""
        return t.node_health()

    @tool
    def assign_node(mac: str, name: str, universe: int = 0) -> str:
        """Name a new node (or a spare taking over a dead one's slot) and set its DMX universe."""
        return t.assign_node(mac, name, universe)

    return server


def _pinger(tools: DmxTools) -> None:
    while True:
        tools.ping()
        time.sleep(PING_S)


def main() -> None:
    # a separate client for check-ins, so they never mix with a running tool call
    threading.Thread(target=_pinger, args=(DmxTools(),), name="dmx-ping", daemon=True).start()
    build_server().run("stdio")


if __name__ == "__main__":
    main()
