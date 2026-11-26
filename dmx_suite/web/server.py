"""Browser UI + JSON API on the gig laptop. Standard library only, no internet needed.

Security (see access.py):
- The server listens on localhost only, unless phone/LAN access is on (which needs a PIN).
- On this computer the page gets in without a PIN, unless "ask for the PIN here too" is ticked.
- Other devices sign in with the PIN and get a session cookie that times out.
- Every change needs a token in a header: the page's own (per run, or per session), or Claude's.
- Claude's token works only from this computer and only for show edits, preview, haze and nodes,
  so Claude can't turn gig lock off or change access settings.
- The Host header must be localhost or an IP address, which blocks DNS-rebinding pages.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import secrets
import threading
import time
from dataclasses import asdict
from html import escape as html_escape
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .. import qr, settings
from ..access import Access, lan_addresses
from ..access import claude_token as default_claude_token
from ..app import App
from ..fixtures import ConfigError
from ..midi.named import device_profiles, load_device_profile
from ..paths import app_token_file
from ..setup import patch_report
from ..store import LockedError, StoreError
from .feed import HEARTBEAT_S, LiveFeed

log = logging.getLogger(__name__)

STATIC = Path(__file__).parent / "static"
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
         ".json": "application/json; charset=utf-8"}
DEFAULT_PORT = 8505
# what Claude's token may change (everything else is the people at the laptop's call)
MAX_UPLOAD = 20 * 1024 * 1024
CLAUDE_WRITES = ("/api/store", "/api/preview", "/api/layout/positions", "/api/steps/edit", "/api/steps/view",
                 "/api/routing/output", "/api/claude/haze",
                 "/api/haze/settings", "/api/devices/set",
                 "/api/nodes/assign", "/api/validate/scene", "/api/undo/claude", "/api/ride/check",
                 "/api/autopilot/check", "/api/generate")
SESSION_COOKIE = "dmx_session"
FRAMES_S = 0.1  # live frame feed (Monitor, address map): 10 a second


def _same(a: str, b: str) -> bool:
    return bool(a) and bool(b) and secrets.compare_digest(a.encode(), b.encode())


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------------- control commands


def _f(args: dict, key: str) -> float:
    try:
        return float(args[key])
    except (KeyError, TypeError, ValueError) as e:
        raise ApiError(400, f"{key} must be a number") from e


def control(app: App, cmd: str, a: dict[str, Any]) -> Any:
    if cmd == "rig":  # run another rig config, live
        return {"ok": True, "notes": app.switch_rig(str(a.get("name", "")))}
    e, c = app.engine, app.ctl
    if cmd == "master":
        e.toggle_master() if a.get("on") is None else e.set_master(bool(a["on"]))
        c.save()
    elif cmd == "blackout":
        e.toggle_blackout() if a.get("on") is None else e.set_blackout(bool(a["on"]))
    elif cmd == "grand":
        e.set_grand(_f(a, "level"))
    elif cmd == "sub":
        e.set_sub(a.get("kind", ""), _f(a, "level"))
    elif cmd == "flash_level":
        e.set_flash_level(_f(a, "level"))
    elif cmd == "haze":
        act = a.get("action")
        if act in ("off", "stop"):
            e.haze_stop()
        elif act in ("manual", "pulse"):
            e.haze_mode(act)
        elif act == "toggle_manual":
            e.haze_toggle_manual()
        elif act == "boost":
            if not e.haze_boost(True):
                raise ApiError(409, "boost refused (disabled or cooling down)")
        elif act == "release":
            e.haze_boost(False)
        elif act == "preset":
            try:
                e.haze_preset(str(a.get("preset", "")))
            except ValueError as err:
                raise ApiError(400, str(err)) from err
        else:
            raise ApiError(400, "haze action: off, manual, pulse, toggle_manual, boost, release, preset")
    elif cmd == "show":
        c.select_show(a["show"], a.get("set"))
    elif cmd == "set":
        c.select_set(a["set"])
    elif cmd == "scene":
        c.select_scene(a["scene"])
    elif cmd == "look":
        c.select_look()
    elif cmd == "next":
        c.next_step()
    elif cmd == "setlist":
        c.load_setlist(a["setlist"], int(a.get("song", 0)))
    elif cmd == "song":
        which = a.get("song", "next")
        {"next": c.next_song, "prev": c.prev_song}.get(which, lambda: c.go_song(int(which)))()
    elif cmd == "step":
        c.go_step(int(a["step"]))
    elif cmd == "steps":  # step scene playing (v3.2): next, back, go, speed, fade
        v = a.get("value")
        return {"result": c.step_scene(str(a.get("action", "next")), None if v is None else float(v))}
    elif cmd == "scene_step":  # play a step scene from one of its steps
        c.select_scene(a["scene"], int(a.get("step", 0)))
    elif cmd == "speed":
        c.set_speed(float(a["value"]))
    elif cmd in ("override", "busk"):  # Override panels ("busk" before v4)
        v = a.get("value")
        return {"result": app.busk(str(a["panel"]), str(a["widget"]), bool(a.get("down", True)),
                                   None if v is None else float(v))}
    elif cmd == "release_all":
        app.engine.release_all(float(a.get("fade_s", 0.5)))
    elif cmd == "tap":
        return {"bpm": c.tap()}
    elif cmd == "tempo":
        c.set_tempo(None if a.get("bpm") in (None, "off") else float(a["bpm"]))
    elif cmd == "find":
        e.find_fixture(a.get("fixture"))
    elif cmd == "chan":
        v = a.get("value")
        e.test_channel(int(a["channel"]), None if v is None else int(v), int(a.get("universe", 0)))
    elif cmd == "setup_off":
        e.clear_setup()
    elif cmd == "position":
        if a.get("release"):
            e.override_position(a["fixture"])
        else:
            e.override_position(a["fixture"], _f(a, "pan"), _f(a, "tilt"))
    elif cmd == "release_positions":
        for fid in list(e.position_override):
            e.override_position(fid)
    elif cmd == "preview_end":
        e.end_preview()
    elif cmd == "flash_test":  # drum-flash check from the setup page
        e.flash(app.files.patch.resolve(a.get("fixtures", ["all"])), int(a.get("velocity", 127)), a.get("colour", "show"))
    else:
        raise ApiError(400, f"unknown command {cmd!r}")
    return {"ok": True, "describe": c.describe()}


# --------------------------------------------------------------------------- handler


def make_handler(app: App, token: str, access: Access, claude: str, on_lan: Any = None,
                 feed: LiveFeed | None = None, app_token: str = "") -> type[BaseHTTPRequestHandler]:
    live = feed or LiveFeed(app.snapshot)

    class Handler(BaseHTTPRequestHandler):
        server_version = "dmx-suite"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:  # quiet console
            log.debug("%s " + fmt, self.client_address[0], *args)

        # ---------------------------------------------------------------- auth helpers

        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
            if host == "localhost":
                return True
            try:
                ipaddress.ip_address(host)
                return True
            except ValueError:
                return False  # a name we don't know: possible DNS rebinding

        def _local(self) -> bool:
            try:
                return ipaddress.ip_address(self.client_address[0]).is_loopback
            except ValueError:
                return False

        def _sid(self) -> str | None:
            c = SimpleCookie(self.headers.get("Cookie") or "")
            return c[SESSION_COOKIE].value if SESSION_COOKIE in c else None

        def _session(self) -> Any:
            return access.session(self._sid())

        def _is_claude(self) -> bool:
            return self._local() and _same(self.headers.get("X-DMX-Token") or "", claude)

        def _reader(self) -> str | None:
            """Who is reading: "ui", "claude" or nobody signed in."""
            if self._is_claude():
                return "claude"
            if self._local() and not access.pin_local:
                return "ui"
            return "ui" if self._session() else None

        def _writer(self) -> str | None:
            """Who is changing something: the page's token for this computer or session, or Claude's."""
            tok = self.headers.get("X-DMX-Token") or ""
            if self._is_claude():
                return "claude"
            if self._local() and not access.pin_local and _same(tok, token):
                return "ui"
            if self._local() and _same(tok, app_token):  # another copy of the app on this computer
                return "ui"
            s = self._session()
            return "ui" if s is not None and _same(tok, s.csrf) else None

        def _page_token(self) -> str:
            if self._local() and not access.pin_local:
                return token
            s = self._session()
            return s.csrf if s else ""

        # ---------------------------------------------------------------- responses

        def _send(self, status: int, body: bytes, ctype: str, extra: dict[str, str] | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data: Any) -> None:
            self._send(status, json.dumps(data, default=str).encode(), "application/json")

        def _error(self, status: int, msg: str) -> None:
            self._json(status, {"ok": False, "error": msg})

        def _raw_body(self, limit: int) -> bytes:
            n = int(self.headers.get("Content-Length") or 0)
            if n > limit:
                raise ApiError(413, "file too large")
            return self.rfile.read(n) if n else b""

        def _body(self) -> dict[str, Any]:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 1_000_000:
                raise ApiError(413, "request too large")
            if not n:
                return {}
            try:
                data = json.loads(self.rfile.read(n))
            except json.JSONDecodeError as e:
                raise ApiError(400, f"bad JSON: {e}") from e
            if not isinstance(data, dict):
                raise ApiError(400, "JSON object expected")
            return data

        # ---------------------------------------------------------------- dispatch

        def _note_client(self) -> None:
            """Local clients (the Claude MCP server) say who they are, for the status bar."""
            name = (self.headers.get("X-DMX-Client") or "").strip().lower()[:20]
            if name and self._local():
                call = (self.headers.get("X-DMX-Call") or "").strip()[:40] or None
                app.note_client(name, call)

        def _guarded(self, fn: Any) -> None:
            if not self._host_ok():
                return self._error(403, "unknown host")
            if not self._local() and not access.lan:
                return self._error(403, "phone/LAN access is off on the laptop")
            self._note_client()
            try:
                fn()
            except ApiError as e:
                self._error(e.status, str(e))
            except LockedError as e:
                self._error(423, str(e))
            except PermissionError as e:
                self._error(403, str(e))
            except (StoreError, ConfigError, ValueError, KeyError) as e:
                msg = f"missing {e}" if isinstance(e, KeyError) else str(e)
                self._error(400, msg)
            except ConnectionError:  # client went away (closed tab or window; Windows reports it as aborted)
                pass
            except Exception:  # never let a UI bug take the server down mid-gig
                log.exception("API error")
                self._error(500, "internal error (see the console)")

        def do_GET(self) -> None:
            self._guarded(self._get)

        def do_POST(self) -> None:
            self._guarded(lambda: self._write("POST"))

        def do_PUT(self) -> None:
            self._guarded(lambda: self._write("PUT"))

        def do_DELETE(self) -> None:
            self._guarded(lambda: self._write("DELETE"))

        def _get(self) -> None:
            url = urlparse(self.path)
            path = url.path
            if path.startswith("/static/"):  # the app's own files: no secrets, needed by the sign-in page
                f = (STATIC / path[len("/static/"):]).resolve()
                if not f.is_relative_to(STATIC.resolve()) or not f.is_file():
                    return self._error(404, "not found")
                return self._send(200, f.read_bytes(), TYPES.get(f.suffix, "application/octet-stream"))
            who = self._reader()
            if path in ("/", "/index.html", "/login"):
                page = "index.html" if who == "ui" and path != "/login" else "login.html"
                return self._page(page)
            if who is None:
                return self._error(401, "sign in with the PIN")
            if who == "claude" and path.startswith("/api/access"):
                return self._error(403, "not available to Claude")
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if path == "/api/access":
                return self._json(200, self._access_status())
            if path == "/api/ping":
                return self._json(200, {"ok": True, "gig_lock": app.gig_lock})
            if path == "/api/effects":
                return self._json(200, app.effects_catalogue())
            if path == "/api/settings":
                return self._json(200, {"settings": settings.load(), "themes": settings.themes(),
                                        "first_run": settings.first_run()})
            if path == "/api/update":  # only when the user asks (UI button); check only, nothing installed
                from ..update import check

                return self._json(200, check())
            if path == "/api/devices":
                return self._json(200, app.devices())
            if path == "/api/interfaces":  # setup wizard: what's plugged in
                from ..detect import interfaces

                return self._json(200, interfaces())
            if path == "/api/state":
                return self._json(200, app.snapshot())
            if path == "/api/layout":
                return self._json(200, app.layout_view())
            if path == "/api/routing":
                return self._json(200, app.routing())
            if path == "/api/devices/list":  # v4: devices plugged in, by USB identity / MIDI port name
                return self._json(200, app.devices_view())
            if path == "/api/monitor/status":  # v4 Monitor page: MIDI ports, rates, energy
                return self._json(200, app.monitor_status())
            if path == "/api/monitor/midi":
                ch = q.get("channel")
                return self._json(200, app.monitor_midi(q.get("dir", "in"), int(q.get("n", 200)), int(q.get("since", 0)),
                                                        q.get("port") or None, int(ch) if ch else None, q.get("type") or None,
                                                        q.get("unmapped") == "1"))
            if path == "/api/monitor/channels":
                return self._json(200, app.channel_names(int(q.get("u", 0))))
            if path == "/api/frame":  # one look at what an interface sent (Monitor, Claude)
                return self._json(200, app.frame_view(int(q.get("u", 0)), q.get("out")))
            if path == "/api/events/frames":  # live frames, only while a page shows them
                return self._frames(int(q.get("u", 0)), q.get("out"))
            if path == "/api/catalogue":
                return self._json(200, app.catalogue())
            if path == "/api/events":
                return self._events(int(q.get("since", 0)))
            if path == "/api/midi":
                since = int(q.get("since", 0))
                return self._json(200, [asdict(e) for e in app.monitor.since(since)])
            if path == "/api/midi/map":
                return self._json(200, app.router.map.to_dict())
            if path == "/api/inputs":  # named inputs (v3), with where each is used
                ins = app.router.inputs
                input_rows = ins.summary()
                for row in input_rows:
                    m = app.router.map.get_input(row["id"])
                    row["mapped"] = m.describe() if m else None
                devices = [{"id": d.id, "name": d.name, "port": d.port, "channel": d.channel, "inputs": d.inputs}
                           for d in ins.devices.values()]
                return self._json(200, {"devices": devices, "inputs": input_rows, "profiles": device_profiles(app.files.root)})
            if path == "/api/points":  # head points of the running rig, plus what each is used by
                rig = app.engine.rig
                return self._json(200, {"rig": app.names[0], "points": [
                    {"name": pt.name, "description": pt.description, "tags": pt.tags, "stage": pt.stage,
                     "heads": {f: {"pan": v[0], "tilt": v[1]} for f, v in pt.heads.items()},
                     "missing": [f.id for f in rig.fixtures if f.type.has("pan") and not f.type.colour_only
                                 and f.id not in pt.heads]} for pt in rig.points.values()],
                    "problems": rig.point_problems()})
            if path == "/api/alerts":
                return self._json(200, app.alerts_view())
            if path == "/api/claude":  # Connect to Claude (Setup page)
                if who == "claude":
                    raise ApiError(403, "not available to Claude")
                return self._json(200, app.claude_status(fresh=q.get("fresh") == "1"))
            if path == "/api/fx":  # FX banks for this rig (v3.3)
                return self._json(200, app.fx_catalogue())
            if path == "/api/presets":  # presets (v3.5): starters + the show's own
                return self._json(200, {k: {"name": v["name"], "tags": v["tags"], "pick": v["pick"], "builtin": v["builtin"]}
                                        for k, v in (app.files.presets or {}).items()})
            if path == "/api/review":  # look review: every look the rig can do, with ratings
                return self._json(200, app.review_looks(q.get("mood") or None, q.get("bank") or None, q.get("palette") or None,
                                                        int(q.get("offset", 0)), int(q.get("limit", 40))))
            if path == "/api/autopilot":  # status and the decision log (v3.4)
                n = int(q.get("n", 50))
                return self._json(200, {"status": app.autopilot.status(app.engine.clock()), "log": app.autopilot.log_since(n),
                                        "priority": app.priority(), "config": app.autopilot.cfg})
            if path == "/api/kelvin":
                from ..colourtheory import KELVIN_PRESETS, hex_of, kelvin

                return self._json(200, [{"name": n, "kelvin": k, "hex": hex_of(kelvin(k))} for n, k in KELVIN_PRESETS])
            if path.startswith("/api/palette/export/"):
                return self._json(200, app.store.export_palette(path.rsplit("/", 1)[1]))
            if path.startswith("/api/colours/used/"):
                return self._json(200, {"used": app.store.colour_users(path.rsplit("/", 1)[1])})
            if path.startswith("/api/points/used/"):
                return self._json(200, {"used": app.store.point_users(path.rsplit("/", 1)[1])})
            if path.startswith("/api/inputs/used/"):
                return self._json(200, {"used": app.store.input_users(path.rsplit("/", 1)[1])})
            if path == "/api/addresses":
                rows, notes = patch_report(app.files.patch, app.engine.rig)
                return self._json(200, {"rows": [asdict(r) for r in rows], "notes": notes})
            if path == "/api/backups":
                return self._json(200, app.store.backups())
            if path == "/api/undo":
                return self._json(200, app.store.history())
            if path == "/api/project":
                return self._json(200, self._project_info())
            if path == "/api/project/download":
                return self._download()
            if path.startswith("/api/ofl/export/"):
                return self._ofl_export(path.rsplit("/", 1)[1])
            if path.startswith("/api/store/"):
                parts = path.split("/")[3:]
                if len(parts) == 1:
                    kind = parts[0]
                    if kind in ("palettes", "fixtures", "panels"):
                        return self._json(200, app.store.read(kind))
                    return self._json(200, app.store.names(kind))
                if len(parts) == 2:
                    return self._json(200, app.store.read(parts[0], parts[1]))
            return self._error(404, "not found")

        def _page(self, name: str) -> None:
            key, meta = settings.theme()
            html = (STATIC / name).read_text(encoding="utf-8")
            density = settings.load().get("density")
            density = density if density in settings.DENSITIES else "compact"
            for k, v in (("__TOKEN__", self._page_token()), ("__THEME__", key), ("__DENSITY__", density),
                         ("__APP_NAME__", html_escape(meta["app_name"]))):
                html = html.replace(k, v)
            self._send(200, html.encode(), TYPES[".html"])

        def _access_status(self) -> dict[str, Any]:
            port = int(self.server.server_address[1])  # type: ignore[index]
            urls = [f"http://{ip}:{port}/" for ip in lan_addresses()]
            out = {**access.status(), "local": self._local(), "port": port, "urls": urls, "qr": None}
            if access.lan and urls:
                out["qr"] = qr.svg(urls[0])
            return out

        def _access_change(self, b: dict) -> dict[str, Any]:
            if not self._local():
                raise PermissionError("access settings can only be changed on the laptop")
            action = b.get("action")
            was = access.lan
            if action == "set_pin":
                access.set_pin(b.get("pin"), b.get("old"))
            elif action == "clear_pin":
                access.clear_pin(b.get("old"))
            elif action == "configure":
                access.configure(b.get("lan"), b.get("pin_local"), b.get("session_hours"))
            else:
                raise ApiError(400, "unknown access action")
            if access.lan != was and on_lan is not None:
                on_lan(access.lan)  # listen on the network, or localhost only (after this reply)
            return {"ok": True, **self._access_status()}

        # ---------------------------------------------------------------- Open Fixture Library

        def _ofl_import(self, b: dict) -> dict[str, Any]:
            """An OFL fixture JSON (picked in the browser) as a fixture type, not saved yet."""
            from ..ofl import ofl_to_type

            data = b.get("json")
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except json.JSONDecodeError as e:
                    raise ApiError(400, f"not an Open Fixture Library file (JSON): {e}") from e
            if not isinstance(data, dict):
                raise ApiError(400, "not an Open Fixture Library file")
            modes = [m.get("name") for m in data.get("modes") or [] if isinstance(m, dict)]
            mode = b.get("mode") or (modes[0] if len(modes) == 1 else None)
            if mode is None:
                return {"ok": True, "modes": modes, "entry": None}
            entry, warnings = ofl_to_type(data, mode, b.get("key") or None, b.get("kind") or None)
            return {"ok": True, "modes": modes, "entry": entry, "warnings": warnings}

        def _ofl_export(self, key: str) -> None:
            from ..ofl import type_to_ofl

            types = app.store.read("fixtures").get("types") or {}
            if key not in types:
                return self._error(404, f"no fixture type {key!r}")
            data = type_to_ofl(key, types[key], time.strftime("%Y-%m-%d"))
            self._send(200, json.dumps(data, indent=2).encode(), "application/json",
                       {"Content-Disposition": f'attachment; filename="{key}.json"'})

        # ---------------------------------------------------------------- .dms show files

        def _project_info(self) -> dict[str, Any]:
            return {"project": app.project_info(), "folder": str(app.files.root),
                    "recent": settings.load().get("recent", []), "local": self._local()}

        def _switch(self, target: Path) -> dict[str, Any]:
            """Restart the app on another show file (the lights go dark for a moment)."""
            from ..package import read_manifest

            app.require_unlocked("opening another show file")
            read_manifest(target)  # refuse a bad or newer file before stopping anything
            settings.add_recent(str(target))
            if app.on_restart is None:
                raise ApiError(409, "this copy of the app can't switch show files; restart it with the file")
            app.on_restart(target)
            return {"ok": True, "restarting": True, "file": str(target)}

        def _project(self, action: str, b: dict) -> dict[str, Any]:
            from ..package import DmsError, create, is_dms, pack
            from ..paths import bundled_shows

            if not self._local():
                raise PermissionError("open and save show files on the laptop (phones can download and upload)")
            raw = str(b.get("path") or "").strip()
            if not raw:
                raise ApiError(400, "no file picked")
            target = Path(raw).expanduser()
            if not target.is_absolute():
                raise ApiError(400, "give the full path of the show file")
            if not is_dms(target):
                target = target.with_suffix(".dms")
            if action == "open":
                if not target.exists():
                    raise ApiError(404, f"no show file {target}")
                return self._switch(target)
            if action == "new":
                app.require_unlocked("starting a new show file")
                create(target, bundled_shows())
                return self._switch(target)
            if action == "save_as":
                if target.exists() and not b.get("overwrite"):
                    raise ApiError(409, f"{target.name} already exists")
                if app.project is not None:
                    app.project.save_as(target)
                else:  # a plain show folder: save it as a .dms and carry on with that
                    pack(app.files.root, target)
                    settings.add_recent(str(target))
                    return {"ok": True, "saved": str(target), "restart_to_use": True, **self._project_info()}
                settings.add_recent(str(target))
                return {"ok": True, "saved": str(target), **self._project_info()}
            raise DmsError(f"unknown show file action {action!r}")

        def _download(self) -> None:
            import tempfile

            from ..package import pack

            name = app.project.name if app.project else f"{app.files.root.name}.dms"
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "show.dms"
                pack(app.files.root, out)
                data = out.read_bytes()
            safe = "".join(c for c in name if c.isalnum() or c in " ._-()") or "show.dms"
            self._send(200, data, "application/octet-stream",
                       {"Content-Disposition": f'attachment; filename="{safe}"'})

        def _upload(self) -> dict[str, Any]:
            """A .dms from a phone or browser: kept next to the open show file (or show folder), then opened."""
            import tempfile

            from ..package import is_dms, unpack

            data = self._raw_body(MAX_UPLOAD)
            name = Path(parse_qs(urlparse(self.path).query).get("name", ["upload.dms"])[0]).name
            name = "".join(c for c in name if c.isalnum() or c in " ._-()").strip() or "upload.dms"
            if not is_dms(name):
                name += ".dms"
            with tempfile.TemporaryDirectory() as tmp:  # check it fully before keeping it
                f = Path(tmp) / "check.dms"
                f.write_bytes(data)
                unpack(f, Path(tmp) / "shows")
            folder = app.project.dms.parent if app.project else app.files.root.parent
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / name
            n = 2
            while target.exists():
                target = folder / f"{Path(name).stem} ({n}).dms"
                n += 1
            target.write_bytes(data)
            return self._switch(target)

        def _login(self, b: dict) -> None:
            try:
                sid, _ = access.login(self.client_address[0], b.get("pin"))
            except PermissionError as e:
                return self._error(429 if "wait" in str(e) else 401, str(e))
            cookie = f"{SESSION_COOKIE}={sid}; Path=/; HttpOnly; SameSite=Strict; Max-Age={7 * 24 * 3600}"
            self._send(200, json.dumps({"ok": True}).encode(), "application/json", {"Set-Cookie": cookie})

        def _logout(self) -> None:
            access.logout(self._sid())
            self._send(200, json.dumps({"ok": True}).encode(), "application/json",
                       {"Set-Cookie": f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"})

        def _events(self, since: int) -> None:
            """Server-sent events: state 10 times a second, plus new MIDI monitor lines."""
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            self.connection.settimeout(5.0)  # a phone that stops reading can't hold this thread forever
            seq = since
            sid = id(self)
            app.screens[sid] = {"ip": self.client_address[0], "local": self._local(), "since": time.time()}
            try:
                self._stream(seq)
            finally:
                app.screens.pop(sid, None)

        def _frames(self, universe: int, out: str | None) -> None:
            """Server-sent events: one interface's frame on one universe, 10 times a second."""
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            self.connection.settimeout(5.0)
            local, sid = self._local(), self._sid()
            last = None
            quiet = time.monotonic()
            while not app_stopping.is_set() and not live.stopped:
                if not local and (not access.lan or access.session(sid, touch=False) is None):
                    return
                body = json.dumps(app.frame_view(universe, out), default=str)
                if body != last or time.monotonic() - quiet > HEARTBEAT_S:
                    self.wfile.write(f"data: {body}\n\n".encode())
                    self.wfile.flush()
                    last, quiet = body, time.monotonic()
                time.sleep(FRAMES_S)

        def _stream(self, seq: int) -> None:
            """Send the shared state when it changes, new MIDI monitor lines, else a heartbeat."""
            local, sid = self._local(), self._sid()
            seen, quiet = -1, time.monotonic()
            while not app_stopping.is_set() and not live.stopped:
                if not local and (not access.lan or access.session(sid, touch=False) is None):
                    return
                version, state = live.wait(seen, live.tick_s * 2)
                midi = [asdict(e) for e in app.monitor.since(seq)]
                parts = []
                if version != seen:
                    parts.append(f'"state": {state}')
                    seen = version
                if midi:
                    seq = midi[-1]["seq"]
                    parts.append(f'"midi": {json.dumps(midi, default=str)}')
                if not parts:
                    if time.monotonic() - quiet < HEARTBEAT_S:
                        continue
                    parts.append('"beat": 1')
                quiet = time.monotonic()
                self.wfile.write(("data: {" + ", ".join(parts) + "}\n\n").encode())
                self.wfile.flush()

        def _write(self, method: str) -> None:
            path = urlparse(self.path).path
            if path == "/api/login" and method == "POST":
                return self._login(self._body())
            if path == "/api/logout" and method == "POST":
                return self._logout()
            who = self._writer()
            if who is None:
                return self._error(401, "missing or wrong X-DMX-Token (sign in again)")
            if who == "claude" and not path.startswith(CLAUDE_WRITES):
                return self._error(403, "not available to Claude")
            if path == "/api/project/upload" and method == "POST":
                return self._json(200, self._upload())
            body = self._body()
            with app.store.acting(who):  # undo remembers who made each change
                return self._dispatch(method, path, body)

        def _dispatch(self, method: str, path: str, body: dict) -> None:
            if method == "POST" and path.startswith("/api/autopilot/"):  # v4 names for the Ride page's routes
                rest = path[len("/api/autopilot/"):]
                path = "/api/ride" if rest == "play" else f"/api/ride/{rest}"
            if path == "/api/access" and method == "POST":
                return self._json(200, self._access_change(body))
            if path == "/api/starter" and method == "POST":
                return self._json(200, {"ok": True, **app.make_starter(bool(body.get("overwrite")))})
            if path == "/api/ofl/import" and method == "POST":
                return self._json(200, self._ofl_import(body))
            if path.startswith("/api/project/") and method == "POST":
                return self._json(200, self._project(path.rsplit("/", 1)[1], body))
            if path in ("/api/undo", "/api/redo", "/api/undo/claude") and method == "POST":
                if path == "/api/redo":
                    done = app.store.redo()
                else:
                    done = app.store.undo("claude" if path.endswith("/claude") else None)
                return self._json(200, {"ok": True, "change": done, "notes": app.reload(), **app.store.history()})
            if path == "/api/control" and method == "POST":
                return self._json(200, control(app, body.get("cmd", ""), body))
            if path == "/api/validate/scene" and method == "POST":  # read-only check, allowed under gig lock
                return self._json(200, app.validate_scene(body.get("data")))
            if path == "/api/settings" and method == "POST":  # this laptop's settings (theme)
                try:
                    return self._json(200, {"ok": True, "settings": settings.save(body)})
                except ValueError as e:
                    raise ApiError(400, str(e)) from e
            if path == "/api/giglock" and method == "POST":
                app.set_gig_lock(bool(body.get("on")))
                return self._json(200, {"ok": True, "gig_lock": app.gig_lock})
            if path == "/api/layout" and method == "PUT":
                bid = app.save_layout(body.get("layout") or {})
                return self._json(200, {"ok": True, "backup": bid})
            if path == "/api/monitor/send" and method == "POST":  # MIDI test send (gig-locked)
                sent = app.midi_send(str(body.get("port", "")), str(body.get("type", "note_on")), int(body.get("channel", 1)),
                                     int(body.get("number", 60)), int(body.get("value", 100)))
                return self._json(200, {"ok": True, "port": sent})
            if path == "/api/devices/replace" and method == "POST":  # mid-gig recovery: allowed under gig lock
                r = app.replace_device(str(body.get("missing", "")), str(body.get("use", "")))
                return self._json(200, {"ok": True, **r})
            if path == "/api/devices/set" and method == "POST":
                uni = body.get("universe")
                r = app.set_device(str(body.get("id", "")), body.get("alias"), None if uni in (None, "") else int(uni),
                                   body.get("driver") or None, bool(body.get("use", True)))
                return self._json(200, {"ok": True, **r})
            if path == "/api/steps/view" and method == "POST":  # v4 step editor: set vs tracked per light
                return self._json(200, app.step_view(body.get("scene") or {}, int(body.get("index", 0))))
            if path == "/api/steps/edit" and method == "POST":  # one step of a saved step scene (Claude, editor)
                return self._json(200, {"ok": True, **app.edit_step(str(body.get("op")), str(body.get("scene")), body)})
            if path == "/api/haze/settings" and method == "POST":  # Haze settings panel (and Claude, saving)
                r = app.haze_settings(body.get("changes") or {}, bool(body.get("save")))
                return self._json(200, {"ok": True, **r})
            if path == "/api/haze/revert" and method == "POST":
                return self._json(200, {"ok": True, **app.haze_revert()})
            if path == "/api/haze/test" and method == "POST":
                span = app.haze_test(str(body.get("mode", "")))
                return self._json(200, {"ok": True, "seconds": span})
            if path == "/api/routing/output" and method == "POST":
                r = app.set_output(int(body.get("index", -1)), body.get("set") or {})
                return self._json(200, {"ok": True, **r})
            if path == "/api/layout/positions" and method == "POST":  # some lights (Claude: set_layout)
                bid = app.set_positions(body.get("positions") or {})
                return self._json(200, {"ok": True, "backup": bid})
            if path == "/api/claude/haze" and method == "POST":
                app.require_unlocked("changing haze")
                return self._json(200, control(app, "haze", body))
            if path == "/api/preview" and method == "POST":
                scene = body.get("scene") or body.get("scene_data")
                if not isinstance(scene, (str, dict)):
                    raise ApiError(400, "preview needs a scene name or scene data")
                step = body.get("step")
                msg = app.preview_scene(scene, float(body.get("seconds", 10)), None if step is None else int(step))
                return self._json(200, {"ok": True, "message": msg})
            if path in ("/api/claude/connect", "/api/claude/disconnect") and method == "POST":
                if not self._local():  # it changes this computer's Claude settings: only from this computer
                    raise ApiError(403, "connect Claude from the laptop itself")
                try:
                    return self._json(200, app.claude_connect(path.endswith("/connect")))
                except (OSError, ValueError) as e:
                    raise ApiError(400, f"couldn't change the Claude settings: {e}") from e
            if path == "/api/alerts" and method == "POST":  # banners: dismiss, minimise, snooze, mute, quiet
                ac, a = app.alert_center, str(body.get("action", ""))
                try:
                    if a == "dismiss":
                        ac.dismiss(str(body["id"]))
                    elif a == "minimise":
                        ac.minimise(str(body["id"]))
                    elif a == "snooze":
                        ac.snooze(str(body["id"]), str(body.get("for", "10min")))
                    elif a == "mute":
                        ac.mute(str(body["id"]), bool(body.get("on", True)))
                    elif a == "quiet":
                        ac.set_quiet(bool(body.get("on", True)))
                    else:
                        raise ApiError(400, "alerts action: dismiss, minimise, snooze, mute or quiet")
                except ValueError as e:
                    raise ApiError(400, str(e)) from e
                return self._json(200, {"ok": True, **app.alerts_view()})
            if path == "/api/ride" and method == "POST":  # play a Ride look: FX + palette + ride settings (v3.3)
                try:
                    return self._json(200, app.ride_play(body.get("pick") or {}, body.get("fade_s")))
                except ValueError as e:
                    raise ApiError(400, str(e)) from e
            if path == "/api/ride/action" and method == "POST":  # Ride page controls (v3.4)
                try:
                    a = str(body.get("action", ""))
                    params = {k: v for k, v in body.items() if k not in ("action", "level")}
                    lvl = body.get("level")
                    result = app.ride_action(a, params, None if lvl is None else float(lvl))
                    return self._json(200, {"ok": True, "result": result})
                except ValueError as e:
                    raise ApiError(400, str(e)) from e
            if path == "/api/generate" and method == "POST":  # generator (v3.5): writes through the store
                try:
                    return self._json(200, app.generate(str(body.get("kind", "scenes")), body))
                except ValueError as e:
                    raise ApiError(400, str(e)) from e
            if method == "POST" and path in ("/api/capture", "/api/ride/reroll", "/api/ride/more", "/api/rate",
                                             "/api/preset/play"):
                try:
                    if path == "/api/capture":
                        return self._json(200, {"ok": True, "backup": app.capture_look(str(body["key"]), body.get("name"))})
                    if path == "/api/ride/reroll":
                        return self._json(200, app.reroll(list(body.get("locks") or []), body.get("mood"), body.get("seed")))
                    if path == "/api/ride/more":
                        return self._json(200, {"picks": app.more_like_this(int(body.get("n", 4)), body.get("seed"))})
                    if path == "/api/rate":
                        return self._json(200, {"ok": True, "backup": app.rate_look(body.get("key") or body.get("pick") or {},
                                                                                   int(body.get("value", 0)))})
                    return self._json(200, app.play_preset(str(body["preset"])))
                except ValueError as e:
                    raise ApiError(400, str(e)) from e
            if path == "/api/ride/learn" and method == "POST":  # MIDI learn a Ride control, saved when learned
                return self._json(200, {"ok": True, "message": app.learn_and_save(str(body["action"]), body.get("params") or {})})
            if path == "/api/flashfx" and method == "POST":
                try:
                    lm = body.get("length_ms")
                    msg = app.flash_fx(str(body.get("fx", "")), bool(body.get("down", True)), body.get("colour"),
                                       str(body.get("side", "left")), None if lm is None else int(lm))
                except ValueError as e:
                    raise ApiError(400, str(e)) from e
                return self._json(200, {"ok": True, "result": msg})
            if path == "/api/ride/check" and method == "POST":  # a pick as a scene + quality notes, nothing played
                from ..fxbanks import BY_ID, Pick

                pick = Pick.from_dict(body.get("pick") or {})
                bad = [x for x in (pick.move, pick.colour, pick.drum) if x and x not in BY_ID]
                if bad:
                    raise ApiError(400, f"unknown FX item(s): {', '.join(bad)}")
                _, scene = app.compose(pick)
                return self._json(200, {"issues": app.quality().combo_issues(pick, str(body.get("mood", "mid"))),
                                        "scene": scene})
            if path == "/api/steps/capture" and method == "POST":  # read only: the lights as a step's `set`
                try:
                    return self._json(200, {"set": app.capture_step(list(body.get("fixtures") or []))})
                except ValueError as e:
                    raise ApiError(400, str(e)) from e
            if path == "/api/colour/preview" and method == "POST":  # read-only: what each light makes of a colour
                return self._json(200, app.colour_preview(body.get("colour"), list(body.get("fixtures") or [])))
            if path == "/api/colour/generate" and method == "POST":
                from ..colourtheory import generate, hex_of
                from ..look import parse_colour

                base = parse_colour(body.get("base", "#ff0000"), "base colour")
                return self._json(200, {"colours": [hex_of(c) for c in generate(base, str(body.get("scheme", "analogous")),
                                                                                   int(body.get("count", 4)))]})
            if path == "/api/palette/preview" and method == "POST":
                msg = app.palette_preview(str(body["palette"]), str(body.get("mode", "static")), float(body.get("seconds", 10)))
                return self._json(200, {"ok": True, "message": msg})
            if path.startswith("/api/midi/") and method == "POST":
                return self._json(200, self._midi(path.rsplit("/", 1)[1], body))
            if path.startswith("/api/nodes/") and method == "POST":
                return self._json(200, self._nodes(path.rsplit("/", 1)[1], body))
            if path.startswith("/api/store"):
                return self._json(200, self._store(method, path.split("/")[3:], body))
            return self._error(404, "not found")

        def _midi(self, action: str, b: dict) -> dict:
            r, m = app.router, app.monitor
            if action == "learn":
                app.require_unlocked("MIDI learn")
                r.learn(b["action"], b.get("params") or {})
                return {"ok": True, "learning": b["action"]}
            if action == "cancel":
                r.cancel_learn()
            elif action == "pause":
                m.paused = bool(b.get("on", not m.paused))
            elif action == "clear":
                m.clear()
            elif action == "remove":
                app.require_unlocked("removing a mapping")
                if b["type"] == "osc":
                    r.map.remove(("osc", 0, 0, b["address"]))
                elif b["type"] == "input":
                    r.map.remove(("input", 0, 0, b["input"]))
                else:
                    r.map.remove((b["type"], int(b["channel"]), int(b["number"]), b.get("port") or ""))
            elif action == "save":  # validated and backed up like every other edit, with learned inputs
                bid = app.save_midi_map()
                return {"ok": True, "saved": str(app.files.midimap_path.name), "backup": bid}
            elif action == "learn_input":
                return {"ok": True, "message": app.learn_input(str(b["input"]), b.get("device"), bool(b.get("add")))}
            elif action == "calibrate":
                return app.calibrate(str(b["input"]), str(b.get("level", "normal")), str(b.get("step", "start")))
            else:
                raise ApiError(404, "unknown MIDI action")
            return {"ok": True}

        def _nodes(self, action: str, b: dict) -> dict:
            from ..node.protocol import AckCode, parse_mac

            if action == "assign":  # waits for the node's heartbeat to confirm it
                return app.assign_node(str(b["mac"]), int(b.get("universe", 0)), str(b["name"]))
            if action == "replace":
                return app.replace_node(str(b["old"]), str(b["new"]))
            if action == "channel":
                return app.set_radio_channel(int(b["channel"]))
            if action == "setup":  # push the fallback looks and channel again
                app.require_unlocked("node set-up")
                return {"ok": True, **app.setup_node(app.node_driver())}
            link = app.node_link()
            if action == "identify":
                code = link.identify(parse_mac(b["mac"]), int(b.get("seconds", 5)))
            else:
                raise ApiError(404, "unknown node action")
            if code != AckCode.OK:
                raise ApiError(502, f"node answered {code.name if code is not None else 'nothing'}")
            return {"ok": True}

        def _store(self, method: str, parts: list[str], b: dict) -> dict:
            s = app.store
            if parts == ["restore"] and method == "POST":
                bid = s.restore(b["backup"], b["file"])
            elif parts == ["fixture"] and method == "POST":
                bid = s.put_fixture(b["entry"])
            elif parts == ["fixture", "remove"] and method == "POST":
                bid = s.remove_fixture(str(b.get("id", "")))
            elif parts == ["patch"] and method == "PUT":
                bid = s.put_patch(b.get("fixtures"))
            elif parts == ["input"] and method == "POST":  # named inputs (v3)
                a = str(b.get("action", "put"))
                if a == "put":
                    bid = s.put_input(str(b["device"]), str(b["name"]), b.get("value") or {}, b.get("device_info"))
                elif a == "rename":
                    bid = s.rename_input(str(b["name"]), str(b["new_name"]))
                elif a == "delete":
                    bid = s.delete_input(str(b["name"]))
                else:
                    raise ApiError(400, "input action: put, rename or delete")
            elif parts == ["colour"] and method == "POST" and b.get("action") == "rename":  # named colours (v3)
                bid = s.rename_colour(str(b["name"]), str(b["new_name"]))
            elif parts == ["palette"] and method == "POST":
                a = str(b.get("action", ""))
                if a == "rename":
                    bid = s.rename_palette(str(b["name"]), str(b["new_name"]))
                elif a == "import":
                    bid = s.import_palette(b.get("data") or {}, bool(b.get("overwrite")))
                else:
                    raise ApiError(400, "palette action: rename or import")
            elif parts == ["point"] and method == "POST":  # head position points (v3)
                a = str(b.get("action", "put"))
                rig = str(b.get("rig") or app.names[0])
                if a in ("put", "store"):
                    bid = s.put_point(rig, str(b["name"]), b.get("value") or {}, merge=a == "store")
                elif a == "rename":
                    bid = s.rename_point(str(b["name"]), str(b["new_name"]))
                elif a == "delete":
                    bid = s.delete_point(rig, str(b["name"]))
                else:
                    raise ApiError(400, "point action: put, store, rename or delete")
            elif parts == ["preset"] and method == "POST":  # presets (v3.5)
                try:
                    if b.get("action", "put") == "delete":
                        bid = app.delete_preset(str(b["id"]))
                    else:
                        bid = app.save_preset(str(b["id"]), b.get("name"), b.get("tags"), b.get("pick"))
                except ValueError as e:
                    raise ApiError(400, str(e)) from e
            elif parts == ["auto"] and method == "POST":  # classification overrides for the running rig (v3.3)
                rig_name = str(b.get("rig") or app.names[0])
                data = s.read("rig", rig_name)
                auto = {k: v for k, v in (("classes", b.get("classes") or {}), ("exclude", b.get("exclude") or [])) if v}
                if auto:
                    data["auto"] = auto
                else:
                    data.pop("auto", None)
                bid = s.put("rig", rig_name, data, f"auto show lights on rig {rig_name}")
            elif parts == ["device"] and method == "POST":
                a = str(b.get("action", "put"))
                if a == "put":
                    bid = s.put_device(str(b["device"]), b.get("value") or {})
                elif a == "delete":
                    bid = s.delete_device(str(b["device"]))
                elif a == "load":  # a device profile (shipped or the show's devices/ folder)
                    bid = s.put_device(str(b.get("as") or b["profile"]), load_device_profile(app.files.root, str(b["profile"])))
                elif a == "export":
                    bid = s.export_device(str(b["device"]))
                else:
                    raise ApiError(400, "device action: put, delete, load or export")
            elif parts == ["group"] and method == "POST":
                bid = s.edit_group(str(b.get("action", "")), str(b.get("name", "")), b.get("fixtures"), b.get("new_name"))
            elif len(parts) == 3 and parts[0] in ("palettes", "fixtures") and method in ("PUT", "DELETE"):
                bid = s.put_entry(parts[0], parts[1], parts[2], None if method == "DELETE" else b.get("value"))
            elif parts == ["panels"] and method == "PUT":
                bid = s.put("panels", "", b.get("data"))
            elif len(parts) == 2 and method == "PUT":
                bid = s.put(parts[0], parts[1], b.get("data"))
            elif len(parts) == 2 and method == "DELETE":
                bid = s.delete(parts[0], parts[1])
            elif len(parts) == 3 and parts[2] == "duplicate" and method == "POST":
                bid = s.duplicate(parts[0], parts[1], b["to"])
            else:
                raise ApiError(404, "unknown store request")
            notes = app.reload()
            return {"ok": True, "backup": bid, "notes": notes}

    return Handler


app_stopping = threading.Event()


class WebServer:
    """`host=None` (the app) follows the access settings: localhost, or every network when phone/LAN
    access is on, switching over when it's turned on or off. A fixed host (tests) stays put."""

    def __init__(self, app: App, host: str | None = None, port: int = DEFAULT_PORT, token: str | None = None,
                 claude_token: str | None = None, access: Access | None = None) -> None:
        self.access = access or Access()
        self.token = token or secrets.token_urlsafe(24)  # the page's, new each run
        self.claude_token = claude_token or default_claude_token()
        self.follow = host is None
        self.host = self._wanted() if host is None else host
        self.feed = LiveFeed(app.snapshot)  # one snapshot a tick, shared by every screen
        self.app_token = secrets.token_urlsafe(24)  # for a second launch of the app on this computer
        self.handler = make_handler(app, self.token, self.access, self.claude_token, self.lan_changed, self.feed,
                                    self.app_token)
        self.httpd = self._serve(self.host, port)
        self.thread: threading.Thread | None = None
        self._swap = threading.Lock()

    def _wanted(self) -> str:
        return "0.0.0.0" if self.access.lan else "127.0.0.1"

    def _serve(self, host: str, port: int) -> ThreadingHTTPServer:
        httpd = ThreadingHTTPServer((host, port), self.handler)
        httpd.daemon_threads = True
        return httpd

    @property
    def port(self) -> int:
        return self.httpd.server_address[1]

    def start(self) -> None:
        app_stopping.clear()
        self.feed.start()
        if self.follow:  # the real app (not a test server): a second launch can hand over a file
            try:
                p = app_token_file()
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(f"{self.port} {self.app_token}", encoding="utf-8")
                p.chmod(0o600)
            except OSError:
                log.warning("couldn't write the app token file")
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="web", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        app_stopping.set()
        self.feed.stop()
        self.httpd.shutdown()
        self.httpd.server_close()

    def lan_changed(self, on: bool) -> None:
        if self.follow:  # after the reply that turned it on/off has gone
            threading.Timer(0.3, self.rebind).start()

    def rebind(self) -> None:
        """Listen where the access settings say, on the same port. Open screens reconnect by themselves."""
        with self._swap:
            host = self._wanted()
            if host == self.host:
                return
            port = self.port
            self.httpd.shutdown()
            self.httpd.server_close()
            try:
                self.httpd = self._serve(host, port)
                self.host = host
            except OSError:
                log.exception("couldn't listen on %s:%s; staying on %s", host, port, self.host)
                self.httpd = self._serve(self.host, port)
            self.thread = threading.Thread(target=self.httpd.serve_forever, name="web", daemon=True)
            self.thread.start()
