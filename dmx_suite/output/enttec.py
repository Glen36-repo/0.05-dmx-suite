"""Enttec Open DMX USB (PC makes the DMX timing) and Enttec DMX USB Pro (interface does).

Both keep running if the interface is missing or unplugged mid-gig: the engine carries on, the
status bar shows it as unplugged, and the port is reopened every couple of seconds until it's back.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from . import d2xx
from .base import OutputDriver, SenderThread
from .timer import high_res

log = logging.getLogger(__name__)

DMX_BAUD = 250000
SLOTS = 512
BREAK_S = 0.000176  # default break floor (v5: per output `break_us`); on a Windows VCP the USB request makes it ~1-2 ms
MAB_S = 0.000012  # default MAB floor (`mab_us`); likewise ~1 ms in practice
WIRE_S = (1 + SLOTS) * 11 / DMX_BAUD  # start code + 512 slots, 11 bits each: ~22.6 ms on the wire
WIRE_MARGIN_S = 0.001
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
        # drop the port before counting the error, so anyone who sees the error count go up also sees
        # the port gone (state "bad"), never a moment of "warn" with a dead port (another thread reads these)
        last = str(e) or type(e).__name__
        try:
            if self.ser is not None:
                self.ser.close()
        except Exception:
            pass
        self.ser = None
        self.last_error = last
        self.errors += 1
        if not self._failing:  # once per outage, never per frame
            log.warning("%s: write failed (%s), reopening", self.port, self.last_error)
            self._failing = True

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


BREAK_METHODS = ("auto", "d2xx", "serial_break", "baud_drop")
METHOD_NAMES = {"d2xx": "D2XX break", "serial_break": "Serial break", "baud_drop": "Baud drop"}
BREAK_US = (88, 1000, 176)  # min, max, default
MAB_US = (8, 100, 12)
FPS = (1, 44, 40)
MIN_SLOTS = 24  # DMX: shorter packets are padded to 24 slots
WINDOW = 40  # frames kept for the measured timing
TIMING_NOTE = ("Measured on the laptop, best effort: an Open DMX interface has no processor, so what "
               "actually reached the DMX line can't be checked from here.")


def wire_s(slots: int) -> float:
    """Time a frame (start code + slots, 11 bits each at 250 kbaud) takes on the line."""
    return (1 + slots) * 11 / DMX_BAUD


def parse_slots(v: Any) -> int | str:
    if v in (None, "", 512):
        return SLOTS
    if v == "patched":
        return "patched"
    if isinstance(v, bool) or not isinstance(v, int) or not MIN_SLOTS <= v <= SLOTS:
        raise ValueError(f"channels: {MIN_SLOTS}-{SLOTS} or 'patched'")
    return v


def check_timing(break_method: Any = "auto", break_us: Any = None, mab_us: Any = None, fps: Any = None,
                 channels: Any = None) -> dict[str, Any]:
    """An output's timing settings, checked, defaults filled in (rig `outputs:` and set_output)."""
    if break_method in (None, ""):
        break_method = "auto"
    if break_method not in BREAK_METHODS:
        raise ValueError(f"break_method: one of {', '.join(BREAK_METHODS)}")
    out: dict[str, Any] = {"break_method": break_method}
    for key, v, (lo, hi, dflt) in (("break_us", break_us, BREAK_US), ("mab_us", mab_us, MAB_US), ("fps", fps, FPS)):
        if v is None:
            v = dflt
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
            raise ValueError(f"{key}: {lo}-{hi}")
        out[key] = v
    out["channels"] = parse_slots(channels)
    return out


def _serial_number_for(port: str) -> str | None:
    try:
        from serial.tools import list_ports

        for p in list_ports.comports():
            if p.device == port:
                return (p.serial_number or "").strip() or None
    except Exception:  # noqa: BLE001 - no port listing here
        pass
    return None


class EnttecOpenDriver(OutputDriver):
    """FTDI-based Open DMX: the PC makes break, MAB and the stream, continuously, on its own thread.

    Break methods (v5, per output, `break_method:`):

    - `serial_break`: pyserial `break_condition` on the COM port (Windows: SetCommBreak / ClearCommBreak,
      which the FTDI VCP driver turns into the same USB request as FT_SetBreakOn/Off). Each is a USB
      round trip, so on Windows the break is ~1-2 ms and the MAB ~1 ms: legal (88 us-1 s, 8 us-1 s).
    - `baud_drop`: one 0x00 at a low baud fakes the break (start + 8 zero bits = 9 bit times low, the
      stop bits are the MAB), then back to 250k for the frame. Works where break requests don't.
    - `d2xx`: FTDI's D2XX library, FT_SetBreakOn/Off and FT_Write, when it's installed.
    - `auto`: d2xx when D2XX is installed and sees this interface, else serial_break.

    `break_us` / `mab_us` are floors the driver waits for; what the laptop measured is in `timing()`.
    The next break waits for the previous frame's wire time, since flush() returns when the chip has
    the data, not when it is on the wire. A new frame (drum hit) goes as soon as the line is free,
    otherwise frames repeat at `fps`. `channels: patched` sends only up to the last patched channel.

    "ok" means the FTDI chip is taking frames. An Open DMX can't report the DMX line itself: a missing
    DMX cable or a dead RS-485 driver still counts frames.
    """

    name = "enttec_open"

    def __init__(self, port: str, universe: int = 0, serial_factory: Callable[..., Any] = _open_dmx_serial,
                 break_method: str = "auto", break_us: float = BREAK_US[2], mab_us: float = MAB_US[2],
                 fps: float = FPS[2], channels: int | str = SLOTS, serial_number: str | None = None,
                 d2xx_factory: Callable[[str], Any] | None = None, d2xx_available: Callable[[], bool] | None = None) -> None:
        self.port = port
        self.universe: int = universe
        self.serial_number = serial_number
        self._serial_factory = serial_factory
        self._d2xx_factory = d2xx_factory or (lambda sn: d2xx.D2xxPort(sn))
        self._d2xx_available = d2xx_available or d2xx.available
        self._cfg_lock = threading.Lock()
        self.settings = check_timing(break_method, break_us, mab_us, fps, channels)
        self.patched_slots: dict[int, int] = {}  # engine: last patched channel per universe
        self.method = self._resolve(self.settings["break_method"])
        # opened on the driver's thread, never on the one building the rig
        self._p = _Port(port, self._open, DMX_BAUD, 2, open_now=False, on_open=_open_dmx_setup)
        self._frame = bytes(SLOTS)
        self._sent_at = -1e9  # when the last frame was handed to the chip
        self._sent_slots = SLOTS
        self._timer_done = high_res()  # Windows: 1 ms waits, or the wire wait and refresh oversleep by ~15 ms
        self._new = threading.Event()
        self._stop = threading.Event()
        self.packets = 0
        self._meas: deque[tuple[float, float, float, float]] = deque(maxlen=WINDOW)  # start, break, mab, write
        self._basis = "measured"
        self._thread = threading.Thread(target=self._run, name="enttec-open", daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------ settings

    def d2xx_ok(self) -> bool:
        try:
            return bool(self._d2xx_available()) and bool(self.serial_number or _serial_number_for(self.port))
        except Exception:  # noqa: BLE001
            return False

    def _resolve(self, method: str) -> str:
        if method == "auto":
            return "d2xx" if self.d2xx_ok() else "serial_break"
        return method

    def _open(self, port: str, baud: int, stopbits: float) -> Any:
        if self.method == "d2xx":
            sn = self.serial_number or _serial_number_for(port)
            if not sn:
                raise OSError("D2XX needs the interface's serial number (not found for this port)")
            return self._d2xx_factory(sn)
        return self._serial_factory(port, baud, stopbits)

    def configure(self, **changes: Any) -> dict[str, Any]:
        """Change break method / timings live (cycle test, set_output). A switch between the COM port
        and D2XX reopens the interface on the driver's thread."""
        with self._cfg_lock:
            merged = {**self.settings, **{k: v for k, v in changes.items() if v is not None}}
            self.settings = check_timing(**merged)
            method = self._resolve(self.settings["break_method"])
            reopen = (method == "d2xx") != (self.method == "d2xx")
            self.method = method
            self._meas.clear()
        if reopen:
            self._p.close()
            self._p.last_try = -1e9
        self._new.set()
        return dict(self.settings)

    def set_latency(self, ms: int = 1) -> int:
        """Set the FTDI latency timer through D2XX (only while this output runs on D2XX)."""
        ser = self._p.ser
        if self.method != "d2xx" or ser is None or not hasattr(ser, "latency_timer"):
            raise ValueError("the latency timer can only be set here while the output uses D2XX; "
                             "otherwise set it in Device Manager (Port Settings › Advanced › Latency Timer = 1)")
        if not 1 <= ms <= 255:
            raise ValueError("latency 1-255 ms")
        ser.latency_timer = ms
        return int(ser.latency_timer)

    def slots(self) -> int:
        n = self.settings["channels"]
        if n == "patched":
            return max(MIN_SLOTS, min(SLOTS, self.patched_slots.get(self.universe, SLOTS)))
        return int(n)

    # ------------------------------------------------------------------ sending

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
        free_at = self._sent_at + wire_s(self._sent_slots) + WIRE_MARGIN_S
        self._wait_until(free_at)

    def _wait_until(self, t: float) -> None:
        left = t - time.perf_counter()
        if left > 0.002:
            self._stop.wait(left - 0.002)
        left = t - time.perf_counter()
        if left > 0:
            _spin(left)

    def _break_mab(self, ser: Any, break_s: float, mab_s: float) -> tuple[float, float, float]:
        """Make break and MAB; returns (break, MAB, MAB end) as the laptop saw them."""
        if self.method == "baud_drop":
            low = max(300, round(9 / break_s))  # 9 bit times low = the break
            ser.baudrate = low
            t0 = time.perf_counter()
            ser.write(b"\x00")
            ser.flush()
            _spin(max(0.0, t0 + 11 / low - time.perf_counter()))  # start, 8 zeros, 2 stop bits on the line
            t1 = time.perf_counter()
            ser.baudrate = DMX_BAUD
            _spin(max(0.0, mab_s - 2 / low - (time.perf_counter() - t1)))
            end = time.perf_counter()
            self._basis = "computed"  # the break length is set by the baud rate, not timed
            return 9 / low, 2 / low + (end - t1), end
        ser.break_condition = True
        t_on = time.perf_counter()
        _spin(break_s)
        ser.break_condition = False
        t_off = time.perf_counter()
        _spin(mab_s)
        end = time.perf_counter()
        self._basis = "measured"
        return t_off - t_on, end - t_off, end

    def _run(self) -> None:
        while not self._stop.is_set():
            self._new.clear()
            if not self._p.ensure():
                self._stop.wait(0.25)
                continue
            ser = self._p.ser
            self._wait_for_wire()
            st = self.settings
            n = self.slots()
            start = time.perf_counter()
            try:
                brk, mab, t_data = self._break_mab(ser, st["break_us"] / 1e6, st["mab_us"] / 1e6)
                frame = self._frame
                data = b"\x00" + frame[:n]  # start code, then channel 1 at index 1
                self._sent_at = t_data
                self._sent_slots = n
                w = ser.write(data)  # the whole frame in one write
                if w is not None and w != len(data):
                    raise OSError(f"short write: {w} of {len(data)} bytes")
                ser.flush()
                self._meas.append((start, brk, mab, time.perf_counter() - t_data))
                self.packets += 1
                self._p.wrote()
                self.wire.record(self.universe, frame)
            except Exception as e:
                self._p.failed(e)
                self._meas.clear()  # an outage isn't a slow frame rate
                continue
            # wake early for a new frame (drum hits), else repeat at the target rate
            self._new.wait(max(0.0, start + 1 / st["fps"] - time.perf_counter()))

    def close(self) -> None:
        self._stop.set()
        self._new.set()
        self._thread.join(timeout=1)
        self._p.close()
        self._timer_done()
        self._timer_done = lambda: None

    # ------------------------------------------------------------------ reporting

    def timing(self) -> dict[str, Any]:
        """Targets beside what the laptop measured, with warnings (break < 88 us, MAB < 8 us, fps < 80 %)."""
        st = dict(self.settings)
        meas = list(self._meas)
        m: dict[str, Any] = {"break_us": None, "mab_us": None, "fps": None, "write_ms": None, "jitter_ms": None,
                             "basis": self._basis}
        warn: list[str] = []
        if meas:
            m["break_us"] = round(min(x[1] for x in meas) * 1e6)
            m["mab_us"] = round(min(x[2] for x in meas) * 1e6)
            m["write_ms"] = round(sum(x[3] for x in meas) / len(meas) * 1000, 2)
            fresh = time.perf_counter() - meas[-1][0] < 2
            if len(meas) >= 3 and fresh:
                dts = [b[0] - a[0] for a, b in zip(meas, meas[1:])]
                avg = sum(dts) / len(dts)
                m["fps"] = round(1 / avg, 1) if avg > 0 else None
                m["jitter_ms"] = round((sum((d - avg) ** 2 for d in dts) / len(dts)) ** 0.5 * 1000, 2)
            if m["break_us"] < 88:
                warn.append(f"break {m['break_us']} µs, under 88")
            if m["mab_us"] < 8:
                warn.append(f"MAB {m['mab_us']} µs, under 8")
            if m["fps"] is not None and m["fps"] < 0.8 * st["fps"]:
                warn.append(f"{m['fps']} fps, under 80 % of {st['fps']}")
        return {"method": self.method, "method_name": METHOD_NAMES.get(self.method, self.method),
                "backend": "d2xx" if self.method == "d2xx" else "com", "d2xx_available": self.d2xx_ok(),
                "target": {**st, "slots": self.slots()}, "measured": m, "warnings": warn, "note": TIMING_NOTE}

    def status(self) -> dict[str, Any]:
        return {"driver": self.name, "port": self.port, "packets": self.packets, "errors": self.errors,
                "last_error": self._p.last_error, "reconnects": self._p.reconnects, "timing": self.timing()}

    def state(self) -> dict[str, Any]:
        s = self._p.state("USB DMX (Open)", self.universe)
        if s["state"] == "ok":
            warn = self.timing()["warnings"]
            if warn:
                s["state"], s["detail"] = "warn", f"{s['detail']} · {warn[0]}"
        return s


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
