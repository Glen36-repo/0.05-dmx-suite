"""Enttec Open DMX USB (PC makes the DMX timing) and Enttec DMX USB Pro (interface does)."""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from .base import OutputDriver

DMX_BAUD = 250000
BREAK_S = 0.000120  # >= 88 us
MAB_S = 0.000016  # >= 8 us
REFRESH_S = 0.025  # 40 Hz


def _serial(port: str, baudrate: int, stopbits: float) -> Any:
    import serial

    return serial.Serial(port, baudrate=baudrate, bytesize=8, parity="N", stopbits=stopbits, write_timeout=1)


def _spin(seconds: float) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        pass


class EnttecOpenDriver(OutputDriver):
    """FTDI-based Open DMX: we bit-bang break/MAB and stream the packet continuously.

    On Windows set the FTDI latency timer to 1 ms (Device Manager > port > Advanced). A new frame
    is sent as soon as the packet on the wire finishes, not on the next refresh tick.
    """

    name = "enttec_open"

    def __init__(self, port: str, universe: int = 0, serial_factory: Callable[..., Any] = _serial) -> None:
        self.port = port
        self.universe = universe
        self._ser = serial_factory(port, DMX_BAUD, 2)
        self._frame = bytes(512)
        self._new = threading.Event()
        self._stop = threading.Event()
        self.packets = 0
        self.errors = 0
        self._thread = threading.Thread(target=self._run, name="enttec-open", daemon=True)
        self._thread.start()

    def send(self, universe: int, frame: bytes) -> None:
        if universe != self.universe:
            return
        self._frame = bytes(frame)
        self._new.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._new.clear()
            try:
                self._ser.break_condition = True
                _spin(BREAK_S)
                self._ser.break_condition = False
                _spin(MAB_S)
                self._ser.write(b"\x00" + self._frame)
                self._ser.flush()
                self.packets += 1
            except Exception:
                self.errors += 1
                time.sleep(0.5)
            self._new.wait(REFRESH_S)  # wake early for a new frame (drum hits)

    def close(self) -> None:
        self._stop.set()
        self._new.set()
        self._thread.join(timeout=1)
        self._ser.close()

    def status(self) -> dict[str, Any]:
        return {"driver": self.name, "port": self.port, "packets": self.packets, "errors": self.errors}


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
        self._ser = serial_factory(port, 115200, 1)
        self._lock = threading.Lock()
        self.packets = 0
        self.errors = 0

    def send(self, universe: int, frame: bytes) -> None:
        if universe != self.universe:
            return
        try:
            with self._lock:
                self._ser.write(pro_packet(frame))
            self.packets += 1
        except Exception:
            self.errors += 1

    def close(self) -> None:
        self._ser.close()

    def status(self) -> dict[str, Any]:
        return {"driver": self.name, "port": self.port, "packets": self.packets, "errors": self.errors}
