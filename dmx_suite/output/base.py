from __future__ import annotations

import time
from collections import deque
from typing import Any, Callable


class OutputDriver:
    name = "base"

    def send(self, universe: int, frame: bytes) -> None:
        """Hand over a full 512-channel frame. Must return quickly."""
        raise NotImplementedError

    def close(self) -> None:
        pass

    def status(self) -> dict[str, Any]:
        return {"driver": self.name}


class NullDriver(OutputDriver):
    name = "null"

    def __init__(self) -> None:
        self.frames = 0

    def send(self, universe: int, frame: bytes) -> None:
        self.frames += 1

    def status(self) -> dict[str, Any]:
        return {"driver": self.name, "frames": self.frames}


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
