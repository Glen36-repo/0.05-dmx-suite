"""Simulated CoreS3 node + AtomS3 receivers. Mirrors firmware/src/node/main.cpp behaviour.

Used by tests and `dmx-node-test --sim` so the laptop side can be built with no hardware.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from . import protocol as p

FW_VERSION = (0, 1, 0)
HEARTBEAT_MS = 1000
RECEIVER_ONLINE_MS = 3500
DEFAULT_HOLD_MS = 2000


@dataclass
class SimReceiver:
    mac: bytes
    universe: int | None = None
    name: str = ""
    rssi: int = -55
    loss_pct: int = 0
    online: bool = True
    announced: bool = False
    frame: bytearray = field(default_factory=lambda: bytearray(p.DMX_CHANNELS))
    last_data_ms: int | None = None
    identify_until_ms: int = 0


class SimNode:
    def __init__(
        self,
        mac: bytes = bytes.fromhex("F412FA000001"),
        receivers: list[SimReceiver] | None = None,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self.mac = mac
        self.name = ""
        self.universe: int | None = 0
        self.receivers = receivers if receivers is not None else []
        self._clock = clock_ms or (lambda: int(time.monotonic() * 1000))
        self.boot_ms = self._clock()
        self.parser = p.Parser()
        self.out = bytearray()
        self.fallback: p.FallbackLook | None = None
        self.output = bytearray(p.DMX_CHANNELS)  # what's on the wired DMX line
        self.live = bytearray(p.DMX_CHANNELS)
        self.mode = p.Mode.FALLBACK  # boots into fallback until frames arrive
        self.fallback_start_ms = self.boot_ms
        self.last_frame_ms: int | None = None
        self.frames_rx = 0
        self.other_errors = 0
        self._rate_window: list[int] = []
        self._next_hb_ms = self.boot_ms
        self._announced = False
        self.identify_until_ms = 0
        self.dmx_packets_sent = 0  # wire packets, incremented on every immediate send

    # ------------------------------------------------------------------ io

    def now(self) -> int:
        return self._clock()

    def receive(self, data: bytes) -> None:
        for pkt in self.parser.feed(data):
            self._handle(pkt)

    def take_output(self) -> bytes:
        self.step()
        data, self.out = bytes(self.out), bytearray()
        return data

    # ------------------------------------------------------------------ behaviour

    def _hold_ms(self) -> int:
        return self.fallback.hold_ms if self.fallback else DEFAULT_HOLD_MS

    def _handle(self, pkt: p.Packet) -> None:
        t, pl = pkt.type, pkt.payload
        now = self.now()
        if t == p.MsgType.DMX_FRAME:
            if not 2 <= len(pl) <= 1 + p.DMX_CHANNELS:
                self._nak(t, p.AckCode.BAD_LENGTH)
                return
            universe, data = pl[0], pl[1:]
            self.frames_rx += 1
            self._rate_window.append(now)
            frame = bytearray(p.DMX_CHANNELS)
            frame[: len(data)] = data
            if universe == (self.universe or 0):
                self.live = frame
                self.last_frame_ms = now
                self.mode = p.Mode.LIVE
                self._send_dmx(self.live)
            self._radio_frame(universe, frame, now)
        elif t == p.MsgType.BLACKOUT:
            if len(pl) != 1:
                self._nak(t, p.AckCode.BAD_LENGTH)
                return
            self.live = bytearray(p.DMX_CHANNELS)
            self.mode = p.Mode.BLACKOUT
            self.last_frame_ms = now
            self._send_dmx(self.live)
            for r in self.receivers:
                if pl[0] in (p.UNIVERSE_ALL, r.universe):
                    r.frame = bytearray(p.DMX_CHANNELS)
        elif t == p.MsgType.PING:
            if len(pl) != 4:
                self._nak(t, p.AckCode.BAD_LENGTH)
                return
            self.out += p.encode(p.MsgType.PONG, pl)
        elif t == p.MsgType.STATUS_REQ:
            self.out += p.status_msg(self.status())
        elif t == p.MsgType.SET_FALLBACK:
            try:
                self.fallback = p.FallbackLook.unpack(pl)
            except p.ProtocolError:
                self._nak(t, p.AckCode.BAD_VALUE)
                return
            self.out += p.ack_msg(t)
        elif t in (p.MsgType.ASSIGN, p.MsgType.IDENTIFY):
            want = 6 + 1 + p.NAME_LEN if t == p.MsgType.ASSIGN else 7
            if len(pl) != want:
                self._nak(t, p.AckCode.BAD_LENGTH)
                return
            mac = pl[:6]
            target = self if mac == self.mac else next((r for r in self.receivers if r.mac == mac), None)
            if target is None:
                self._nak(t, p.AckCode.UNKNOWN_TARGET)
                return
            if t == p.MsgType.ASSIGN:
                target.universe = None if pl[6] == p.UNIVERSE_NONE else pl[6]
                target.name = p.unpack_name(pl[7:])
            else:
                target.identify_until_ms = now + pl[6] * 1000
            self.out += p.ack_msg(t)
        else:
            self._nak(t, p.AckCode.UNKNOWN_TYPE)

    def _nak(self, t: int, code: p.AckCode) -> None:
        self.other_errors += 1
        self.out += p.ack_msg(t, code)

    def _send_dmx(self, frame: bytes | bytearray) -> None:
        self.output[:] = frame
        self.dmx_packets_sent += 1

    def _radio_frame(self, universe: int, frame: bytes | bytearray, now: int) -> None:
        for r in self.receivers:
            # unassigned receivers follow universe 0 so a fresh single-universe rig works
            if r.online and (0 if r.universe is None else r.universe) == universe:
                r.frame[:] = frame
                r.last_data_ms = now

    def step(self) -> None:
        now = self.now()
        # live -> fallback after hold time with no frames (blackout stays black)
        if self.mode == p.Mode.LIVE and self.last_frame_ms is not None:
            if now - self.last_frame_ms > self._hold_ms():
                self.mode = p.Mode.FALLBACK
                self.fallback_start_ms = now
        if self.mode == p.Mode.FALLBACK:
            frame = p.render_fallback(self.fallback, now - self.fallback_start_ms)
            self._send_dmx(frame)
            self._radio_frame(self.universe or 0, frame, now)
        # heartbeats
        if not self._announced:
            self.out += p.heartbeat_msg(self.heartbeat(), announce=True)
            self._announced = True
        if now >= self._next_hb_ms:
            self._next_hb_ms = now + HEARTBEAT_MS
            self.out += p.heartbeat_msg(self.heartbeat())
            for r in self.receivers:
                if not r.online:
                    continue
                self.out += p.heartbeat_msg(self.receiver_heartbeat(r), announce=not r.announced)
                r.announced = True
            self.out += p.status_msg(self.status())

    def status(self) -> p.Status:
        now = self.now()
        self._rate_window = [t for t in self._rate_window if now - t < 1000]
        return p.Status(
            uptime_ms=now - self.boot_ms,
            frames_rx=self.frames_rx,
            frame_rate=float(len(self._rate_window)),
            crc_errors=self.parser.crc_errors,
            other_errors=self.other_errors,
            mode=self.mode,
            receivers_online=sum(1 for r in self.receivers if r.online),
        )

    def heartbeat(self) -> p.Heartbeat:
        now = self.now()
        return p.Heartbeat(
            mac=self.mac,
            node_type=p.NodeType.DMX_TX,
            fw=FW_VERSION,
            uptime_s=(now - self.boot_ms) // 1000,
            rssi=None,
            loss_pct=None,
            last_data_age_ms=None if self.last_frame_ms is None else now - self.last_frame_ms,
            universe=self.universe,
            name=self.name,
        )

    def receiver_heartbeat(self, r: SimReceiver) -> p.Heartbeat:
        now = self.now()
        return p.Heartbeat(
            mac=r.mac,
            node_type=p.NodeType.DMX_RX,
            fw=FW_VERSION,
            uptime_s=(now - self.boot_ms) // 1000,
            rssi=r.rssi,
            loss_pct=r.loss_pct,
            last_data_age_ms=None if r.last_data_ms is None else now - r.last_data_ms,
            universe=r.universe,
            name=r.name,
        )


class SimTransport:
    """Transport that talks to a SimNode in-process."""

    def __init__(self, node: SimNode) -> None:
        self.node = node

    def write(self, data: bytes) -> None:
        self.node.receive(data)

    def read(self) -> bytes:
        return self.node.take_output()

    def close(self) -> None:
        pass


def default_sim() -> SimNode:
    """Node with three unnamed receivers, like a fresh rig."""
    return SimNode(
        receivers=[
            SimReceiver(bytes.fromhex("F412FA00A001"), rssi=-52),
            SimReceiver(bytes.fromhex("F412FA00A002"), rssi=-67, loss_pct=2),
            SimReceiver(bytes.fromhex("F412FA00A003"), rssi=-84, loss_pct=14),
        ]
    )
