"""Browser UI + JSON API on the gig laptop. Standard library only, no internet needed.

Security: every change needs the session token (sent by the page in a header); the server binds to
localhost unless started with --lan; from another device (phone) the page must be opened with the
token link; and the Host header must be localhost or an IP address, which blocks DNS-rebinding pages.
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

from .. import settings
from ..app import App
from ..fixtures import ConfigError
from ..setup import patch_report
from ..store import LockedError, StoreError

log = logging.getLogger(__name__)

STATIC = Path(__file__).parent / "static"
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
         ".json": "application/json; charset=utf-8"}
DEFAULT_PORT = 8505
TOKEN_FILE = Path.home() / ".dmx_suite" / "token"


def load_token(path: Path = TOKEN_FILE) -> str:
    """Session token shared by the web UI and the local MCP server. Created on first run."""
    try:
        tok = path.read_text(encoding="utf-8").strip()
        if len(tok) >= 20:
            return tok
    except OSError:
        pass
    tok = secrets.token_urlsafe(24)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tok, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return tok


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
        else:
            raise ApiError(400, "haze action: off, manual, pulse, toggle_manual, boost, release")
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
    elif cmd == "speed":
        c.set_speed(float(a["value"]))
    elif cmd == "busk":
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


def make_handler(app: App, token: str) -> type[BaseHTTPRequestHandler]:
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

        def _query_token(self) -> str | None:
            vals = parse_qs(urlparse(self.path).query).get("t")
            return vals[0] if vals else None

        def _cookie_token(self) -> str | None:
            c = SimpleCookie(self.headers.get("Cookie") or "")
            return c["dmx_token"].value if "dmx_token" in c else None

        def _can_read(self) -> bool:
            if self._local():
                return True
            return secrets.compare_digest(self._query_token() or self._cookie_token() or "", token)

        def _can_write(self) -> bool:
            return secrets.compare_digest(self.headers.get("X-DMX-Token") or "", token)

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
            self._note_client()
            try:
                fn()
            except ApiError as e:
                self._error(e.status, str(e))
            except LockedError as e:
                self._error(423, str(e))
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
            if not self._can_read():
                return self._error(401, "open the link with the access token (shown in the console)")
            extra = {}
            if self._query_token():
                extra["Set-Cookie"] = f"dmx_token={token}; Path=/; HttpOnly; SameSite=Strict"
            if path in ("/", "/index.html"):
                key, meta = settings.theme()
                html = (STATIC / "index.html").read_text(encoding="utf-8")
                for k, v in (("__TOKEN__", token), ("__THEME__", key), ("__APP_NAME__", html_escape(meta["app_name"]))):
                    html = html.replace(k, v)
                return self._send(200, html.encode(), TYPES[".html"], {"Cache-Control": "no-store", **extra})
            if path.startswith("/static/"):
                f = (STATIC / path[len("/static/"):]).resolve()
                if not f.is_relative_to(STATIC.resolve()) or not f.is_file():
                    return self._error(404, "not found")
                return self._send(200, f.read_bytes(), TYPES.get(f.suffix, "application/octet-stream"), extra)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if path == "/api/ping":
                return self._json(200, {"ok": True, "gig_lock": app.gig_lock})
            if path == "/api/effects":
                return self._json(200, app.effects_catalogue())
            if path == "/api/settings":
                return self._json(200, {"settings": settings.load(), "themes": settings.themes()})
            if path == "/api/update":  # only when the user asks (UI button); check only, nothing installed
                from ..update import check

                return self._json(200, check())
            if path == "/api/devices":
                return self._json(200, app.devices())
            if path == "/api/state":
                return self._json(200, app.snapshot())
            if path == "/api/catalogue":
                return self._json(200, app.catalogue())
            if path == "/api/events":
                return self._events(int(q.get("since", 0)))
            if path == "/api/midi":
                since = int(q.get("since", 0))
                return self._json(200, [asdict(e) for e in app.monitor.since(since)])
            if path == "/api/midi/map":
                return self._json(200, app.router.map.to_dict())
            if path == "/api/addresses":
                rows, notes = patch_report(app.files.patch, app.engine.rig)
                return self._json(200, {"rows": [asdict(r) for r in rows], "notes": notes})
            if path == "/api/backups":
                return self._json(200, app.store.backups())
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

        def _events(self, since: int) -> None:
            """Server-sent events: state 10 times a second, plus new MIDI monitor lines."""
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            seq = since
            sid = id(self)
            app.screens[sid] = {"ip": self.client_address[0], "local": self._local(), "since": time.time()}
            try:
                self._stream(seq)
            finally:
                app.screens.pop(sid, None)

        def _stream(self, seq: int) -> None:
            while not app_stopping.is_set():
                midi = [asdict(e) for e in app.monitor.since(seq)]
                if midi:
                    seq = midi[-1]["seq"]
                payload = json.dumps({"state": app.snapshot(), "midi": midi}, default=str)
                self.wfile.write(f"data: {payload}\n\n".encode())
                self.wfile.flush()
                time.sleep(0.1)

        def _write(self, method: str) -> None:
            if not self._can_write():
                return self._error(401, "missing or wrong X-DMX-Token")
            path = urlparse(self.path).path
            body = self._body()
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
            if path == "/api/claude/haze" and method == "POST":
                app.require_unlocked("changing haze")
                return self._json(200, control(app, "haze", body))
            if path == "/api/preview" and method == "POST":
                scene = body.get("scene") or body.get("scene_data")
                if not isinstance(scene, (str, dict)):
                    raise ApiError(400, "preview needs a scene name or scene data")
                msg = app.preview_scene(scene, float(body.get("seconds", 10)))
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
                r.learn(b["action"], b.get("params") or {})
                return {"ok": True, "learning": b["action"]}
            if action == "cancel":
                r.cancel_learn()
            elif action == "pause":
                m.paused = bool(b.get("on", not m.paused))
            elif action == "clear":
                m.clear()
            elif action == "remove":
                if b["type"] == "osc":
                    r.map.remove(("osc", 0, 0, b["address"]))
                else:
                    r.map.remove((b["type"], int(b["channel"]), int(b["number"]), b.get("port") or ""))
            elif action == "save":
                app.require_unlocked("saving the MIDI map")
                path = app.files.midimap_path  # validated and backed up like every other edit
                bid = app.store.put("midi", path.stem, r.map.to_dict(), f"save MIDI map {path.stem}")
                return {"ok": True, "saved": str(path.name), "backup": bid}
            else:
                raise ApiError(404, "unknown MIDI action")
            return {"ok": True}

        def _nodes(self, action: str, b: dict) -> dict:
            from ..node.protocol import AckCode, parse_mac

            link = app.node_link()
            if action == "assign":
                app.require_unlocked("assigning nodes")
                code = link.assign(parse_mac(b["mac"]), int(b.get("universe", 0)), b["name"])
            elif action == "identify":
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
    def __init__(self, app: App, host: str = "127.0.0.1", port: int = DEFAULT_PORT, token: str | None = None) -> None:
        self.token = token or load_token()
        self.httpd = ThreadingHTTPServer((host, port), make_handler(app, self.token))
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="web", daemon=True)

    @property
    def port(self) -> int:
        return self.httpd.server_address[1]

    def start(self) -> None:
        app_stopping.clear()
        self.thread.start()

    def stop(self) -> None:
        app_stopping.set()
        self.httpd.shutdown()
        self.httpd.server_close()
