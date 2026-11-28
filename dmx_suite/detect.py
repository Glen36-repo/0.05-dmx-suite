"""Which DMX interfaces are plugged in (setup wizard). Best guess from the USB IDs:
the 0.05 node (Espressif ESP32-S3), Enttec DMX USB Pro, and FTDI cables that are usually an
Enttec Open DMX (or another FTDI-based Open DMX clone). Art-Net and sACN can't be seen this way:
the wizard asks for those."""

from __future__ import annotations

from typing import Any

ESPRESSIF = 0x303A
FTDI = 0x0403


def guess(vid: int | None, pid: int | None, text: str) -> str | None:
    t = text.lower()
    if vid == ESPRESSIF or "esp32" in t or "m5stack" in t:
        return "node"
    if "dmx usb pro" in t or "usb pro" in t:
        return "usb_dmx_pro"
    if vid == FTDI or "ftdi" in t or "open dmx" in t:
        return "usb_dmx_open"
    return None


def interfaces(ports: Any = None) -> list[dict[str, Any]]:
    """Serial ports with a driver guess; `ports` (for tests) stands in for comports()."""
    if ports is None:
        try:
            from serial.tools import list_ports

            ports = list_ports.comports()
        except Exception:  # noqa: BLE001 - no pyserial port listing here
            return []
    out = []
    for p in ports:
        text = " ".join(str(x) for x in (getattr(p, "description", ""), getattr(p, "manufacturer", ""),
                                         getattr(p, "product", "")) if x)
        vid, pid = getattr(p, "vid", None), getattr(p, "pid", None)
        out.append({"port": p.device, "description": text or p.device, "driver": guess(vid, pid, text),
                    "usb": f"{vid:04x}:{pid:04x}" if vid is not None and pid is not None else None})
    out.sort(key=lambda d: (d["driver"] is None, d["port"]))
    return out
