"""Devices found on this laptop (v4): USB DMX interfaces, 0.05 nodes on USB, MIDI ports.

Each device is known by what it says it is, not by a model name written into the code:

- USB serial (DMX interfaces, the 0.05 node): the USB descriptor - product string, manufacturer,
  serial number, VID:PID. Its id is `usb:VVVV:PPPP:SERIAL`, so it keeps its universe and settings when
  Windows gives it another COM number or the plug order changes. Without a serial number the id falls
  back to the port (`port:COM3`) and the device is flagged `stable: false`.
- MIDI: the port name the OS reports ("UM-ONE", "TD-25", or just "USB MIDI Interface"); id
  `midi-in:<name>` / `midi-out:<name>` without the trailing Windows port index.

The name shown is the product string when the device has a real one; generic chip names ("FT232R USB
UART", "USB Serial Port") become "USB DMX interface (FTDI, SN A1B2C3)". The rig gives each device an
alias (`outputs: - {device: usb:0403:6001:A1B2C3, alias: Stage DMX, universe: 0}`).

`DeviceRegistry` rescans every couple of seconds (hot-plug, no restart) with scanners that tests replace.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable
from typing import Any

from .detect import guess

GENERIC = ("ft232r usb uart", "usb serial port", "usb serial", "usb-serial", "usb <-> serial", "usb2.0-serial",
           "usb uart", "cp2102", "ch340", "usb jtag/serial debug unit")
VENDORS = {0x0403: "FTDI", 0x303A: "Espressif", 0x10C4: "Silicon Labs", 0x1A86: "WCH"}


def midi_base(name: str) -> str:
    """A MIDI port name without the Windows index Windows adds ("UM-ONE 2" -> "UM-ONE")."""
    return re.sub(r"\s+\d+$", "", name.strip())


def _serial_ports() -> list[Any]:
    try:
        from serial.tools import list_ports

        return list(list_ports.comports())
    except Exception:  # noqa: BLE001 - no pyserial port listing here
        return []


def _midi_names() -> tuple[list[str], list[str]]:
    try:
        import mido

        return list(mido.get_input_names()), list(mido.get_output_names())
    except Exception:  # noqa: BLE001 - no MIDI backend here
        return [], []


def describe_serial(p: Any) -> dict[str, Any]:
    vid, pid = getattr(p, "vid", None), getattr(p, "pid", None)
    product = (getattr(p, "product", None) or "").strip()
    desc = (getattr(p, "description", None) or "").strip()
    maker = (getattr(p, "manufacturer", None) or "").strip()
    sn = (getattr(p, "serial_number", None) or "").strip()
    port = p.device
    text = " ".join(x for x in (desc, maker, product) if x)
    real = next((x for x in (product, desc) if x and x.lower() not in GENERIC and x != port and not x.startswith(port)), "")
    if real:
        name = real
    else:
        vendor = VENDORS.get(vid or -1, maker or "USB")
        name = f"USB DMX interface ({vendor}" + (f", SN {sn})" if sn else ")")
    stable = bool(sn and vid is not None)
    dev_id = f"usb:{vid:04x}:{pid:04x}:{sn}" if stable else f"port:{port}"
    return {"id": dev_id, "kind": "serial", "port": port, "name": name, "product": product or None,
            "description": desc or None, "manufacturer": maker or None, "serial_number": sn or None,
            "vid_pid": f"{vid:04x}:{pid:04x}" if vid is not None and pid is not None else None,
            "driver": guess(vid, pid, text), "stable": stable}


def describe_midi(name: str, out: bool) -> dict[str, Any]:
    base = midi_base(name)
    return {"id": f"midi-{'out' if out else 'in'}:{base}", "kind": "midi_out" if out else "midi_in", "port": name,
            "name": base, "stable": True}


class DeviceRegistry:
    """What's plugged in now, rescanned in the background; reports devices that came and went."""

    def __init__(self, serial_scan: Callable[[], list[Any]] = _serial_ports,
                 midi_scan: Callable[[], tuple[list[str], list[str]]] = _midi_names, rescan_s: float = 2.0) -> None:
        self.serial_scan = serial_scan
        self.midi_scan = midi_scan
        self.rescan_s = rescan_s
        self.found: dict[str, dict[str, Any]] = {}
        self.seen_ever: set[str] = set()
        self.on_change: list[Callable[[dict[str, Any], str], None]] = []  # (device, "added" | "removed")
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.scan()

    def scan(self) -> dict[str, dict[str, Any]]:
        now: dict[str, dict[str, Any]] = {}
        for p in self.serial_scan():
            try:
                d = describe_serial(p)
            except Exception:  # noqa: BLE001 - one odd port mustn't hide the others
                continue
            now[d["id"]] = d
        ins, outs = self.midi_scan()
        for n in ins:
            d = describe_midi(n, False)
            now.setdefault(d["id"], d)
        for n in outs:
            d = describe_midi(n, True)
            now.setdefault(d["id"], d)
        with self._lock:
            added = [now[k] for k in now.keys() - self.found.keys()]
            removed = [self.found[k] for k in self.found.keys() - now.keys()]
            self.found = now
            self.seen_ever |= set(now)
        for d in added:
            self._emit(d, "added")
        for d in removed:
            self._emit(d, "removed")
        return now

    def _emit(self, d: dict[str, Any], what: str) -> None:
        for fn in list(self.on_change):
            try:
                fn(d, what)
            except Exception:  # noqa: BLE001 - a listener problem mustn't stop the scan
                pass

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="device-scan", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self.rescan_s):
            self.scan()

    def stop(self) -> None:
        self._stop.set()

    def get(self, dev_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self.found.get(dev_id)

    def all(self) -> list[dict[str, Any]]:
        with self._lock:
            return sorted(self.found.values(), key=lambda d: (d["kind"], d["name"]))

    def port_for(self, dev_id: str) -> str | None:
        """Where a device is now (its COM port or MIDI port name), or None if it isn't plugged in."""
        d = self.get(dev_id)
        return d["port"] if d else None
