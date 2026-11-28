"""FTDI D2XX, loaded through ctypes when FTDI's driver library is installed (v5, optional).

No Python package: on Windows `ftd2xx.dll` comes with FTDI's CDM driver (the same install that gives
the COM port), on Linux / macOS `libftd2xx`. Without it the Open DMX driver uses the COM port
(pyserial) and the `d2xx` break method isn't offered.

`D2xxPort` looks enough like a pyserial port (break_condition, baudrate, write, flush, rts / dtr,
reset_*_buffer, close) for the Open DMX driver to use either. Tests pass a fake library object.
"""

from __future__ import annotations

import ctypes
import sys
import time
from typing import Any

FT_OK = 0
FT_DEVICE_NOT_FOUND = 2
FT_DEVICE_NOT_OPENED = 3
FT_OPEN_BY_SERIAL_NUMBER = 1
FT_PURGE_RX, FT_PURGE_TX = 1, 2
FT_BITS_8, FT_STOP_BITS_2, FT_PARITY_NONE = 8, 2, 0
FT_FLOW_NONE = 0
STATUS = {0: "ok", 1: "invalid handle", 2: "device not found", 3: "device not opened (in use by another program?)",
          4: "I/O error", 5: "insufficient resources", 6: "invalid parameter"}

_lib: Any = None
_tried = False


def _names() -> tuple[str, ...]:
    if sys.platform == "win32":
        return ("ftd2xx", "ftd2xx64")
    if sys.platform == "darwin":
        return ("libftd2xx.dylib",)
    return ("libftd2xx.so", "libftd2xx.so.1")


def load(force: Any = None) -> Any:
    """The D2XX library, or None when it isn't installed. `force` (tests) replaces it; False clears it."""
    global _lib, _tried
    if force is not None:
        _lib, _tried = (None if force is False else force), True
        return _lib
    if _tried:
        return _lib
    _tried = True
    for n in _names():
        try:
            if sys.platform == "win32":  # mypy checks each platform's branch on that platform
                _lib = ctypes.WinDLL(n)
            else:
                _lib = ctypes.CDLL(n)
            return _lib
        except OSError:
            continue
    return None


def available() -> bool:
    return load() is not None


class D2xxError(OSError):
    def __init__(self, what: str, code: int) -> None:
        super().__init__(f"D2XX {what}: {STATUS.get(code, f'status {code}')}")
        self.code = code


def _check(what: str, code: int) -> None:
    if code != FT_OK:
        raise D2xxError(what, code)


def devices(lib: Any = None) -> list[dict[str, Any]]:
    """FTDI devices D2XX can see: serial number, description, whether another program has it open."""
    lib = lib or load()
    if lib is None:
        return []
    n = ctypes.c_ulong(0)
    if lib.FT_CreateDeviceInfoList(ctypes.byref(n)) != FT_OK:
        return []
    out = []
    for i in range(n.value):
        flags, typ, dev_id, loc = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_ulong()
        sn, desc, h = ctypes.create_string_buffer(16), ctypes.create_string_buffer(64), ctypes.c_void_p()
        if lib.FT_GetDeviceInfoDetail(i, ctypes.byref(flags), ctypes.byref(typ), ctypes.byref(dev_id),
                                      ctypes.byref(loc), sn, desc, ctypes.byref(h)) != FT_OK:
            continue
        out.append({"serial_number": sn.value.decode(errors="replace"), "description": desc.value.decode(errors="replace"),
                    "open": bool(flags.value & 1)})  # FT_FLAGS_OPENED
    return out


class D2xxPort:
    """One FTDI device opened through D2XX by serial number, set up for DMX (250k 8N2, no flow control)."""

    def __init__(self, serial_number: str, baudrate: int = 250000, lib: Any = None) -> None:
        self.lib = lib or load()
        if self.lib is None:
            raise OSError("D2XX isn't installed (FTDI's ftd2xx library)")
        self.serial_number = serial_number
        self.port = f"D2XX {serial_number}"
        self.h = ctypes.c_void_p()
        _check("open", self.lib.FT_OpenEx(ctypes.c_char_p(serial_number.encode()), FT_OPEN_BY_SERIAL_NUMBER,
                                          ctypes.byref(self.h)))
        self._baud = 0
        try:
            self.baudrate = baudrate
            _check("8N2", self.lib.FT_SetDataCharacteristics(self.h, FT_BITS_8, FT_STOP_BITS_2, FT_PARITY_NONE))
            _check("flow control", self.lib.FT_SetFlowControl(self.h, FT_FLOW_NONE, 0, 0))
        except Exception:
            self.close()
            raise

    # pyserial-like surface ------------------------------------------------------------
    @property
    def baudrate(self) -> int:
        return self._baud

    @baudrate.setter
    def baudrate(self, b: int) -> None:
        _check("baud rate", self.lib.FT_SetBaudRate(self.h, int(b)))
        self._baud = int(b)

    @property
    def break_condition(self) -> None:
        return None

    @break_condition.setter
    def break_condition(self, on: bool) -> None:
        _check("break", (self.lib.FT_SetBreakOn if on else self.lib.FT_SetBreakOff)(self.h))

    @property
    def rts(self) -> None:
        return None

    @rts.setter
    def rts(self, v: bool) -> None:
        _check("RTS", (self.lib.FT_SetRts if v else self.lib.FT_ClrRts)(self.h))

    @property
    def dtr(self) -> None:
        return None

    @dtr.setter
    def dtr(self, v: bool) -> None:
        _check("DTR", (self.lib.FT_SetDtr if v else self.lib.FT_ClrDtr)(self.h))

    def reset_input_buffer(self) -> None:
        _check("purge", self.lib.FT_Purge(self.h, FT_PURGE_RX))

    def reset_output_buffer(self) -> None:
        _check("purge", self.lib.FT_Purge(self.h, FT_PURGE_TX))

    def write(self, data: bytes) -> int:
        n = ctypes.c_ulong(0)
        buf = ctypes.create_string_buffer(bytes(data), len(data))
        _check("write", self.lib.FT_Write(self.h, buf, len(data), ctypes.byref(n)))
        return n.value

    def flush(self, timeout: float = 0.1) -> None:
        """Until the chip's transmit queue is empty (like pyserial: the chip has it, not the wire)."""
        end = time.perf_counter() + timeout
        rx, tx, ev = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_ulong()
        while time.perf_counter() < end:
            _check("status", self.lib.FT_GetStatus(self.h, ctypes.byref(rx), ctypes.byref(tx), ctypes.byref(ev)))
            if tx.value == 0:
                return

    def close(self) -> None:
        if self.h:
            try:
                self.lib.FT_Close(self.h)
            finally:
                self.h = ctypes.c_void_p()

    # D2XX only ---------------------------------------------------------------------------
    @property
    def latency_timer(self) -> int:
        v = ctypes.c_ubyte(0)
        _check("latency timer", self.lib.FT_GetLatencyTimer(self.h, ctypes.byref(v)))
        return v.value

    @latency_timer.setter
    def latency_timer(self, ms: int) -> None:
        _check("latency timer", self.lib.FT_SetLatencyTimer(self.h, int(ms)))

    def com_port(self) -> str | None:
        n = ctypes.c_long(-1)
        if self.lib.FT_GetComPortNumber(self.h, ctypes.byref(n)) != FT_OK or n.value < 0:
            return None
        return f"COM{n.value}"
