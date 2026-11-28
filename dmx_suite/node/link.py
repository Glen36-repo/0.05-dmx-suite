"""Laptop side of the node link: send frames, read status/heartbeats, track health."""

from __future__ import annotations

import itertools
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

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


class ReconnectingSerial:
    """The node's USB port, surviving an unplug: writes are dropped and reads return nothing while
    it's gone, and it's reopened every couple of seconds (Windows keeps the COM number for a device)."""

    REOPEN_S = 2.0

    def __init__(self, port: str, opener: Callable[[str], Transport] | None = None) -> None:
        self.port = port
        self._opener = opener or SerialTransport
        self._t: Transport | None = None
        self._last_try = -1e9
        self.connected_once = False
        self.errors = 0
        self.last_error = ""
        self._lock = threading.Lock()
        self._ensure()

    @property
    def is_open(self) -> bool:
        return self._t is not None

    def _ensure(self) -> Transport | None:
        if self._t is not None:
            return self._t
        now = time.monotonic()
        if now - self._last_try < self.REOPEN_S:
            return None
        self._last_try = now
        try:
            self._t = self._opener(self.port)
            self.connected_once = True
        except Exception as e:
            self.last_error = str(e) or type(e).__name__
        return self._t

    def _fail(self, e: Exception) -> None:
        self.errors += 1
        self.last_error = str(e) or type(e).__name__
        try:
            if self._t is not None:
                self._t.close()
        except Exception:
            pass
        self._t = None

    def write(self, data: bytes) -> None:
        with self._lock:
            t = self._ensure()
            if t is None:
                return
            try:
                t.write(data)
            except Exception as e:
                self._fail(e)

    def read(self) -> bytes:
        with self._lock:
            t = self._ensure()
        if t is None:
            time.sleep(0.05)
            return b""
        try:
            return t.read()
        except Exception as e:
            with self._lock:
                self._fail(e)
            return b""

    def close(self) -> None:
        with self._lock:
            if self._t is not None:
                self._t.close()
                self._t = None


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
        self._req_ids = itertools.cycle(range(1, 256))
        self._poll_lock = threading.Lock()  # the simulated node can be polled from two threads
        self.node_fw: tuple[int, int, int] | None = None  # the node's firmware, from its heartbeat
        self.on_node_announce: list[Callable[[p.Heartbeat], None]] = []  # node (re)connected
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

    @property
    def v11(self) -> bool:
        """The node speaks protocol v1.1 (firmware 0.2): request ids, per-universe fallbacks, channel."""
        return p.supports_v11(self.node_fw)

    def set_fallback(self, look: p.FallbackLook, universe: int | None = None, timeout: float = 1.0) -> p.AckCode | None:
        """Store a fallback look: for one universe (firmware 0.2), else the node's own universe."""
        if universe is not None and self.v11:
            return self._request(p.MsgType.SET_FALLBACK_UNIVERSE, lambda r: p.set_fallback_universe(universe, look, r), timeout)
        return self._request(p.MsgType.SET_FALLBACK, lambda r: p.set_fallback(look, r), timeout)

    def set_channel(self, channel: int, timeout: float = 1.0) -> p.AckCode | None:
        if not self.v11:
            return p.AckCode.UNKNOWN_TYPE  # firmware 0.1 has a fixed channel
        return self._request(p.MsgType.SET_CHANNEL, lambda r: p.set_channel(channel, r), timeout)

    def assign(self, mac: bytes, universe: int, name: str, timeout: float = 1.0) -> p.AckCode | None:
        return self._request(p.MsgType.ASSIGN, lambda r: p.assign(mac, universe, name, r), timeout)

    def assign_confirmed(self, mac: bytes, universe: int, name: str, timeout: float = 1.0,
                         confirm_s: float = 4.0) -> tuple[p.AckCode | None, bool]:
        """ASSIGN, then wait for that node's own heartbeat to show the new name and universe (the
        radio link to a receiver is one-way, so its heartbeat is the only proof it took it)."""
        since = time.monotonic()
        code = self.assign(mac, universe, name, timeout)
        if code != p.AckCode.OK:
            return code, False
        want_uni = None if universe == p.UNIVERSE_NONE else universe
        key = p.mac_str(mac)

        def took() -> bool:
            rec = self.health.nodes.get(key)
            hb = rec.heartbeat if rec else None
            return (rec is not None and hb is not None and rec.last_seen is not None and rec.last_seen >= since
                    and hb.name == name and (hb.universe == want_uni or hb.node_type == p.NodeType.DMX_TX))

        return code, self._wait(took, confirm_s)

    def identify(self, mac: bytes, seconds: int = 5, timeout: float = 1.0) -> p.AckCode | None:
        return self._request(p.MsgType.IDENTIFY, lambda r: p.identify(mac, seconds, r), timeout)

    def _request(self, msg_type: int, build: Callable[[int | None], bytes], timeout: float) -> p.AckCode | None:
        """Send a request that gets an ACK. To firmware 0.2 it carries a request id, so an ACK for an
        earlier request of the same type (one that timed out) can't be taken for this one's."""
        req = next(self._req_ids) if self.v11 else None
        with self._cv:
            self._acks = [a for a in self._acks if a.acked_type != msg_type]
        self._send(build(req))
        found: list[p.Ack] = []

        def got() -> bool:
            for a in self._acks:
                if a.acked_type == msg_type and (req is None or a.req is None or a.req == req):
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
        with self._poll_lock:
            return self._poll()

    def _poll(self) -> list[p.Message]:
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
                    if m.node_type == p.NodeType.DMX_TX:
                        self.node_fw = m.fw
                elif isinstance(m, p.Announce):
                    self.health.update(m.heartbeat)
                    if m.heartbeat.node_type == p.NodeType.DMX_TX:
                        self.node_fw = m.heartbeat.fw
            self._cv.notify_all()
        self.health.tick()
        for m in msgs:
            for fn in self.on_message:
                fn(m)
            if isinstance(m, p.Announce) and m.heartbeat.node_type == p.NodeType.DMX_TX:
                for hook in self.on_node_announce:  # node plugged in or restarted
                    hook(m.heartbeat)
        return msgs

    def start(self) -> None:
        if self._thread:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="node-link-rx", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                if not self.poll():
                    time.sleep(0.002)
            except Exception:  # a bad read must never stop the status/heartbeat reader
                time.sleep(0.1)

    def close(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
            self._thread = None
        self.t.close()
