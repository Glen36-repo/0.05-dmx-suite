"""Enttec Open DMX USB (PC makes the DMX timing) and Enttec DMX USB Pro (interface does).

Both keep running if the interface is missing or unplugged mid-gig: the engine carries on, the
status bar shows it as unplugged, and the port is reopened every couple of seconds until it's back.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from .base import OutputDriver, SenderThread
from .timer import high_res

log = logging.getLogger(__name__)

DMX_BAUD = 250000
SLOTS = 512
BREAK_S = 0.000120  # >= 88 us (the spin is a floor: on a Windows VCP the USB request makes it ~1-2 ms)
MAB_S = 0.000016  # >= 8 us (likewise ~1 ms in practice)
WIRE_S = (1 + SLOTS) * 11 / DMX_BAUD  # start code + 512 slots, 11 bits each: ~22.6 ms on the wire
WIRE_MARGIN_S = 0.001
REFRESH_S = 0.025  # idle refresh; with break, MAB and wire time a frame takes ~26-27 ms (~37-38 fps)
REOPEN_S = 2.0
FRESH_S = 1.0  # a write this recent counts as connected


def _serial(port: str, baudrate: int, stopbits: float, rts: bool | None = None) -> Any:
    """Open the port with flow control off; `rts=False` keeps RTS (and DTR) low from the moment it opens."""
    import serial

    ser = serial.Serial()  # not opened yet, so RTS/DTR can be set before pyserial raises them on open
    ser.port = port
    ser.baudrate, ser.bytesize, ser.parity, ser.stopbits = baudrate, 8, "N", stopbits
    ser.rtscts = ser.xonxoff = ser.dsrdtr = False
    ser.write_timeout = 1
    if rts is not None:
        ser.rts = rts
        ser.dtr = rts
    ser.open()
    return ser


def _spin(seconds: float) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        pass


class _Port:
    """Serial port that can go away and come back."""

    def __init__(self, port: str, factory: Callable[..., Any], baud: int, stopbits: float, *,
                 open_now: bool = True, on_open: Callable[[Any], None] | None = None) -> None:
        self.port, self.factory, self.baud, self.stopbits = port, factory, baud, stopbits
        self.on_open = on_open
        self.ser: Any = None
        self.last_try = -1e9
        self.ok_at: float | None = None
        self.errors = 0
        self.last_error = ""
        self.reconnects = 0
        self._failing = False
        if open_now:
            self.ensure()

    def ensure(self) -> bool:
        if self.ser is not None:
            return True
        now = time.monotonic()
        if now - self.last_try < REOPEN_S:
            return False
        self.last_try = now
        try:
            ser = self.factory(self.port, self.baud, self.stopbits)
            if self.on_open is not None:
                self.on_open(ser)
            self.ser = ser
            if self.ok_at is not None:
                self.reconnects += 1
                log.info("%s reopened", self.port)
            return True
        except Exception as e:
            self.last_error = str(e) or type(e).__name__
            return False

    def failed(self, e: Exception) -> None:
        self.errors += 1
        self.last_error = str(e) or type(e).__name__
        if not self._failing:  # once per outage, never per frame
            log.warning("%s: write failed (%s), reopening", self.port, self.last_error)
            self._failing = True
        try:
            if self.ser is not None:
                self.ser.close()
        except Exception:
            pass
        self.ser = None

    def wrote(self) -> None:
        self.ok_at = time.monotonic()
        self._failing = False

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
        err = f" ({self.last_error})" if self.last_error else ""
        return {"kind": "output", "name": label, "state": "bad", "detail": f"{self.port} {why}, retrying{err}"}


def _open_dmx_setup(ser: Any) -> None:
    """Enttec's Open DMX sample: flow control off (done in _serial), clear RTS, purge both buffers.
    Some FTDI clones use RTS as the RS-485 transmit enable, so RTS raised on open can leave the line dead."""
    steps: tuple[tuple[str, Callable[[], Any]], ...] = (
        ("clear RTS", lambda: setattr(ser, "rts", False)), ("clear DTR", lambda: setattr(ser, "dtr", False)),
        ("purge input", lambda: ser.reset_input_buffer()), ("purge output", lambda: ser.reset_output_buffer()))
    for what, step in steps:  # best effort: a port that refuses one of these may still send DMX
        try:
            step()
        except Exception as e:
            log.warning("%s: couldn't %s (%s)", getattr(ser, "port", "?"), what, e)


def _open_dmx_serial(port: str, baudrate: int, stopbits: float) -> Any:
    return _serial(port, baudrate, stopbits, rts=False)


class EnttecOpenDriver(OutputDriver):
    """FTDI-based Open DMX: the PC makes break, MAB and the stream, continuously, on its own thread.

    Break and MAB come from pyserial's break_condition (Windows: SetCommBreak / ClearCommBreak, which the
    FTDI VCP driver turns into the same USB request as D2XX FT_SetBreakOn/Off). Each takes a USB round
    trip, so the break is ~1-2 ms and the MAB ~1 ms: inside DMX's limits (88 us to 1 s, 8 us to 1 s).
    flush() returns when the chip has the data, not when it is on the wire, so the next break waits for
    the previous frame's wire time (WIRE_S); a new frame still goes as soon as the line is free.
    Steady rate ~37-38 fps. On Windows set the FTDI latency timer to 1 ms (Device Manager > port > Advanced).

    "ok" means the FTDI chip is taking frames. An Open DMX can't report the DMX line itself: a missing
    DMX cable or a dead RS-485 driver still counts frames.
    """

    name = "enttec_open"

    def __init__(self, port: str, universe: int = 0, serial_factory: Callable[..., Any] = _open_dmx_serial) -> None:
        self.port = port
        self.universe: int = universe
        # opened on the driver's thread, never on the one building the rig
        self._p = _Port(port, serial_factory, DMX_BAUD, 2, open_now=False, on_open=_open_dmx_setup)
        self._frame = bytes(SLOTS)
        self._sent_at = -1e9  # when the last frame was handed to the chip
        self._timer_done = high_res()  # Windows: 1 ms waits, or the wire wait and refresh oversleep by ~15 ms
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
        self._frame = bytes(frame[:SLOTS]).ljust(SLOTS, b"\x00")  # always 512 slots
        self._new.set()

    def _wait_for_wire(self) -> None:
        """Don't break into the previous frame: wait until it has left the chip."""
        free_at = self._sent_at + WIRE_S + WIRE_MARGIN_S
        left = free_at - time.perf_counter()
        if left > 0.002:
            self._stop.wait(left - 0.002)
        left = free_at - time.perf_counter()
        if left > 0:
            _spin(left)

    def _run(self) -> None:
        while not self._stop.is_set():
            self._new.clear()
            if not self._p.ensure():
                self._stop.wait(0.25)
                continue
            ser = self._p.ser
            self._wait_for_wire()
            try:
                ser.break_condition = True
                _spin(BREAK_S)
                ser.break_condition = False
                _spin(MAB_S)
                frame = self._frame
                data = b"\x00" + frame  # start code, then channel 1 at index 1
                self._sent_at = time.perf_counter()
                n = ser.write(data)  # the whole frame in one write
                if n is not None and n != len(data):
                    raise OSError(f"short write: {n} of {len(data)} bytes")
                ser.flush()
                self.packets += 1
                self._p.wrote()
                self.wire.record(self.universe, frame)
            except Exception as e:
                self._p.failed(e)
                continue
            self._new.wait(REFRESH_S)  # wake early for a new frame (drum hits)

    def close(self) -> None:
        self._stop.set()
        self._new.set()
        self._thread.join(timeout=1)
        self._p.close()
        self._timer_done()
        self._timer_done = lambda: None

    def status(self) -> dict[str, Any]:
        return {"driver": self.name, "port": self.port, "packets": self.packets, "errors": self.errors,
                "last_error": self._p.last_error, "reconnects": self._p.reconnects}

    def state(self) -> dict[str, Any]:
        return self._p.state("USB DMX (Open)", self.universe)


SOM, EOM, LABEL_SEND_DMX = 0x7E, 0xE7, 6


def pro_packet(frame: bytes) -> bytes:
    data = b"\x00" + bytes(frame)  # start code + 512
    n = len(data)
    return bytes([SOM, LABEL_SEND_DMX, n & 0xFF, n >> 8]) + data + bytes([EOM])


class EnttecProDriver(OutputDriver):
    """DMX USB Pro (and clones): one 'send DMX' packet per frame; the interface keeps refreshing."""

    name = "enttec_pro"

    def __init__(self, port: str, universe: int = 0, serial_factory: Callable[..., Any] = _serial,
                 threaded: bool = True) -> None:
        self.port = port
        self.universe: int = universe
        self._lock = threading.Lock()
        self.packets = 0
        self._sender = SenderThread(self._write, self.name) if threaded else None
        with self._lock:  # first open (and any later reopen) happens off the engine thread when threaded
            self._p = _Port(port, serial_factory, 115200, 1)

    @property
    def errors(self) -> int:
        return self._p.errors

    def send(self, universe: int, frame: bytes) -> None:
        if universe != self.universe:
            return
        if self._sender is not None:
            self._sender.put(universe, frame)
        else:
            self._write(universe, frame)

    def flush(self, timeout: float = 2.0) -> bool:
        return self._sender.flush(timeout) if self._sender else True

    def _write(self, universe: int, frame: bytes) -> None:
        with self._lock:
            if not self._p.ensure():
                return
            try:
                self._p.ser.write(pro_packet(frame))
                self.packets += 1
                self._p.wrote()
                self.wire.record(universe, frame)
            except Exception as e:
                self._p.failed(e)

    def close(self) -> None:
        if self._sender is not None:
            self._sender.close()
        self._p.close()

    def status(self) -> dict[str, Any]:
        return {"driver": self.name, "port": self.port, "packets": self.packets, "errors": self.errors,
                "dropped": self._sender.dropped if self._sender else 0, "last_error": self._p.last_error,
                "reconnects": self._p.reconnects}

    def state(self) -> dict[str, Any]:
        return self._p.state("USB DMX Pro", self.universe)
