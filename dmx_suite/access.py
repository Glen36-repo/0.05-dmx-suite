"""Who may use the UI and API (R6).

- This computer: the desktop window and a browser on the laptop get in without a PIN, unless
  "ask for the PIN on this computer too" is ticked.
- Phones and other computers: only when phone/LAN access is turned on, which needs a PIN first.
  Signing in with the PIN gives a session (cookie) that ends after `session_hours` without use,
  when the PIN changes, or when LAN access is turned off.
- Claude (MCP): its own token (`claude_token` in app data), local only, never a UI session, so
  it can't turn gig lock off or change these settings.

Saved in app data `access.json` (per laptop, not in the show folder). The PIN is kept only as a
salted PBKDF2 hash.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .paths import data_dir

ITERATIONS = 200_000
MIN_PIN = 4
MAX_FAILS = 5  # wrong PINs from one address before it has to wait
LOCKOUT_S = 30.0
DEFAULTS: dict[str, Any] = {"pin_hash": None, "lan": False, "pin_local": False, "session_hours": 12}


def hash_pin(pin: str, salt: bytes | None = None, iterations: int = ITERATIONS) -> str:
    salt = salt or secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${h.hex()}"


def pin_matches(pin: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, iters, salt, want = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        got = hash_pin(pin, bytes.fromhex(salt), int(iters)).rsplit("$", 1)[1]
    except (ValueError, TypeError):
        return False
    return secrets.compare_digest(got, want)


def check_pin_text(pin: Any) -> str:
    if not isinstance(pin, str) or len(pin.strip()) < MIN_PIN:
        raise ValueError(f"the PIN needs at least {MIN_PIN} characters")
    if len(pin) > 64:
        raise ValueError("the PIN can be 64 characters at most")
    return pin.strip()


def claude_token_path() -> Path:
    return data_dir() / "claude_token"


def claude_token(path: Path | None = None) -> str:
    """Claude's token, shared with the MCP server through app data. Made on first use."""
    p = path or claude_token_path()
    try:
        tok = p.read_text(encoding="utf-8").strip()
        if len(tok) >= 20:
            return tok
    except OSError:
        pass
    tok = secrets.token_urlsafe(24)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(tok, encoding="utf-8")
    try:
        p.chmod(0o600)
    except OSError:
        pass
    return tok


def lan_addresses() -> list[str]:
    """This computer's IPv4 addresses on the local network (best guess first)."""
    out: list[str] = []
    try:  # the address used for the default route; nothing is sent
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            out.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = str(info[4][0])
            if ip not in out:
                out.append(ip)
    except OSError:
        pass
    return [ip for ip in out if not ip.startswith("127.")]


@dataclass
class Session:
    csrf: str
    ip: str
    created: float
    last: float


@dataclass
class Access:
    path: Path = field(default_factory=lambda: data_dir() / "access.json")
    clock: Any = time.time
    sessions: dict[str, Session] = field(default_factory=dict)
    fails: dict[str, tuple[int, float]] = field(default_factory=dict)  # ip -> (count, last)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        self.data = self._load()

    # ------------------------------------------------------------------ settings

    def _load(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return dict(DEFAULTS)
        return {**DEFAULTS, **{k: v for k, v in (raw if isinstance(raw, dict) else {}).items() if k in DEFAULTS}}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
        try:
            tmp.chmod(0o600)
        except OSError:
            pass
        os.replace(tmp, self.path)

    @property
    def pin_set(self) -> bool:
        return bool(self.data["pin_hash"])

    @property
    def lan(self) -> bool:
        return bool(self.data["lan"]) and self.pin_set

    @property
    def pin_local(self) -> bool:
        return bool(self.data["pin_local"]) and self.pin_set

    @property
    def session_s(self) -> float:
        return float(self.data["session_hours"]) * 3600

    def status(self) -> dict[str, Any]:
        return {"pin_set": self.pin_set, "lan": self.lan, "pin_local": self.pin_local,
                "session_hours": self.data["session_hours"], "sessions": len(self.sessions)}

    def set_pin(self, new: Any, old: Any = None) -> None:
        """Set or change the PIN (the old one is needed to change it). Signs every session out."""
        new = check_pin_text(new)
        with self._lock:
            if self.pin_set and not pin_matches(str(old or ""), self.data["pin_hash"]):
                raise PermissionError("the current PIN is wrong")
            self.data["pin_hash"] = hash_pin(new)
            self.sessions.clear()
            self._save()

    def clear_pin(self, old: Any) -> None:
        """Remove the PIN: LAN access goes off with it."""
        with self._lock:
            if self.pin_set and not pin_matches(str(old or ""), self.data["pin_hash"]):
                raise PermissionError("the current PIN is wrong")
            self.data.update(pin_hash=None, lan=False, pin_local=False)
            self.sessions.clear()
            self._save()

    def configure(self, lan: Any = None, pin_local: Any = None, session_hours: Any = None) -> None:
        with self._lock:
            if lan is not None:
                if lan and not self.pin_set:
                    raise ValueError("set a PIN before turning on phone/LAN access")
                self.data["lan"] = bool(lan)
                if not lan:  # phones are signed out at once
                    self.sessions = {k: s for k, s in self.sessions.items() if s.ip in ("127.0.0.1", "::1")}
            if pin_local is not None:
                if pin_local and not self.pin_set:
                    raise ValueError("set a PIN first")
                self.data["pin_local"] = bool(pin_local)
            if session_hours is not None:
                h = float(session_hours)
                if not 0.25 <= h <= 168:
                    raise ValueError("sessions can last 0.25 to 168 hours")
                self.data["session_hours"] = h
            self._save()

    # ------------------------------------------------------------------ sessions

    def login(self, ip: str, pin: Any) -> tuple[str, Session]:
        now = self.clock()
        with self._lock:
            n, last = self.fails.get(ip, (0, 0.0))
            if n >= MAX_FAILS and now - last < LOCKOUT_S:
                raise PermissionError(f"too many wrong PINs: wait {int(LOCKOUT_S - (now - last)) + 1} s")
            if not self.pin_set or not pin_matches(str(pin or ""), self.data["pin_hash"]):
                self.fails[ip] = (n + 1 if now - last < LOCKOUT_S * 10 else 1, now)
                raise PermissionError("wrong PIN")
            self.fails.pop(ip, None)
            sid = secrets.token_urlsafe(24)
            s = Session(secrets.token_urlsafe(24), ip, now, now)
            self.sessions[sid] = s
            return sid, s

    def session(self, sid: str | None, touch: bool = True) -> Session | None:
        if not sid:
            return None
        now = self.clock()
        with self._lock:
            s = self.sessions.get(sid)
            if s is None:
                return None
            if now - s.last > self.session_s:
                del self.sessions[sid]
                return None
            if touch:
                s.last = now
            return s

    def logout(self, sid: str | None) -> None:
        with self._lock:
            self.sessions.pop(sid or "", None)
