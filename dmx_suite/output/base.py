from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from typing import Any


class OutputDriver:
    name = "base"

    def send(self, universe: int, frame: bytes) -> None:
        """Hand over a full 512-channel frame. Must return quickly."""
        raise NotImplementedError

    def close(self) -> None:
        pass

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
