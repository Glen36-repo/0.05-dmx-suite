"""Node health tracking from heartbeats. States per docs/PROTOCOL.md §2."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum

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
        self._seen: set[str] = set()  # macs with a logged first state
        # heartbeats arrive on the node reader thread; the UI, CLI and app read from others
        self._lock = threading.RLock()

    def records(self) -> list[NodeRecord]:
        """A copy of the node list, safe to loop over while heartbeats keep arriving."""
        with self._lock:
            return list(self.nodes.values())

    # rig config lists the expected nodes: missing ones show offline straight away
    def expect(self, nodes: Iterable[tuple[str, str]]) -> None:
        with self._lock:
            self._expect(nodes)

    def _expect(self, nodes: Iterable[tuple[str, str]]) -> None:
        for mac, name in nodes:
            rec = self.nodes.setdefault(mac.upper(), NodeRecord(mac.upper()))
            rec.expected = True
            rec.expected_name = name

    def update(self, hb: Heartbeat) -> NodeRecord:
        with self._lock:
            mac = mac_str(hb.mac)
            rec = self.nodes.setdefault(mac, NodeRecord(mac))
            rec.heartbeat = hb
            rec.last_seen = self._clock()
            self._set(rec, self._classify(rec))
            return rec

    def tick(self) -> None:
        with self._lock:
            for rec in list(self.nodes.values()):
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
        first = rec.mac not in self._seen
        if state == rec.state and not first:
            return
        ev = HealthEvent(self._wall(), rec.mac, rec.name, None if first else rec.state, state)
        rec.state = state
        self._seen.add(rec.mac)
        self.log.append(ev)
        del self.log[:-1000]  # keep the last thousand changes (the app writes them to the gig log)
        for fn in self.listeners:
            fn(ev)

    def alerts(self) -> list[NodeRecord]:
        """Nodes needing attention: expected but offline, or weak."""
        return [
            r
            for r in self.records()
            if (r.state == State.OFFLINE and (r.expected or r.heartbeat)) or r.state == State.WEAK
        ]
