"""Enttec Open DMX USB (PC makes the DMX timing) and Enttec DMX USB Pro (interface does).

Both keep running if the interface is missing or unplugged mid-gig: the engine carries on, the
status bar shows it as unplugged, and the port is reopened every couple of seconds until it's back.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from .base import OutputDriver

DMX_BAUD = 250000
BREAK_S = 0.000120  # >= 88 us
MAB_S = 0.000016  # >= 8 us
REFRESH_S = 0.025  # 40 Hz
REOPEN_S = 2.0
FRESH_S = 1.0  # a write this recent counts as connected


def _serial(port: str, baudrate: int, stopbits: float) -> Any:
    import serial

    return serial.Serial(port, baudrate=baudrate, bytesize=8, parity="N", stopbits=stopbits, write_timeout=1)


def _spin(seconds: float) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        pass


class _Port:
    """Serial port that can go away and come back."""

    def __init__(self, port: str, factory: Callable[..., Any], baud: int, stopbits: float) -> None:
        self.port, self.factory, self.baud, self.stopbits = port, factory, baud, stopbits
        self.ser: Any = None
        self.last_try = -1e9
        self.ok_at: float | None = None
        self.errors = 0
        self.last_error = ""
        self.reconnects = 0
        self.ensure()

    def ensure(self) -> bool:
        if self.ser is not None:
            return True
        now = time.monotonic()
        if now - self.last_try < REOPEN_S:
            return False
        self.last_try = now
        try:
            self.ser = self.factory(self.port, self.baud, self.stopbits)
            if self.ok_at is not None:
                self.reconnects += 1
            return True
        except Exception as e:
            self.last_error = str(e) or type(e).__name__
            return False

    def failed(self, e: Exception) -> None:
        self.errors += 1
        self.last_error = str(e) or type(e).__name__
        try:
            self.ser.close()
        except Exception:
            pass
        self.ser = None

    def wrote(self) -> None:
        self.ok_at = time.monotonic()

    def close(self) -> None:
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None

    def state(self, label: str, universe: int) -> dict[str, Any]:
        fresh = self.ok_at is not None and time.monotonic() - self.ok_at < FRESH_S
        if self.ser is not None and fresh:
            return {"kind": "output", "name": label, "state": "ok", "detail": f"{self.port} · universe {universe}"}
        if self.ser is not None:
            return {"kind": "output", "name": label, "state": "warn", "detail": f"{self.port} · no frames yet"}
        why = "not found" if self.ok_at is None else "unplugged"
        return {"kind": "output", "name": label, "state": "bad", "detail": f"{self.port} {why}, retrying"}


class EnttecOpenDriver(OutputDriver):
    """FTDI-based Open DMX: we bit-bang break/MAB and stream the packet continuously.

    On Windows set the FTDI latency timer to 1 ms (Device Manager > port > Advanced). A new frame
    is sent as soon as the packet on the wire finishes, not on the next refresh tick.
    """

    name = "enttec_open"

    def __init__(self, port: str, universe: int = 0, serial_factory: Callable[..., Any] = _serial) -> None:
        self.port = port
        self.universe = universe
        self._p = _Port(port, serial_factory, DMX_BAUD, 2)
        self._frame = bytes(512)
        self._new = threading.Event()
        self._stop = threading.Event()
        self.packets = 0
        self._thread = threading.Thread(target=self._run, name="enttec-open", daemon=True)
        self._thread.start()

    @property
    def errors(self) -> int:
        return self._p.errors

    @property
    def _ser(self) -> Any:
        return self._p.ser

    def send(self, universe: int, frame: bytes) -> None:
        if universe != self.universe:
            return
        self._frame = bytes(frame)
        self._new.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._new.clear()
            if not self._p.ensure():
                self._stop.wait(0.25)
                continue
            ser = self._p.ser
            try:
                ser.break_condition = True
                _spin(BREAK_S)
                ser.break_condition = False
                _spin(MAB_S)
                ser.write(b"\x00" + self._frame)
                ser.flush()
                self.packets += 1
                self._p.wrote()
            except Exception as e:
                self._p.failed(e)
                continue
            self._new.wait(REFRESH_S)  # wake early for a new frame (drum hits)

    def close(self) -> None:
        self._stop.set()
        self._new.set()
        self._thread.join(timeout=1)
        self._p.close()

    def status(self) -> dict[str, Any]:
        return {"driver": self.name, "port": self.port, "packets": self.packets, "errors": self.errors}

    def state(self) -> dict[str, Any]:
        return self._p.state("Enttec Open DMX", self.universe)


SOM, EOM, LABEL_SEND_DMX = 0x7E, 0xE7, 6


def pro_packet(frame: bytes) -> bytes:
    data = b"\x00" + bytes(frame)  # start code + 512
    n = len(data)
    return bytes([SOM, LABEL_SEND_DMX, n & 0xFF, n >> 8]) + data + bytes([EOM])


class EnttecProDriver(OutputDriver):
    """DMX USB Pro (and clones): one 'send DMX' packet per frame; the interface keeps refreshing."""

    name = "enttec_pro"

    def __init__(self, port: str, universe: int = 0, serial_factory: Callable[..., Any] = _serial) -> None:
        self.port = port
        self.universe = universe
        self._p = _Port(port, serial_factory, 115200, 1)
        self._lock = threading.Lock()
        self.packets = 0

    @property
    def errors(self) -> int:
        return self._p.errors

    def send(self, universe: int, frame: bytes) -> None:
        if universe != self.universe:
            return
        with self._lock:
            if not self._p.ensure():
                return
            try:
                self._p.ser.write(pro_packet(frame))
                self.packets += 1
                self._p.wrote()
            except Exception as e:
                self._p.failed(e)

    def close(self) -> None:
        self._p.close()

    def status(self) -> dict[str, Any]:
        return {"driver": self.name, "port": self.port, "packets": self.packets, "errors": self.errors}

    def state(self) -> dict[str, Any]:
        return self._p.state("Enttec DMX Pro", self.universe)
