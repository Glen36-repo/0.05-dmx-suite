"""One running session: show files, engine, show control, MIDI, store, gig lock, health log.
Shared by the console, the browser UI and the Claude (MCP) API.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from .engine import Engine
from .fixtures import EMITTERS, Kind
from .midi.map import ACTIONS
from .midi.monitor import MidiMonitor
from .midi.router import MidiRouter
from .node.health import HealthEvent
from .output import NodeSerialDriver, OutputDriver
from .scenes import ScenePlayer, parse_scene
from .showctl import ShowController
from .showfiles import ShowFiles, load_show
from .store import LockedError, ShowStore

log = logging.getLogger(__name__)


class App:
    def __init__(self, files: ShowFiles, drivers: list[OutputDriver], state_path: Path | None = None,
                 log_dir: Path | None = None, rig: str = "full", look: str = "default", midi: str = "default") -> None:
        self.files = files
        self.names = (rig, look, midi)
        self.engine = Engine(files.rig, drivers, files.look)
        self.ctl = ShowController(self.engine, files, state_path)
        self.monitor = MidiMonitor()
        self.router = MidiRouter(self.engine, files.midimap, self.monitor, self.ctl)
        self.gig_lock = False
        self.store = ShowStore(files.root, lambda: self.gig_lock)
        self.log_dir = log_dir
        self.alerts: list[dict[str, Any]] = []  # node dropped / weak, newest last
        self._lock = threading.RLock()
        self.started = time.time()
        for d in drivers:
            if isinstance(d, NodeSerialDriver):
                d.link.health.expect(files.rig.nodes)
                d.link.health.listeners.append(self._health_event)
        self._load_lock_state(state_path)

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
        out = []
        for d in self.engine.drivers:
            if isinstance(d, NodeSerialDriver):
                for r in d.link.health.nodes.values():
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

    # ------------------------------------------------------------------ reload after edits

    def reload(self) -> list[str]:
        """Pick up edited scenes, palettes, shows, setlists and MIDI map without stopping.
        Fixture and rig changes need a restart (the patch is live on the rig)."""
        rig, look, midi = self.names
        new = load_show(self.files.root, rig, look, midi)
        notes = []
        if new.patch.fixtures.keys() != self.files.patch.fixtures.keys() or new.rig.present != self.files.rig.present:
            notes.append("fixture/rig changes take effect after a restart")
        new.rig, new.patch = self.files.rig, self.files.patch  # keep the live patch
        self.files = new
        self.ctl.files = new
        self.router.map = new.midimap
        return notes

    # ------------------------------------------------------------------ preview

    def preview_scene(self, scene: str | dict, seconds: float = 10) -> str:
        self.require_unlocked("preview")
        if isinstance(scene, str):
            if scene not in self.files.scenes:
                raise ValueError(f"no scene {scene!r}")
            sc = self.files.scenes[scene]
        else:
            sc = parse_scene(scene, self.files.patch, self.files.palettes, scene.get("name", "preview"))
        self.engine.preview(ScenePlayer(sc, self.engine.rig, self.engine.clock(), self.ctl.tempo.eff), seconds, sc)
        msg = f"previewing {sc.name} for {seconds:.0f} s, then back to {self.ctl.describe()}"
        if not self.engine.master:
            msg += " (MASTER is off, so the rig stays dark)"
        return msg

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
        }

    def catalogue(self) -> dict[str, Any]:
        """Names for the UI's buttons and lists."""
        f = self.files
        return {
            "shows": {k: {"name": s.name, "sets": list(s.sets), "default_set": s.default_set} for k, s in f.shows.items()},
            "scenes": {k: s.name for k, s in f.scenes.items()},
            "setlists": {k: {"name": s.name, "songs": [x.name for x in s.songs]} for k, s in f.setlists.items()},
            "positions": sorted(f.palettes.positions),
            "fixtures": [{"id": fx.id, "kind": fx.kind.value, "type": fx.type.name, "colour_only": fx.type.colour_only,
                          "moves": fx.type.has("pan") and not fx.type.colour_only} for fx in self.engine.rig.fixtures],
            "groups": self.engine.rig.patch.groups(),
            "actions": sorted(ACTIONS),
        }
