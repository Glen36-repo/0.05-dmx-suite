"""0.05 node over USB serial (phase 1 protocol). `port: sim` uses the simulated node."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from ..node.health import HealthTracker
from ..node.link import NodeLink, ReconnectingSerial
from ..node.sim import SimTransport, default_sim
from .base import OutputDriver, SenderThread


class NodeSerialDriver(OutputDriver):
    name = "node_serial"

    def __init__(self, port: str, health: HealthTracker | None = None) -> None:
        self.port = port
        transport = SimTransport(default_sim()) if port == "sim" else ReconnectingSerial(port)
        self.link = NodeLink(transport, health)
        self.errors = 0
        self.on_connect: Callable[[NodeSerialDriver], Any] | None = None  # set by the app
        self.link.on_node_announce.append(lambda hb: self._connected())
        # real node: a sender thread does the USB writes (and port reopening), never the engine
        self._sender = SenderThread(self._write, self.name) if port != "sim" else None
        if port != "sim":
            self.link.start()  # reader thread: status + heartbeats

    def _connected(self) -> None:
        """The node (re)announced itself: the app's set-up (fallback looks, channel) runs on its own
        thread, because it waits for ACKs that this reader thread has to read."""
        if self.on_connect is not None:
            threading.Thread(target=self.on_connect, args=(self,), name="node-setup", daemon=True).start()

    def send(self, universe: int, frame: bytes) -> None:
        if self._sender is not None:
            self._sender.put(universe, frame)
            return
        self._write(universe, frame)
        self.link.poll()  # simulated node answers straight away

    def _write(self, universe: int, frame: bytes) -> None:
        try:
            self.link.send_frame(frame, universe)
            self.wire.record(universe, frame)
        except Exception:
            self.errors += 1

    def flush(self, timeout: float = 2.0) -> bool:
        return self._sender.flush(timeout) if self._sender else True

    def close(self) -> None:
        if self._sender is not None:
            self._sender.close()
        self.link.close()

    def state(self) -> dict[str, Any]:
        label = "0.05 node"
        if self.port == "sim":
            return {"kind": "output", "name": label, "state": "sim", "detail": "simulated node"}
        t = self.link.t
        if isinstance(t, ReconnectingSerial) and not t.is_open:
            why = "unplugged" if t.connected_once else "not found"
            return {"kind": "output", "name": label, "state": "bad", "detail": f"{self.port} {why}, retrying"}
        st, at = self.link.stats.last_status, self.link.stats.last_status_at
        if st is None or at is None or time.monotonic() - at > 3.0:
            return {"kind": "output", "name": label, "state": "warn", "detail": f"{self.port} · no reply from node"}
        detail = f"{self.port} · {st.mode.name.lower()} · {st.frame_rate:.0f} fps · {st.receivers_online} receivers"
        return {"kind": "output", "name": label, "state": "ok" if st.mode.name == "LIVE" else "warn", "detail": detail}

    def status(self) -> dict[str, Any]:
        s = self.link.stats.last_status
        return {
            "driver": self.name,
            "port": self.port,
            "frames": self.link.stats.frames_sent,
            "errors": self.errors,
            "node_mode": s.mode.name.lower() if s else None,
            "node_rate": s.frame_rate if s else None,
        }
