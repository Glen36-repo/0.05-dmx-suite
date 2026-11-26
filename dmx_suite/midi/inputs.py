"""MIDI input ports. Real ports need python-rtmidi (Windows wheels); the simulator uses FakeMidiIn.

MidiInputs opens every port matching the wanted names (case-insensitive fragments such as "UM-ONE",
"H2MIDI"; none = every port) and rescans every couple of seconds, so a USB MIDI interface that's
unplugged and plugged back in mid-gig (often under a new Windows name like "UM-ONE 2") reconnects by
itself. Interfaces have no heartbeat, so their status is just connected / disconnected.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

log = logging.getLogger(__name__)

Handler = Callable[[Any, str], Any]  # (mido message, port name)


def port_names() -> list[str]:
    import mido

    return list(mido.get_input_names())


def _open(name: str, callback: Callable[[Any], Any]) -> Any:
    import mido

    return mido.open_input(name, callback=callback)


class MidiInputs:
    """Opens ports with callbacks, so a drum hit is handled on arrival (no polling)."""

    def __init__(
        self,
        wanted: list[str] | None,
        handler: Handler,
        lister: Callable[[], list[str]] = port_names,
        opener: Callable[[str, Callable[[Any], Any]], Any] = _open,
        rescan_s: float = 2.0,
        watch: bool = True,
    ) -> None:
        self.wanted = [w for w in (wanted or []) if w]
        self.handler = handler
        self.lister = lister
        self.opener = opener
        self.rescan_s = rescan_s
        self.open: dict[str, Any] = {}
        self.errors = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.rescan()
        self._thread: threading.Thread | None = None
        if watch:
            self._thread = threading.Thread(target=self._watch, name="midi-rescan", daemon=True)
            self._thread.start()

    def _matches(self, name: str) -> bool:
        return not self.wanted or any(w.lower() in name.lower() for w in self.wanted)

    def rescan(self) -> None:
        try:
            names = set(self.lister())
        except Exception:
            self.errors += 1
            return
        with self._lock:
            for name in list(self.open):
                if name not in names:  # unplugged
                    log.warning("MIDI input %s disconnected", name)
                    try:
                        self.open.pop(name).close()
                    except Exception:
                        pass
            for name in sorted(names):
                if name in self.open or not self._matches(name):
                    continue
                try:
                    self.open[name] = self.opener(name, lambda msg, n=name: self.handler(msg, n))
                    log.info("MIDI input %s connected", name)
                except Exception:
                    self.errors += 1
                    log.exception("couldn't open MIDI input %s", name)

    def _watch(self) -> None:
        while not self._stop.wait(self.rescan_s):
            self.rescan()

    @property
    def ports(self) -> list[Any]:
        with self._lock:
            return list(self.open.values())

    def status(self) -> list[dict[str, Any]]:
        """One entry per wanted name (connected or not), or per open port when none were named."""
        with self._lock:
            names = list(self.open)
        if not self.wanted:
            return [{"name": n, "connected": True} for n in names]
        out = []
        for w in self.wanted:
            match = [n for n in names if w.lower() in n.lower()]
            out.append({"name": w, "connected": bool(match), "port": match[0] if match else None})
        return out

    def close(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        with self._lock:
            for p in self.open.values():
                try:
                    p.close()
                except Exception:
                    pass
            self.open.clear()


class FakeMidiIn:
    """Simulator input: inject messages as if they came from a port."""

    def __init__(self, handler: Handler, name: str = "sim") -> None:
        import mido  # noqa: F401  load now so the first simulated hit isn't slowed by the import

        self.handler = handler
        self.name = name

    def _send(self, msg: Any, port: str | None) -> Any:
        return self.handler(msg, port or self.name)

    def note(self, note: int, velocity: int = 100, channel: int = 10, port: str | None = None) -> Any:
        import mido

        return self._send(mido.Message("note_on", channel=channel - 1, note=note, velocity=velocity), port)

    def note_off(self, note: int, channel: int = 10, port: str | None = None) -> Any:
        import mido

        return self._send(mido.Message("note_off", channel=channel - 1, note=note, velocity=0), port)

    def program(self, program: int, channel: int = 1, port: str | None = None) -> Any:
        import mido

        return self._send(mido.Message("program_change", channel=channel - 1, program=program), port)

    def cc(self, control: int, value: int, channel: int = 1, port: str | None = None) -> Any:
        import mido

        return self._send(mido.Message("control_change", channel=channel - 1, control=control, value=value), port)

    def close(self) -> None:
        pass
