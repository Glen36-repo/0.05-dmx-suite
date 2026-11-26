"""0.05 node over USB serial (phase 1 protocol). `port: sim` uses the simulated node."""

from __future__ import annotations

from typing import Any

from ..node.health import HealthTracker
from ..node.link import NodeLink, SerialTransport
from ..node.sim import SimTransport, default_sim
from .base import OutputDriver


class NodeSerialDriver(OutputDriver):
    name = "node_serial"

    def __init__(self, port: str, health: HealthTracker | None = None) -> None:
        self.port = port
        transport = SimTransport(default_sim()) if port == "sim" else SerialTransport(port)
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
