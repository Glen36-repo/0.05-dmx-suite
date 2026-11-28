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
from .alerts import AlertCenter
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
        self.midi_out_monitor = MidiMonitor()  # v4: everything the app sends out over MIDI
        self.midi_outputs: Any = None  # midi.outputs.MidiOutputs when the rig lists midi_outputs
        self.router = MidiRouter(self.engine, files.midimap, self.monitor, self.ctl, files.inputs)
        self.router.busk = self.busk  # MIDI / OSC action `busk`
        self.router.input_listeners.append(self._input_hit)  # step scenes waiting on an input (v3.2)
        self.router.flash_fx = self.flash_fx_input  # MIDI / OSC action flash_fx (v3.3)
        from .drums import BUS
        from .fxbanks import Pick

        self.bus = BUS  # named input hits by role: drum-reactive effects, autopilot energy
        self.ride_pick = Pick()  # what the Ride page shows / last played (v3.3)
        from .autopilot import Autopilot
        from .classify import auto_rig

        self.autopilot = Autopilot(
            play=lambda pick, fade: self.ride_play(pick.to_dict(), fade, by="autopilot"),
            rig_auto=lambda: auto_rig(self.engine.rig),
            palettes=lambda: self.files.palettes.sets,
            quality=self.quality, bus=self.bus, cfg=files.rig.autopilot, log_dir=log_dir,
            master_off=lambda: self.engine.rig.profile.master_gate and not self.engine.master,
            flash=lambda kind: self.flash_fx(kind, True, "show", length_ms=500),
            ratings=self.look_ratings, presets=self.preset_picks, playing=lambda: self.ride_pick)
        self.router.ride = self.ride_action
        from .darkness import Darkness

        self.darkness = Darkness(self.engine.clock, lambda: self.autopilot.st.mood)  # v6
        self.darkness.configure(files.rig.autopilot)
        self.ctl.on_manual = self._manual_pick
        self.ctl.on_setlist = self._setlist_walk
        self.ctl.on_song_auto = self._song_auto
        self.gig_lock = False
        self.cycle: Any = None  # v5 break-method cycle test (dmxcheck.MethodCycle)
        self.output_health: dict[int, dict[str, Any]] = {}  # v5: FTDI / port checks per Open DMX output
        self._health_wake = threading.Event()
        self._health_thread: threading.Thread | None = None
        self.health_probe: Any = None  # tests: a fake output.ftdi.Probe
        self._faultfind: Any = None  # v5 fault-find wizard (faultfind.FaultFinder)
        from collections import deque as _deque

        self.kit_hits: Any = _deque(maxlen=200)  # v6: (wall time, input id, velocity) of kit pad hits
        self.kit_learning: dict[str, Any] | None = None  # v6: {kit, piece, zone, armed, result}
        self.project: Any = None  # package.DmsProject when running a .dms show file
        self.on_restart: Any = None  # restart the app on another show file (set by the cli)
        self.store = ShowStore(files.root, self._store_locked)
        self.log_dir = log_dir
        self.alerts: list[dict[str, Any]] = []  # node dropped / weak, newest last
        self.show_problem: dict[str, str] | None = None  # running the last good show files (cli start-up)
        self.files_rev = 0  # up after every reload (edit, undo, restore, rig switch): open screens fetch again
        self.osc: Any = None  # osc.OscServer, when the rig turns OSC on
        self.osc_error: str | None = None
        self.midi_inputs: Any = None  # MidiInputs when running live
        self.registry: Any = None  # devices.DeviceRegistry when running live (v4: devices by USB identity)
        self.clients: dict[str, dict[str, Any]] = {}  # e.g. "claude": {first, last, calls, last_call}
        self.screens: dict[int, dict[str, Any]] = {}  # open browser streams: id -> {ip, local, since}
        self._fps = (time.monotonic(), 0, 0.0)  # (window start, frames at start, last rate)
        self._lock = threading.RLock()
        self.started = time.time()
        self.node_setup: dict[str, Any] = {}  # last node set-up: when, firmware, what was pushed, problems
        for d in drivers:
            if isinstance(d, NodeSerialDriver):
                d.link.health.expect(files.rig.nodes)
                d.link.health.listeners.append(self._health_event)
                d.on_connect = self.setup_node
                if d.link.node_fw is not None:  # it announced itself before the app was built
                    d._connected()
        self._load_lock_state(state_path)
        self._loaded_sig = self._rig_sig()
        # alerts and banners (v3.1): mutes kept in app data per rig config, changes logged
        alerts_file = state_path.with_name("alerts.json") if state_path else None
        self.alert_center = AlertCenter(alerts_file, log_dir, rig=rig)

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
                unis = [u for u in (sorted(set(self.engine.rig.universes)) or [0]) if d.carries(u)]
                out.append({"mac": None, "name": d.name, "state": "connected", "driver": d.status(), "universes": unis})
        return out

    # ------------------------------------------------------------------ 0.05 node set-up (R8)

    MIN_NODE_FW = (0, 2, 0)

    def fallback_frames(self) -> dict[int, bytes]:
        """What each universe shows if the laptop goes away: the static look, MASTER on, full
        masters, no haze, run through the rules like any frame."""
        from .faders import Masters
        from .rules import ControlState, RuleLayer

        rig = self.engine.rig
        frames = RuleLayer(rig).render(self.files.look, ControlState(True, False, {}, 0.0), Masters(1.0, {}, 1.0, 0.0))
        return {u: bytes(f) for u, f in frames.items()}

    def setup_node(self, driver: Any) -> dict[str, Any]:
        """A node connected or restarted: store the fallback looks, move it to the rig's radio
        channel, and note anything to fix (old firmware, development pairing key)."""
        from .node import protocol as p

        link = driver.link
        out: dict[str, Any] = {"at": time.time(), "fw": ".".join(map(str, link.node_fw or ())), "fallbacks": {},
                               "problems": []}
        if link.node_fw is not None and tuple(link.node_fw) < self.MIN_NODE_FW:
            out["problems"].append(f"node firmware {out['fw']} is older than this app expects "
                                   f"({'.'.join(map(str, self.MIN_NODE_FW))}): update it (firmware/README.md)")
        own = next((r.heartbeat.universe for r in link.health.records()
                    if r.heartbeat and r.heartbeat.node_type == p.NodeType.DMX_TX), 0) or 0
        frames = self.fallback_frames()
        universes = sorted(frames, key=lambda u: (u != own, u))[:p.MAX_FALLBACKS if link.v11 else 1]
        for u in universes:
            if not link.v11 and u != own:
                continue
            look = p.FallbackLook(hold_ms=2000, period_s=0, level=0, rgb_addr=[], base=frames[u])
            code = link.set_fallback(look, universe=u if link.v11 else None, timeout=2.0)
            out["fallbacks"][u] = code.name.lower() if code is not None else "no answer"
        skipped = [u for u in frames if u not in universes]
        if skipped:
            out["problems"].append(f"universes {skipped} have no fallback look (the node keeps {p.MAX_FALLBACKS})")
        ch = self.engine.rig.radio_channel
        if ch is not None and link.v11:
            code = link.set_channel(ch, timeout=2.0)
            out["channel"] = ch if code == p.AckCode.OK else f"not set ({code.name.lower() if code else 'no answer'})"
        self.node_setup = out
        return out

    def node_problems(self) -> list[str]:
        out = list(self.node_setup.get("problems", []))
        for d in self.engine.drivers:
            if isinstance(d, NodeSerialDriver):
                st = d.link.stats.last_status
                if st is not None and st.dev_key:
                    out.append("node built with the development pairing key: set PAIRING_KEY for the gig")
                if st is not None and st.dmx_failed:
                    out.append("node's DMX output didn't start: check the Unit DMX wiring")
        return out

    def assign_node(self, mac: str, universe: int, name: str) -> dict[str, Any]:
        from .node.protocol import AckCode, parse_mac

        self.require_unlocked("naming nodes")
        code, confirmed = self.node_link().assign_confirmed(parse_mac(mac), universe, name)
        if code != AckCode.OK:
            raise ValueError(f"node answered {code.name if code is not None else 'nothing'}")
        return {"ok": True, "confirmed": confirmed}

    def replace_node(self, old_mac: str, new_mac: str) -> dict[str, Any]:
        """A node or receiver died and a spare is in: give the spare the dead one's name and
        universe, and put its MAC in the rig in place of the old one."""
        self.require_unlocked("replacing a node")
        link = self.node_link()
        recs = {r.mac: r for r in link.health.records()}
        old, new = recs.get(old_mac.upper()), recs.get(new_mac.upper())
        if old is None:
            raise ValueError(f"no node {old_mac}")
        if new is None or new.heartbeat is None:
            raise ValueError(f"{new_mac} isn't heard: switch the spare on first")
        if old.heartbeat and new.heartbeat.node_type != old.heartbeat.node_type:
            raise ValueError("the spare is a different kind of board")
        name = old.name
        if not name:
            raise ValueError("the old node has no name to pass on")
        universe = old.heartbeat.universe if old.heartbeat and old.heartbeat.universe is not None else 0
        result = self.assign_node(new_mac, universe, name)
        rig_name = self.names[0]
        data = self.store.read("rig", rig_name)
        nodes = [n for n in data.get("nodes") or [] if str(n.get("mac", "")).upper() != old_mac.upper()]
        nodes.append({"mac": new_mac.upper(), "name": name})
        data["nodes"] = nodes
        self.store.put("rig", rig_name, data, f"replace node {name}: {old_mac} -> {new_mac}")
        with link.health._lock:
            link.health.nodes.pop(old_mac.upper(), None)
        self.reload()
        return {**result, "name": name, "universe": universe}

    def set_radio_channel(self, channel: int) -> dict[str, Any]:
        from .node.protocol import AckCode

        self.require_unlocked("changing the radio channel")
        link = self.node_link()
        if not link.v11:
            raise ValueError("the node's firmware can't change channel: update it to 0.2")
        rig_name = self.names[0]
        data = self.store.read("rig", rig_name)
        data["radio_channel"] = int(channel)
        self.store.put("rig", rig_name, data, f"radio channel {channel}")  # checked (1-13) like any edit
        self.reload()
        code = link.set_channel(int(channel), timeout=2.0)
        if code != AckCode.OK:
            raise ValueError(f"node answered {code.name if code is not None else 'nothing'}")
        return {"ok": True, "channel": int(channel)}

    def node_driver(self) -> Any:
        for d in self.engine.drivers:
            if isinstance(d, NodeSerialDriver):
                return d
        raise ValueError("no 0.05 node output in this rig")

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

    # ------------------------------------------------------------------ Connect to Claude (Setup page)

    def claude_shows(self) -> Path:
        """What Claude's tools open: the .dms show file when running one, else the show folder."""
        return Path(self.project.dms) if self.project is not None else Path(self.files.root)

    def claude_status(self, fresh: bool = False) -> dict[str, Any]:
        """Each Claude app on this computer and whether it has the 0.05 tools for this show; cached
        30 s (the status bar asks often), fresh after Connect / Disconnect."""
        from . import claude_setup

        now = time.time()
        cached = getattr(self, "_claude_status", None)
        if not fresh and cached is not None and now - cached[0] < 30:
            st = cached[1]
        else:
            st = claude_setup.status(self.claude_shows())
            self._claude_status = (now, st)
        c = self.clients.get("claude")
        return {**st, "last_seen": c["last"] if c else None, "last_call": c["last_call"] if c else None,
                "calls": c["calls"] if c else 0}

    def claude_connect(self, connect: bool = True) -> dict[str, Any]:
        from . import claude_setup

        changed = claude_setup.connect(self.claude_shows()) if connect else claude_setup.disconnect()
        return {"ok": True, "changed": changed, "status": self.claude_status(fresh=True)}

    def engine_fps(self) -> float:
        start, frames0, rate = self._fps
        now = time.monotonic()
        if now - start >= 1.0:
            rate = (self.engine.frames_sent - frames0) / (now - start)
            self._fps = (now, self.engine.frames_sent, rate)
        return rate

    # ------------------------------------------------------------------ devices (v4)

    def devices_view(self) -> dict[str, Any]:
        """Devices plugged in now, what each is used for, configured ones that are missing, new ones."""
        rig = self.engine.rig
        found = self.registry.all() if self.registry is not None else []
        ids = {d["id"] for d in found}
        rows, new = [], []
        for d in found:
            use: dict[str, Any] | None = None
            if d["kind"] == "serial":
                for i, o in enumerate(rig.outputs):
                    if o.get("device") == d["id"] or (not o.get("device") and o.get("port") == d["port"]):
                        use = {"output": i, "universe": o.get("universe"), "driver": o["driver"], "alias": o.get("alias")}
                        break
                if use is None and d.get("driver"):
                    new.append(d)
            elif d["kind"] == "midi_in":
                hit = next((w for w in rig.midi_inputs if w.lower() in d["port"].lower()), None)
                if hit is not None or not rig.midi_inputs:
                    use = {"midi_in": True, "alias": rig.midi_aliases.get(hit or "") or None}
                else:
                    new.append(d)
            else:
                mo = [x for x in rig.midi_outputs if x["device"] == d["id"]]
                if mo:
                    use = {"midi_out": True, "alias": mo[0].get("alias")}
            rows.append({**d, "use": use, "alias": (use or {}).get("alias") or None})
        missing = [{"output": i, "device": o["device"], "alias": o.get("alias"), "label": device_label(o["device"]),
                    "universe": o.get("universe")}
                   for i, o in enumerate(rig.outputs) if o.get("device") and o["device"] not in ids]
        missing += [{"midi_out": True, "device": o["device"], "alias": o.get("alias"), "label": device_label(o["device"])}
                    for o in rig.midi_outputs if o["device"] not in ids]
        ports_in = [d["port"].lower() for d in found if d["kind"] == "midi_in"]
        missing += [{"midi_in": True, "device": f"midi-in:{n}", "alias": a, "label": n}
                    for n, a in rig.midi_aliases.items() if not any(n.lower() in p for p in ports_in)]
        return {"devices": rows, "missing": missing if self.registry is not None else [], "new": new,
                "scanning": self.registry is not None}

    def rebuild_outputs(self, outputs: list[dict[str, Any]]) -> list[str]:
        """Swap the DMX outputs for these, live: new drivers open first, then take over between frames,
        then the old ones close. The simulator's outputs (not made from the rig) are left alone."""
        from .cli import resolve_output
        from .output import make_driver

        if any(d.cfg is None for d in self.engine.drivers):
            return ["simulator: outputs aren't rebuilt (no hardware)"]
        new = []
        try:
            for o in outputs:
                new.append(make_driver(resolve_output(o, self.registry) if self.registry is not None else dict(o)))
        except Exception as e:
            for d in new:
                d.close()
            raise ValueError(f"outputs not changed: {e}") from e
        for d in new:
            if isinstance(d, NodeSerialDriver):
                d.link.health.expect(self.engine.rig.nodes)
                d.link.health.listeners.append(self._health_event)
                d.on_connect = self.setup_node
        with self.engine.lock:
            old, self.engine.drivers = self.engine.drivers, new
            self.engine.hint_drivers()
        for d in old:
            try:
                d.close()
            except Exception:  # noqa: BLE001 - an unplugged port may not close cleanly
                log.debug("closing an old output failed", exc_info=True)
        self.engine.output()  # the new outputs get a frame now, not on the next tick
        self.output_health = {}
        self._health_wake.set()
        return [f"outputs rebuilt: {len(new)} live"]

    def replace_device(self, missing: str, use: str) -> dict[str, Any]:
        """Mid-gig recovery: a configured interface has gone (missing), use this plugged-in one instead.
        Same universe, alias and settings; allowed under gig lock (only this change)."""
        rig_name = self.names[0]
        data = self.store.read("rig", rig_name)
        d = self.registry.get(use) if self.registry is not None else None
        if d is None:
            raise ValueError(f"{use} isn't plugged in")
        changed = False
        for o in data.get("outputs") or []:
            if o.get("device") == missing:
                if use.startswith("usb:"):
                    o["device"] = use
                else:  # no serial number: it can only be kept by its port
                    o.pop("device", None)
                o["port"] = d["port"]
                if d.get("driver") in ("usb_dmx_open", "usb_dmx_pro") and o.get("driver") in ("usb_dmx_open", "usb_dmx_pro"):
                    o["driver"] = d["driver"]  # an Open DMX standing in for a Pro (or the other way)
                changed = True
        ins = data.get("midi_inputs") or []
        for i, x in enumerate(ins):
            if isinstance(x, dict) and x.get("device") == missing and use.startswith("midi-in:"):
                ins[i] = {**x, "device": use}
                changed = True
        outs = data.get("midi_outputs") or []
        for x in outs:
            if x.get("device") == missing and use.startswith("midi-out:"):
                x["device"] = use
                changed = True
        if not changed:
            raise ValueError(f"nothing in rig {rig_name} uses {missing}")
        with self.store.recovery():
            bid = self.store.put("rig", rig_name, data, f"use {d['name']} instead of {missing}")
        notes = self.reload()
        return {"backup": bid, "notes": notes}

    def set_device(self, dev_id: str, alias: str | None = None, universe: int | None = None, driver: str | None = None,
                   use: bool = True) -> dict[str, Any]:
        """Name a device and say what it's for: a USB interface sends a universe; a MIDI input is opened
        (role comes from its named inputs); a MIDI output is used for feedback / test sends."""
        rig_name = self.names[0]
        data = self.store.read("rig", rig_name)
        d = self.registry.get(dev_id) if self.registry is not None else None
        if dev_id.startswith(("usb:", "port:")):
            outs = list(data.get("outputs") or [])
            idx = next((i for i, o in enumerate(outs) if o.get("device") == dev_id
                        or (d and not o.get("device") and o.get("port") == d["port"])), None)
            if idx is None:
                if not use:
                    raise ValueError(f"{dev_id} isn't used by an output")
                outs.append({"driver": driver or (d or {}).get("driver") or "usb_dmx_open", "universe": 0})
                idx = len(outs) - 1
            o = dict(outs[idx])
            if dev_id.startswith("usb:"):
                o["device"] = dev_id
            if d:
                o["port"] = d["port"]
            for k, v in (("alias", alias), ("universe", universe), ("driver", driver)):
                if v not in (None, ""):
                    o[k] = v
            if use:
                outs[idx] = o
            else:
                outs.pop(idx)
            data["outputs"] = outs
        elif dev_id.startswith("midi-in:"):
            base = dev_id.split(":", 1)[1]
            ins = [x for x in (data.get("midi_inputs") or []) if not (
                (isinstance(x, dict) and x.get("device") == dev_id) or (isinstance(x, str) and x.lower() == base.lower()))]
            if use:
                ins.append({"device": dev_id, **({"alias": alias} if alias else {})})
            data["midi_inputs"] = ins
        elif dev_id.startswith("midi-out:"):
            outs = [x for x in (data.get("midi_outputs") or []) if x.get("device") != dev_id]
            if use:
                outs.append({"device": dev_id, **({"alias": alias} if alias else {})})
            data["midi_outputs"] = outs
        else:
            raise ValueError("a device id is usb:VID:PID:SERIAL, port:COM3, midi-in:<name> or midi-out:<name>")
        bid = self.store.put("rig", rig_name, data, f"device {alias or dev_id} on rig {rig_name}")
        notes = self.reload()
        return {"backup": bid, "notes": notes}

    # ------------------------------------------------------------------ routing (v4)

    def routing(self) -> dict[str, Any]:
        """Which universe goes out which interface, with live stats from what each one really sent."""
        from .rig import routing_problems

        rig = self.engine.rig
        used = sorted(set(rig.universes)) if rig.fixtures else []
        rows: list[dict[str, Any]] = []
        for i, d in enumerate(self.engine.drivers):
            st = d.state()
            cfg = d.cfg or {}
            for u in used or [0]:
                if not d.carries(u):
                    continue
                w = d.wire.stats(u)
                st_d = d.status()
                kind = "node link" if isinstance(d, NodeSerialDriver) else "wired"
                rows.append({"universe": u, "output": i, "kind": kind,
                             "interface": cfg.get("alias") or st["name"], "driver": cfg.get("driver", d.name),
                             "port": cfg.get("port") or getattr(d, "port", None), "device": cfg.get("device"),
                             "state": st["state"], "detail": st["detail"],
                             "packets": st_d.get("packets", st_d.get("frames")), "errors": st_d.get("errors", 0),
                             "timing": st_d.get("timing"), "checks": self._health_summary(i), **w})
        for n in self.nodes():
            if n.get("mac"):
                rows.append({"universe": n.get("universe"), "output": None, "kind": "node",
                             "interface": n["name"] or n["mac"],
                             "driver": "node", "mac": n["mac"], "state": n["state"], "detail": f"rssi {n.get('rssi')}",
                             "packets": None, "errors": None, "fps": None, "frames": None, "jitter_ms": None,
                             "last_frame_age_ms": n.get("last_data_age_ms"), "all_zero": None})
        return {"universes": used, "rows": rows, "problems": routing_problems(rig)}

    # ------------------------------------------------------------------ haze settings (v4)

    def haze_settings(self, changes: dict[str, Any], save: bool) -> dict[str, Any]:
        """Haze settings panel: `changes` over the running rig's `haze:` block. save=False tries them live
        (not written, reverts on the next reload); save=True writes the rig file. Rule 5 is untouched:
        this edits the haze controller only."""
        from .rig import parse_haze

        rig_name = self.names[0]
        data = self.store.read("rig", rig_name)
        block = {**(data.get("haze") or {}), **(changes or {})}
        cfg = parse_haze(block)  # checked before anything changes
        if save:
            data["haze"] = block
            bid = self.store.put("rig", rig_name, data, f"haze settings for rig {rig_name}")
            self.reload()
            return {"backup": bid, "settings": cfg.to_dict(), "rig": rig_name}
        self.engine.haze_settings(cfg)
        return {"applied": True, "settings": cfg.to_dict(), "rig": rig_name}

    def haze_revert(self) -> dict[str, Any]:
        """Back to the saved haze settings (undo the live tries)."""
        self.engine.haze_settings(self.engine.rig.haze)
        return {"settings": self.engine.rig.haze.to_dict(), "rig": self.names[0]}

    def haze_test(self, mode: str) -> float:
        self.require_unlocked("testing the haze")
        return self.engine.haze_test(mode)

    # ------------------------------------------------------------------ Monitor page (v4)

    def channel_names(self, universe: int) -> dict[int, str]:
        """Channel number (1-512) -> 'bar_2 red px5' for the lights patched on a universe."""
        out: dict[int, str] = {}
        for f in self.engine.rig.patch.fixtures.values():
            if f.universe != universe:
                continue
            for ch in f.type.channels:
                px = f" px{ch.pixel + 1}" if ch.pixel is not None else ""
                out[f.address + ch.offset] = f"{f.id} {ch.role}{px}"
        return out

    def monitor_status(self) -> dict[str, Any]:
        """MIDI ports in and out with their state, hit and clock rates, the autopilot's energy."""
        ins = self.midi_inputs.status() if self.midi_inputs is not None else []
        outs = self.midi_outputs.status() if self.midi_outputs is not None else []
        aliases = self.engine.rig.midi_aliases
        now = self.engine.clock()
        last_in: dict[str, float] = {}
        for e in self.monitor.query(200):
            last_in[e.port] = e.time
        return {"midi_in": [{**m, "alias": aliases.get(m["name"]), "last": last_in.get(m.get("port") or "")} for m in ins],
                "midi_in_sim": self.midi_inputs is None, "midi_out": outs,
                "rates": self.monitor.rates(), "energy": round(self.autopilot.energy.level(now), 3)}

    def monitor_midi(self, direction: str = "in", n: int = 200, since: int = 0, port: str | None = None,
                     channel: int | None = None, kind: str | None = None, unmapped: bool = False) -> list[dict[str, Any]]:
        from dataclasses import asdict

        mon = self.monitor if direction != "out" else self.midi_out_monitor
        return [asdict(e) for e in mon.query(n, port, channel, kind, unmapped, since)]

    def midi_send(self, port: str, kind: str, channel: int, number: int, value: int = 0) -> str:
        self.require_unlocked("a MIDI test send")
        if self.midi_outputs is None:
            raise ValueError("no MIDI outputs are set up (Setup > Plugged in: tick MIDI out on a port)")
        return self.midi_outputs.send(port, kind, channel, number, value)

    def frame_view(self, universe: int, out: str | int | None = None) -> dict[str, Any]:
        """The 512 channels an interface really sent on a universe (Monitor, address map). `out` is an
        output index (default: the first that carries the universe), or "engine" for the engine's own
        frame before the outputs (labelled so). An interface that hasn't sent says so: no values."""
        import base64

        drivers = self.engine.drivers
        if out == "engine":
            f = self.engine.frames.get(universe)
            return {"universe": universe, "out": "engine", "source": "Engine (before outputs)",
                    "frame": base64.b64encode(bytes(f)).decode() if f is not None else None,
                    "no_frames": f is None, "stats": {"frames": self.engine.frames_sent}}
        if out in (None, ""):
            idx = next((i for i, d in enumerate(drivers) if d.carries(universe)), None)
        else:
            idx = int(out)
        if idx is None or not 0 <= idx < len(drivers):
            return {"universe": universe, "out": None, "source": "no output carries this universe", "frame": None,
                    "no_frames": True, "stats": {}}
        d = drivers[idx]
        frame = d.wire.frame(universe) if d.carries(universe) else None
        st = d.state()
        tst = self.engine.test_status()
        testing = tst is not None and tst["universe"] == universe and tst["output"] in (None, idx)
        return {"universe": universe, "out": idx, "test": tst if testing else None,
                "source": (d.cfg or {}).get("alias") or st["name"],
                "carries": d.carries(universe), "frame": base64.b64encode(frame).decode() if frame is not None else None,
                "checks": self._health_summary(idx), "timing": d.status().get("timing"),
                "no_frames": frame is None, "stats": {**d.wire.stats(universe), "errors": d.status().get("errors", 0),
                                                       "state": st["state"], "detail": st["detail"]}}

    def set_output(self, index: int, changes: dict[str, Any]) -> dict[str, Any]:
        """Change (or with index -1 add) one `outputs:` entry of the running rig: driver, port, universe,
        alias, device. Written to the rig file (validated, backed up, gig-locked)."""
        from .rig import parse_outputs

        rig_name = self.names[0]
        data = self.store.read("rig", rig_name)
        outs = list(data.get("outputs") or [])
        if index == -1:
            outs.append({})
            index = len(outs) - 1
        if not 0 <= index < len(outs):
            raise ValueError(f"no output {index}; the rig has {len(outs)} (index from 0, -1 adds one)")
        from .rig import TIMING_KEYS

        bad = set(changes) - {"driver", "port", "universe", "alias", "device", "host", "universes", *TIMING_KEYS}
        if bad:
            raise ValueError(f"an output takes driver, port, universe, alias, device, {', '.join(TIMING_KEYS)} "
                             f"(not {sorted(bad)})")
        outs[index] = {**outs[index], **{k: v for k, v in changes.items() if v is not None}}
        parse_outputs(outs)  # checked before writing
        data["outputs"] = outs
        bid = self.store.put("rig", rig_name, data, f"output {index + 1} on rig {rig_name}")
        notes = self.reload()
        return {"backup": bid, "notes": notes, "outputs": outs}

    # ------------------------------------------------------------------ test patterns (v5)

    def run_test(self, args: dict[str, Any], by: str = "ui") -> dict[str, Any]:
        """Start a test pattern from the Monitor page / Claude. Gig lock allows keep-alive only."""
        from .testpattern import TIMEOUT_S, TestPattern

        pattern = str(args.get("pattern", ""))
        if pattern != "keep_alive":
            self.require_unlocked("a test pattern other than keep-alive")

        def num(k: str, cast: Any = int) -> Any:
            v = args.get(k)
            return None if v in (None, "") else cast(v)

        out = num("output")
        tp = TestPattern(pattern, universe=num("universe") or 0, output=out, fixture=args.get("fixture") or None,
                         channel=num("channel"), value=num("value"), dwell_s=num("dwell_s", float) or 2.0,
                         timeout_s=num("timeout_s", float) or TIMEOUT_S, patched_only=bool(args.get("patched_only")),
                         by=by, extra={"role": args.get("role")} if args.get("role") else {})
        return self.engine.run_test(tp)

    def stop_test(self, why: str = "stopped") -> bool:
        if self.cycle is not None and self.cycle.state == "running":
            self.cycle.stop()
        return self.engine.stop_test(why)

    # cycle test (v5 item 1): break methods in turn, "Lights responded" saves the one that worked

    def start_cycle(self, index: int, by: str = "ui", step_s: float | None = None) -> dict[str, Any]:
        from .dmxcheck import STEP_S, MethodCycle

        self.require_unlocked("the break-method cycle test")
        if self.cycle is not None and self.cycle.state == "running":
            self.cycle.stop()
        self.cycle = MethodCycle(self.engine, index, self.set_output, step_s or STEP_S, by).start()
        return self.cycle.view()

    def cycle_view(self) -> dict[str, Any] | None:
        return self.cycle.view() if self.cycle is not None else None

    def cycle_confirm(self) -> dict[str, Any]:
        if self.cycle is None:
            raise ValueError("no cycle test has run")
        self.require_unlocked("saving a break method")
        return self.cycle.confirm()

    def save_cycle_step(self, index: int, step: int) -> dict[str, Any]:
        """Save step `step` (1-based, as listed by the last cycle on this output) without re-running it."""
        from .dmxcheck import cycle_steps

        drv = dict(self._open_outputs()).get(index)
        if drv is None:
            raise ValueError("not a USB DMX (Open) output")
        steps = self.cycle.steps if self.cycle is not None and self.cycle.index == index else cycle_steps(drv)
        if not 1 <= step <= len(steps):
            raise ValueError(f"step 1-{len(steps)}")
        s = steps[step - 1]
        self.set_output(index, {"break_method": s["break_method"], "break_us": s["break_us"]})
        return {k: s[k] for k in ("step", "label", "break_method", "break_us")}

    # ------------------------------------------------------------------ output health checks (v5 item 2)

    def _open_outputs(self) -> list[tuple[int, Any]]:
        from .output.enttec import EnttecOpenDriver

        return [(i, d) for i, d in enumerate(self.engine.drivers) if isinstance(d, EnttecOpenDriver)]

    def check_outputs(self) -> list[dict[str, Any]]:
        """Run the checklist on every USB DMX (Open) output now (also kept for the status bar)."""
        from .output.ftdi import check_interface

        out: dict[int, dict[str, Any]] = {}
        for i, d in self._open_outputs():
            cfg = d.cfg or {}
            info = None
            if self.registry is not None:
                info = (self.registry.get(cfg["device"]) if cfg.get("device") else None) or next(
                    (x for x in self.registry.all() if x.get("port") == d.port), None)
            r = check_interface(d.port, info, d, self.health_probe)
            r.update({"output": i, "interface": cfg.get("alias") or info and info.get("name") or "USB DMX (Open)",
                      "universe": d.universe, "checked": time.time()})
            out[i] = r
        self.output_health = out
        return [out[i] for i in sorted(out)]

    def start_health_checks(self, every_s: float = 60.0) -> None:
        """Check at start, on hot-plug (device registry), after outputs change, and every minute."""
        if self._health_thread is not None:
            return
        if self.registry is not None:
            self.registry.on_change.append(lambda d, what: self._health_wake.set())

        def run() -> None:
            while True:
                try:
                    self.check_outputs()
                except Exception:  # noqa: BLE001 - a check must never take anything down
                    log.debug("output checks failed", exc_info=True)
                self._health_wake.wait(every_s)
                self._health_wake.clear()
                time.sleep(1.0)  # let a new port settle / the new driver open

        self._health_thread = threading.Thread(target=run, name="output-checks", daemon=True)
        self._health_thread.start()

    def _health_summary(self, index: int) -> dict[str, Any] | None:
        h = self.output_health.get(index)
        if h is None:
            return None
        return {"result": h["result"], "driver_type": h["driver_type"], "latency_ms": h["latency_ms"],
                "d2xx_available": h["d2xx_available"],
                "problems": [f"{c['name']}: {c['detail']}" for c in h["checks"] if c["result"] in ("fail", "warn")]}

    def fault_find(self, action: str, answer: str = "", fixture: str | None = None, by: str = "ui") -> dict[str, Any]:
        """The "Rig not responding" wizard (v5 item 3): start, answer, test, status."""
        from .faultfind import FaultFinder

        if self._faultfind is None:
            self._faultfind = FaultFinder(self)
        ff = self._faultfind
        if action == "start":
            return ff.start(by)
        if action == "answer":
            return ff.answer(answer, fixture)
        if action == "test":
            return {**ff.view(), **ff.run_test()}
        if action == "status":
            return ff.view()
        raise ValueError("fault_find action: start, answer, test or status")

    def set_output_latency(self, index: int, ms: int = 1) -> dict[str, Any]:
        self.require_unlocked("changing the latency timer")
        drv = dict(self._open_outputs()).get(index)
        if drv is None:
            raise ValueError("not a USB DMX (Open) output")
        got = drv.set_latency(ms)
        self._health_wake.set()
        return {"output": index, "latency_ms": got}

    def routing_problems_cached(self) -> list[str]:
        from .rig import routing_problems

        rig = self.engine.rig
        key = (id(rig), repr(rig.outputs), tuple(rig.universes))
        if getattr(self, "_rp_cache", (None,))[0] != key:
            self._rp_cache = (key, routing_problems(rig))
        return self._rp_cache[1]

    def layout_problems(self) -> list[dict[str, Any]]:
        """Overlapping / touching lights on the running rig's layout (worked out once per rig)."""
        from .layout import layout_problems

        rig = self.engine.rig
        key = (id(rig), repr(rig.layout), len(rig.fixtures))  # a reload may change the layout in place
        if getattr(self, "_lp_cache", (None,))[0] != key:
            self._lp_cache = (key, layout_problems(rig))
        return self._lp_cache[1]

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
            st = d.state()
            cfg = d.cfg or {}
            found = self.registry.get(cfg["device"]) if self.registry is not None and cfg.get("device") else None
            if cfg.get("alias") or found:  # the name the band gave it, or what the device says it is
                st["model"] = found["name"] if found else st["name"]
                st["name"] = cfg.get("alias") or (found or {}).get("name") or st["name"]
            unis = [u for u in (sorted(set(self.engine.rig.universes)) or [0]) if d.carries(u)]
            if unis and st.get("state") != "sim":  # which universe(s) it carries, at the front
                st["detail"] = f"U{','.join(map(str, unis))} · {st['detail']}"
            out.append(st)
        for h in list(self.output_health.values()):
            bad = [c for c in h["checks"] if c["result"] in ("fail", "warn")]
            if bad:
                worst = next((c for c in bad if c["result"] == "fail"), bad[0])
                more = f" (+{len(bad) - 1})" if len(bad) > 1 else ""
                out.append({"kind": "dmx_check", "name": f"{h['interface']} checks",
                            "state": "bad" if worst["result"] == "fail" else "warn",
                            "detail": f"{worst['name']}: {worst['detail']}{more}"
                                      + (f". Fix: {worst['fix']}" if worst["fix"] else ""),
                            "output": h["output"]})
        tst = self.engine.test_status()
        if tst is not None:
            where = f"output {tst['output'] + 1}" if tst["output"] is not None else f"U{tst['universe']}"
            out.append({"kind": "test", "name": "TEST", "state": "warn",
                        "detail": f"{tst['name']} on {where}, {tst['left_s']:.0f} s left (Monitor: Stop test)"})
        rp = self.routing_problems_cached()
        if rp:
            more = f" (+{len(rp) - 1})" if len(rp) > 1 else ""
            out.append({"kind": "routing", "name": "Routing", "state": "warn", "detail": rp[0] + more})
        lp = self.layout_problems()
        if lp:
            pairs = ", ".join(f"{p['a']}/{p['b']}" for p in lp[:4]) + (" ..." if len(lp) > 4 else "")
            n_over = sum(1 for p in lp if p["kind"] == "overlap")
            what = f"{n_over} in the same place" if n_over else f"{len(lp)} touching"
            out.append({"kind": "layout", "name": "Layout", "state": "warn", "detail": f"{what}: {pairs} (Layout page)"})
        for msg in self.node_problems():
            out.append({"kind": "node", "name": "0.05 node", "state": "warn", "detail": msg})
        dv = self.devices_view() if self.registry is not None else None
        for m in (dv or {}).get("missing", []):
            out.append({"kind": "device", "name": m["alias"] or m["label"], "state": "warn",
                        "detail": f"missing: {m['alias'] or m['label']} ({m['label']}); Setup > Devices: use another"})
        for n in (dv or {}).get("new", []):
            what = "MIDI device" if n["kind"].startswith("midi") else "USB interface"
            out.append({"kind": "device_new", "name": n["name"], "state": "warn",
                        "detail": f"New {what}: {n['name']}; assign it? (Setup > Devices)"})
        if self.midi_inputs is not None:
            aliases = self.engine.rig.midi_aliases
            for m in self.midi_inputs.status():
                out.append({"kind": "midi", "name": f"MIDI {aliases.get(m['name']) or m['name']}",
                            "state": "ok" if m["connected"] else "bad",
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
            if c is None:
                try:
                    regs = [t["registered"] for t in self.claude_status()["targets"] if t["installed"]]
                except Exception:  # a config we can't read: say "not connected" rather than fail the status bar
                    regs = []
                detail = ("set up: open Claude to use it" if "current" in regs
                          else "not set up: Setup > Connect to Claude")
            else:
                detail = f"last seen {_ago(now - c['last'])} ago"
            out.append({"kind": "claude", "name": "Claude", "state": "idle", "detail": detail})
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
                notes = self._reload()
            except Exception:
                self.names = old
                raise
            self.alert_center.set_rig(name)
            return notes

    def _reload(self) -> list[str]:
        try:
            return self._do_reload()
        finally:  # after the new files are in place, so a screen that sees the new number fetches them
            self.files_rev += 1

    def _do_reload(self) -> list[str]:
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
            if new.rig.osc != old_rig.osc:
                notes.append("OSC changes take effect after a restart")
                new.rig.osc = old_rig.osc
            if new.rig.outputs != old_rig.outputs:  # v4: outputs are rebuilt live (USB interfaces reopen)
                notes += self.rebuild_outputs(new.rig.outputs)
            if new.rig.midi_inputs != old_rig.midi_inputs and self.midi_inputs is not None:
                self.midi_inputs.wanted = [w for w in new.rig.midi_inputs if w]  # its 2 s rescan opens them
            self.engine.swap_rig(new.rig, new.look)
            old_ap = self.autopilot.cfg
            self.autopilot.cfg = new.rig.autopilot
            self.autopilot.energy.cfg = new.rig.autopilot
            if (old_ap.get("timing"), old_ap.get("layers")) != (new.rig.autopilot.get("timing"), new.rig.autopilot.get("layers")):
                self.autopilot.st.layer_next.clear()  # v7: new layer timing starts its clocks from now
            self.darkness.configure(new.rig.autopilot)
            self._loaded_sig = sig
            self.files = new
            self.ctl.files = new
            self.router.map = new.midimap
            self.router.inputs = new.inputs
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
        self.router.inputs = new.inputs
        if self.show_problem:
            notes.append("show files fixed: now running them, not the last good version")
            self.show_problem = None
        return notes

    def capture_step(self, fixtures: list[str]) -> dict[str, Any]:
        """What the chosen lights show now, as a step's `set` (step scene editor: capture)."""
        look = self.engine.look
        try:
            ids = self.engine.rig.patch.resolve(list(fixtures) or ["all"])
        except ConfigError as e:
            raise ValueError(str(e)) from e
        out: dict[str, Any] = {}
        for fid in ids:
            fl = look.fixtures.get(fid)
            fx = self.engine.rig.patch.fixtures[fid]
            if fl is None or fx.kind == Kind.HAZE:
                continue
            d: dict[str, Any] = {}
            if fl.pixels:
                d["pixels"] = [{k: round(v, 4) for k, v in c.items() if v} or "off" for c in fl.pixels]
            elif fl.colour:
                d["colour"] = {k: round(v, 4) for k, v in fl.colour.items() if v} or "off"
            if fl.pan is not None and fl.tilt is not None and not fx.type.colour_only:
                d["position"] = {"pan": round(fl.pan, 5), "tilt": round(fl.tilt, 5)}
            for k in ("gobo", "colour_wheel", "strobe", "prism"):
                v = getattr(fl, k)
                if v is not None:
                    d[k] = int(v)
            for k in ("zoom", "focus", "frost"):
                v = getattr(fl, k)
                if v is not None:
                    d[k] = round(v, 4)
            if d:
                out[fid] = d
        return out

    def _input_hit(self, inp: Any, m: Any, now: float) -> None:
        if "darkness" in inp.roles and m.type in ("control_change", "osc"):  # v6: expression pedal rides darkness
            v = m.level if getattr(m, "level", None) is not None else m.value / 127
            lvl = inp.level(round(v * 127))
            self.darkness.cc = {"input": inp.id, "describe": inp.describe(), "range": list(inp.range)}
            self.darkness.set(lvl, "cc")
            return
        if m.pressed:
            if m.type == "note" and inp.kit:
                self.kit_hits.append((time.time(), inp.id, m.value))
            if m.type == "note" and inp.roles:
                self.bus.add(inp.id, inp.roles, inp.strength(m.value), now)
                # v6: the drums tempo (tap pads, count-in too), with the kit zone's weight / floor / tempo flag
                self.ctl.tempo.hit(inp.roles, m.value, now, inp.tempo_weight, inp.tempo_floor, inp.tempo)
            if m.type == "note" and inp.trigger:
                self._kit_trigger(inp.trigger)
            self.ctl.step_input(inp.id)

    # ------------------------------------------------------------------ FX banks, ride, Flash FX (v3.3)

    def quality(self) -> Any:
        from .quality import Quality, load_rules

        return Quality(load_rules(self.files.root))

    def fx_catalogue(self) -> dict[str, Any]:
        """The FX banks for this rig: every item, whether this rig can run it (rig size scaling),
        how the lights are classified, the palettes and the quality rules."""
        from .classify import auto_rig
        from .colourtheory import hex_of
        from .fxbanks import FLASH_ITEMS, ITEMS, can_run

        ar = auto_rig(self.engine.rig)
        return {"rig": ar.summary(), "items": [{**i.to_json(), "available": can_run(i, ar), "excluded": i.id in ar.excluded_fx}
                                               for i in [*ITEMS, *FLASH_ITEMS]],
                "palettes": {k: {"name": v["name"], "tags": v["tags"], "excluded": k in ar.excluded_palettes,
                                 "swatches": [hex_of(c) for c in v["resolved"]][:6]}
                             for k, v in self.files.palettes.sets.items()},
                "pick": self.ride_pick.to_dict(), "quality": self.quality().r}

    def compose(self, pick: Any, name: str = "Autopilot") -> Any:
        """A pick as a checked scene for the running rig (rules, rig scaling)."""
        from .classify import auto_rig
        from .fxbanks import compose

        pal = self.files.palettes
        sets = pal.sets
        key = pick.palette if pick.palette in sets else next(iter(sets))
        data = compose(pick, auto_rig(self.engine.rig), list(sets[key]["colours"]), name)
        return parse_scene(data, self.files.patch, pal, name), data

    def ride_play(self, pick_data: dict[str, Any], fade_s: float | None = None, by: str = "ride") -> dict[str, Any]:
        """Play a Ride look now: FX + palette + ride settings (the Ride page; the autopilot uses it too)."""
        from .fxbanks import Pick

        pick = Pick.from_dict(pick_data)
        if by == "ride" and self.autopilot.st.on:  # picked by hand on the Ride page: the autopilot carries on from it
            now = self.engine.clock()
            self.autopilot.st.history.append(pick)
            self.autopilot.st.pick = pick
            self.autopilot.st.next_change = now + float(self.autopilot.cfg["moods"][self.autopilot.st.mood])
        sc, data = self.compose(pick)
        if sc.uses_intensity and self.engine.rig.profile.master_gate:
            raise ValueError(f"{sc.name} {INTENSITY_RULE1}")
        fade = (pick.ride.fade * 4.0) if fade_s is None else fade_s
        issues = self.quality().combo_issues(pick, "mid")
        self.ride_pick = pick
        label = " + ".join(x for x in (pick.move, pick.colour, pick.drum) if x) + f" · {pick.palette}"
        prefix = "Autopilot" if by == "autopilot" else "Autopilot look"
        self.darkness.fade = pick.ride.fade  # soft black edges and easing follow the look's fade
        player = ScenePlayer(sc, self.engine.rig, self.engine.clock(), self.ctl.tempo.eff,
                             darkness=self.darkness, edge=pick.ride.fade)  # v6: darkness for Autopilot looks only
        self.ctl.select_ride(f"{prefix}: {label}", player, sc, fade, manual=by != "autopilot")
        return {"ok": True, "playing": label, "issues": issues, "scene": data}

    # ------------------------------------------------------------------ autopilot and Ride controls (v3.4)

    def _manual_pick(self) -> None:
        """The band picked a look, scene or show by hand: the autopilot steps aside."""
        if self.autopilot.st.on:
            self.autopilot.set_on(False, self.engine.clock())

    def _setlist_walk(self, which: str) -> None:
        if self.autopilot.st.on:
            self.autopilot.walk(which, self.engine.clock())

    def look_ratings(self) -> dict[str, int]:
        return dict(getattr(self.files, "ratings", {}) or {})

    def preset_picks(self) -> dict[str, Any]:
        return {k: v["pick"] for k, v in (getattr(self.files, "presets", {}) or {}).items()}

    def _song_auto(self, presets: list[str] | None, mood: str | None) -> None:
        """A setlist song run by the autopilot on some presets only (None: back to any look)."""
        ap, now = self.autopilot, self.engine.clock()
        ap.limit_to(presets)
        if presets is None:
            return
        if mood:
            ap.st.mood, ap.st.mood_manual = mood, True
        if ap.st.on:
            ap.change(now, "preset")
        else:
            ap.set_on(True, now)

    # ------------------------------------------------------------------ presets, ratings, generator (v3.5)

    def generator(self, seed: str | None = None, autopilot: bool = False) -> Any:
        from .classify import auto_rig
        from .generator import Context, Generator

        ctx = Context(auto_rig(self.engine.rig), self.files.palettes.sets, self.quality(), self.look_ratings())
        return Generator(ctx, seed if seed is not None else time.strftime("%Y%m%d%H%M%S"), autopilot)

    def play_preset(self, key: str) -> dict[str, Any]:
        pre = (self.files.presets or {}).get(key)
        if pre is None:
            raise ValueError(f"no preset {key!r}")
        return self.ride_play(pre["pick"])

    def save_preset(self, key: str, name: str | None = None, tags: list[str] | None = None,
                    pick: dict[str, Any] | None = None) -> str:
        """Save a look as a preset (the Ride page's current look when no pick is given)."""
        from .presets import ID

        if not ID.match(key):
            raise ValueError("preset names use lower case letters, digits, _ or -")
        data = self.store.read("presets")
        presets = data.setdefault("presets", {}) or {}
        data["presets"] = presets
        presets[key] = {"name": name or key.replace("_", " ").capitalize(), "tags": list(tags or []),
                        "pick": pick if pick is not None else self._clean_pick(self.ride_pick.to_dict())}
        bid = self.store.put("presets", "", data, f"preset {key}")
        self.reload()
        return bid

    def delete_preset(self, key: str) -> str:
        from .presets import STARTERS

        data = self.store.read("presets")
        if key not in (data.get("presets") or {}):
            raise ValueError(f"{key} is a starter preset" if key in STARTERS else f"no preset {key!r}")
        used = [u for u in self.store._files_using(lambda d: _uses_preset(d, key))]
        if used:
            raise ValueError(f"preset {key} is still used: {', '.join(used)}")
        del data["presets"][key]
        bid = self.store.put("presets", "", data, f"delete preset {key}")
        self.reload()
        return bid

    @staticmethod
    def _clean_pick(d: dict[str, Any]) -> dict[str, Any]:
        defaults = {"speed": 1.0, "fade": 0.5, "fan": 0.5, "size": 0.5, "shift": 0.0}
        from .fxbanks import norm_pick

        d = norm_pick(d)
        out = {k: v for k, v in d.items() if v not in (None, {}, "")}
        out["feel"] = {k: v for k, v in d.get("feel", {}).items() if defaults.get(k) != v}
        if not out["feel"]:
            out.pop("feel")
        return out

    def rate_look(self, pick: dict[str, Any] | str, value: int) -> str:
        """Thumbs up (1), down (-1), ban (-2) or clear (0) a look (look review page)."""
        from .presets import look_key

        if value not in (1, -1, -2, 0):
            raise ValueError("rating is 1 (liked), -1 (disliked), -2 (banned) or 0 (clear)")
        key = pick if isinstance(pick, str) else look_key(pick)
        data = self.store.read("ratings")
        looks = data.setdefault("looks", {}) or {}
        data["looks"] = looks
        if value == 0:
            looks.pop(key, None)
        else:
            looks[key] = value
        bid = self.store.put("ratings", "", data, f"rate {key}: {value}")
        self.reload()
        return bid

    def review_looks(self, mood: str | None = None, bank: str | None = None, palette: str | None = None,
                     offset: int = 0, limit: int = 40) -> dict[str, Any]:
        """Every look the rig can do (or a filtered subset), in a fixed order, with its rating."""
        from .classify import auto_rig
        from .fxbanks import available

        ar = auto_rig(self.engine.rig)
        moves: list[str | None] = [None, *[i.id for i in available(ar, "move", mood)]]
        colours = [i.id for i in available(ar, "colour", mood)]
        pals = [palette] if palette else list(self.files.palettes.sets)
        if bank == "move":
            colours = ["static"]
        elif bank == "colour":
            moves = [None]
        looks = [{"move": m, "colour": c, "palette": p} for p in pals for c in colours for m in moves]
        ratings = self.look_ratings()
        from .presets import look_key

        rows = [{**lk, "key": look_key(lk), "rating": ratings.get(look_key(lk), 0)} for lk in looks]
        return {"total": len(rows), "offset": offset, "looks": rows[offset:offset + limit]}

    def capture_look(self, key: str, name: str | None = None) -> str:
        """"Save this look": what's showing now as a scene (a Ride / autopilot look as its layers,
        anything else as a still of every light), ready to edit in the scene builder."""
        from .store import NAME

        if not NAME.match(key):
            raise ValueError("scene names use lower case letters, digits, _ or -")
        if self.ctl.mode == "ride":
            pick = self.autopilot.st.pick if self.autopilot.st.on and self.autopilot.st.pick else self.ride_pick
            gen = self.generator("capture")
            data = gen.scene(pick, name or key.replace("_", " ").capitalize(), self.autopilot.st.mood, None)
            data["generated"]["seed"] = "capture"
        else:
            still = self.capture_step(["all"])
            data = {"name": name or key.replace("_", " ").capitalize(),
                    "layers": ([{"fixtures": [fid], **attrs} for fid, attrs in still.items()]
                               or [{"fixtures": ["all"], "colour": "off"}]),
                    "generated": {"seed": "capture", "from": self.ctl.describe()}}
        bid = self.store.put("scene", key, data, f"capture look as scene {key}")
        self.reload()
        return bid

    def generate(self, kind: str, b: dict[str, Any]) -> dict[str, Any]:
        """Write generated scenes / a show / starter shows for a setlist (validated, backed up)."""
        from .generator import PLAN_DEFAULT, slug, song_plan
        from .versions import stamped

        gen = self.generator(str(b.get("seed") or "") or None)
        changes: dict[Any, str | None] = {}
        made: dict[str, list[str]] = {"scenes": [], "shows": []}

        def add(kind_: str, k: str, data: dict[str, Any]) -> None:
            p = self.store.path(kind_, k)
            if p.exists() and not b.get("overwrite"):
                raise ValueError(f"{p.relative_to(self.files.root).as_posix()} already exists (generate again with overwrite)")
            changes[p] = self.store.text_for(p, stamped(data))
            made["scenes" if kind_ == "scene" else "shows"].append(k)

        if kind == "scenes":
            for k, data in gen.scenes(str(b.get("mood", "mid")), b.get("style"), b.get("palette"), int(b.get("count", 4)),
                                      str(b.get("prefix") or f"gen_{gen.seed}")).items():
                add("scene", k, data)
        elif kind == "show":
            plan = [(str(x["section"]), str(x["mood"]), int(x.get("length", 1))) for x in b.get("plan") or []] or PLAN_DEFAULT
            show, scenes = gen.show(str(b.get("name") or "Generated show"), plan, b.get("style"), b.get("palette"),
                                    float(b.get("hold_s", 30)))
            for k, data in scenes.items():
                add("scene", k, data)
            add("show", slug(str(b.get("name") or "generated_show")), show)
        elif kind == "setlist":
            key = str(b.get("setlist") or "")
            if key not in self.files.setlists:
                raise ValueError(f"no setlist {key!r}")
            for song in self.files.setlists[key].songs:
                plan, hold = song_plan(song.mood, song.bpm)
                show, scenes = gen.show(song.name, plan, b.get("style"), b.get("palette"), hold)
                for k, data in scenes.items():
                    add("scene", k, data)
                add("show", slug(song.name, "song"), show)
        else:
            raise ValueError("generate scenes, show or setlist")
        bid = self.store.apply(changes, f"generate {kind}: {', '.join(made['shows'] or made['scenes'])}")
        self.reload()
        return {"ok": True, "backup": bid, "seed": gen.seed, **made}

    def reroll(self, locks: list[str], mood: str | None = None, seed: str | None = None) -> dict[str, Any]:
        """Lock and re-roll on the Ride page: keep the locked parts of the current look, new rest."""
        gen = self.generator(seed, autopilot=True)
        p = gen.reroll(self.ride_pick, tuple(locks), mood or self.autopilot.st.mood)
        return self.ride_play(p.to_dict())

    def more_like_this(self, n: int = 4, seed: str | None = None) -> list[dict[str, Any]]:
        return [p.to_dict() for p in self.generator(seed, autopilot=True).more_like(self.ride_pick, n)]

    def exclude_fx(self, item: str, excluded: bool) -> dict[str, Any]:
        """Leave an FX type out of the autopilot's picks (or put it back), saved in the rig file. It can
        still be played by hand. Allowed under gig lock (a type misbehaving mid-gig), like "Use this instead"."""
        from .fxbanks import BY_ID

        it = BY_ID.get(item)
        if it is None or it.bank == "flash":
            raise ValueError(f"no autopilot FX type {item!r}")
        return self._auto_exclude("exclude_fx", item, it.label, excluded)

    def exclude_palette(self, palette: str, excluded: bool) -> dict[str, Any]:
        """v7 palette bank: leave a palette out of the autopilot's picks (or put it back). A tap still plays it."""
        sets = self.files.palettes.sets
        if palette not in sets:
            raise ValueError(f"no palette {palette!r}")
        return self._auto_exclude("exclude_palettes", palette, f"palette {sets[palette]['name']}", excluded)

    def _auto_exclude(self, key: str, item: str, label: str, excluded: bool) -> dict[str, Any]:
        rig_name = self.names[0]
        data = self.store.read("rig", rig_name)
        auto = dict(data.get("auto") or {})
        now = [x for x in auto.get(key) or [] if x != item]
        if excluded:
            now.append(item)
        if now:
            auto[key] = now
        else:
            auto.pop(key, None)
        if auto:
            data["auto"] = auto
        else:
            data.pop("auto", None)
        verb = "leave out" if excluded else "put back"
        with self.store.recovery():  # mid-gig: like "Use this instead", allowed under gig lock
            bid = self.store.put("rig", rig_name, data, f"autopilot: {verb} {label} on rig {rig_name}")
        self.reload()
        return {"ok": True, "backup": bid, "excluded": now}

    def priority(self) -> dict[str, Any]:
        """Live control priority, highest first, and which level is in charge now."""
        e = self.engine
        levels = [("blackout", e.blackout), ("drum_flash", e.rig.profile.master_gate and not e.master),
                  ("flash_override", bool(e.held())), ("hold", self.autopilot.st.hold), ("autopilot", self.autopilot.st.on)]
        top = next((k for k, on in levels if on), "show")
        return {"levels": [k for k, on in levels if on], "top": top}

    # ------------------------------------------------------------------ drum kits (v6 Part C)

    def _kit_trigger(self, trig: dict[str, str]) -> None:
        """A drummer trigger pad: its scene / preset / Flash FX, separate from the FCB1010."""
        try:
            if "scene" in trig:
                self.ctl.select_scene(trig["scene"])
            elif "preset" in trig:
                self.play_preset(trig["preset"])
            elif "flash_fx" in trig:
                self.flash_fx(trig["flash_fx"], True, "show", length_ms=500)
        except Exception as e:  # noqa: BLE001 - a bad trigger must never stop the show
            log.warning("kit trigger %s failed: %s", trig, e)

    def _kits_now(self) -> tuple[dict[str, Any], str | None, bool]:
        """(kits by id, active id, derived) - a show without kits gets band_kit as a view of its drum inputs."""
        from .kits import derive_kit

        ins = self.files.inputs
        if ins.kits:
            return ins.kits, ins.active_kit, False
        flashes = {m.input: {k: v for k, v in m.params.items() if k in ("fixtures", "colour", "length_ms", "min_level")}
                   for m in self.files.midimap.mappings if m.type == "input" and m.action == "flash" and m.input}
        kit = derive_kit(self.store.read("inputs"), flashes)
        return ({kit.id: kit} if kit else {}), (kit.id if kit else None), True

    def kit_view(self) -> dict[str, Any]:
        from .kits import KIT_ROLES

        kits, active, derived = self._kits_now()
        now = time.time()
        live = {}
        for t_, iid, vel in list(self.kit_hits):
            if now - t_ < 2.0:
                live[iid] = {"age_ms": round((now - t_) * 1000), "velocity": vel}
        kit = kits.get(active or "")
        ch = kit.channel if kit else 0
        known = {n for k in ([kit] if kit else []) for _, z in k.zones() for n in z.notes}
        unmapped: dict[int, dict[str, Any]] = {}
        for e in self.monitor.query(300):
            if e.type in ("note", "note_on") and e.value > 0 and (ch in (0, e.channel)) and e.result == "unmapped" \
                    and e.number not in known and now - e.time < 60:
                unmapped[e.number] = {"note": e.number, "name": e.note, "velocity": e.value, "age_s": round(now - e.time, 1)}
        return {"active": active, "derived": derived, "kits": {k: v.to_dict() for k, v in kits.items()},
                "live": live, "unmapped": sorted(unmapped.values(), key=lambda x: x["age_s"]),
                "learning": self.kit_learning, "roles": list(KIT_ROLES)}

    def save_kit(self, kid: str, data: dict[str, Any], activate: bool = False, note: str = "") -> dict[str, Any]:
        """Write a kit. The first kit save of a show turns the drum-input view into a real kit (migration):
        drum inputs move into it, their flash mappings leave the MIDI map, both files backed up first."""
        from .kits import migrate, parse_kit

        kit = parse_kit(kid, data)
        ins = self.store.read("inputs")
        midi = self.names[2]
        if not ins.get("kits"):  # first time: migrate (store.apply backs up inputs.yaml and the MIDI map)
            mp = self.store.read("midi", midi)
            kits, _, _ = self._kits_now()
            view = kits.get("band_kit")
            if view is not None and view.id != kid:  # the show's drum inputs become band_kit (active), then this
                new_ins, new_mp = migrate(ins, mp, view)
                new_ins["kits"][kid] = kit.to_dict()
                if activate:
                    new_ins["active_kit"] = kid
            else:  # the kit carries its own flash targets (the view filled them in); the view's inputs go too
                new_ins, new_mp = migrate(ins, mp, kit, also=view)
            if activate or not ins.get("active_kit"):
                new_ins["active_kit"] = kid
            pi, pm = self.store.path("inputs", ""), self.store.path("midi", midi)
            bid = self.store.apply({pi: self.store.text_for(pi, new_ins), pm: self.store.text_for(pm, new_mp)},
                                   note or f"drum kit {kid} (from the drum inputs; MIDI map backed up)")
        else:
            ins["kits"] = {**ins["kits"], kid: kit.to_dict()}
            if activate:
                ins["active_kit"] = kid
            bid = self.store.put("inputs", "", ins, note or f"drum kit {kid}")
        notes = self.reload()
        return {"backup": bid, "notes": notes, **self.kit_view()}

    def _kit_data(self, kid: str) -> dict[str, Any]:
        kits, _, _ = self._kits_now()
        if kid not in kits:
            raise ValueError(f"no kit {kid!r} (have {', '.join(kits) or 'none'})")
        return kits[kid].to_dict()

    def set_kit_piece(self, kid: str, piece: str, zone: str = "head", changes: dict[str, Any] | None = None,
                      remove: bool = False) -> dict[str, Any]:
        """Add / change / remove one piece's zone (notes, role, weight, velocity_floor, tempo, flash, trigger,
        name; piece_name renames the piece). remove with zone "" removes the whole piece."""
        data = self._kit_data(kid)
        pieces = data.setdefault("pieces", {})
        ch = dict(changes or {})
        if remove:
            if piece not in pieces:
                raise ValueError(f"no piece {piece!r}")
            if zone:
                pieces[piece]["zones"].pop(zone, None)
                if not pieces[piece]["zones"]:
                    del pieces[piece]
            else:
                del pieces[piece]
            return self.save_kit(kid, data, note=f"drum kit {kid}: remove {piece}{'/' + zone if zone else ''}")
        p = pieces.setdefault(piece, {"name": ch.get("piece_name") or piece.replace("_", " ").title(), "zones": {}})
        if ch.get("piece_name"):
            p["name"] = ch.pop("piece_name")
        ch.pop("piece_name", None)
        z = dict(p["zones"].get(zone) or {"notes": [], "role": "trigger_only"})
        for k, v in ch.items():
            if v is None or v == "":
                z.pop(k, None)
            else:
                z[k] = v
        p["zones"][zone] = z
        return self.save_kit(kid, data, note=f"drum kit {kid}: {piece}/{zone}")

    def set_active_kit(self, kid: str) -> dict[str, Any]:
        kits, _, derived = self._kits_now()
        if kid not in kits:
            raise ValueError(f"no kit {kid!r}")
        if derived:
            return self.save_kit(kid, kits[kid].to_dict(), activate=True)
        ins = self.store.read("inputs")
        ins["active_kit"] = kid
        bid = self.store.put("inputs", "", ins, f"active drum kit {kid}")
        notes = self.reload()
        return {"backup": bid, "notes": notes, **self.kit_view()}

    def new_kit(self, kid: str, template: str = "gm") -> dict[str, Any]:
        from .kits import ID, gm_kit

        if not ID.match(kid):
            raise ValueError("kit ids use lower case letters, digits, _ or -")
        kits, _, _ = self._kits_now()
        if kid in kits:
            raise ValueError(f"there's already a kit {kid!r}")
        if template != "gm":
            raise ValueError("template: gm (General MIDI)")
        return self.save_kit(kid, gm_kit(kid).to_dict())

    def export_kit(self, kid: str) -> str:
        from .yamlio import plain_dump

        return plain_dump({"kit": kid, **self._kit_data(kid)})

    def import_kit(self, text: str, kid: str | None = None, activate: bool = False) -> dict[str, Any]:
        import yaml as _yaml

        try:
            d = _yaml.safe_load(text)
        except _yaml.YAMLError as e:
            raise ValueError(f"not valid YAML: {e}") from e
        if not isinstance(d, dict):
            raise ValueError("a kit is a mapping: kit, name, channel, pieces")
        kid = kid or str(d.pop("kit", "") or "imported_kit")
        d.pop("kit", None)
        return self.save_kit(kid, d, activate, note=f"import drum kit {kid}")

    def kit_learn(self, kid: str, piece: str, zone: str = "head", add: bool = False) -> dict[str, Any]:
        """Arm learn: the next pad hit becomes this piece's zone note (add=True adds a note)."""
        self.require_unlocked("drum kit learn")
        self._kit_data(kid)
        self.kit_learning = {"kit": kid, "piece": piece, "zone": zone, "armed": True, "result": None}
        state = self.kit_learning

        def learned(msg: dict[str, Any]) -> None:
            if msg.get("type") != "note":
                state.update(armed=False, result="that wasn't a note: arm it again and hit the pad")
                return
            try:
                data = self._kit_data(kid)
                p = data.setdefault("pieces", {}).setdefault(piece, {"name": piece.replace("_", " ").title(), "zones": {}})
                z = dict(p["zones"].get(zone) or {"role": "trigger_only"})
                z["notes"] = list(dict.fromkeys([*(z.get("notes") or [] if add else []), msg["number"]]))
                p["zones"][zone] = z
                # the same note in another zone of this kit moves here
                for opid, op in data["pieces"].items():
                    for ozid, oz in op["zones"].items():
                        if (opid, ozid) != (piece, zone) and msg["number"] in (oz.get("notes") or []):
                            oz["notes"] = [n for n in oz["notes"] if n != msg["number"]]
                with self.store.acting("ui"):
                    self.save_kit(kid, data, note=f"learn {kid} {piece}/{zone}: note {msg['number']}")
                state.update(armed=False, result=f"note {msg['number']} (ch {msg['channel']})")
            except Exception as e:  # noqa: BLE001 - say so on the page
                state.update(armed=False, result=f"not saved: {e}")

        self.router.learn_input(f"kit {kid} {piece}/{zone}", learned)
        return dict(state)

    # ------------------------------------------------------------------ tempo from the drums (v6 Part B)

    def tempo_view(self, debug: bool = False) -> dict[str, Any]:
        tc, now = self.ctl.tempo, self.engine.clock()
        out: dict[str, Any] = {"status": tc.status(now), "params": tc.config.beat.to_dict()}
        if debug:
            out["debug"] = tc.tracker.debug(now)
        return out

    def _save_tempo(self, block: dict[str, Any], what: str) -> str:
        rig_name = self.names[0]
        data = self.store.read("rig", rig_name)
        data["tempo"] = {**(data.get("tempo") or {}), **block}
        bid = self.store.put("rig", rig_name, data, f"tempo: {what} on rig {rig_name}")
        self.reload()
        return bid

    def set_tempo_source(self, source: str, save: bool = False) -> dict[str, Any]:
        """drums / tap / midi_clock / off, live (a live control: allowed under gig lock); save writes the rig."""
        self.ctl.tempo.set_source(source, self.engine.clock())
        out = self.tempo_view()
        if save:
            out["backup"] = self._save_tempo({"source": self.ctl.tempo.source}, f"source {source}")
        return out

    def set_tempo_params(self, changes: dict[str, Any], save: bool = False) -> dict[str, Any]:
        """Tune the drums tracker live (deadband, hold, jump, lock range, window, weights, floor, confidence ...)."""
        p = self.ctl.tempo.set_params(changes or {})
        out = self.tempo_view()
        if save:
            out["backup"] = self._save_tempo({k: getattr(p, k) for k in (changes or {})}, "tracker settings")
        return out

    # ------------------------------------------------------------------ Autopilot darkness (v6)

    def set_darkness(self, value: float, source: str = "slider") -> dict[str, Any]:
        """Live darkness 0-100 %: eased in over the look's fade; holds until the next set (mood) change.
        A performance control, so allowed under gig lock."""
        v = float(value)
        if not 0 <= v <= 100:
            raise ValueError("darkness 0-100 (%)")
        self.darkness.set(v / 100, source)
        return self.darkness.status()

    def set_set_darkness(self, which: str, value: float | None) -> dict[str, Any]:
        """A set's stored darkness (LOW / MID / HIGH), loaded on that set; None clears it. Saved to the rig."""
        from .autopilot import MOODS

        which = str(which).lower()
        if which not in MOODS:
            raise ValueError("set is low, mid or high")
        if value is not None and not 0 <= float(value) <= 100:
            raise ValueError("darkness 0-100 (%)")
        rig_name = self.names[0]
        data = self.store.read("rig", rig_name)
        ap = dict(data.get("autopilot") or {})
        sd = dict(ap.get("set_darkness") or {})
        if value is None:
            sd.pop(which, None)
        else:
            sd[which] = round(float(value), 1)
        ap["set_darkness"] = sd
        data["autopilot"] = ap
        bid = self.store.put("rig", rig_name, data, f"autopilot: {which} darkness on rig {rig_name}")
        self.reload()
        return {"backup": bid, **self.darkness.status()}

    def save_autopilot(self, changes: dict[str, Any]) -> dict[str, Any]:
        """v7: Autopilot page settings (layer timing, between songs, darkness) merged into the running rig's
        `autopilot:` block, checked, backed up (the store's gig lock applies)."""
        from .autopilot import merge_settings
        from .fixtures import ConfigError

        if not isinstance(changes, dict) or not changes:
            raise ValueError("no autopilot settings given")
        rig_name = self.names[0]
        data = self.store.read("rig", rig_name)
        try:
            data["autopilot"] = merge_settings(data.get("autopilot"), changes)
        except ConfigError as e:
            raise ValueError(str(e)) from e
        bid = self.store.put("rig", rig_name, data, f"autopilot settings ({', '.join(changes)}) on rig {rig_name}")
        self.reload()
        return {"backup": bid, "config": self.autopilot.cfg}

    def ride_action(self, action: str, p: dict[str, Any], level: float | None = None) -> str:
        """Autopilot page controls (v3 Ride page), from the page, MIDI or OSC."""
        from .fxbanks import BY_ID, RANGES

        now = self.engine.clock()
        ap = self.autopilot
        if action == "autopilot":
            state = p.get("state", "toggle")
            on = (not ap.st.on) if state == "toggle" else state == "on"
            ap.set_on(on, now)
            return f"autopilot {'on' if on else 'off'}"
        if action == "hold":
            on = not ap.st.hold if p.get("on") is None else bool(p["on"])
            ap.set_hold(on)
            return f"hold {'on' if on else 'off'}"
        if action == "look_next":
            if ap.st.on:
                ap.next(now)
                return "next look"
            return "look_next: autopilot is off"
        if action == "look_prev":
            ap.previous(now)
            return "previous look"
        if action == "mood":
            m = p.get("mood", "auto")
            if m in ("up", "down"):
                return f"mood {ap.mood_step(1 if m == 'up' else -1, now)}"
            ap.set_mood(None if m == "auto" else m, now)
            return f"mood {m}"
        if action in ("walk_on", "walk_off"):
            ap.walk(action, now)
            return action.replace("_", "-")
        if action == "preset":
            self.play_preset(str(p.get("preset")))
            return f"preset {p.get('preset')}"
        if action == "darkness":  # v6: live, eased; the look carries on (no re-play)
            v = level if level is not None else float(p.get("value", 0)) / 100
            got = self.darkness.set(v, "cc" if level is not None else str(p.get("source") or "slider"))
            return f"darkness {round(got * 100)}%"
        from .midi.map import canonical

        action = canonical(action)  # v3 names (ride_fx, ride_speed ...) still work
        pick = self.ride_pick
        if action == "autopilot_fx":
            bank, item = p.get("bank"), p.get("item")
            if bank not in ("move", "colour", "drum") or (item and item not in BY_ID):
                raise ValueError("autopilot_fx needs bank move/colour/drum and an FX item")
            setattr(pick, bank, item or None)
        elif action == "autopilot_palette":
            if p.get("palette") not in self.files.palettes.sets:
                raise ValueError(f"no palette {p.get('palette')!r}")
            pick.palette = p["palette"]
        elif action == "exclude_palette":  # v7 palette bank (MIDI / API / Claude): saved, no look change
            on = p.get("excluded")
            pal = str(p.get("palette") or "")
            if on is None:  # a pedal press toggles
                from .classify import auto_rig

                on = pal not in auto_rig(self.engine.rig).excluded_palettes
            self.exclude_palette(pal, bool(on))
            return f"palette {pal} {'left out' if on else 'put back'}"
        elif action in ("autopilot_lock", "palette_lock"):  # v7 layer lock (palette_lock: the v3 palette one)
            layer = "palette" if action == "palette_lock" else str(p.get("layer") or "")
            on = self.autopilot.set_lock(layer, None if p.get("on") is None else bool(p["on"]))
            return f"{layer} lock {'on' if on else 'off'}"
        elif action.startswith("feel_") and action[5:] in RANGES:
            key = action[5:]
            lo, hi = RANGES[key]
            bank = p.get("bank")
            v = lo + (hi - lo) * float(level if level is not None else p.get("value", 0.5)) if key != "speed" \
                else 4 ** (2 * float(level if level is not None else p.get("value", 0.5)) - 1)
            if p.get("value") is not None and level is None:
                v = max(lo, min(hi, float(p["value"])))
            target = pick.ride if not bank else pick.bank_ride.setdefault(bank, type(pick.ride)())
            setattr(target, key, v)
        else:
            raise ValueError(f"unknown autopilot action {action!r}")
        self.ride_play(pick.to_dict())
        return f"{action} ok"

    def learn_and_save(self, action: str, params: dict[str, Any] | None = None) -> str:
        """MIDI learn from the Ride page: the next pad or pedal does `action`, and the map is saved."""
        self.require_unlocked("MIDI learn")

        def learned(_m: Any) -> None:
            try:
                with self.store.acting("ui"):
                    self.save_midi_map()
            except Exception as e:  # e.g. gig lock came on meanwhile: the mapping still works until restart
                log.warning("couldn't save the learned mapping: %s", e)

        self.router.learn(action, params or {}, learned)
        return f"hit a pad or press a pedal for {action}"

    def flash_fx(self, kind: str, down: bool = True, colour: Any = None, side: str = "left",
                 length_ms: int | None = None) -> str:
        """Flash FX: held while down (length_ms None), or a timed hit."""
        from . import flashfx

        key = f"flashfx/{kind}"
        if not down:
            if length_ms is None:  # control priority: releasing fades back to the level below
                self.engine.release(key, self.engine.rig.release_fade_s)
            return f"{kind} off"
        lights, left = flashfx.lights_for(self)
        col = None
        if colour not in (None, "show"):
            col = self.files.palettes.colour(colour, "flash_fx colour") if isinstance(colour, str) else colour
        elif colour == "show":
            col = dict(self.engine.look.show_colour)
        now = self.engine.clock()
        length = None if length_ms is None else max(0.02, length_ms / 1000)
        fn = flashfx.make(kind, lights, now, col, length or 0.4, side=side, left=left,
                          frozen=self.engine.look if kind == "freeze" else None)
        self.engine.hold(flashfx.override(key, fn, now, length, 0.0))
        return f"{kind} on"

    def flash_fx_input(self, p: dict[str, Any], pressed: bool, one_shot: bool) -> str:
        """MIDI / OSC flash_fx: a pad or pedal holds it; a program change (no release) is timed."""
        length = p.get("length_ms")
        if one_shot and length is None:
            length = 400
        if not pressed and length is not None:
            return "release"
        return self.flash_fx(str(p["fx"]), pressed, p.get("colour"), str(p.get("side", "left")),
                             None if length is None else int(length))

    # ------------------------------------------------------------------ named inputs (v3)

    def save_midi_map(self) -> str:
        """Save the running MIDI map, with any inputs MIDI learn made, as one checked change."""
        self.require_unlocked("saving the MIDI map")
        from .versions import stamped

        path = self.files.midimap_path
        changes: dict[Any, str | None] = {path: self.store.text_for(path, self.router.map.to_dict())}
        if self.router.new_inputs:
            data = self.store.read("inputs")
            devices = data.setdefault("devices", {}) or {}
            data["devices"] = devices
            for iid in self.router.new_inputs:
                inp = self.router.inputs.get(iid)
                if inp is None:
                    continue
                dev = devices.setdefault(inp.device, {"name": self.router.inputs.devices[inp.device].name, "inputs": {}})
                dev.setdefault("inputs", {})[iid] = inp.to_dict(dev.get("channel"), dev.get("port"))
            ip = self.store.path("inputs", "")
            changes[ip] = self.store.text_for(ip, stamped(data))
        bid = self.store.apply(changes, f"save MIDI map {path.stem}")
        self.router.new_inputs = []
        self.reload()
        return bid

    def learn_input(self, name: str, device: str | None = None, add: bool = False) -> str:
        """Arm input learn: the next message becomes input `name`'s (new inputs go in `device`).
        add=True adds the note to the ones it has (snare head + rim)."""
        self.require_unlocked("MIDI learn")
        from .midi.named import suggest

        def learned(msg: dict[str, Any]) -> None:
            data = self.store.read("inputs")
            devs = data.setdefault("devices", {}) or {}
            data["devices"] = devs
            did = next((d for d, v in devs.items() if name in ((v or {}).get("inputs") or {})), None) or device or "learned"
            dev = devs.setdefault(did, {"name": did.replace("_", " ").title(), "inputs": {}})
            dev.setdefault("inputs", {})
            entry = dict(dev["inputs"].get(name) or {})
            if msg["type"] == "osc":
                entry.update({"type": "osc", "address": msg["address"]})
                for k in ("notes", "number", "numbers", "channel", "port", "velocity"):
                    entry.pop(k, None)
            else:
                same = entry.get("type") == msg["type"]
                entry["type"] = msg["type"]
                entry.pop("address", None)
                if msg["type"] == "note":
                    had = entry.get("notes") if same and add else []
                    entry["notes"] = list(dict.fromkeys([*(had or []), msg["number"]]))
                    entry.pop("number", None)
                else:
                    entry["number"] = msg["number"]
                    entry.pop("notes", None)
                    entry.pop("velocity", None)
                if msg["channel"] != dev.get("channel"):
                    entry["channel"] = msg["channel"]
                else:
                    entry.pop("channel", None)
                if msg.get("port") and dev.get("port") is None and entry.get("port"):
                    entry["port"] = msg["port"]
            if "name" not in entry:
                entry["name"] = suggest(msg["type"], msg["channel"], msg["number"], msg.get("address") or "")[1]
            dev["inputs"][name] = entry
            try:
                with self.store.acting("ui"):
                    self.store.put("inputs", "", data, f"learn input {name}")
                self.reload()
            except Exception as e:  # e.g. the message is already another input's: say so in the monitor
                log.warning("input learn for %s refused: %s", name, e)
                self.learn_error = str(e)

        self.learn_error = ""
        self.router.learn_input(name, learned)
        return f"hit the pad or press the pedal for {name}"

    def calibrate(self, name: str, level: str, action: str = "start") -> dict[str, Any]:
        """Velocity calibration: `start` listens to input `name`; play it at `level` (quiet, normal
        or loud) a few times; `done` stores the median velocity in its curve (inputs.yaml)."""
        import statistics

        if level not in ("quiet", "normal", "loud"):
            raise ValueError("level is quiet, normal or loud")
        inp = self.router.inputs.get(name)
        if inp is None or inp.type != "note":
            raise ValueError(f"{name!r} isn't a note input: only pads and keys have a velocity")
        if action == "start":
            self.require_unlocked("calibration")
            self._cal_hits: list[int] = []

            def hit(i: Any, m: Any, now: float) -> None:
                if i.id == name and m.pressed:
                    self._cal_hits.append(int(m.value))

            self._cal_listener = hit
            self.router.input_listeners.append(hit)
            return {"ok": True, "listening": name, "level": level}
        listener = getattr(self, "_cal_listener", None)
        if listener in self.router.input_listeners:
            self.router.input_listeners.remove(listener)
        hits = list(getattr(self, "_cal_hits", []))
        if action == "cancel":
            return {"ok": True}
        if not hits:
            raise ValueError(f"no hits on {name} heard: play it a few times, then press done")
        value = int(statistics.median(hits))
        data = self.store.read("inputs")
        for dev in (data.get("devices") or {}).values():
            entry = ((dev or {}).get("inputs") or {}).get(name)
            if entry is not None:
                curve = dict(entry.get("curve") or {})
                curve[level] = value
                order = [curve[k] for k in ("quiet", "normal", "loud") if k in curve]
                if order != sorted(order) or len(set(order)) != len(order):
                    raise ValueError(f"{level} came out at velocity {value}, which doesn't sit between the "
                                     f"other levels ({curve}): play it again")
                entry["curve"] = curve
                bid = self.store.put("inputs", "", data, f"calibrate {name} {level}: velocity {value}")
                self.reload()
                return {"ok": True, "velocity": value, "hits": len(hits), "curve": curve, "backup": bid}
        raise ValueError(f"no input {name!r} in inputs.yaml")

    # ------------------------------------------------------------------ colour wheel and palettes (v3)

    def colour_preview(self, colour: Any, fixtures: list[str]) -> dict[str, Any]:
        """What each light can really make of `colour` (colour wheel): the channel values after
        colour mixing, the colour you'd see, and for wheel lights the slot it snaps to."""
        from .colourmix import brightness, mix, nearest_slot
        from .colourtheory import hex_of
        from .look import parse_colour

        c = self.files.palettes.colour(colour, "colour") if isinstance(colour, str) else parse_colour(colour, "colour")
        try:
            fixtures = self.engine.rig.patch.resolve(list(fixtures))  # groups and "all" too
        except ConfigError:
            pass
        want = hex_of({k: min(1.0, c.get(k, 0.0) + c.get("white", 0.0)) for k in ("red", "green", "blue")})
        out = []
        for fid in fixtures:
            fx = self.engine.rig.patch.fixtures.get(fid)
            if fx is None:
                continue
            t = fx.type
            em = t.emitters
            row: dict[str, Any] = {"id": fid, "emitters": sorted(em)}
            if em:
                m = mix(c, t)
                row["channels"] = {k: round(m.get(k, 0.0), 4) for k in em}
                shown = {k: m.get(k, 0.0) for k in ("red", "green", "blue")}
                for k, (r, g, b) in (("white", (1, 1, 1)), ("amber", (1, 0.5, 0))):
                    if k in em:
                        shown = {"red": shown["red"] + r * m.get(k, 0.0), "green": shown["green"] + g * m.get(k, 0.0),
                                 "blue": shown["blue"] + b * m.get(k, 0.0)}
                if not any(x in em for x in ("red", "green", "blue")):
                    level = brightness(m)
                    shown = {"red": level, "green": level, "blue": level}
                row["shown"] = hex_of({k: min(1.0, v) for k, v in shown.items()})
            slot = nearest_slot(c, t) if t.wheel else None
            if slot is not None:
                row["slot"] = next((k for k, v in t.wheel.items() if v is slot), str(slot.value))
                row["shown"] = hex_of(slot.colour or {})
            row["differs"] = row.get("shown", want) != want
            out.append(row)
        return {"colour": want, "fixtures": out}

    def palette_preview(self, key: str, mode: str = "static", seconds: float = 10) -> str:
        """Show a palette on the rig for a few seconds: one colour per light (static) or a chase."""
        pal = self.files.palettes.sets.get(key)
        if pal is None:
            raise ValueError(f"no palette {key!r}")
        lights = [f.id for f in self.engine.rig.fixtures if f.type.emitters and f.kind != Kind.HAZE
                  and f.id not in self.engine.rig.exempt]
        cols = pal["colours"]
        if mode == "chase":
            if len(cols) < 2:
                cols = [cols[0], "off"]
            layers = [{"fixtures": lights, "effect": "colour_chase", "colours": cols, "period_s": 4, "spread": 1, "fade": True}]
        else:
            layers = [{"fixtures": [f], "colour": cols[i % len(cols)]} for i, f in enumerate(lights)]
        return self.preview_scene({"name": f"palette {pal['name']}", "layers": layers}, seconds)

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

    def layout_view(self) -> dict[str, Any]:
        from .layout import layout_view

        return {"rig": self.names[0], **layout_view(self.engine.rig)}

    def set_positions(self, positions: dict[str, Any]) -> str:
        """Set some lights' places ({fid: {x, y, z, rot}}) in this rig's file; the rest stay as they are."""
        from .layout import merge_positions

        rig_name = self.names[0]
        data = self.store.read("rig", rig_name)
        data["layout"] = merge_positions(self.engine.rig, data.get("layout"), positions)
        bid = self.store.put("rig", rig_name, data, f"place {', '.join(sorted(positions))} on rig {rig_name}")
        self.reload()
        return bid

    # ------------------------------------------------------------------ preview

    def preview_scene(self, scene: str | dict, seconds: float = 10, step: int | None = None,
                      play_from: int | None = None, darkness: float | None = None) -> str:
        """Play a scene for a while. step: hold that step (0-based); play_from: run the steps from there."""
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
        first = step if step is not None else (play_from or 0)
        dk = None if darkness is None else max(0.0, min(1.0, float(darkness) / 100))
        self.engine.preview(ScenePlayer(sc, self.engine.rig, self.engine.clock(), self.ctl.tempo.eff,
                                        first_step=first, only_step=step,
                                        darkness=None if dk is None else (lambda now: dk)), seconds, sc)
        msg = f"previewing {sc.name} for {seconds:.0f} s, then back to {self.ctl.describe()}"
        if dk is not None:
            msg += f" (at darkness {round(dk * 100)} %; the live value is unchanged)"
        if self.engine.rig.profile.master_gate and not self.engine.master:
            msg += " (MASTER is off, so the rig stays dark)"
        return msg

    # ------------------------------------------------------------------ busking

    def busk(self, panel_key: str, wid: str, down: bool = True, level: float | None = None) -> str:
        """A busk widget pressed (down), let go, or its fader moved (level 0-1). From the Busk page,
        or MIDI / OSC (action busk)."""
        panel = self.files.panels.get(panel_key)
        if panel is None:
            raise ValueError(f"no Override panel {panel_key!r}")
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
            elif t in ("step_speed", "step_fade"):
                try:
                    self.ctl.step_scene("speed" if t == "step_speed" else "fade",
                                        4 ** (2 * level - 1) if t == "step_speed" else 2 * level)
                except ConfigError:
                    return f"{w.label}: no step scene playing"
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
            st = re.search(r"step (\d+)(?: ([^:]+))?:", str(e))
            return {"ok": False, "error": str(e), "layer": int(m.group(1)) if m and not st else None,
                    "step": int(st.group(1)) - 1 if st else None, "target": st.group(2) if st else None}
        return {"ok": True, "length_s": sc.length, "layers": len(sc.layers), "problems": self._limit_problems(sc)}

    def _limit_problems(self, sc: Any) -> list[dict[str, Any]]:
        """Positions outside the running rig's head limits (rule 8 holds them at the limit, but the
        editor says so against the step)."""
        rig = self.engine.rig
        out: list[dict[str, Any]] = []
        groups = [(None, sc.layers)] + ([(i, st.layers) for i, st in enumerate(sc.steps.steps)] if sc.steps else [])
        for step, layers in groups:
            for ly in layers:
                for fid, (pan, tilt) in (ly.params.get("position") or {}).items():
                    lim = rig.limit(fid)
                    if not (lim.pan[0] - 1e-6 <= pan <= lim.pan[1] + 1e-6 and lim.tilt[0] - 1e-6 <= tilt <= lim.tilt[1] + 1e-6):
                        out.append({"step": step, "fixture": fid,
                                    "message": f"{fid} pan {pan:.0%} tilt {tilt:.0%} is outside its head limits; "
                                               "it's held at the limit (rule 8)"})
        return out

    def step_view(self, data: Any, index: int) -> dict[str, Any]:
        from .steps import track_view

        if isinstance(data, str):
            data = self.store.read("scene", data)
        return track_view(upgrade(data, "scene", "scene"), index, self.files.patch)

    def edit_step(self, op: str, scene: str, b: dict[str, Any]) -> dict[str, Any]:
        """Step tools (Claude, the editor): add, update, move, delete one step of a saved step scene."""
        s = self.store
        raw = b.get("step_ref")
        if op != "add" and not isinstance(raw, (int, str)):
            raise ValueError("which step: its number (1 = first) or name")
        ref: int | str = raw if isinstance(raw, (int, str)) else 0
        if op == "add":
            bid = s.add_step(scene, b.get("step") or {}, b.get("at"))
        elif op == "update":
            bid = s.update_step(scene, ref, b.get("set"), b.get("timing"), bool(b.get("replace")))
        elif op == "move":
            bid = s.move_step(scene, ref, int(b.get("to", 1)))
        elif op == "delete":
            bid = s.delete_step(scene, ref)
        else:
            raise ValueError("op is add, update, move or delete")
        notes = self.reload()
        return {"backup": bid, "notes": notes}

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
            "palettes": {k: {"name": v["name"], "tags": v["tags"], "colours": v["colours"], "builtin": bool(v.get("builtin")),
                             "hex": [hexed(c) for c in v["resolved"]]} for k, v in pal.sets.items()},
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

    def alert_devices(self) -> list[dict[str, Any]]:
        """The status bar's devices plus every 0.05 node and receiver that's offline or weak."""
        out = self.devices()
        for n in self.nodes():
            if n.get("mac") and n["state"] in ("offline", "weak"):
                out.append({"kind": "node", "name": n["name"] or n["mac"], "state": "bad" if n["state"] == "offline" else "warn",
                            "detail": f"{n['name'] or n['mac']} {n['state']}"})
        return out

    def alerts_view(self) -> dict[str, Any]:
        self.alert_center.update(self.alert_devices())
        return self.alert_center.snapshot()

    def snapshot(self) -> dict[str, Any]:
        e, now = self.engine, self.engine.clock()
        hz = e.haze.status(now)
        n = self.ctl.now()
        return {
            "time": time.time(),
            "files_rev": self.files_rev,
            "master": e.master,
            "profile": e.rig.profile.summary(),
            "tempo": self.ctl.tempo.status(e.clock()),
            "override": self._busk_state(),
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
                     "next_pulse_s": hz.next_pulse_in_s, "boost_cooldown_s": hz.boost_cooldown_s,
                     "testing": hz.testing, "preset": hz.preset, "settings": e.haze.cfg.to_dict(),
                     "rig": self.names[0]},
            "now": n.__dict__,
            "describe": self.ctl.describe(),
            "preview_s": e.previewing,
            "test": e.test_status(),
            "setup": {"find": e.find, "channels": [{"universe": u, "channel": c, "value": v}
                                                   for (u, c), v in e.channel_test.items()]},
            "fixtures": self.fixture_view(),
            "nodes": self.nodes(),
            "node_setup": self.node_setup,
            "alerts": self.alerts[-5:],
            "alert_center": self.alerts_view(),
            "autopilot": {**self.autopilot.status(e.clock()), "darkness": self.darkness.status(e.clock())},
            "ride": {"pick": self.ride_pick.to_dict(), "palette_lock": self.autopilot.locked("palette")},
            "priority": self.priority(),
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
            "generated": sorted([f"show:{k}" for k, s in f.shows.items() if s.generated]
                                + [f"scene:{k}" for k, s in f.scenes.items() if s.generated]),
            "setlists": {k: {"name": s.name, "songs": [x.name for x in s.songs]} for k, s in f.setlists.items()},
            "positions": sorted(f.palettes.positions),
            "fixtures": [{"id": fx.id, "kind": fx.kind.value, "type": fx.type.name, "colour_only": fx.type.colour_only,
                          "emitters": sorted(fx.type.emitters),
                          "roles": sorted({c.role for c in fx.type.channels}),
                          "moves": fx.type.has("pan") and not fx.type.colour_only, "pixels": fx.type.pixels,
                          "gobo": fx.type.has("gobo"), "wheel": fx.type.has("colour_wheel"),
                          "pan_range": fx.type.pan_range, "tilt_range": fx.type.tilt_range,
                          "type_key": fx.type.key, "universe": fx.universe, "address": fx.address,
                          "footprint": fx.type.footprint, "groups": list(fx.groups),
                          "channels": [c.role + (f" px{c.pixel + 1}" if c.pixel is not None else "") for c in fx.type.channels]}
                         for fx in self.engine.rig.fixtures],
            "layout": {fid: p.to_dict() | {"shape": p.shape, "cols": p.cols}
                       for fid, p in full_layout(self.engine.rig).items()},
            "layout_problems": self.layout_problems(),
            "head_limits": {f.id: {"pan": list(self.engine.rig.limit(f.id).pan), "tilt": list(self.engine.rig.limit(f.id).tilt)}
                            for f in self.engine.rig.fixtures if f.type.has("pan") and not f.type.colour_only},
            "rig_name": self.names[0],
            "rigs": sorted(p.stem for p in (self.files.root / "rigs").glob("*.yaml")),
            "groups": self.engine.rig.patch.groups(),
            "pixel_groups": {k: {f: sorted(p + 1 for p in px) for f, px in v.items()}
                             for k, v in self.engine.rig.patch.pixel_groups.items()},
            "actions": sorted(ACTIONS),
            "panels": {k: {"name": p.name, "widgets": [{"id": w.id, "type": w.type, "label": w.label, "mode": w.mode,
                                                         "target": w.target, "action": w.action} for w in p.widgets]}
                       for k, p in f.panels.items()},
        }


def _uses_preset(data: Any, key: str) -> int:
    """How many times show-file data names preset `key` (show steps, setlist songs)."""
    if isinstance(data, dict):
        n = 1 if data.get("preset") == key or (isinstance(data.get("presets"), list) and key in data["presets"]) else 0
        return n + sum(_uses_preset(v, key) for v in data.values())
    if isinstance(data, list):
        return sum(_uses_preset(x, key) for x in data)
    return 0



def device_label(dev_id: str) -> str:
    """A device id as words for a 'missing' notice: usb:0403:6001:A1B2 -> FTDI SN A1B2."""
    from .devices import VENDORS

    if dev_id.startswith("usb:"):
        parts = dev_id.split(":")
        try:
            vendor = VENDORS.get(int(parts[1], 16), f"USB {parts[1]}:{parts[2]}")
        except (IndexError, ValueError):
            return dev_id
        return f"{vendor} SN {parts[3]}" if len(parts) > 3 else vendor
    return dev_id.split(":", 1)[-1]

def _ago(seconds: float) -> str:
    s = int(seconds)
    return f"{s} s" if s < 90 else f"{s // 60} min"
