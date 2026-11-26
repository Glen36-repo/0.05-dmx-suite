"""Node health tracking from heartbeats. States per docs/PROTOCOL.md §2."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterable

from .protocol import Heartbeat, mac_str


class State(str, Enum):
    ONLINE = "online"
    WEAK = "weak"
    OFFLINE = "offline"
    NEW = "new"


@dataclass
class Thresholds:
    offline_after_s: float = 3.5  # 3 missed 1 s heartbeats
    weak_rssi_dbm: int = -80
    weak_loss_pct: int = 10


@dataclass
class NodeRecord:
    mac: str
    expected: bool = False
    expected_name: str = ""
    heartbeat: Heartbeat | None = None
    last_seen: float | None = None  # monotonic seconds
    state: State = State.OFFLINE

    @property
    def name(self) -> str:
        if self.heartbeat and self.heartbeat.name:
            return self.heartbeat.name
        return self.expected_name


@dataclass
class HealthEvent:
    time: float  # wall clock (time.time())
    mac: str
    name: str
    old: State | None
    new: State


class HealthTracker:
    """Keeps one record per node MAC; call `update()` on each heartbeat and `tick()` regularly."""

    def __init__(
        self,
        thresholds: Thresholds | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self.t = thresholds or Thresholds()
        self._clock = clock
        self._wall = wall_clock
        self.nodes: dict[str, NodeRecord] = {}
        self.log: list[HealthEvent] = []
        self.listeners: list[Callable[[HealthEvent], None]] = []

    # rig config lists the expected nodes: missing ones show offline straight away
    def expect(self, nodes: Iterable[tuple[str, str]]) -> None:
        for mac, name in nodes:
            rec = self.nodes.setdefault(mac.upper(), NodeRecord(mac.upper()))
            rec.expected = True
            rec.expected_name = name

    def update(self, hb: Heartbeat) -> NodeRecord:
        mac = mac_str(hb.mac)
        rec = self.nodes.setdefault(mac, NodeRecord(mac))
        rec.heartbeat = hb
        rec.last_seen = self._clock()
        self._set(rec, self._classify(rec))
        return rec

    def tick(self) -> None:
        for rec in self.nodes.values():
            self._set(rec, self._classify(rec))

    def _classify(self, rec: NodeRecord) -> State:
        if rec.last_seen is None or self._clock() - rec.last_seen > self.t.offline_after_s:
            return State.OFFLINE
        hb = rec.heartbeat
        assert hb is not None
        if not hb.name:
            return State.NEW
        if (hb.rssi is not None and hb.rssi < self.t.weak_rssi_dbm) or (
            hb.loss_pct is not None and hb.loss_pct > self.t.weak_loss_pct
        ):
            return State.WEAK
        return State.ONLINE

    def _set(self, rec: NodeRecord, state: State) -> None:
        first = not any(e.mac == rec.mac for e in self.log)
        if state == rec.state and not first:
            return
        ev = HealthEvent(self._wall(), rec.mac, rec.name, None if first else rec.state, state)
        rec.state = state
        self.log.append(ev)
        for fn in self.listeners:
            fn(ev)

    def alerts(self) -> list[NodeRecord]:
        """Nodes needing attention: expected but offline, or weak."""
        return [
            r
            for r in self.nodes.values()
            if (r.state == State.OFFLINE and (r.expected or r.heartbeat)) or r.state == State.WEAK
        ]
