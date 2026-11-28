"""USB DMX (Open) health checks (v5): what the FTDI interface and Windows are set to, before blaming
the lights. Run at start, on hot-plug, after outputs change and every minute; each check is
pass / warn / fail / unknown with the fix in plain words.

- driver: VCP (a COM port) or D2XX available, and which one the output uses
- latency: the FTDI latency timer (Windows registry FTDIBUS `LatencyTimer`, Linux sysfs, or D2XX);
  over 1 ms is amber
- exclusive: the port opened for us alone; "access denied" / busy = red, naming Daslight, QLC+ or
  FreeStyler when one is running
- serial: 250000 baud, 8 data bits, no parity, 2 stop bits on the open port
- power: USB selective suspend on (power plan, or the interface's own setting) = amber, it can drop the
  interface mid-gig
- timing: the measured break / MAB / fps (enttec.py) inside limits

Everything that reads the OS goes through `Probe`, so tests give a fake one. Registry value names for
power saving vary by Windows build: confirm them on the gig laptop (`check_outputs` says "unknown"
rather than guessing when a value isn't there).
"""

from __future__ import annotations

import importlib
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import d2xx

LATENCY_FIX = "Device Manager › Ports › {port} › Port Settings › Advanced › Latency Timer = 1"
CONFLICTS = {"daslight": "Daslight", "dvc": "Daslight", "qlcplus": "QLC+", "freestyler": "FreeStyler",
             "magicq": "MagicQ"}
FTDIBUS = r"SYSTEM\CurrentControlSet\Enum\FTDIBUS"
USB = r"SYSTEM\CurrentControlSet\Enum\USB"
USB_SUBGROUP = "2a737441-1930-4402-8d77-b2bebba308a3"  # power plan: USB settings
USB_SUSPEND = "48e6b7a6-50f5-4782-a5d4-53bb8f07e226"  # power plan: USB selective suspend setting


class Probe:
    """Reads the OS. Every method returns None when it can't tell."""

    platform = sys.platform

    def reg_values(self, path: str) -> dict[str, Any] | None:  # HKLM
        if self.platform != "win32":
            return None
        try:
            winreg: Any = importlib.import_module("winreg")
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
                out: dict[str, Any] = {}
                i = 0
                while True:
                    try:
                        name, val, _ = winreg.EnumValue(k, i)
                    except OSError:
                        return out
                    out[name] = val
                    i += 1
        except OSError:
            return None

    def reg_subkeys(self, path: str) -> list[str] | None:
        if self.platform != "win32":
            return None
        try:
            winreg: Any = importlib.import_module("winreg")
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
                keys: list[str] = []
                i = 0
                while True:
                    try:
                        keys.append(winreg.EnumKey(k, i))
                    except OSError:
                        return keys
                    i += 1
        except OSError:
            return None

    def read(self, path: str) -> str | None:
        try:
            return Path(path).read_text().strip()
        except OSError:
            return None

    def processes(self) -> list[str] | None:
        cmd = ["tasklist", "/fo", "csv", "/nh"] if self.platform == "win32" else ["ps", "-eo", "comm="]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=5,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            return None
        if self.platform == "win32":
            return [line.split('","')[0].strip('"') for line in r.stdout.splitlines() if line]
        return [line.strip() for line in r.stdout.splitlines() if line.strip()]

    def usb_suspend_plan(self) -> bool | None:
        """Power plan's USB selective suspend (AC), Windows only."""
        if self.platform != "win32":
            return None
        try:
            r = subprocess.run(["powercfg", "/query", "SCHEME_CURRENT", USB_SUBGROUP, USB_SUSPEND], capture_output=True,
                               text=True, timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            return None
        m = re.search(r"Current AC Power Setting Index:\s*0x([0-9a-f]+)", r.stdout, re.I)
        return None if m is None else int(m.group(1), 16) != 0


def _check(key: str, name: str, result: str, detail: str, fix: str = "") -> dict[str, str]:
    return {"key": key, "name": name, "result": result, "detail": detail, "fix": fix}


def _ftdibus_params(probe: Probe, vid_pid: str | None, sn: str | None) -> dict[str, Any] | None:
    """`Device Parameters` of this interface's FTDIBUS key (Windows), found by VID, PID and serial number."""
    if not (vid_pid and sn):
        return None
    vid, pid = (x.upper() for x in vid_pid.split(":"))
    keys = probe.reg_subkeys(FTDIBUS) or []
    prefix = f"VID_{vid}+PID_{pid}+{sn}".upper()
    for k in keys:
        if k.upper().startswith(prefix):  # FTDI adds the channel letter: ...+A1B2C3A
            return probe.reg_values(rf"{FTDIBUS}\{k}\0000\Device Parameters")
    return None


def check_interface(port: str, info: dict[str, Any] | None, drv: Any, probe: Probe | None = None) -> dict[str, Any]:
    """Checklist for one USB DMX (Open) output. `info` is the device registry's entry (vid_pid, serial
    number) when known; `drv` the running EnttecOpenDriver."""
    probe = probe or Probe()
    info = info or {}
    sn = info.get("serial_number") or getattr(drv, "serial_number", None)
    vid_pid = info.get("vid_pid")
    checks: list[dict[str, str]] = []
    params = _ftdibus_params(probe, vid_pid, sn) if probe.platform == "win32" else None
    tty = Path(port).name

    # driver: VCP vs D2XX
    d2xx_ok = bool(drv.d2xx_ok()) if drv is not None else d2xx.available()
    if probe.platform == "win32":
        vcp = bool(params and params.get("PortName"))
    else:
        vcp = (probe.read(f"/sys/class/tty/{tty}/device/driver/module/srcversion") is not None
               or Path(f"/sys/class/tty/{tty}").exists())
    using = getattr(drv, "method", None)
    driver = "d2xx" if using == "d2xx" else "vcp" if vcp or port.upper().startswith("COM") or "tty" in port else "unknown"
    detail = {"d2xx": "D2XX (FTDI library)", "vcp": f"VCP (COM port {port})", "unknown": "not known"}[driver]
    detail += "; D2XX available" if d2xx_ok else "; D2XX not installed (d2xx break method not offered)"
    checks.append(_check("driver", "Driver", "pass" if driver != "unknown" else "unknown", detail))

    # latency timer
    lat: int | None = None
    if using == "d2xx" and getattr(drv, "_ser", None) is not None and hasattr(drv._ser, "latency_timer"):
        try:
            lat = int(drv._ser.latency_timer)
        except Exception:  # noqa: BLE001
            lat = None
    if lat is None and params is not None and "LatencyTimer" in params:
        lat = int(params["LatencyTimer"])
    if lat is None and probe.platform != "win32":
        v = probe.read(f"/sys/bus/usb-serial/devices/{tty}/latency_timer")
        lat = int(v) if v and v.isdigit() else None
    fix = LATENCY_FIX.format(port=port) + (" (or Set latency to 1 ms here: D2XX is open)" if using == "d2xx" else "")
    if lat is None:
        checks.append(_check("latency", "Latency timer", "unknown", "couldn't read it", fix))
    else:
        checks.append(_check("latency", "Latency timer", "pass" if lat <= 1 else "warn", f"{lat} ms",
                             "" if lat <= 1 else fix))

    # exclusive open
    err = (getattr(getattr(drv, "_p", None), "last_error", "") or "") if drv is not None else ""
    is_open = drv is not None and getattr(drv, "_ser", None) is not None
    busy = bool(re.search(r"access is denied|permission|busy|in use|not opened|errno 13|errno 16", err, re.I))
    if is_open:
        checks.append(_check("exclusive", "Port to ourselves", "pass", f"{port} open, nothing else holding it"))
    elif busy:
        procs = probe.processes() or []
        names = sorted({v for p in procs for k, v in CONFLICTS.items() if k in p.lower()})
        who = f": {', '.join(names)} is running" if names else ""
        checks.append(_check("exclusive", "Port to ourselves", "fail", f"{port} is held by another program{who} ({err})",
                             f"Close {' / '.join(names) if names else 'the other lighting program'}; the port is "
                             "reopened by itself within 2 s"))
    else:
        checks.append(_check("exclusive", "Port to ourselves", "unknown",  # missing, not taken: the output's own state says so
                             f"{port} not open" + (f" ({err})" if err else ""),
                             "Plug the interface in, or pick its port in Setup › Devices" if err else ""))

    # serial settings on the open port
    ser = getattr(drv, "_ser", None) if drv is not None else None
    if ser is None:
        checks.append(_check("serial", "250k 8N2", "unknown", "port not open"))
    else:
        b, bits, par, stop = (getattr(ser, k, None) for k in ("baudrate", "bytesize", "parity", "stopbits"))
        bad = []
        if using != "baud_drop" and b not in (None, 250000):
            bad.append(f"baud {b}")
        if bits not in (None, 8):
            bad.append(f"{bits} data bits")
        if par not in (None, "N"):
            bad.append(f"parity {par}")
        if stop not in (None, 2):
            bad.append(f"{stop} stop bits")
        what = "250000 baud, 8N2" + (" (baud changes each frame: baud drop)" if using == "baud_drop" else "")
        checks.append(_check("serial", "250k 8N2", "fail" if bad else "pass", ", ".join(bad) or what,
                             "Reopen the output (Setup › Devices) or restart the program" if bad else ""))

    # USB power saving
    plan = probe.usb_suspend_plan()
    dev_suspend = None
    if probe.platform == "win32" and vid_pid and sn:
        vid, pid = (x.upper() for x in vid_pid.split(":"))
        p = probe.reg_values(rf"{USB}\VID_{vid}&PID_{pid}\{sn}\Device Parameters") or {}
        vals = [p[k] for k in ("SelectiveSuspendEnabled", "EnhancedPowerManagementEnabled") if k in p]
        dev_suspend = any(bool(v) for v in vals) if vals else None
    if plan is None and dev_suspend is None:
        checks.append(_check("power", "USB power saving", "unknown", "couldn't read the power settings",
                             "Power Options › USB settings › USB selective suspend = Disabled"))
    elif plan or dev_suspend:
        where = " and ".join(x for x, on in (("power plan", plan), ("this interface", dev_suspend)) if on)
        checks.append(_check("power", "USB power saving", "warn", f"USB selective suspend is on ({where}): Windows can "
                             "switch the interface off mid-gig",
                             "Power Options › Change plan settings › Advanced › USB settings › USB selective suspend = "
                             "Disabled; Device Manager › USB Serial Converter › Power Management: untick 'Allow the "
                             "computer to turn off this device'"))
    else:
        checks.append(_check("power", "USB power saving", "pass", "selective suspend off"))

    # timing (measured)
    if drv is not None and hasattr(drv, "timing"):
        t = drv.timing()
        m = t["measured"]
        if m["break_us"] is None:
            checks.append(_check("timing", "Timing", "unknown", "no frames measured yet"))
        else:
            detail = (f"{t['method_name']}: break {m['break_us']} µs, MAB {m['mab_us']} µs, {m['fps'] or '-'} fps "
                      f"(target {t['target']['fps']}), write {m['write_ms']} ms, jitter {m['jitter_ms'] or '-'} ms")
            checks.append(_check("timing", "Timing", "warn" if t["warnings"] else "pass",
                                 detail + (f": {'; '.join(t['warnings'])}" if t["warnings"] else ""),
                                 "Try another break method (Monitor › Cycle break methods)" if t["warnings"] else ""))

    results = {c["result"] for c in checks}
    worst = "fail" if "fail" in results else "warn" if "warn" in results else "pass"
    return {"port": port, "driver_type": driver, "d2xx_available": d2xx_ok, "latency_ms": lat, "result": worst,
            "checks": checks}
