"""What Claude can do with the show, as plain Python (the MCP server in mcp_server.py wraps these).

Talks to the running engine's local API when it's up (gig lock, live reload, preview, haze, nodes);
otherwise edits the show folder directly through the same validated, backed-up store.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
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
  v4: a set: key may be a pixel selection (colour only): bar_1:px3, bar_1:px1-4, bars:px1,8, bars:odd /
  even / first3 / last3, or a saved pixel group (fixtures.yaml pixel_groups:, e.g. bar_tips). Edit one
  step with add_step / update_step / move_step / delete_step instead of rewriting the scene.
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
STAGE AND PATCH (v4): get_layout / set_layout place lights on the stage plan ({x, y} in 25 cm cells from
  the top left, back of the stage at the top; rot degrees; z height in metres; reverse for a bar mounted
  backwards). Spatial effects use these places, so lights in one place show the same part of an effect:
  get_layout lists overlaps and touching lights - spread them. delete_fixture takes a light out of the
  patch and every rig.
ROUTING AND DEVICES (v4): list_outputs = which universe goes out which interface (USB DMX by device
  identity, Art-Net/sACN, the 0.05 node link, each wireless node) with fps, frames, errors, last frame and
  an all-zero flag, plus problems (a universe with lights but no output ...). set_output changes one output
  (applied live). list_devices / set_device: what's plugged in as each device reports itself (product,
  serial, VID:PID, COM port; MIDI port names), aliases, and what each is used for.
FAULT-FINDING (v4): "software running, rig dark": list_outputs, then monitor_dmx (the frame an interface
  really sent: no frames / all zero / values per channel with names), then check MASTER, blackout, grand
  master. "Pedal does nothing": monitor_midi (each event, the named input it matched, what it did or
  'unmapped'); fix the input with save_input.
DRUM KIT (v6): the drummer's kit defined once in inputs.yaml `kits:` (one active): pieces (kick, snare,
  hi-hat, toms, cymbals, extra pads, tap pad) with zones (head / rim / x_stick, closed / pedal / open, bow /
  bell / edge), each a named input with notes, role (kick, snare, hat, tom, cymbal, tap, count_in,
  trigger_only), tempo weight, velocity floor, tempo y/n, drum flash target (fixtures / colour / length_ms:
  the kit owns them, not the MIDI map) and an optional drummer trigger (scene / preset / flash_fx). Tempo,
  drum flash and autopilot energy all read it. list_kits / get_kit (with unmapped notes heard), set_kit_piece,
  set_active_kit, kit_learn_status (arm a zone, the next hit is its note). A show without kits shows
  band_kit as a view of its drum inputs; the first change writes it (inputs and flash mappings move in,
  backed up).
TEMPO FROM THE DRUMS (v6): the band plays without a click, so the module's MIDI clock isn't used. Source
  `drums` (set_tempo_source; v3 `kick` = drums) tracks every drum hit weighted (kick 1, snare 1, hat 0.5,
  tom 0.6, cymbal 0.4; ghost notes under the velocity floor ignored), seeded by a tap (tap_tempo, FCB tap,
  a tap-role pad) or a count-in (4 even hits on a count_in pad after 2 s quiet), searching only +-15 % of
  the seed (no half / double time lock). Output: median of 8 beats, moves only when > 3 % off for 4 beats
  (then glides), a > 15 % change only after 8 beats (re-seed); phase nudged <= 10 % a beat. Low confidence
  (fills, breakdowns, drums stopped) = freewheel at the last tempo, never timers. tempo_status: BPM, beat,
  bar, confidence, freewheel, seed source. set_tempo_params tunes it live (save to keep). step_beats steps
  and beat-synced effects follow it; step_s scenes stay on timers. Source off: last BPM (120 if none).
DARKNESS AND LIT (v6): darkness puts BLACK INTO THE AUTOPILOT'S EFFECTS, it is not a dimmer. Under the 0.05
  band profile black is always colour off (RGB/W/A/UV 0), never intensity or the dimmer; MASTER keeps on/off;
  no glow. A layer's `lit:` (0-100 %, also on a whole scene) shapes its own black: narrower bands in sweeps
  and chases, black slots in palettes and colour cycles (50 % = colour, black ...), gaps between gradient /
  rainbow segments, a regular black pattern on still colours (moves with shift). Autopilot looks render
  lit x (1 - darkness); hand-made scenes and shows play as authored; Override ignores it; the kick light is
  exempt; heads keep moving dark; drum flash (MASTER off) leaves black slots black. set_autopilot {darkness}
  sets it live (eased over the look's fade; holds until the next LOW / MID / HIGH change), set_set_darkness
  stores a set's value, autopilot_status shows it with its source and CC, preview_look takes darkness.
DMX DIAGNOSTICS (v5): "rig dark, lights in auto / sound mode, frames counting" = no valid DMX reaches
  them. fault_find (start, then answer) walks the same steps as the Monitor page wizard. check_outputs:
  USB DMX (Open) checklist (VCP / D2XX, latency timer > 1 ms, port held by Daslight / QLC+ / FreeStyler,
  250k 8N2, USB selective suspend, measured timing) with fixes. test_output_methods: cycle break methods
  (d2xx, serial_break, baud_drop, long break) with All full; the band taps Lights responded, or tell it
  save_step. run_test_pattern / stop_test_pattern: all_full, chase, find, ramp, keep_alive straight to the
  interface (bypasses MASTER and masters; head limits apply; haze always 0). set_output takes break_method,
  break_us, mab_us, fps, channels. Measured timing is host-side: the wire can't be verified on an Open DMX.
HAZE SETTINGS (v4): set_haze / save_haze_settings tune the haze controller only (level, pulse_level,
  pulse_on_s, pulse_every_s, boost_level, boost_s, boost_cooldown_s, max_on_s, rest_s, auto_off_min,
  default_mode, presets [{name, mode, level}]). Scenes and shows still never set haze (rule 5).
OVERRIDE PANELS (panels.yaml; "busk" before v4): panels of widgets (colour, flash, solo, effect, go, fader, haze)
  played by hand over the show; Override sits above the show and the autopilot (control priority).
  MIDI action `override` (panel, widget); `busk` still works.
SETLIST (setlists/<name>.yaml): songs: [{name, show, set} or {name, scene}, optional master: on/off].
PALETTES: colours / gobos (DMX value, or per fixture type) / palettes (named colour sets with tags).
HEAD POINTS (v3, per rig file `positions:`): named aim points, e.g. drum_kit, audience_l, each with a
  description, tags (band, audience, safe, floor, ceiling...), a rough stage place {x, y, z} and
  per-head pan/tilt 0-1. Scenes name them (`position: drum_kit`, sweep from/to). list_points shows
  them with descriptions: use them to work out where to aim. A head a point doesn't cover stays put.
PRESETS AND GENERATOR (v3.5): presets.yaml {presets: {id: {name, tags, pick: {move, colour, drum,
  palette, feel}}}} (starter presets built in). Show step {preset: id, hold_s}; setlist song
  {name, preset: id} or {name, presets: [ids], mood} (the autopilot plays only those for that song).
  generate kind scenes {mood, style rock|ballad|acoustic|opera|dance, palette, count, prefix, seed},
  show {name, plan: [{section, mood, length}], style, palette, hold_s}, setlist {setlist, style}:
  writes plain scenes/shows with a `generated:` note (seed etc.); same seed = same files. Then refine
  them like any scene. ratings.yaml holds look ratings from the review page (liked looks favoured).
AUTOPILOT (v3.4): changes looks on a timer per mood (rig `autopilot:` moods {low, mid, high} seconds,
  variation, no_repeat, fade per mood, energy {window_s, full_rate}, fill {window_s, hits, crash_s},
  between {on, gap_s, start first_hit|count_in, count_in, min_song_s, fade_in, fade_out, ignore [input ids],
  look} for between songs (v7; look and walk_on / walk_off take a generated look or {scene: id}), palettes). Energy comes
  from named input roles. autopilot_status shows what it's doing and the decision log (why each look
  was chosen); save_autopilot_settings tunes it, e.g. "less movement, more blue in the verses" ->
  palettes: [cool, ice], and quality busy scores for the move items. Darkness (v7): set_darkness mode manual | auto
  (between Min and Max markers, time_at_max % at Max, a minimum hold; a slider / pedal move goes back to Manual).
  Layer timing (v7): save_autopilot_settings timing together | staggered, layers {move, colour, palette,
  darkness: {every_s | every_looks | on: song|set, spread, locked}}. Palette bank (v7): play_palette plays one
  now; exclude_palette leaves one out of the autopilot's picks (rig auto: exclude_palettes), like FX types.
AUTO SHOW (v3.3): list_fx shows the FX banks for this rig (Move, Colour, Flash, drum-reactive), how the
  lights are classified, and the palettes. preview_look tries a pick {move, colour, drum, palette, feel:
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



def _channel_list(text: str) -> list[int]:
    """'1-14, 300' -> [1, 2, ... 14, 300]."""
    out: list[int] = []
    for part in (text or "").replace(" ", "").split(","):
        if not part:
            continue
        a, _, b = part.partition("-")
        try:
            out += list(range(int(a), int(b or a) + 1))
        except ValueError as e:
            raise StoreError(f"channels: numbers or ranges like 1-14, 300 (not {part!r})") from e
    return out

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

    def preview_look(self, pick_yaml: str, seconds: float = 10, darkness: float | None = None) -> str:
        """Compose an FX pick for this rig, say what the quality rules think, and play it for a while."""
        pick = _yaml(pick_yaml, "pick")
        r = self._live("POST", "/api/autopilot/check", {"pick": pick, "mood": pick.get("mood", "mid")})
        body: dict[str, Any] = {"scene_data": r["scene"], "seconds": seconds}
        if darkness is not None:
            body["darkness"] = darkness
        msg = self._live("POST", "/api/preview", body)["message"]
        issues = r["issues"]
        return msg + (". Quality: " + "; ".join(issues) if issues else ". Quality: fine")

    def autopilot_status(self, n: int = 20) -> str:
        r = self._live("GET", f"/api/autopilot?n={int(n)}")
        return _dump(r)  # includes darkness: {darkness, now, source, set_darkness, cc}

    def list_kits(self) -> str:
        r = self._live("GET", "/api/kits")
        rows = {k: {"name": v["name"], "channel": v.get("channel"), "pieces": len(v.get("pieces") or {})}
                for k, v in r["kits"].items()}
        note = "band_kit is a view of the drum inputs until the first kit change saves it" if r["derived"] else ""
        return _dump({"active": r["active"], "kits": rows, **({"note": note} if note else {})})

    def get_kit(self, kit: str = "") -> str:
        r = self._live("GET", "/api/kits")
        kid = kit or r["active"]
        if kid not in r["kits"]:
            raise StoreError(f"no kit {kid!r}")
        return _dump({"kit": kid, "active": kid == r["active"], **r["kits"][kid], "unmapped_notes": r["unmapped"]})

    def set_kit_piece(self, kit: str, piece: str, zone: str = "head", notes: str = "", role: str = "",
                      weight: float | None = None, velocity_floor: int | None = None, tempo: bool | None = None,
                      flash_yaml: str = "", trigger_yaml: str = "", name: str = "", piece_name: str = "",
                      remove: bool = False) -> str:
        changes: dict[str, Any] = {}
        if notes:
            changes["notes"] = [int(x) for x in str(notes).replace(",", " ").split()]
        for k, v in (("role", role), ("weight", weight), ("velocity_floor", velocity_floor), ("tempo", tempo),
                     ("name", name), ("piece_name", piece_name)):
            if v not in ("", None):
                changes[k] = v
        if flash_yaml:
            changes["flash"] = _yaml(flash_yaml, "flash") if flash_yaml.strip() not in ("none", "off") else None
        if trigger_yaml:
            changes["trigger"] = _yaml(trigger_yaml, "trigger") if trigger_yaml.strip() not in ("none", "off") else None
        body = {"action": "piece", "kit": kit, "piece": piece, "zone": zone, "changes": changes, "remove": remove}
        r = self._live("POST", "/api/kits", body)
        return f"saved (backup {r['backup']})"

    def set_active_kit(self, kit: str) -> str:
        r = self._live("POST", "/api/kits", {"action": "active", "kit": kit})
        return f"active kit {r['active']} (backup {r['backup']})"

    def kit_learn_status(self, kit: str = "", piece: str = "", zone: str = "head", arm: bool = False,
                         add: bool = False) -> str:
        if arm:
            r = self._live("POST", "/api/kits", {"action": "learn", "kit": kit, "piece": piece, "zone": zone, "add": add})
            return _dump({**r["learning"], "note": "ask the drummer to hit that pad (zone) once"})
        r = self._live("GET", "/api/kits")
        return _dump(r["learning"] or {"armed": False, "note": "nothing armed"})

    def tempo_status(self) -> str:
        r = self._live("GET", "/api/tempo")
        return _dump({**r["status"], "params": r["params"]})

    def tap_tempo(self) -> str:
        r = self._live("POST", "/api/tempo", {"action": "tap"})
        return f"tap: {r['bpm']:.1f} BPM" if r.get("bpm") else "tap noted (one more tap sets the tempo)"

    def set_tempo_source(self, source: str, save: bool = False) -> str:
        r = self._live("POST", "/api/tempo", {"action": "source", "source": source, "save": save})
        return _dump({**r["status"], **({"saved": r["backup"]} if save else {})})

    def set_tempo_params(self, params_yaml: str, save: bool = False) -> str:
        changes = _yaml(params_yaml, "tempo settings")
        r = self._live("POST", "/api/tempo", {"action": "params", "params": changes, "save": save})
        return _dump({"params": r["params"], **({"saved": r["backup"]} if save else {})})

    def set_autopilot(self, darkness: float) -> str:
        r = self._live("POST", "/api/darkness", {"value": darkness})
        back = " (Auto darkness is off: back to Manual)" if r.get("dropped") else ""
        return f"darkness {r['darkness']:g} % (eases in over the look's fade; holds until the next set change){back}"

    def set_darkness(self, mode: str | None = None, mn: float | None = None, mx: float | None = None,
                     time_at_max: float | None = None, hold_s: float | None = None, value: float | None = None,
                     set: str | None = None) -> str:
        given = {k: v for k, v in (("mode", mode), ("min", mn), ("max", mx), ("time_at_max", time_at_max),
                                   ("hold_s", hold_s), ("value", value)) if v is not None}
        if not given:
            raise StoreError("give a mode, markers or a value")
        if set:
            r = self._live("POST", "/api/darkness/set", {"set": set, "value": given})
            return f"saved (backup {r['backup']}): {set} darkness {_dump(given).strip()}"
        r = self._live("POST", "/api/darkness", given)
        if r["mode"] == "auto":
            return (f"darkness Auto: {r['min']:g}-{r['max']:g} %, {r['time_at_max']:g} % of the time at Max, "
                    f"hold {r['hold_s']:g} s (now {r['now']:g} %)")
        return f"darkness Manual {r['darkness']:g} % (eases in over the look's fade; holds until the next set change)"

    def set_set_darkness(self, set: str, value: float | None) -> str:
        r = self._live("POST", "/api/darkness/set", {"set": set, "value": value})
        return f"saved (backup {r['backup']}): {set} darkness {'cleared' if value is None else f'{value:g} %'}"

    def play_palette(self, palette: str) -> str:
        r = self._live("POST", "/api/autopilot/palette", {"palette": palette, "play": True})
        return r.get("message", "ok")

    def exclude_palette(self, palette: str, excluded: bool = True) -> str:
        r = self._live("POST", "/api/autopilot/palette", {"palette": palette, "excluded": excluded})
        return (f"palette {palette} {'left out of' if excluded else 'back in'} the autopilot's picks "
                f"(backup {r['backup']}); excluded now: {', '.join(r['excluded']) or 'none'}")

    def save_autopilot_settings(self, rig: str, yaml_text: str = "{}", timing: str | None = None,
                                layers: dict[str, Any] | None = None, between: dict[str, Any] | None = None) -> str:
        from .autopilot import merge_settings

        data = _yaml(yaml_text or "{}", "autopilot settings")
        for k, v in (("timing", timing), ("layers", layers), ("between", between)):
            if v is not None:
                data[k] = v
        if not data:
            raise StoreError("no autopilot settings given")
        cur = self.local.read("rig", rig)
        try:
            cur["autopilot"] = merge_settings(cur.get("autopilot"), data)
        except ConfigError as e:
            raise StoreError(str(e)) from e
        return self._write("PUT", f"/api/store/rig/{rig}", {"data": cur}, lambda: self.local.put("rig", rig, cur))

    def generate(self, kind: str, settings_yaml: str) -> str:
        b = {**_yaml(settings_yaml or "{}", "generator settings"), "kind": kind}
        r = self._live("POST", "/api/generate", b)
        return _dump({k: r[k] for k in ("seed", "scenes", "shows", "backup")})

    def list_presets(self) -> str:
        return _dump(self._live("GET", "/api/presets"))

    def save_preset(self, name: str, yaml_text: str) -> str:
        d = _yaml(yaml_text, "preset")
        body = {"action": "put", "id": name, "name": d.get("name"), "tags": d.get("tags"), "pick": d.get("pick", d)}
        return self._write("POST", "/api/store/preset", body, lambda: self._save_preset_offline(name, body))

    def _save_preset_offline(self, name: str, body: dict) -> str:
        data = self.local.read("presets")
        data.setdefault("presets", {})[name] = {k: v for k, v in (("name", body["name"] or name), ("tags", body["tags"] or []),
                                                                  ("pick", body["pick"]))}
        return self.local.put("presets", "", data)

    # ------------------------------------------------------------------ layout (v4)

    def _rig_name(self, rig: str = "") -> str:
        if rig:
            return rig
        names = self.local.names("rig")
        return "full" if "full" in names else names[0]

    def get_layout(self, rig: str = "") -> str:
        try:
            if not rig:
                return _dump(self._call("GET", "/api/layout"))
        except Offline:
            pass
        from .layout import layout_view

        name = self._rig_name(rig)
        r = load_rig(self.shows / "rigs" / f"{name}.yaml", load_patch(self.shows / "fixtures.yaml"))
        return _dump({"rig": name, **layout_view(r)})

    def set_layout(self, positions_yaml: str, rig: str = "") -> str:
        positions = _yaml(positions_yaml, "positions")
        if rig:  # a named rig: straight to its file (the running rig picks it up on its next reload)
            return f"saved to rigs/{rig}.yaml (backup {self._set_layout_offline(rig, positions)})"
        return self._write("POST", "/api/layout/positions", {"positions": positions},
                           lambda: self._set_layout_offline(self._rig_name(), positions))

    def _set_layout_offline(self, rig: str, positions: dict) -> str:
        from .layout import merge_positions

        r = load_rig(self.shows / "rigs" / f"{rig}.yaml", load_patch(self.shows / "fixtures.yaml"))
        data = self.local.read("rig", rig)
        data["layout"] = merge_positions(r, data.get("layout"), positions)
        return self.local.put("rig", rig, data, f"place {', '.join(sorted(positions))} on rig {rig}")

    def list_outputs(self) -> str:
        try:
            return _dump(self._call("GET", "/api/routing"))
        except Offline:
            from .rig import routing_problems

            name = self._rig_name()
            r = load_rig(self.shows / "rigs" / f"{name}.yaml", load_patch(self.shows / "fixtures.yaml"))
            return _dump({"rig": name, "outputs": r.outputs, "universes": r.universes, "problems": routing_problems(r),
                          "note": "the engine isn't running: no live stats"})

    def set_output(self, index: int, driver: str = "", port: str = "", universe: int | None = None, mac: str = "",
                   alias: str = "", break_method: str = "", break_us: float | None = None, mab_us: float | None = None,
                   fps: float | None = None, channels: str = "") -> str:
        if mac:  # a wireless node: its universe is set on the node itself
            if universe is None:
                raise StoreError("a node needs universe")
            return self.assign_node(mac, alias or mac, universe)
        ch: int | str | None = int(channels) if channels.isdigit() else (channels or None)
        given = (("driver", driver), ("port", port), ("universe", universe), ("alias", alias),
                 ("break_method", break_method), ("break_us", break_us), ("mab_us", mab_us), ("fps", fps), ("channels", ch))
        changes = {k: v for k, v in given if v not in ("", None)}
        r = self._live("POST", "/api/routing/output", {"index": index, "set": changes})
        notes = "; ".join(r.get("notes") or [])  # outputs are rebuilt live
        return f"saved (backup {r['backup']})" + (f". {notes}" if notes else "")

    def run_test_pattern(self, pattern: str, universe: int | None = None, output: int | None = None, fixture: str = "",
                         channel: int | None = None, value: int | None = None, dwell_s: float | None = None,
                         timeout_s: float | None = None, patched_only: bool = False, role: str = "") -> str:
        body = {"pattern": pattern, "universe": universe, "output": output, "fixture": fixture, "channel": channel,
                "value": value, "dwell_s": dwell_s, "timeout_s": timeout_s, "patched_only": patched_only, "role": role}
        r = self._live("POST", "/api/test/run", {k: v for k, v in body.items() if v not in (None, "")})
        return _dump({"running": r["test"], "note": "stop it with stop_test_pattern (or it stops itself at timeout_s)"})

    def fault_find(self, action: str = "start", answer: str = "", fixture: str = "") -> str:
        r = self._live("POST", "/api/faultfind", {"action": action, "answer": answer, "fixture": fixture})
        keep = ("stage", "step", "number", "of", "instruction", "answers", "test", "test_allowed", "flag", "outcome",
                "running", "cycle")
        out = {k: r[k] for k in keep if r.get(k) not in (None, "", [])}
        if r.get("stage") == "done":
            out["summary"] = r["summary"]
        return _dump(out)

    def check_outputs(self) -> str:
        r = self._live("GET", "/api/outputs/check")["outputs"]
        if not r:
            return "no USB DMX (Open) outputs in this rig: the checks are for FTDI interfaces"
        return _dump(r)

    def test_output_methods(self, output: int, save_step: int = 0) -> str:
        """Run the break-method cycle on an Open DMX output and wait for it; or save_step N afterwards."""
        if save_step:
            r = self._live("POST", "/api/cycle/save", {"output": output, "step": save_step})
            return _dump({"saved": r["saved"]})
        c = self._live("POST", "/api/cycle/start", {"output": output})["cycle"]
        end = time.monotonic() + c["step_s"] * c["of"] + 15
        last = None
        while time.monotonic() < end:
            time.sleep(0.5)
            c = self._live("GET", "/api/cycle")["cycle"]
            last = c
            if c["state"] != "running":
                break
        out = {k: last[k] for k in ("state", "result", "steps", "original")} if last else c
        if out.get("state") == "no_response":
            out["note"] = ("no step was confirmed: the output is back as it was. If the band saw one work, "
                           "call again with save_step = its number (1-based, from steps).")
        return _dump(out)

    def stop_test_pattern(self) -> str:
        r = self._live("POST", "/api/test/stop", {"why": "stopped by Claude"})
        return "stopped: normal output is back" if r["stopped"] else "no test pattern was running"

    def monitor_dmx(self, universe: int = 0, output: str = "", channels: str = "") -> str:
        """What one interface really sent on a universe: stats and channel values with names."""
        import base64

        q = f"/api/frame?u={int(universe)}" + (f"&out={output}" if output != "" else "")
        v = self._live("GET", q)
        names = {int(k): n for k, n in self._live("GET", f"/api/monitor/channels?u={int(universe)}").items()}
        out: dict[str, Any] = {k: v[k] for k in ("universe", "out", "source", "no_frames", "stats")}
        if v.get("frame"):
            frame = base64.b64decode(v["frame"])
            want = _channel_list(channels) or sorted(set(names) | {i + 1 for i, x in enumerate(frame) if x})
            out["channels"] = {c: {"value": frame[c - 1], "name": names.get(c, "")} for c in want if 1 <= c <= 512}
            out["non_zero"] = sum(1 for x in frame if x)
        else:
            out["channels"] = {}
            out["note"] = "this interface hasn't sent a frame on this universe: nothing is going out"
        return _dump(out)

    def monitor_midi(self, direction: str = "in", n: int = 50, port: str = "", channel: int = 0, type: str = "",
                     unmapped_only: bool = False) -> str:
        qs = f"dir={direction}&n={int(n)}&unmapped={'1' if unmapped_only else '0'}"
        if port:
            qs += f"&port={urllib.parse.quote(port)}"
        if channel:
            qs += f"&channel={int(channel)}"
        if type:
            qs += f"&type={urllib.parse.quote(type)}"
        rows = self._live("GET", f"/api/monitor/midi?{qs}")
        status = self._live("GET", "/api/monitor/status")
        keep = ("time", "port", "channel", "type", "number", "note", "value", "input", "roles", "result")
        return _dump({"events": [{k: r[k] for k in keep} for r in rows], "ports_in": status["midi_in"],
                      "ports_out": status["midi_out"], "rates": status["rates"], "energy": status["energy"]})

    def list_devices(self) -> str:
        r = self._live("GET", "/api/devices/list")
        if not r.get("scanning"):
            r["note"] = "the engine runs in simulator mode: no hardware is scanned"
        return _dump(r)

    def set_device(self, device: str, alias: str = "", universe: int | None = None, driver: str = "", use: bool = True) -> str:
        body = {"id": device, "alias": alias or None, "universe": universe, "driver": driver or None, "use": use}
        r = self._live("POST", "/api/devices/set", body)
        notes = "; ".join(r.get("notes") or [])
        return f"saved (backup {r['backup']})" + (f". {notes}" if notes else "")

    def delete_fixture(self, fixture: str) -> str:
        return self._write("POST", "/api/store/fixture/remove", {"id": fixture}, lambda: self.local.remove_fixture(fixture))

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

    def save_input(self, device: str, name: str, value_yaml: str, device_info_yaml: str = "") -> str:
        if not device:
            raise StoreError("save_input needs device (the device id the input belongs to, e.g. td25)")
        value = _yaml(value_yaml, "input")
        info = _yaml(device_info_yaml, "device info") if device_info_yaml.strip() else None
        body = {"action": "put", "device": device, "name": name, "value": value, "device_info": info}
        return self._write("POST", "/api/store/input", body, lambda: self.local.put_input(device, name, value, info))

    def rename_input(self, name: str, new_name: str) -> str:
        return self._write("POST", "/api/store/input", {"action": "rename", "name": name, "new_name": new_name},
                           lambda: self.local.rename_input(name, new_name))

    def save_point(self, rig: str, name: str, value_yaml: str) -> str:
        value = _yaml(value_yaml, "point")
        return self._write("POST", "/api/store/point", {"action": "put", "rig": rig, "name": name, "value": value},
                           lambda: self.local.put_point(rig, name, value))

    def list_backups(self) -> str:
        return _dump(self.local.backups(30)) or "no backups yet"

    def save_haze_settings(self, settings_yaml: str, rig: str = "") -> str:
        """Haze controller settings (levels %, seconds, auto_off_min, presets) into the rig's haze: block."""
        changes = _yaml(settings_yaml, "haze settings")
        if not rig:
            try:
                r = self._call("POST", "/api/haze/settings", {"changes": changes, "save": True})
                return f"saved (backup {r['backup']}) for rig {r['rig']}"
            except Offline:
                rig = self._rig_name()
        from .rig import parse_haze

        data = self.local.read("rig", rig)
        block = {**(data.get("haze") or {}), **changes}
        parse_haze(block)
        data["haze"] = block
        return f"saved to rigs/{rig}.yaml (backup {self.local.put('rig', rig, data, f'haze settings for rig {rig}')})"

    def now_playing(self) -> str:
        s = self._live("GET", "/api/state")
        keep = {k: s[k] for k in ("describe", "master", "blackout", "gig_lock", "grand", "subs", "haze", "preview_s", "rig")}
        return _dump(keep)

    def node_health(self) -> str:
        s = self._live("GET", "/api/state")
        outs = [{k: r.get(k) for k in ("output", "universe", "interface", "port", "state", "detail", "timing")}
                for r in self._live("GET", "/api/routing")["rows"] if r.get("timing")]
        return _dump({"nodes": s["nodes"], "usb_dmx": outs, "recent_alerts": s["alerts"]})

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

    def preview_scene(self, scene: str, seconds: float = 10, step: int = 0) -> str:
        """`scene` is a scene name, or a whole scene in YAML (try it before saving). step: a step scene's
        step number (1 = first) to hold on."""
        body: dict[str, Any] = {"seconds": seconds}
        if step:
            body["step"] = int(step) - 1
        if "\n" in scene or ":" in scene:
            body["scene_data"] = _yaml(scene, "scene")
        else:
            body["scene"] = scene
        return self._live("POST", "/api/preview", body)["message"]

    # ------------------------------------------------------------------ step scenes, one step at a time (v4)

    def _step_op(self, op: str, scene: str, body: dict[str, Any]) -> str:
        b = {"op": op, "scene": scene, **body}

        def offline() -> str:
            s = self.local
            raw = body.get("step_ref")
            ref: int | str = raw if isinstance(raw, (int, str)) else 0
            if op == "add":
                return s.add_step(scene, body["step"], body.get("at"))
            if op == "update":
                return s.update_step(scene, ref, body.get("set"), body.get("timing"), bool(body.get("replace")))
            if op == "move":
                return s.move_step(scene, ref, int(body["to"]))
            return s.delete_step(scene, ref)

        return self._write("POST", "/api/steps/edit", b, offline)

    @staticmethod
    def _ref(step: str | int) -> int | str:
        return int(step) if isinstance(step, int) or str(step).isdigit() else str(step)

    def add_step(self, scene: str, step_yaml: str, at: int = 0) -> str:
        return self._step_op("add", scene, {"step": _yaml(step_yaml, "step"), "at": at or None})

    def update_step(self, scene: str, step: str | int, set_yaml: str = "", timing_yaml: str = "", replace: bool = False) -> str:
        body: dict[str, Any] = {"step_ref": self._ref(step), "replace": replace}
        if set_yaml.strip():
            body["set"] = _yaml(set_yaml, "set")
        if timing_yaml.strip():
            body["timing"] = _yaml(timing_yaml, "timing")
        if "set" not in body and "timing" not in body:
            raise StoreError("update_step needs set_yaml and/or timing_yaml")
        return self._step_op("update", scene, body)

    def move_step(self, scene: str, step: str | int, to: int) -> str:
        return self._step_op("move", scene, {"step_ref": self._ref(step), "to": int(to)})

    def delete_step(self, scene: str, step: str | int) -> str:
        return self._step_op("delete", scene, {"step_ref": self._ref(step)})

    def set_haze(self, action: str) -> str:
        if action not in ("off", "manual", "pulse"):
            raise StoreError("haze action: off, manual or pulse (boost stays on the footswitch)")
        self._live("POST", "/api/claude/haze", {"action": action})
        return f"haze {action}"

    def assign_node(self, mac: str, name: str, universe: int = 0) -> str:
        self._live("POST", "/api/nodes/assign", {"mac": mac, "name": name, "universe": universe})
        return f"named {mac} {name!r} on universe {universe}"
