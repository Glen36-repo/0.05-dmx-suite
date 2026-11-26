"""Laptop side of the node link: send frames, read status/heartbeats, track health."""

from __future__ import annotations

import itertools
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

from . import protocol as p
from .health import HealthTracker


class Transport(Protocol):
    def write(self, data: bytes) -> None: ...
    def read(self) -> bytes:
        """Return whatever bytes are available (may be empty). Must not block long."""
        ...
    def close(self) -> None: ...


class SerialTransport:
    """USB CDC serial port (pyserial)."""

    def __init__(self, port: str, timeout: float = 0.01) -> None:
        import serial  # imported here so sim/tests run without pyserial

        self._s = serial.Serial(port, baudrate=115200, timeout=timeout, write_timeout=0.5)

    def write(self, data: bytes) -> None:
        self._s.write(data)

    def read(self) -> bytes:
        n = self._s.in_waiting
        return self._s.read(n or 1)

    def close(self) -> None:
        self._s.close()


@dataclass
class LinkStats:
    frames_sent: int = 0
    crc_errors_rx: int = 0
    decode_errors: int = 0
    last_status: p.Status | None = None
    last_status_at: float | None = None


class NodeLink:
    """Owns a transport. Call `poll()` regularly, or `start()` for a reader thread."""

    def __init__(self, transport: Transport, health: HealthTracker | None = None) -> None:
        self.t = transport
        self.parser = p.Parser()
        self.health = health or HealthTracker()
        self.stats = LinkStats()
        self._tokens = itertools.count(1)
        self._pongs: dict[int, float] = {}
        self._acks: list[p.Ack] = []
        self._cv = threading.Condition()
        self._wlock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.on_message: list[Callable[[p.Message], None]] = []

    # ------------------------------------------------------------------ send

    def _send(self, data: bytes) -> None:
        with self._wlock:
            self.t.write(data)

    def send_frame(self, channels: bytes | bytearray, universe: int = 0) -> None:
        self._send(p.dmx_frame(channels, universe))
        self.stats.frames_sent += 1

    def blackout(self, universe: int = p.UNIVERSE_ALL) -> None:
        self._send(p.blackout(universe))

    def request_status(self) -> None:
        self._send(p.status_req())

    def ping(self, timeout: float = 1.0) -> float | None:
        """Round-trip time in seconds, or None on timeout."""
        token = next(self._tokens) & 0xFFFFFFFF
        t0 = time.perf_counter()
        self._send(p.ping(token))
        if not self._wait(lambda: token in self._pongs, timeout):
            return None
        return self._pongs.pop(token) - t0

    def set_fallback(self, look: p.FallbackLook, timeout: float = 1.0) -> p.AckCode | None:
        return self._request(p.MsgType.SET_FALLBACK, p.set_fallback(look), timeout)

    def assign(self, mac: bytes, universe: int, name: str, timeout: float = 1.0) -> p.AckCode | None:
        return self._request(p.MsgType.ASSIGN, p.assign(mac, universe, name), timeout)

    def identify(self, mac: bytes, seconds: int = 5, timeout: float = 1.0) -> p.AckCode | None:
        return self._request(p.MsgType.IDENTIFY, p.identify(mac, seconds), timeout)

    def _request(self, msg_type: int, data: bytes, timeout: float) -> p.AckCode | None:
        with self._cv:
            self._acks = [a for a in self._acks if a.acked_type != msg_type]
        self._send(data)
        found: list[p.Ack] = []

        def got() -> bool:
            for a in self._acks:
                if a.acked_type == msg_type:
                    found.append(a)
                    self._acks.remove(a)
                    return True
            return False

        return found[0].code if self._wait(got, timeout) else None

    def _wait(self, pred: Callable[[], bool], timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        if self._thread is None:  # no reader thread: poll inline
            while True:
                self.poll()
                with self._cv:
                    if pred():
                        return True
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.001)
        with self._cv:
            return self._cv.wait_for(pred, timeout=max(0.0, deadline - time.monotonic()))

    # ------------------------------------------------------------------ receive

    def poll(self) -> list[p.Message]:
        data = self.t.read()
        msgs: list[p.Message] = []
        if not data:
            self.health.tick()
            return msgs
        for pkt in self.parser.feed(data):
            try:
                msgs.append(p.decode(pkt))
            except p.ProtocolError:
                self.stats.decode_errors += 1
        self.stats.crc_errors_rx = self.parser.crc_errors
        now = time.perf_counter()
        with self._cv:
            for m in msgs:
                if isinstance(m, p.Pong):
                    self._pongs[m.token] = now
                elif isinstance(m, p.Ack):
                    self._acks.append(m)
                elif isinstance(m, p.Status):
                    self.stats.last_status = m
                    self.stats.last_status_at = time.monotonic()
                elif isinstance(m, p.Heartbeat):
                    self.health.update(m)
                elif isinstance(m, p.Announce):
                    self.health.update(m.heartbeat)
            self._cv.notify_all()
        self.health.tick()
        for m in msgs:
            for fn in self.on_message:
                fn(m)
        return msgs

    def start(self) -> None:
        if self._thread:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="node-link-rx", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            if not self.poll():
                time.sleep(0.002)

    def close(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
            self._thread = None
        self.t.close()
