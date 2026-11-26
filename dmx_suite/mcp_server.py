"""MCP server so Claude (Desktop) can read, build, check and preview shows in plain words.

Run by Claude Desktop over stdio: `dmx-suite mcp`. Needs the `mcp` package (pip install -e .[claude]).
"""

from __future__ import annotations

import functools
import threading
import time

import yaml

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
                t.refresh()  # a .dms show file the app saved since the last call
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
    def list_fx() -> str:
        """The FX banks (Move, Colour, Flash, drum-reactive) for the running rig: each item's busy score, speed,
        moods and whether this rig can run it (rig size scaling); how the lights are classified; the palettes."""
        return t.list_fx()

    @tool
    def preview_look(pick_yaml: str, seconds: float = 10) -> str:
        """Try an auto-show look on the rig: '{move: pan_sweep, colour: colour_chase, drum: kick_pump,
        palette: cool, ride: {speed: 1, fan: 0.5, size: 0.5}, mood: mid}'. Says what the look quality rules
        think. Not during gig lock. Haze is never part of a look."""
        return t.preview_look(pick_yaml, seconds)

    @tool
    def get_quality_rules() -> str:
        """The look quality rules (busy scores, mood speeds, contrast, palette rules, autopilot weights)."""
        return t.quality_rules()

    @tool
    def save_quality_rules(yaml_text: str) -> str:
        """Tune the look quality rules (quality.yaml: only the parts you change), e.g. 'max_busy: 1.1' or
        'busy: {ballyhoo: 1.0}' or 'mood_speeds: {low: [slow]}'."""
        return t.save_quality_rules(yaml_text)

    @tool
    def autopilot_status(n: int = 20) -> str:
        """What the autopilot is doing and why: on/off, mood, energy, next change, control priority, and
        the last n decisions (time, energy, mood, look, trigger, reason). Engine must be running."""
        return t.autopilot_status(n)

    @tool
    def save_autopilot_settings(rig: str, yaml_text: str) -> str:
        """Tune the autopilot for a rig (merged into its `autopilot:` block), e.g.
        '{moods: {low: 75, mid: 45, high: 25}, palettes: [cool, ice], no_repeat: 6, gap_s: 5}'."""
        return t.save_autopilot_settings(rig, yaml_text)

    @tool
    def generate(kind: str, settings_yaml: str = "{}") -> str:
        """Generate editable scenes or shows for the running rig from the FX banks. kind: scenes
        ('{mood: low, style: ballad, palette: cool, count: 5, prefix: slow_blues}'), show
        ('{name: Opener, plan: [{section: verse, mood: low, length: 2}, {section: chorus, mood: high, length: 2}]}')
        or setlist ('{setlist: example, style: rock}': a starter show per song from its mood and bpm).
        Same seed gives the same files. Not during gig lock."""
        return t.generate(kind, settings_yaml)

    @tool
    def list_presets() -> str:
        """Presets (saved auto-show looks): id, name, tags, pick; starters are built in."""
        return t.list_presets()

    @tool
    def save_preset(name: str, yaml_text: str) -> str:
        """Save a preset: '{name: Verse blues, tags: [low], pick: {move: swim, colour: colour_fade, palette: cool,
        ride: {speed: 0.8}}}'. Use presets in show steps ({preset: id}) and setlist songs ({preset: id} or
        {presets: [ids], mood: high} to have the autopilot play only those for the song)."""
        return t.save_preset(name, yaml_text)

    @tool
    def get_alerts() -> str:
        """Alerts: what's offline or failing now and recently (time, device, message, state: active,
        dismissed, muted, snoozed, cleared), and which devices are muted for this rig. Read only."""
        return t.get_alerts()

    @tool
    def list_inputs() -> str:
        """Named MIDI/OSC inputs (inputs.yaml): devices, each input's notes / numbers / OSC address, roles."""
        return t.list_inputs()

    @tool
    def save_input(device: str, name: str, value_yaml: str) -> str:
        """Add or change a named input in a device (made if new), e.g. device 'td25', name 'kick',
        value_yaml '{name: Kick, type: note, notes: [35], roles: [kick, activity]}'. Every MIDI map
        entry that names the input follows. Types: note (notes: [...]), program_change / control_change
        (number), osc (address). Optional: channel (1-16 or any), port, velocity [lo, hi], shared, colour."""
        return t.save_input(device, name, value_yaml)

    @tool
    def rename_input(name: str, new_name: str) -> str:
        """Rename a named input; every file that uses it is updated in the same change."""
        return t.rename_input(name, new_name)

    @tool
    def list_points() -> str:
        """Head position points per rig: description, tags, stage place and each head's pan/tilt (0-1).
        The reference for aiming heads in scenes (`position: <point>`)."""
        return t.list_points()

    @tool
    def save_point(rig: str, name: str, value_yaml: str) -> str:
        """Add or replace a head point in a rig, e.g. '{description: Lead singer mic, tags: [band, safe],
        stage: {x: centre, y: front, z: mid}, heads: {mh_a: {pan: 0.45, tilt: 0.4}}}'. A head outside its
        head limits is refused (rule 8)."""
        return t.save_point(rig, name, value_yaml)

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
        """Add or change one palette entry. section: colours, gobos or palettes. value_yaml e.g. '"#ff3300"'
        for a colour, or '{name: Warm, tags: [warm, low], colours: [amber, "#ff4000"]}' for a palette.
        (Head positions are points in the rig file: use save_point.)"""
        return t.save_entry("palettes", section, name, value_yaml)

    @tool
    def delete_palette_entry(section: str, name: str) -> str:
        """Remove a palette entry (refused if a scene or show still uses it)."""
        return t.save_entry("palettes", section, name, None)

    @tool
    def save_fixture_type(key: str, yaml_text: str) -> str:
        """Add or change a fixture type (channel map), e.g. from a fixture manual. Channel roles: dimmer, red,
        green, blue, white, amber, uv, pan, tilt, pt_speed (invert: true if 0 = fastest), colour_wheel, gobo,
        strobe (default = shutter open value), zoom, focus, frost, prism, haze, fixed (default value); add
        `<role>_fine` after dimmer/pan/tilt/zoom/focus for 16-bit; `invert: true` on pan/tilt/zoom/focus/frost.
        Optional: colour_mix: auto (mix colours for the fixture's emitters; the default for new types),
        wheel: {name: {value, colour: "#rrggbb"}}, gobos: {name: value}, sub: head|bar|wash|kick.
        Set verified: false until it's checked on the real fixture."""
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
    def undo_last_change() -> str:
        """Undo your own last change to the show files (changes made at the laptop are never touched).
        Refused if the files have changed since; then use restore_backup."""
        return t.undo_last_change()

    @tool
    def now_playing() -> str:
        """What's running: show/set/song, MASTER, blackout, masters, haze (mode, output, settings, preset),
        gig lock. Engine must be running."""
        return t.now_playing()

    @tool
    def preview_scene(scene: str, seconds: float = 10) -> str:
        """Play a scene on the rig for a few seconds, then go back to what was running. `scene` is a saved
        scene name or a whole scene as YAML (to try before saving). Not allowed during gig lock."""
        return t.preview_scene(scene, seconds)

    @tool
    def set_haze(action: str, settings_yaml: str = "") -> str:
        """Haze mode: off, manual or pulse (or '' to leave the mode). With settings_yaml, also tune the haze
        controller and save it to the running rig: '{level: 41, pulse_level: 30, pulse_on_s: 1, pulse_every_s: 61,
        boost_level: 100, boost_s: 0, boost_cooldown_s: 20, max_on_s: 60, rest_s: 30, auto_off_min: 120,
        default_mode: off, presets: [{name: Haze 4 Med, mode: manual, level: 41}]}' (levels %). Not during gig
        lock. Scenes and shows never set haze (rule 5)."""
        out = []
        if settings_yaml.strip():
            out.append(t.save_haze_settings(settings_yaml))
        if action:
            out.append(t.set_haze(action))
        return "; ".join(out) or "nothing to do: give an action or settings"

    @tool
    def save_haze_settings(settings_yaml: str, rig: str = "") -> str:
        """Tune the haze controller (same settings as set_haze) for a rig without changing the mode."""
        return t.save_haze_settings(settings_yaml, rig)

    @tool
    def get_layout(rig: str = "") -> str:
        """Where every light sits on the stage plan: {x, y, z, rot} per fixture (x, y in 25 cm cells from the
        top left, back of the stage at the top; rot degrees, 0 = facing the audience), the stage size, and
        lights in the same place or touching. Spatial effects use these places. Default: the running rig."""
        return t.get_layout(rig)

    @tool
    def set_layout(positions_yaml: str, rig: str = "") -> str:
        """Place one or many lights: '{par_1: {x: 4, y: 2}, par_4: {x: 30, y: 2, rot: 90}, bar_2: {reverse: true}}'.
        Only the lights named change; a partial place (just rot) keeps the rest. z = height in metres.
        Validated and backed up; not during gig lock. Default: the running rig."""
        return t.set_layout(positions_yaml, rig)

    @tool
    def save_layout_position(fixture: str, x: float, y: float, rot: float = 0, rig: str = "") -> str:
        """Place one light (same as set_layout with one entry)."""
        return t.set_layout(yaml.safe_dump({fixture: {"x": x, "y": y, "rot": rot}}), rig)

    @tool
    def list_outputs() -> str:
        """The routing table: which universe goes out which interface (USB DMX, Art-Net/sACN, the 0.05 node
        link, each wireless node), with state, fps, frames, errors, last frame age and whether the last frame
        sent was all zeros. Plus routing problems (a universe with lights but no output, an output with no
        lights, an output with no universe: given). Use it first when the software runs but the rig is dark."""
        return t.list_outputs()

    @tool
    def set_output(index: int, driver: str = "", port: str = "", universe: int | None = None, mac: str = "",
                   alias: str = "") -> str:
        """Change output `index` (from list_outputs; -1 adds one): driver (usb_dmx_open, usb_dmx_pro, node,
        artnet, sacn), port (COM3), universe (0-15), alias (e.g. Stage DMX). With mac: set a wireless node's
        universe instead. Not during gig lock. Applied live: the outputs are rebuilt between frames."""
        return t.set_output(index, driver, port, universe, mac, alias)

    @tool
    def list_devices() -> str:
        """Devices plugged into the laptop, as they report themselves: USB DMX interfaces and the 0.05 node
        (product name, manufacturer, serial number, VID:PID, COM port, driver guess) and MIDI ports (OS name),
        with their alias and what each is used for (universe, MIDI in/out); configured devices that are
        missing; new ones not assigned yet. Engine must be running (not the simulator)."""
        return t.list_devices()

    @tool
    def set_device(device: str, alias: str = "", universe: int | None = None, driver: str = "", use: bool = True) -> str:
        """Name a device and say what it's for. device is an id from list_devices (usb:0403:6001:A1B2C3,
        midi-in:UM-ONE, midi-out:...). A USB interface sends `universe` (driver usb_dmx_open / usb_dmx_pro /
        node; default from what was detected); a MIDI input is opened; use=false stops using it. Saved to the
        running rig by device identity, so a new COM number keeps its universe. Not during gig lock."""
        return t.set_device(device, alias, universe, driver, use)

    @tool
    def delete_fixture(fixture: str) -> str:
        """Take a patched light out of the patch and every rig (layout, head limits). Refused if a scene or
        look names it directly; not during gig lock. Backed up (undo_last_change)."""
        return t.delete_fixture(fixture)

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
