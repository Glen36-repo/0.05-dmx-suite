"""The live feed behind every open screen (server-sent events).

One thread takes a snapshot of the engine 10 times a second and turns it into JSON once, however
many screens are open; screens are only sent a new state when it has changed. A screen with nothing
new still gets a small heartbeat every few seconds, so it can tell a quiet show from a dead link.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

log = logging.getLogger(__name__)

TICK_S = 0.1
HEARTBEAT_S = 5.0


class LiveFeed:
    def __init__(self, snapshot: Any, tick_s: float = TICK_S) -> None:
        self.snapshot = snapshot
        self.tick_s = tick_s
        self.version = 0
        self.payload = ""  # the latest state as JSON
        self.cond = threading.Condition()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.builds = 0  # snapshots taken (tests)

    def start(self) -> None:
        self._stop.clear()
        self.build()
        self._thread = threading.Thread(target=self._run, name="live-feed", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self.cond:
            self.cond.notify_all()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def build(self) -> None:
        try:
            payload = json.dumps(self.snapshot(), default=str)
        except Exception:  # never let a snapshot bug stop every screen
            log.exception("live feed snapshot failed")
            return
        self.builds += 1
        with self.cond:
            if payload != self.payload:
                self.payload = payload
                self.version += 1
                self.cond.notify_all()

    def _run(self) -> None:
        while not self._stop.wait(self.tick_s):
            self.build()

    def wait(self, seen: int, timeout: float) -> tuple[int, str]:
        """The latest (version, state JSON), waiting up to `timeout` for one newer than `seen`."""
        end = time.monotonic() + timeout
        with self.cond:
            while self.version == seen and not self._stop.is_set():
                left = end - time.monotonic()
                if left <= 0:
                    break
                self.cond.wait(left)
            return self.version, self.payload
