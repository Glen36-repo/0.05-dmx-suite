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

from .fixtures import ConfigError, load_patch
from .look import INTENSITY_RULE1
from .palettes import load_palettes
from .rig import load_rig
from .versions import upgrade
from .scenes import EFFECTS, parse_scene
from .paths import default_shows
from .store import ShowStore, StoreError

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
  position, gobo, colour_wheel, strobe, speed (0-1, 1 = fastest).
EFFECTS and their keys:
{effects}
SHOW (shows/<name>.yaml): sets on fixed step timers; each set has `scenes` (order: sequence|random)
  or `auto` {colours, energy: low|mid|high, head_mix: [matching, white, contrast],
  patterns: [all, heads_only, bars_only, kit], movement: [random, sweep, static], flash, fades}.
SETLIST (setlists/<name>.yaml): songs: [{name, show, set} or {name, scene}, optional master: on/off].
PALETTES: colours / positions (per head or {pan, tilt}) / gobos (DMX value, or per fixture type).

Every save keeps the previous file in .backups/ (list_backups, restore_backup).
Gig lock (set by the band at the laptop): read only, no preview, no haze changes.
"""


def guide() -> str:
    eff = "\n".join(f"  {k}: {', '.join(sorted(v))}" for k, v in EFFECTS.items())
    return GUIDE.replace("{effects}", eff)


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
        self.shows = Path(shows or default_shows())
        self.url = (url or os.environ.get("DMX_SUITE_URL") or DEFAULT_URL).rstrip("/")
        self._token = token
        self.local = ShowStore(self.shows)
        self.call_label: str | None = None  # which Claude tool is running, for the status bar

    # ------------------------------------------------------------------ transport

    @property
    def token(self) -> str:
        if self._token is None:
            from .web.server import TOKEN_FILE

            try:
                self._token = TOKEN_FILE.read_text(encoding="utf-8").strip()
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
            bid = local()
            return f"saved to the show files (backup {bid}); the engine isn't running"

    # ------------------------------------------------------------------ read

    def get_guide(self) -> str:
        return guide()

    def list_fixtures(self) -> str:
        patch = load_patch(self.shows / "fixtures.yaml")
        out = {
            "fixtures": [{"id": f.id, "type": f.type.key, "kind": f.kind.value, "address": f.address, "universe": f.universe,
                          "groups": f.groups, "colour_only": f.type.colour_only, "moves": f.type.has("pan") and not f.type.colour_only,
                          "pixels": f.type.pixels} for f in patch.fixtures.values()],
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
        pal = load_palettes(self.shows / "palettes.yaml", patch)
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
