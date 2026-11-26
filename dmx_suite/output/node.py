"""0.05 node over USB serial (phase 1 protocol). `port: sim` uses the simulated node."""

from __future__ import annotations

import time
from typing import Any

from ..node.health import HealthTracker
from ..node.link import NodeLink, ReconnectingSerial
from ..node.sim import SimTransport, default_sim
from .base import OutputDriver


class NodeSerialDriver(OutputDriver):
    name = "node_serial"

    def __init__(self, port: str, health: HealthTracker | None = None) -> None:
        self.port = port
        transport = SimTransport(default_sim()) if port == "sim" else ReconnectingSerial(port)
        self.link = NodeLink(transport, health)
        self.errors = 0
        if port != "sim":
            self.link.start()  # reader thread: status + heartbeats

    def send(self, universe: int, frame: bytes) -> None:
        try:
            self.link.send_frame(frame, universe)
        except Exception:
            self.errors += 1
        if self.port == "sim":
            self.link.poll()

    def close(self) -> None:
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
