"""OSC input: a UDP listener for controllers such as TouchOSC or a lighting desk. Off unless the
rig file turns it on:

    osc:
      port: 9000
      allow: [192.168.1.0/24]        # who may send; default: this computer and private networks

Messages go through the same map and router as MIDI: a mapping `{type: osc, address: /dmx/grand,
action: grand_master}` in the MIDI map file. A float argument (0-1) drives faders directly; for
buttons, a value of 0.5 or more (or no argument) is a press. Bundles are unpacked. The listener
runs on its own thread and never holds up the engine.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import struct
import threading
import time
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

PRIVATE = ["127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "::1/128"]


class OscError(ValueError):
    pass


def _string(data: bytes, i: int) -> tuple[str, int]:
    end = data.index(b"\x00", i)
    return data[i:end].decode("utf-8", "replace"), (end + 4) & ~3


def parse_message(data: bytes) -> tuple[str, list[Any]]:
    try:
        address, i = _string(data, 0)
        if not address.startswith("/"):
            raise OscError(f"not an OSC address: {address!r}")
        if i >= len(data):
            return address, []
        tags, i = _string(data, i)
        if not tags.startswith(","):
            raise OscError("missing OSC type tags")
        args: list[Any] = []
        for tag in tags[1:]:
            if tag == "i":
                args.append(struct.unpack(">i", data[i:i + 4])[0])
                i += 4
            elif tag == "f":
                args.append(struct.unpack(">f", data[i:i + 4])[0])
                i += 4
            elif tag == "h":
                args.append(struct.unpack(">q", data[i:i + 8])[0])
                i += 8
            elif tag == "d":
                args.append(struct.unpack(">d", data[i:i + 8])[0])
                i += 8
            elif tag == "s":
                s, i = _string(data, i)
                args.append(s)
            elif tag == "b":
                n = struct.unpack(">i", data[i:i + 4])[0]
                args.append(data[i + 4:i + 4 + n])
                i = (i + 4 + n + 3) & ~3
            elif tag in "TF":
                args.append(tag == "T")
            elif tag in "NI":
                args.append(None)
            else:
                raise OscError(f"OSC type {tag!r} not supported")
        return address, args
    except (struct.error, ValueError) as e:
        raise OscError(f"bad OSC message: {e}") from e


def parse_packet(data: bytes) -> list[tuple[str, list[Any]]]:
    """Messages in a packet (bundles unpacked, nested ones too)."""
    if data.startswith(b"#bundle\x00"):
        out, i = [], 16  # "#bundle\0" + 8-byte time tag
        while i + 4 <= len(data):
            n = struct.unpack(">i", data[i:i + 4])[0]
            out += parse_packet(data[i + 4:i + 4 + n])
            i += 4 + n
        return out
    return [parse_message(data)]


def build_message(address: str, *args: Any) -> bytes:
    """An OSC message (for tests and tools): ints, floats, strings, bools."""
    def pad(b: bytes) -> bytes:
        return b + b"\x00" * (4 - len(b) % 4)

    tags, body = ",", b""
    for a in args:
        if isinstance(a, bool):
            tags += "T" if a else "F"
        elif isinstance(a, int):
            tags, body = tags + "i", body + struct.pack(">i", a)
        elif isinstance(a, float):
            tags, body = tags + "f", body + struct.pack(">f", a)
        else:
            tags, body = tags + "s", body + pad(str(a).encode())
    return pad(address.encode()) + pad(tags.encode()) + body


def level_of(args: list[Any]) -> float | None:
    """The first number argument as 0-1 (bools count; ints above 1 are read as 0-127)."""
    for a in args:
        if isinstance(a, bool):
            return 1.0 if a else 0.0
        if isinstance(a, (int, float)):
            v = float(a)
            if isinstance(a, int) and v > 1:
                v /= 127
            return min(1.0, max(0.0, v))
    return None


class OscServer:
    """Listens on a UDP port and hands each message to `handle(address, args, source)`."""

    def __init__(self, handle: Callable[[str, list[Any], str], Any], port: int, allow: list[str] | None = None,
                 host: str = "0.0.0.0") -> None:
        self.handle = handle
        self.port = int(port)
        self.allow = [ipaddress.ip_network(a, strict=False) for a in (allow or PRIVATE)]
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((host, self.port))
        self.port = self.sock.getsockname()[1]  # port 0: whatever's free (tests)
        self.sock.settimeout(0.5)
        self.received = 0
        self.refused = 0
        self.errors = 0
        self.last_at: float | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="osc", daemon=True)

    def start(self) -> OscServer:
        self._thread.start()
        return self

    def allowed(self, ip: str) -> bool:
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return any(a in net for net in self.allow)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                data, (ip, _) = self.sock.recvfrom(65535)
            except TimeoutError:
                continue
            except OSError:
                if self._stop.is_set():
                    return
                continue
            if not self.allowed(ip):
                self.refused += 1
                continue
            try:
                for address, args in parse_packet(data):
                    self.received += 1
                    self.last_at = time.monotonic()
                    self.handle(address, args, ip)
            except OscError as e:
                self.errors += 1
                log.debug("OSC from %s: %s", ip, e)
            except Exception:  # noqa: BLE001 - one bad message must not stop the listener
                self.errors += 1
                log.exception("OSC handling failed")

    def stop(self) -> None:
        self._stop.set()
        self.sock.close()
        self._thread.join(timeout=1)

    def state(self) -> dict[str, Any]:
        recent = self.last_at is not None and time.monotonic() - self.last_at < 10
        detail = f"port {self.port} · {self.received} messages" + (f" · {self.refused} refused" if self.refused else "")
        return {"kind": "osc", "name": "OSC", "state": "ok" if recent else "idle", "detail": detail}
