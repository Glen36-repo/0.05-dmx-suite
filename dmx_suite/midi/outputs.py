"""MIDI output ports (v4): open the ones the rig lists (`midi_outputs:`) and log everything sent, so the
Monitor page shows what the app puts out (test sends now; feedback to controllers later).

Like MIDI inputs, ports are matched by name fragment and rescanned, so a re-plugged interface comes back.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from .monitor import MidiMonitor, MonitorEntry, note_name

log = logging.getLogger(__name__)


def out_names() -> list[str]:
    import mido

    return list(mido.get_output_names())


def _open(name: str) -> Any:
    import mido

    return mido.open_output(name)


TYPES = ("note_on", "note_off", "control_change", "program_change")


class MidiOutputs:
    def __init__(self, wanted: list[str], monitor: MidiMonitor, lister: Callable[[], list[str]] = out_names,
                 opener: Callable[[str], Any] = _open) -> None:
        self.wanted = [w for w in wanted if w]
        self.monitor = monitor
        self.lister = lister
        self.opener = opener
        self.open: dict[str, Any] = {}
        self._lock = threading.Lock()
        self.errors = 0
        self.rescan()

    def rescan(self) -> None:
        try:
            names = self.lister()
        except Exception:  # noqa: BLE001 - no MIDI backend
            names = []
        with self._lock:
            for n in names:
                if n in self.open or not any(w.lower() in n.lower() for w in self.wanted):
                    continue
                try:
                    self.open[n] = self.opener(n)
                except Exception:  # noqa: BLE001 - busy or gone: try again next scan
                    self.errors += 1
            for n in [n for n in self.open if n not in names]:
                self.open.pop(n, None)

    def status(self) -> list[dict[str, Any]]:
        with self._lock:
            opened = list(self.open)
        return [{"name": w, "connected": any(w.lower() in o.lower() for o in opened),
                 "port": next((o for o in opened if w.lower() in o.lower()), None)} for w in self.wanted]

    def send(self, port: str, kind: str, channel: int, number: int, value: int = 0, why: str = "test send") -> str:
        """Send one message (channel 1-16) and log it. Returns the port it went to."""
        import mido

        if kind not in TYPES:
            raise ValueError(f"type is one of {', '.join(TYPES)}")
        if not 1 <= channel <= 16 or not 0 <= number <= 127 or not 0 <= value <= 127:
            raise ValueError("channel 1-16, number and value 0-127")
        with self._lock:
            name = next((o for o in self.open if port.lower() in o.lower()), None)
            out = self.open.get(name) if name else None
        if out is None:
            raise ValueError(f"no MIDI output {port!r} open; have {', '.join(self.open) or 'none'}")
        if kind == "program_change":
            msg = mido.Message(kind, channel=channel - 1, program=number)
        elif kind == "control_change":
            msg = mido.Message(kind, channel=channel - 1, control=number, value=value)
        else:
            msg = mido.Message(kind, channel=channel - 1, note=number, velocity=value)
        out.send(msg)
        self.monitor.add(MonitorEntry(time.time(), name or port, channel, kind, number, value, why,
                                      note=note_name(number) if kind.startswith("note") else "", direction="out"))
        return name or port
