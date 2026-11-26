"""What Claude can do with the show, as plain Python (the MCP server in mcp_server.py wraps these).

Talks to the running engine's local API when it's up (gig lock, live reload, preview, haze, nodes);
otherwise edits the show folder directly through the same validated, backed-up store.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml

from . import effects
from .fixtures import ConfigError, load_patch
from .look import INTENSITY_RULE1
from .paths import default_shows, giglock_on
from .rig import load_rig
from .scenes import parse_scene
from .showfiles import folder_palettes
from .store import ShowStore, StoreError
from .versions import upgrade

DEFAULT_URL = "http://127.0.0.1:8505"

GUIDE = """\
0.05 DMX Suite: how shows are built, and the rules every change is checked against.

RULES (a write that breaks one is rejected with the reason).
Safety rules, always on:
4. No background glow: anything not lit by the scene is fully off.
5. Haze is never set by scenes or shows, only by the haze controls (set_haze).
6. The grand master scales brightness only (not position, colour choice or haze).
8. Moving-head pan/tilt limits from the rig are always enforced at output.
Profile rules: each rig file has a `profile:` ("0.05_band", or "generic"); now_playing shows it.
1. "0.05 band": MASTER owns on/off. Scenes never set dimmers or `intensity`; switch a light on/off
   with its colour (off = "off"). "generic": lights follow the scene; a layer may set
   `intensity: 0-1`. A scene is checked against every rig's profile.
2. "0.05 band": MASTER off = the rig is dark and drum hits flash it. "generic": no drum flash.
3. "0.05 band": MASTER never affects the kick-drum light (`master_exempt`).
Fixture definition:
7. U'King heads (colour_only) are colour only: no position, sweep or random_move on them.
   Use the `movers` group for movement, `heads` for colour.

STEP SCENE (v3.2, `type: steps`): hand-programmed steps. Scene step_s / step_beats / fade_s defaults,
  playback loop|once|bounce, advance timer|manual|{input: <named input>}, move dark|lit (default
  from the profile: 0.05 band dark, generic lit), dark_s. steps: [{name, set: {lights or group:
  {colour, position, gobo, colour_wheel, strobe, zoom, focus, frost, prism, speed}}, step_s,
  step_beats, fade_s, move}]. Tracking: a step keeps everything from the step before, so only list
  what changes. Optional `layers` are effects over the steps. move: lit glides heads (inside limits).
SCENE (scenes/<name>.yaml): layers applied in order; later layers override earlier ones.
  name: Blue kit
  show_colour: blue            # drum flashes use this
  layers:
    - {fixtures: [bars], effect: pixel_chase, colour: blue, background: off, width: 3, period_s: 2}
    - {fixtures: [washes], colour: deep_blue}
    - {fixtures: [heads], effect: colour_chase, colours: [blue, white], period_s: 4, spread: 1}
    - {fixtures: [movers], position: drum_kit, gobo: dots}
    - {fixtures: [washes], colour: red, fallback: [bars]}   # used when the rig has no washes
  `fixtures` takes fixture ids and/or groups ("all" too). Colours: palette names, "#rrggbb",
  [r, g, b] 0-1, or {red, green, blue, white, amber, uv} 0-1. Positions: palette names or
  {pan, tilt} 0-1. Timing: period_s = one cycle; spread 0-1 = how much of a cycle is spread
  across the layer's fixtures (0 in step, 1 evenly round). Static keys: colour, pixels,
  position, gobo, colour_wheel, strobe, speed (0-1, 1 = fastest); they can sit alongside an effect
  (not a position with a movement effect). Layer keys: level 0-1, blend replace|max|add, mute.
  Effects that run across lights also take: mapping order|spatial (spatial = by where the lights
  are on the layout, each pixel where it's drawn), direction forward|reverse|centre_out|out_centre|
  random|angle, angle (degrees, 0 = left to right, 90 = top to bottom), groups_of N.
  Scene `length_s` = one cycle (default: the longest effect period).
EFFECTS (name: what it does. Settings):
{effects}
SHOW (shows/<name>.yaml): sets; each set has `steps` [{scene, repeats N | hold_s | hold_beats |
  hold_bars, fade_s}] with set `fade_s`, `order` sequence|random, `loop`; or `auto` {colours,
  energy: low|mid|high, head_mix: [matching, white, contrast], patterns: [all, heads_only,
  bars_only, kit], movement: [random, sweep, static], flash, fades} with `step_s`.
  (Old files with `scenes` + `step_s` still load.) Layers may time effects in `beats`.
BUSK PANELS (panels.yaml): panels of widgets (colour, flash, solo, effect, go, fader, haze).
SETLIST (setlists/<name>.yaml): songs: [{name, show, set} or {name, scene}, optional master: on/off].
PALETTES: colours / gobos (DMX value, or per fixture type) / palettes (named colour sets with tags).
HEAD POINTS (v3, per rig file `positions:`): named aim points, e.g. drum_kit, audience_l, each with a
  description, tags (band, audience, safe, floor, ceiling...), a rough stage place {x, y, z} and
  per-head pan/tilt 0-1. Scenes name them (`position: drum_kit`, sweep from/to). list_points shows
  them with descriptions: use them to work out where to aim. A head a point doesn't cover stays put.
AUTOPILOT (v3.4): changes looks on a timer per mood (rig `autopilot:` moods {low, mid, high} seconds,
  variation, no_repeat, fade per mood, energy {window_s, full_rate}, fill {window_s, hits, crash_s},
  gap_s and count_in for between songs, talking / walk_on / walk_off looks, palettes). Energy comes
  from named input roles. autopilot_status shows what it's doing and the decision log (why each look
  was chosen); save_autopilot_settings tunes it, e.g. "less movement, more blue in the verses" ->
  palettes: [cool, ice], and quality busy scores for the move items.
AUTO SHOW (v3.3): list_fx shows the FX banks for this rig (Move, Colour, Flash, drum-reactive), how the
  lights are classified, and the palettes. preview_look tries a pick {move, colour, drum, palette, ride:
  {speed, fade, fan, size, shift}, mood} and says what the look quality rules think (get_quality_rules,
  save_quality_rules tune them: busy scores, one lead at a time, mood speeds, contrast, palettes).
NAMED INPUTS (v3, inputs.yaml): MIDI/OSC inputs defined once in devices (e.g. td25: kick, snare,
  crash; fcb1010: pedals) with roles (kick, snare, tom, cymbal, count_in, activity). MIDI maps
  name them: `{input: snare, action: flash, fixtures: [bars]}`. To change a note, change the input.

Every save keeps the previous file in .backups/ (list_backups, restore_backup); undo_last_change
undoes your own last change (never one made at the laptop).
Gig lock (set by the band at the laptop): read only, no preview, no haze changes.
"""


def guide() -> str:
    return GUIDE.replace("{effects}", effects.guide())


class Offline(Exception):
    pass


def _dump(data: Any) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=None, width=110)


def _yaml(text: str | dict, what: str) -> dict:
    if isinstance(text, dict):
        return text
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise StoreError(f"{what}: not valid YAML: {e}") from e
    if not isinstance(data, dict):
        raise StoreError(f"{what}: expected a YAML mapping")
    return data


class DmxTools:
    def __init__(self, shows: Path | None = None, url: str | None = None, token: str | None = None) -> None:
        from .package import DmsProject, is_dms, work_dir

        self.shows = Path(shows or default_shows())
        self.url = (url or os.environ.get("DMX_SUITE_URL") or DEFAULT_URL).rstrip("/")
        self._token = token
        # a .dms show file: Claude reads its own unpacked copy, refreshed when the file changes
        self.project = None
        if is_dms(self.shows):
            self.project = DmsProject(self.shows, work_dir(self.shows, "-claude"), lock=False)
            self.project.open()
            self.shows = self.project.work
        self.local = ShowStore(self.shows, giglock_on)  # the app's gig lock binds offline edits too
        if self.project is not None:
            self.local.after_commit = self.project.save
        self.call_label: str | None = None  # which Claude tool is running, for the status bar

    # ------------------------------------------------------------------ transport

    @property
    def token(self) -> str:
        if self._token is None:
            from .access import claude_token

            try:
                self._token = claude_token()
            except OSError:
                self._token = ""
        return self._token

    def _call(self, method: str, path: str, body: Any = None) -> Any:
        data = None if body is None else json.dumps(body).encode()
        headers = {"Content-Type": "application/json", "X-DMX-Token": self.token, "X-DMX-Client": "claude"}
        if self.call_label:
            headers["X-DMX-Call"] = self.call_label
        req = urllib.request.Request(self.url + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read()).get("error", str(e))
            except (ValueError, AttributeError):
                msg = str(e)
            raise StoreError(msg) from None
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            raise Offline(str(e)) from None

    def ping(self) -> bool:
        """Tell the engine Claude Desktop has the 0.05 tools loaded. False if the engine isn't running."""
        saved, self.call_label = self.call_label, None
        try:
            self._call("GET", "/api/ping")
            return True
        except (Offline, StoreError):
            return False
        finally:
            self.call_label = saved

    def _online(self) -> bool:
        try:
            self._call("GET", "/api/catalogue")
            return True
        except Offline:
            return False

    def _live(self, method: str, path: str, body: Any = None) -> Any:
        try:
            return self._call(method, path, body)
        except Offline:
            raise StoreError("the engine isn't running (start `dmx-suite run`), so this live action isn't available") from None

    def _write(self, method: str, path: str, body: Any, local: Any) -> str:
        """Through the running engine (gig lock + live reload) if it's up, else straight to the files."""
        try:
            r = self._call(method, path, body)
            notes = "; ".join(r.get("notes") or [])
            return f"saved (backup {r['backup']})" + (f". {notes}" if notes else "")
        except Offline:
            bid = self._offline(local)
            return f"saved to the show files (backup {bid}); the engine isn't running"

    def refresh(self) -> None:
        """Pick up a .dms show file saved by the app since the last call."""
        if self.project is not None:
            self.project.refresh()

    def _offline(self, change: Any) -> Any:
        """An edit with the app closed; a .dms show file is locked while it's written."""
        if self.project is None:
            return change()
        from .package import drop_lock, take_lock

        other = take_lock(self.project.dms)
        if other is not None:
            raise StoreError(f"{self.project.name} is open on {other.get('host', '?')}: start the app there "
                             "and make the change through it")
        try:
            self.project.refresh()
            return change()
        finally:
            drop_lock(self.project.dms)

    # ------------------------------------------------------------------ read

    def get_guide(self) -> str:
        return guide()

    def list_fixtures(self) -> str:
        patch = load_patch(self.shows / "fixtures.yaml")
        out = {
            "fixtures": [{"id": f.id, "type": f.type.key, "kind": f.kind.value, "address": f.address,
                          "universe": f.universe, "groups": f.groups, "colour_only": f.type.colour_only,
                          "moves": f.type.has("pan") and not f.type.colour_only, "pixels": f.type.pixels}
                         for f in patch.fixtures.values()],
            "groups": patch.groups(),
            "types": {k: {"name": t.name, "kind": t.kind.value, "verified": t.verified,
                          "channels": [c.role + (f"[px{c.pixel + 1}]" if c.pixel is not None else "") for c in t.channels]}
                      for k, t in patch.types.items()},
        }
        return _dump(out)

    def get_palettes(self) -> str:
        return self.local.read_text("palettes")

    def list(self, kind: str) -> str:
        names = self.local.names(kind)
        rows = []
        for n in names:
            try:
                title = self.local.read(kind, n).get("name", "")
            except (StoreError, yaml.YAMLError):
                title = "(unreadable)"
            rows.append(f"{n}: {title}")
        return "\n".join(rows) or f"no {kind}s"

    def get(self, kind: str, name: str) -> str:
        return self.local.read_text(kind, name)

    def get_midi_map(self) -> str:
        names = self.local.names("midi")
        return "\n---\n".join(f"# midi/{n}.yaml\n" + self.local.read_text("midi", n) for n in names)

    def list_fx(self) -> str:
        r = self._live("GET", "/api/fx")
        items = [{k: i[k] for k in ("id", "bank", "label", "busy", "speed", "moods", "available")} for i in r["items"]]
        return _dump({"rig": r["rig"], "items": items, "palettes": r["palettes"]})

    def quality_rules(self) -> str:
        from .quality import load_rules

        return _dump(load_rules(self.shows))

    def save_quality_rules(self, yaml_text: str) -> str:
        data = _yaml(yaml_text, "quality rules")
        return self._write("PUT", "/api/store/quality/", {"data": data}, lambda: self.local.put("quality", "", data))

    def preview_look(self, pick_yaml: str, seconds: float = 10) -> str:
        """Compose an FX pick for this rig, say what the quality rules think, and play it for a while."""
        pick = _yaml(pick_yaml, "pick")
        r = self._live("POST", "/api/ride/check", {"pick": pick, "mood": pick.get("mood", "mid")})
        msg = self._live("POST", "/api/preview", {"scene_data": r["scene"], "seconds": seconds})["message"]
        issues = r["issues"]
        return msg + (". Quality: " + "; ".join(issues) if issues else ". Quality: fine")

    def autopilot_status(self, n: int = 20) -> str:
        r = self._live("GET", f"/api/autopilot?n={int(n)}")
        return _dump(r)

    def save_autopilot_settings(self, rig: str, yaml_text: str) -> str:
        data = _yaml(yaml_text, "autopilot settings")
        cur = self.local.read("rig", rig)
        cur["autopilot"] = {**(cur.get("autopilot") or {}), **data}
        return self._write("PUT", f"/api/store/rig/{rig}", {"data": cur}, lambda: self.local.put("rig", rig, cur))

    def get_alerts(self) -> str:
        return _dump(self._live("GET", "/api/alerts"))

    def list_inputs(self) -> str:
        return self.local.read_text("inputs") if (self.shows / "inputs.yaml").exists() else "no inputs.yaml yet"

    def list_points(self) -> str:
        out = {}
        for r in self.local.names("rig"):
            pts = self.local.read("rig", r).get("positions") or {}
            if pts:
                out[r] = pts
        return _dump(out) if out else "no head points yet (Heads page: aim, then store to a point)"

    def save_input(self, device: str, name: str, value_yaml: str) -> str:
        value = _yaml(value_yaml, "input")
        return self._write("POST", "/api/store/input", {"action": "put", "device": device, "name": name, "value": value},
                           lambda: self.local.put_input(device, name, value))

    def rename_input(self, name: str, new_name: str) -> str:
        return self._write("POST", "/api/store/input", {"action": "rename", "name": name, "new_name": new_name},
                           lambda: self.local.rename_input(name, new_name))

    def save_point(self, rig: str, name: str, value_yaml: str) -> str:
        value = _yaml(value_yaml, "point")
        return self._write("POST", "/api/store/point", {"action": "put", "rig": rig, "name": name, "value": value},
                           lambda: self.local.put_point(rig, name, value))

    def list_backups(self) -> str:
        return _dump(self.local.backups(30)) or "no backups yet"

    def now_playing(self) -> str:
        s = self._live("GET", "/api/state")
        keep = {k: s[k] for k in ("describe", "master", "blackout", "gig_lock", "grand", "subs", "haze", "preview_s", "rig")}
        return _dump(keep)

    def node_health(self) -> str:
        s = self._live("GET", "/api/state")
        return _dump({"nodes": s["nodes"], "recent_alerts": s["alerts"]})

    # ------------------------------------------------------------------ validate (dry run)

    def validate_scene(self, scene_yaml: str) -> str:
        data = _yaml(scene_yaml, "scene")
        patch = load_patch(self.shows / "fixtures.yaml")
        pal = folder_palettes(self.shows, patch)
        try:
            data = upgrade(data, "scene", "scene")
            sc = parse_scene(data, patch, pal, data.get("name", "scene"))
            if sc.uses_intensity:  # rule 1: only rigs whose profile doesn't use MASTER on/off
                gated = [rp.stem for rp in sorted((self.shows / "rigs").glob("*.yaml"))
                         if load_rig(rp, patch).profile.master_gate]
                if gated:
                    return f"rejected: {sc.name} {INTENSITY_RULE1} (rig {', '.join(gated)})"
        except ConfigError as e:
            return f"rejected: {e}"
        return f"ok: {sc.name}, {len(sc.layers)} layers"

    # ------------------------------------------------------------------ write

    def save(self, kind: str, name: str, text: str) -> str:
        data = _yaml(text, kind)
        return self._write("PUT", f"/api/store/{kind}/{name}", {"data": data},
                           lambda: self.local.put(kind, name, data, f"claude: put {kind} {name}"))

    def delete(self, kind: str, name: str) -> str:
        return self._write("DELETE", f"/api/store/{kind}/{name}", {}, lambda: self.local.delete(kind, name))

    def duplicate(self, kind: str, src: str, dst: str) -> str:
        return self._write("POST", f"/api/store/{kind}/{src}/duplicate", {"to": dst},
                           lambda: self.local.duplicate(kind, src, dst))

    def save_entry(self, kind: str, section: str, name: str, value_yaml: str | None) -> str:
        value = None if value_yaml is None else yaml.safe_load(value_yaml)
        method = "DELETE" if value is None else "PUT"
        return self._write(method, f"/api/store/{kind}/{section}/{name}", {"value": value},
                           lambda: self.local.put_entry(kind, section, name, value))

    def save_fixture(self, entry_yaml: str) -> str:
        entry = _yaml(entry_yaml, "fixture")
        return self._write("POST", "/api/store/fixture", {"entry": entry}, lambda: self.local.put_fixture(entry))

    def restore_backup(self, backup: str, file: str) -> str:
        return self._write("POST", "/api/store/restore", {"backup": backup, "file": file},
                           lambda: self.local.restore(backup, file))

    # ------------------------------------------------------------------ live (engine must be running)

    def undo_last_change(self) -> str:
        """Undo Claude's own last change (never one made at the laptop)."""
        try:
            r = self._call("POST", "/api/undo/claude", {})
            c = r["change"]
        except Offline:
            c = self._offline(self.local.undo)
        return f"undone: {c['note']} ({', '.join(c['files'])})"

    def preview_scene(self, scene: str, seconds: float = 10) -> str:
        """`scene` is a scene name, or a whole scene in YAML (try it before saving)."""
        body: dict[str, Any] = {"seconds": seconds}
        if "\n" in scene or ":" in scene:
            body["scene_data"] = _yaml(scene, "scene")
        else:
            body["scene"] = scene
        return self._live("POST", "/api/preview", body)["message"]

    def set_haze(self, action: str) -> str:
        if action not in ("off", "manual", "pulse"):
            raise StoreError("haze action: off, manual or pulse (boost stays on the footswitch)")
        self._live("POST", "/api/claude/haze", {"action": action})
        return f"haze {action}"

    def assign_node(self, mac: str, name: str, universe: int = 0) -> str:
        self._live("POST", "/api/nodes/assign", {"mac": mac, "name": name, "universe": universe})
        return f"named {mac} {name!r} on universe {universe}"
