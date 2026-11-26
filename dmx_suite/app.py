"""One running session: show files, engine, show control, MIDI, store, gig lock, health log.
Shared by the console, the browser UI and the Claude (MCP) API.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any

from . import effects
from .busk import Override
from .engine import Engine
from .fixtures import EMITTERS, ConfigError, Kind
from .layout import full_layout
from .look import INTENSITY_RULE1
from .midi.map import ACTIONS
from .midi.monitor import MidiMonitor
from .midi.router import MidiRouter
from .node.health import HealthEvent
from .output import NodeSerialDriver, OutputDriver
from .profile import resolve_exempt
from .rig import parse_placement
from .scenes import ScenePlayer, parse_scene
from .showctl import ShowController
from .showfiles import ShowFiles, load_show
from .store import LockedError, ShowStore
from .versions import upgrade

log = logging.getLogger(__name__)


class App:
    def __init__(self, files: ShowFiles, drivers: list[OutputDriver], state_path: Path | None = None,
                 log_dir: Path | None = None, rig: str = "full", look: str = "default", midi: str = "default",
                 clock: Any = None) -> None:
        self.files = files
        self.names = (rig, look, midi)
        self.engine = Engine(files.rig, drivers, files.look, **({"clock": clock} if clock else {}))
        self.ctl = ShowController(self.engine, files, state_path)
        self.monitor = MidiMonitor()
        self.router = MidiRouter(self.engine, files.midimap, self.monitor, self.ctl)
        self.router.busk = self.busk  # MIDI / OSC action `busk`
        self.gig_lock = False
        self.project: Any = None  # package.DmsProject when running a .dms show file
        self.on_restart: Any = None  # restart the app on another show file (set by the cli)
        self.store = ShowStore(files.root, self._store_locked)
        self.log_dir = log_dir
        self.alerts: list[dict[str, Any]] = []  # node dropped / weak, newest last
        self.show_problem: dict[str, str] | None = None  # running the last good show files (cli start-up)
        self.osc: Any = None  # osc.OscServer, when the rig turns OSC on
        self.osc_error: str | None = None
        self.midi_inputs: Any = None  # MidiInputs when running live
        self.clients: dict[str, dict[str, Any]] = {}  # e.g. "claude": {first, last, calls, last_call}
        self.screens: dict[int, dict[str, Any]] = {}  # open browser streams: id -> {ip, local, since}
        self._fps = (time.monotonic(), 0, 0.0)  # (window start, frames at start, last rate)
        self._lock = threading.RLock()
        self.started = time.time()
        for d in drivers:
            if isinstance(d, NodeSerialDriver):
                d.link.health.expect(files.rig.nodes)
                d.link.health.listeners.append(self._health_event)
        self._load_lock_state(state_path)
        self._loaded_sig = self._rig_sig()

    # ------------------------------------------------------------------ gig lock

    def _load_lock_state(self, state_path: Path | None) -> None:
        self._lock_path = state_path.with_name(".giglock") if state_path else None
        if self._lock_path and self._lock_path.exists():
            self.gig_lock = self._lock_path.read_text().strip() == "on"

    def set_gig_lock(self, on: bool) -> None:
        self.gig_lock = on
        if self._lock_path:
            self._lock_path.write_text("on" if on else "off")
        if on:
            self.engine.end_preview()

    def _store_locked(self) -> bool | str:
        if self.gig_lock:
            return True
        if self.project is not None and self.project.read_only:
            return f"{self.project.name} is open on another computer: read-only here"
        return False

    def attach_project(self, project: Any) -> None:
        """Run on a .dms: every saved change is packed back into it."""
        self.project = project
        self.store.after_commit = project.save

    def project_info(self) -> dict[str, Any] | None:
        p = self.project
        if p is None:
            return None
        return {"name": p.name, "path": str(p.dms), "read_only": p.read_only, "error": p.save_error,
                "notes": list(p.notes)}

    def require_unlocked(self, what: str) -> None:
        if self.gig_lock:
            raise LockedError(f"gig lock is on: {what} isn't allowed")

    # ------------------------------------------------------------------ health

    def _health_event(self, ev: HealthEvent) -> None:
        if ev.new.value in ("offline", "weak") and ev.old is not None:
            self.alerts.append({"time": ev.time, "mac": ev.mac, "name": ev.name, "state": ev.new.value})
            self.alerts = self.alerts[-50:]
        if self.log_dir:
            try:
                self.log_dir.mkdir(parents=True, exist_ok=True)
                path = self.log_dir / f"health-{time.strftime('%Y-%m-%d')}.jsonl"
                with path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"time": ev.time, "mac": ev.mac, "name": ev.name,
                                        "from": ev.old.value if ev.old else None, "to": ev.new.value}) + "\n")
            except OSError:
                log.exception("health log write failed")

    def nodes(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for d in self.engine.drivers:
            if isinstance(d, NodeSerialDriver):
                for r in d.link.health.records():
                    hb = r.heartbeat
                    out.append({
                        "mac": r.mac, "name": r.name, "state": r.state.value, "expected": r.expected,
                        "type": hb.node_type.name if hb else None, "fw": hb.fw_str if hb else None,
                        "rssi": hb.rssi if hb else None, "loss_pct": hb.loss_pct if hb else None,
                        "last_data_age_ms": hb.last_data_age_ms if hb else None,
                        "universe": hb.universe if hb else None, "uptime_s": hb.uptime_s if hb else None,
                    })
            else:
                out.append({"mac": None, "name": d.name, "state": "connected", "driver": d.status()})
        return out

    def node_link(self) -> Any:
        for d in self.engine.drivers:
            if isinstance(d, NodeSerialDriver):
                return d.link
        raise ValueError("no 0.05 node output in this rig")

    # ------------------------------------------------------------------ status bar

    def note_client(self, name: str, call: str | None = None) -> None:
        """A local client (the Claude MCP server) checked in or made a call."""
        now = time.time()
        c = self.clients.setdefault(name, {"first": now, "last": now, "calls": 0, "last_call": None, "last_call_at": None})
        c["last"] = now
        if call:
            c["calls"] += 1
            c["last_call"], c["last_call_at"] = call, now

    def engine_fps(self) -> float:
        start, frames0, rate = self._fps
        now = time.monotonic()
        if now - start >= 1.0:
            rate = (self.engine.frames_sent - frames0) / (now - start)
            self._fps = (now, self.engine.frames_sent, rate)
        return rate

    def devices(self) -> list[dict[str, Any]]:
        """Everything outside the engine, for the status bar: kind, name, state (ok/warn/bad/sim/idle), detail."""
        out: list[dict[str, Any]] = []
        fps = self.engine_fps()
        running = self.engine._thread is not None
        e = self.engine
        fault_age = e.clock() - e.fault_at if e.fault is not None and e.fault_at is not None else None
        if fault_age is not None and fault_age < 300:
            out.append({"kind": "engine", "name": "Engine", "state": "bad",
                        "detail": f"fault {_ago(fault_age)} ago, back to the static look: {e.fault}"})
        else:
            out.append({"kind": "engine", "name": "Engine", "state": ("ok" if fps >= 35 else "warn") if running else "warn",
                        "detail": f"{fps:.0f} fps" if running else "not running"})
        p = self.project
        if p is not None:
            state = "bad" if p.save_error else "warn" if p.read_only or p.recovered else "ok"
            detail = p.save_error or "; ".join(p.notes) or p.name
            out.append({"kind": "files", "name": "Show file", "state": state, "detail": detail})
        if self.show_problem:
            out.append({"kind": "files", "name": "Show files", "state": "bad",
                        "detail": f"running the last good version (backup {self.show_problem['backup']}): "
                                  f"{self.show_problem['problem']}"})
        for d in self.engine.drivers:
            out.append(d.state())
        if self.midi_inputs is not None:
            for m in self.midi_inputs.status():
                out.append({"kind": "midi", "name": f"MIDI {m['name']}", "state": "ok" if m["connected"] else "bad",
                            "detail": m.get("port") or ("connected" if m["connected"] else "unplugged")})
        else:
            out.append({"kind": "midi", "name": "MIDI", "state": "sim", "detail": "simulated input"})
        if self.osc is not None:
            out.append(self.osc.state())
        elif self.osc_error:
            out.append({"kind": "osc", "name": "OSC", "state": "bad", "detail": self.osc_error})
        c = self.clients.get("claude")
        now = time.time()
        if c is None or now - c["last"] > 75:
            out.append({"kind": "claude", "name": "Claude", "state": "idle",
                        "detail": "not connected" if c is None else f"last seen {_ago(now - c['last'])} ago"})
        else:
            busy = c["last_call_at"] is not None and now - c["last_call_at"] < 60
            detail = f"{c['last_call']} {_ago(now - c['last_call_at'])} ago" if busy else "connected"
            if self.gig_lock:
                detail += " · read-only (gig lock)"
            out.append({"kind": "claude", "name": "Claude", "state": "ok", "detail": detail, "active": busy})
        screens = list(self.screens.values())  # web threads add/remove while we read
        phones = sum(1 for s in screens if not s["local"])
        n = len(screens)
        out.append({"kind": "screens", "name": "Screens", "state": "ok" if n else "idle",
                    "detail": f"{n} open" + (f" ({phones} phone/tablet)" if phones else "")})
        return out

    # ------------------------------------------------------------------ reload after edits

    def reload(self) -> list[str]:
        with self._lock:  # the web page, Claude and a restore can all reload at once
            return self._reload()

    def _rig_sig(self) -> str:
        """What the patch and rig were loaded from (a change means the rig is rebuilt live)."""
        import hashlib

        h = hashlib.sha1()
        root, rig = self.files.root, self.names[0]
        for p in (root / "fixtures.yaml", *sorted((root / "rigs").glob(f"{rig}.y*ml"))):
            try:
                h.update(p.read_bytes())
            except OSError:
                pass
        h.update(rig.encode())
        return h.hexdigest()

    def switch_rig(self, name: str) -> list[str]:
        """Run another rig config (e.g. the small rig) without a restart."""
        self.require_unlocked("switching rig")
        if not (self.files.root / "rigs" / f"{name}.yaml").exists():
            raise ValueError(f"no rig {name!r}")
        with self._lock:
            old = self.names
            self.names = (name, old[1], old[2])
            try:
                return self._reload()
            except Exception:
                self.names = old
                raise

    def _reload(self) -> list[str]:
        """Pick up edited show files without stopping. A changed patch or rig (fixtures, addresses,
        profile, limits, haze...) is rebuilt and swapped in on the next frame; what's playing is
        built again on it. Output and input settings (DMX interfaces, MIDI ports, OSC) still need
        a restart."""
        rig, look, midi = self.names
        new = load_show(self.files.root, rig, look, midi)
        notes = []
        sig = self._rig_sig()
        if sig != getattr(self, "_loaded_sig", None) and hasattr(self, "_loaded_sig"):
            old_rig = self.files.rig
            if (new.rig.outputs, new.rig.midi_inputs, new.rig.osc) != (old_rig.outputs, old_rig.midi_inputs, old_rig.osc):
                notes.append("output, MIDI input and OSC changes take effect after a restart")
                new.rig.outputs, new.rig.midi_inputs, new.rig.osc = old_rig.outputs, old_rig.midi_inputs, old_rig.osc
            self.engine.swap_rig(new.rig, new.look)
            self._loaded_sig = sig
            self.files = new
            self.ctl.files = new
            self.router.map = new.midimap
            self.ctl.replay()
            notes.append(f"rig {new.rig.name} updated live")
            if self.show_problem:
                notes.append("show files fixed: now running them, not the last good version")
                self.show_problem = None
            return notes
        self._loaded_sig = sig
        live = self.files.rig
        live.layout = new.rig.layout  # the layout is display only: apply now
        for fid, fx in live.patch.fixtures.items():  # groups are labels: apply now too
            if fid in new.patch.fixtures:
                fx.groups = list(new.patch.fixtures[fid].groups)
        live.exempt = resolve_exempt(live.profile, live.patch, live.present)
        new.rig, new.patch = live, self.files.patch  # keep the live patch
        self.files = new
        self.ctl.files = new
        self.router.map = new.midimap
        if self.show_problem:
            notes.append("show files fixed: now running them, not the last good version")
            self.show_problem = None
        return notes

    def make_starter(self, overwrite: bool = False) -> dict[str, Any]:
        """Write the starter show (and its scenes) for the running rig, then play it."""
        from .starters import starter
        from .versions import stamped

        self.require_unlocked("making the starter show")
        scenes, show = starter(self.engine.rig)
        changes: dict[Any, str | None] = {}
        exists = []
        for name, data in scenes.items():
            p = self.store.path("scene", name)
            exists += [p.name] if p.exists() else []
            changes[p] = self.store.text_for(p, stamped(data))
        p = self.store.path("show", "starter")
        exists += [p.name] if p.exists() else []
        changes[p] = self.store.text_for(p, stamped(show))
        if exists and not overwrite:
            raise ValueError(f"there's already a starter show ({', '.join(exists)}): replace it?")
        bid = self.store.apply(changes, "starter show")
        notes = self.reload()
        self.ctl.select_show("starter", "calm")
        return {"backup": bid, "scenes": sorted(scenes), "notes": notes}

    def save_layout(self, layout: dict[str, Any]) -> str:
        """Write the light layout into this rig's file (validated + backed up like any edit)."""
        rig_name = self.names[0]
        data = self.store.read("rig", rig_name)
        if not isinstance(layout, dict):
            raise ValueError("layout must map fixture ids to {x, y, rot, shape}")
        data["layout"] = {fid: parse_placement(fid, p).to_dict() for fid, p in layout.items()}
        data.pop("stage", None)
        bid = self.store.put("rig", rig_name, data, f"light layout for rig {rig_name}")
        self.reload()
        return bid

    # ------------------------------------------------------------------ preview

    def preview_scene(self, scene: str | dict, seconds: float = 10) -> str:
        self.require_unlocked("preview")
        if isinstance(scene, str):
            if scene not in self.files.scenes:
                raise ValueError(f"no scene {scene!r}")
            sc = self.files.scenes[scene]
        else:
            scene = upgrade(scene, "scene", "preview")
            sc = parse_scene(scene, self.files.patch, self.files.palettes, scene.get("name", "preview"))
            if sc.uses_intensity and self.engine.rig.profile.master_gate:
                raise ValueError(f"{sc.name} {INTENSITY_RULE1}")
        self.engine.preview(ScenePlayer(sc, self.engine.rig, self.engine.clock(), self.ctl.tempo.eff), seconds, sc)
        msg = f"previewing {sc.name} for {seconds:.0f} s, then back to {self.ctl.describe()}"
        if self.engine.rig.profile.master_gate and not self.engine.master:
            msg += " (MASTER is off, so the rig stays dark)"
        return msg

    # ------------------------------------------------------------------ busking

    def busk(self, panel_key: str, wid: str, down: bool = True, level: float | None = None) -> str:
        """A busk widget pressed (down), let go, or its fader moved (level 0-1). From the Busk page,
        or MIDI / OSC (action busk)."""
        panel = self.files.panels.get(panel_key)
        if panel is None:
            raise ValueError(f"no busk panel {panel_key!r}")
        w = panel.widget(wid)
        e, key = self.engine, f"{panel_key}/{wid}"
        present = frozenset(f for f in w.fixtures if f in e.rig.present)
        held = any(o.key == key for o in e.held())
        if w.type in ("colour", "flash", "solo"):
            momentary = w.type == "solo" or w.mode == "flash"
            if momentary and not down:
                e.release(key, 0.0 if w.type == "flash" or w.mode == "flash" else panel.release_fade_s)
                return f"{w.label} off"
            if not down:
                return "release"
            if held and not momentary:
                e.release(key, panel.release_fade_s)
                return f"{w.label} off"
            if w.type == "solo":
                keep = frozenset(e.rig.exempt) - present  # the kick light keeps its own rules (rule 3)
                e.hold(Override(key, "solo", present, keep=keep))
            else:
                e.hold(Override(key, "colour", present, colour=w.colour))
            return f"{w.label} on"
        if w.type == "effect":
            if not down:
                return "release"
            if held:
                e.release(key, panel.release_fade_s)
                return f"{w.label} off"
            assert w.scene is not None
            sc = self.files.scenes[w.scene]
            e.hold(Override(key, "effect", source=ScenePlayer(sc, e.rig, e.clock(), self.ctl.tempo.eff)))
            return f"{w.label} on"
        if w.type == "go":
            if not down:
                return "release"
            if w.scene:
                self.ctl.select_scene(w.scene)
            elif w.show:
                self.ctl.select_show(w.show, w.set)
            return self.ctl.describe()
        if w.type == "fader":
            if level is None:
                return "fader: needs a value"
            t = w.target or ""
            if t == "grand":
                e.set_grand(level)
            elif t == "flash_level":
                e.set_flash_level(level)
            elif t == "speed":
                self.ctl.set_speed(4 ** (2 * level - 1))
            elif t.startswith("sub:"):
                e.set_sub(t[4:], level)
            return f"{w.label} {round(level * 100)}%"
        # haze
        if w.action == "boost":
            ok = e.haze_boost(down)
            return f"{w.label} {'on' if down and ok else 'off'}"
        if not down:
            return "release"
        {"off": e.haze_stop, "manual": e.haze_toggle_manual, "pulse": lambda: e.haze_mode("pulse")}[str(w.action)]()
        return f"haze {w.action}"

    def validate_scene(self, data: Any) -> dict[str, Any]:
        """Check scene data the way saving would, without saving (scene builder). Says which
        layer is at fault so the builder can mark it."""
        try:
            if not isinstance(data, dict):
                raise ValueError("a scene is a mapping with layers")
            data = upgrade(data, "scene", "scene")
            sc = parse_scene(data, self.files.patch, self.files.palettes, data.get("name") or "scene")
            if sc.uses_intensity and self.engine.rig.profile.master_gate:
                raise ValueError(f"{sc.name} {INTENSITY_RULE1}")
        except (ConfigError, ValueError, TypeError, KeyError, AttributeError) as e:
            m = re.search(r"layer (\d+)", str(e))
            return {"ok": False, "error": str(e), "layer": int(m.group(1)) if m else None}
        return {"ok": True, "length_s": sc.length, "layers": len(sc.layers)}

    def _busk_state(self) -> dict[str, Any]:
        held = self.engine.held()
        lights: dict[str, list[str]] = {}
        for o in held:
            for fid in (o.fixtures if o.kind != "effect" else []):
                lights.setdefault(fid, []).append(o.key)
        return {"held": [o.key for o in held], "lights": lights}

    def effects_catalogue(self) -> dict[str, Any]:
        """What the scene builder needs: every effect's settings, and the palette to pick from."""
        pal = self.files.palettes

        def hexed(c: dict[str, float]) -> str:
            r = min(1.0, c.get("red", 0) + c.get("white", 0) + c.get("amber", 0))
            g = min(1.0, c.get("green", 0) + c.get("white", 0) + 0.6 * c.get("amber", 0))
            b = min(1.0, c.get("blue", 0) + c.get("white", 0) + c.get("uv", 0))
            return "#" + "".join(f"{round(v * 255):02x}" for v in (r, g, b))

        return {
            "effects": effects.schemas(),
            "blends": list(effects.BLENDS),
            "colours": {k: hexed(c) for k, c in pal.colours.items()},
            "positions": sorted(pal.positions),
            "gobos": sorted(pal.gobos),
            "intensity": not self.engine.rig.profile.master_gate,  # scenes may set intensity
        }

    # ------------------------------------------------------------------ snapshot for the UI

    def fixture_view(self) -> list[dict[str, Any]]:
        frames = self.engine.frames
        out = []
        for fx in self.engine.rig.fixtures:
            frame = frames.get(fx.universe)
            if frame is None:
                continue
            vals = {ch: frame[fx.slot(ch)] for ch in fx.type.channels}
            dim = next((v / 255 for ch, v in vals.items() if ch.role == "dimmer"), 1.0)

            def rgb(pixel: int | None) -> str:
                e = {r: 0.0 for r in EMITTERS}
                for ch, v in vals.items():
                    if ch.role in EMITTERS and (pixel is None or ch.pixel == pixel or ch.pixel is None):
                        e[ch.role] = max(e[ch.role], v / 255)
                r = e["red"] + e["white"] + e["amber"] + 0.4 * e["uv"]
                g = e["green"] + e["white"] + 0.6 * e["amber"]
                b = e["blue"] + e["white"] + e["uv"]
                return "#" + "".join(f"{round(min(1.0, c * dim) * 255):02x}" for c in (r, g, b))

            item: dict[str, Any] = {"id": fx.id, "kind": fx.kind.value, "type": fx.type.name,
                                    "colour_only": fx.type.colour_only}
            if fx.kind == Kind.HAZE:
                item["haze"] = next(iter(vals.values())) / 255
            elif fx.type.pixels:
                item["pixels"] = [rgb(i) for i in range(fx.type.pixels)]
            else:
                item["colour"] = rgb(None)
            if fx.type.has("pan"):
                def axis(name: str) -> float:
                    c = next(v for ch, v in vals.items() if ch.role == name)
                    f = next((v for ch, v in vals.items() if ch.role == name + "_fine"), None)
                    return ((c << 8) | f) / 65535 if f is not None else c / 255
                item["pan"], item["tilt"] = axis("pan"), axis("tilt")
                item["override"] = fx.id in self.engine.position_override
            out.append(item)
        return out

    def snapshot(self) -> dict[str, Any]:
        e, now = self.engine, self.engine.clock()
        hz = e.haze.status(now)
        n = self.ctl.now()
        return {
            "time": time.time(),
            "master": e.master,
            "profile": e.rig.profile.summary(),
            "tempo": self.ctl.tempo.status(e.clock()),
            "busk": self._busk_state(),
            "fault": {"message": e.fault, "count": e.faults} if e.fault else None,
            "show_problem": self.show_problem,
            "project": self.project_info(),
            "blackout": e.blackout,
            "gig_lock": self.gig_lock,
            "grand": e.masters.grand.target,
            "flash_level": e.masters.flash.target,
            "subs": {k.value: f.target for k, f in e.masters.subs.items() if k != Kind.HAZE},
            "haze": {"enabled": hz.enabled, "mode": hz.mode.value, "on": hz.output_on, "level": hz.level,
                     "boosting": hz.boosting, "resting": hz.resting, "auto_off_s": hz.auto_off_in_s,
                     "next_pulse_s": hz.next_pulse_in_s, "boost_cooldown_s": hz.boost_cooldown_s},
            "now": n.__dict__,
            "describe": self.ctl.describe(),
            "preview_s": e.previewing,
            "setup": {"find": e.find, "channels": [{"universe": u, "channel": c, "value": v}
                                                   for (u, c), v in e.channel_test.items()]},
            "fixtures": self.fixture_view(),
            "nodes": self.nodes(),
            "alerts": self.alerts[-5:],
            "learning": self.router.learning,
            "rig": e.rig.name,
            "midi_inputs": self.midi_inputs.status() if self.midi_inputs is not None else [],
            "devices": self.devices(),
        }

    def catalogue(self) -> dict[str, Any]:
        """Names for the UI's buttons and lists."""
        f = self.files
        return {
            "shows": {k: {"name": s.name, "sets": list(s.sets), "default_set": s.default_set,
                          "steps": {sk: [{"scene": st.scene, "name": f.scenes[st.scene].name, "repeats": st.repeats,
                                          "hold_s": st.hold_s, "hold_beats": st.hold_beats}
                                         for st in ss.steps] for sk, ss in s.sets.items()}}
                      for k, s in f.shows.items()},
            "scenes": {k: s.name for k, s in f.scenes.items()},
            "setlists": {k: {"name": s.name, "songs": [x.name for x in s.songs]} for k, s in f.setlists.items()},
            "positions": sorted(f.palettes.positions),
            "fixtures": [{"id": fx.id, "kind": fx.kind.value, "type": fx.type.name, "colour_only": fx.type.colour_only,
                          "moves": fx.type.has("pan") and not fx.type.colour_only, "pixels": fx.type.pixels,
                          "gobo": fx.type.has("gobo"), "wheel": fx.type.has("colour_wheel"),
                          "pan_range": fx.type.pan_range, "tilt_range": fx.type.tilt_range}
                         for fx in self.engine.rig.fixtures],
            "layout": {fid: {"x": p.x, "y": p.y, "rot": p.rot, "shape": p.shape, "cols": p.cols}
                       for fid, p in full_layout(self.engine.rig).items()},
            "rig_name": self.names[0],
            "rigs": sorted(p.stem for p in (self.files.root / "rigs").glob("*.yaml")),
            "groups": self.engine.rig.patch.groups(),
            "actions": sorted(ACTIONS),
            "panels": {k: {"name": p.name, "widgets": [{"id": w.id, "type": w.type, "label": w.label, "mode": w.mode,
                                                         "target": w.target, "action": w.action} for w in p.widgets]}
                       for k, p in f.panels.items()},
        }


def _ago(seconds: float) -> str:
    s = int(seconds)
    return f"{s} s" if s < 90 else f"{s // 60} min"
