from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)


class SenderThread:
    """Writes frames on its own thread, so the engine never waits for a device.

    `put` keeps only the newest frame per universe (an older one not written yet is simply
    replaced: the device only ever needs the latest) and wakes the thread at once, so a drum hit
    goes out straight away. A slow write, a USB hiccup or reopening an unplugged port holds up
    only this thread, never the show or the other outputs."""

    def __init__(self, write: Callable[[int, bytes], None], name: str) -> None:
        self._write = write
        self._frames: dict[int, bytes] = {}
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._idle = threading.Event()
        self._idle.set()
        self._stop = False
        self.errors = 0
        self.dropped = 0  # frames replaced before they were written (device slower than the show)
        self._thread = threading.Thread(target=self._run, name=f"out-{name}", daemon=True)
        self._thread.start()

    def put(self, universe: int, frame: bytes) -> None:
        with self._lock:
            if universe in self._frames:
                self.dropped += 1
            self._frames[universe] = bytes(frame)
            self._idle.clear()
        self._wake.set()

    def _run(self) -> None:
        while not self._stop:
            self._wake.wait(0.5)
            self._wake.clear()
            while True:
                with self._lock:
                    batch, self._frames = self._frames, {}
                    if not batch:
                        self._idle.set()
                        break
                for u, f in batch.items():
                    try:
                        self._write(u, f)
                    except Exception:  # noqa: BLE001 - a device problem must never end the thread
                        self.errors += 1
                        log.debug("output write failed", exc_info=True)

    def flush(self, timeout: float = 2.0) -> bool:
        """Wait until everything handed over has been written (tests, closing)."""
        return self._idle.wait(timeout)

    def close(self) -> None:
        self.flush(0.5)
        self._stop = True
        self._wake.set()
        self._thread.join(timeout=1)


class OutputDriver:
    name = "base"

    def send(self, universe: int, frame: bytes) -> None:
        """Hand over a full 512-channel frame. Must return quickly."""
        raise NotImplementedError

    def close(self) -> None:
        pass

    def flush(self, timeout: float = 2.0) -> bool:
        """Wait for frames still being written (drivers with a sender thread)."""
        return True

    def status(self) -> dict[str, Any]:
        return {"driver": self.name}

    def state(self) -> dict[str, Any]:
        """For the status bar: state is ok / warn / bad / sim, detail is a few words."""
        return {"kind": "output", "name": self.name, "state": "ok", "detail": ""}


class NullDriver(OutputDriver):
    name = "null"

    def __init__(self) -> None:
        self.frames = 0

    def send(self, universe: int, frame: bytes) -> None:
        self.frames += 1

    def status(self) -> dict[str, Any]:
        return {"driver": self.name, "frames": self.frames}

    def state(self) -> dict[str, Any]:
        return {"kind": "output", "name": "No output", "state": "sim", "detail": "frames go nowhere"}


class LogDriver(OutputDriver):
    """Keeps the latest frame per universe and a short history (simulator, tests)."""

    name = "log"

    def __init__(self, history: int = 200, on_frame: Callable[[int, bytes], None] | None = None) -> None:
        self.last: dict[int, bytes] = {}
        self.history: deque[tuple[float, int, bytes]] = deque(maxlen=history)
        self.frames = 0
        self.on_frame = on_frame

    def send(self, universe: int, frame: bytes) -> None:
        frame = bytes(frame)
        self.last[universe] = frame
        self.history.append((time.perf_counter(), universe, frame))
        self.frames += 1
        if self.on_frame:
            self.on_frame(universe, frame)

    def status(self) -> dict[str, Any]:
        return {"driver": self.name, "frames": self.frames}

    def state(self) -> dict[str, Any]:
        return {"kind": "output", "name": "Simulator", "state": "sim", "detail": "no DMX hardware"}
