"""Simulated CoreS3 node + AtomS3 receivers. Mirrors firmware/src/node/main.cpp behaviour (0.2).

Used by tests and `dmx-node-test --sim` so the laptop side can be built with no hardware.
Radio is modelled per universe like the firmware: every frame sent to a universe carries that
universe's next sequence number, a receiver drops each packet with its `loss_pct` chance, and the
loss it reports is worked out from the gaps it saw (not just copied), as on the AtomS3.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from . import protocol as p

FW_VERSION = (0, 2, 0)
HEARTBEAT_MS = 1000
RECEIVER_ONLINE_MS = 3500
DEFAULT_HOLD_MS = 2000


@dataclass
class SimReceiver:
    mac: bytes
    universe: int | None = None
    name: str = ""
    rssi: int = -55
    loss_pct: int = 0  # chance (%) each radio packet is lost
    online: bool = True
    announced: bool = False
    frame: bytearray = field(default_factory=lambda: bytearray(p.DMX_CHANNELS))
    last_data_ms: int | None = None
    identify_until_ms: int = 0
    channel: int = 1
    last_seq: int | None = None
    got: int = 0
    missed: int = 0
    measured_loss: int | None = None  # what the last heartbeat reported

    @property
    def active_universe(self) -> int:
        return 0 if self.universe is None else self.universe

    def hear(self, universe: int, seq: int, frame: bytes | bytearray, now: int, rng: random.Random) -> None:
        """One radio DMX packet (all its chunks) for `universe`, as the AtomS3 handles it."""
        if universe != self.active_universe:
            return  # another universe: not counted, so it can't look like loss
        if rng.random() * 100 < self.loss_pct:
            return  # lost on the air
        if self.last_seq is not None:
            gap = (seq - self.last_seq) & 0xFF
            if 1 < gap < 64:
                self.missed += gap - 1
        self.got += 1
        self.last_seq = seq
        self.frame[:] = frame
        self.last_data_ms = now

    def take_loss(self) -> int:
        total = self.got + self.missed
        self.measured_loss = self.missed * 100 // total if total else 0
        self.got = self.missed = 0
        return self.measured_loss


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
        self.fallbacks: dict[int, p.FallbackLook] = {}  # universe -> look (0.2: up to MAX_FALLBACKS)
        self.frames: dict[int, bytearray] = {}  # universe -> last frame (keep-alive)
        self.seen_ms: dict[int, int] = {}
        self.radio_seq: dict[int, int] = {}
        self.radio_sent: dict[int, int] = {}  # packets per universe (tests)
        self.channel = 1
        self.dev_key = True
        self._radio_last_ms = -10**9
        self.rng = random.Random(5)

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
        own = self.fallbacks.get(self.universe or 0)
        return own.hold_ms if own else DEFAULT_HOLD_MS

    @property
    def fallback(self) -> p.FallbackLook | None:  # the node's own universe (v1 name)
        return self.fallbacks.get(self.universe or 0)

    def _active(self, u: int, now: int) -> bool:
        return (u in self.seen_ms and now - self.seen_ms[u] < 10_000) or u in self.fallbacks

    def _ack(self, t: int, code: p.AckCode = p.AckCode.OK, req: int | None = None) -> None:
        if code != p.AckCode.OK:
            self.other_errors += 1
        self.out += p.ack_msg(t, code, req)

    def _set_fallback(self, universe: int, payload: bytes) -> p.AckCode:
        if not 0 <= universe < p.MAX_UNIVERSES:
            return p.AckCode.BAD_VALUE
        try:
            look = p.FallbackLook.unpack(payload)
        except p.ProtocolError:
            return p.AckCode.BAD_VALUE
        if universe not in self.fallbacks and len(self.fallbacks) >= p.MAX_FALLBACKS:
            return p.AckCode.BAD_VALUE
        self.fallbacks[universe] = look
        return p.AckCode.OK

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
            self.last_frame_ms = now
            self.mode = p.Mode.LIVE
            if universe == (self.universe or 0):
                self.live = frame
                self._send_dmx(self.live)
            if universe < p.MAX_UNIVERSES:
                self.frames[universe] = bytearray(frame)
                self.seen_ms[universe] = now
                self._radio_frame(universe, frame, now)
        elif t == p.MsgType.BLACKOUT:
            if len(pl) != 1:
                self._nak(t, p.AckCode.BAD_LENGTH)
                return
            self.mode = p.Mode.BLACKOUT
            self.last_frame_ms = now
            for u in range(p.MAX_UNIVERSES):  # every universe, not just the node's own
                if pl[0] not in (p.UNIVERSE_ALL, u):
                    continue
                self.frames[u] = bytearray(p.DMX_CHANNELS)
                if u == (self.universe or 0):
                    self.live = bytearray(p.DMX_CHANNELS)
                    self._send_dmx(self.live)
                if pl[0] == u or self._active(u, now) or u == (self.universe or 0):
                    self._radio_frame(u, self.frames[u], now)
        elif t == p.MsgType.PING:
            if len(pl) != 4:
                self._nak(t, p.AckCode.BAD_LENGTH)
                return
            self.out += p.encode(p.MsgType.PONG, pl)
        elif t == p.MsgType.STATUS_REQ:
            self.out += p.status_msg(self.status())
        elif t == p.MsgType.SET_FALLBACK:
            got = p.split_request(pl, p.fallback_size(pl)) if p.fallback_size(pl) else None
            if got is None:
                self._nak(t, p.AckCode.BAD_LENGTH)
                return
            self._ack(t, self._set_fallback(self.universe or 0, got[0]), got[1])
        elif t == p.MsgType.SET_FALLBACK_UNIVERSE:
            size = p.fallback_size(pl[1:]) if pl else 0
            got = p.split_request(pl, size + 1) if size else None
            if got is None:
                self._nak(t, p.AckCode.BAD_LENGTH)
                return
            self._ack(t, self._set_fallback(pl[0], got[0][1:]), got[1])
        elif t == p.MsgType.SET_CHANNEL:
            got = p.split_request(pl, 1)
            if got is None:
                self._nak(t, p.AckCode.BAD_LENGTH)
                return
            ch = got[0][0]
            if not p.MIN_CHANNEL <= ch <= p.MAX_CHANNEL:
                self._ack(t, p.AckCode.BAD_VALUE, got[1])
                return
            self.channel = ch
            for r in self.receivers:  # they hear SET_CHANNEL on the old channel and follow
                if r.online:
                    r.channel = ch
            self._ack(t, p.AckCode.OK, got[1])
        elif t in (p.MsgType.ASSIGN, p.MsgType.IDENTIFY):
            want = 6 + 1 + p.NAME_LEN if t == p.MsgType.ASSIGN else 7
            got = p.split_request(pl, want)
            if got is None:
                self._nak(t, p.AckCode.BAD_LENGTH)
                return
            body, req = got
            mac = body[:6]
            target = self if mac == self.mac else next((r for r in self.receivers if r.mac == mac), None)
            if target is None:
                self._ack(t, p.AckCode.UNKNOWN_TARGET, req)
                return
            if t == p.MsgType.ASSIGN:
                if target is self:
                    target.universe = 0 if body[6] == p.UNIVERSE_NONE else body[6]
                else:
                    target.universe = None if body[6] == p.UNIVERSE_NONE else body[6]
                target.name = p.unpack_name(body[7:])
            else:
                target.identify_until_ms = now + body[6] * 1000
            self._ack(t, p.AckCode.OK, req)
        else:
            self._nak(t, p.AckCode.UNKNOWN_TYPE)

    def _nak(self, t: int, code: p.AckCode) -> None:
        self.other_errors += 1
        self.out += p.ack_msg(t, code)

    def _send_dmx(self, frame: bytes | bytearray) -> None:
        self.output[:] = frame
        self.dmx_packets_sent += 1

    def _radio_frame(self, universe: int, frame: bytes | bytearray, now: int) -> None:
        if not 0 <= universe < p.MAX_UNIVERSES:
            return
        seq = self.radio_seq.get(universe, 0)
        self.radio_seq[universe] = (seq + 1) & 0xFF  # per universe, as firmware 0.2
        self.radio_sent[universe] = self.radio_sent.get(universe, 0) + 1
        self._radio_last_ms = now
        for r in self.receivers:
            # unassigned receivers follow universe 0 so a fresh single-universe rig works
            if r.online and r.channel == self.channel:
                r.hear(universe, seq, frame, now, self.rng)

    def step(self) -> None:
        now = self.now()
        # live -> fallback after hold time with no frames (blackout stays black)
        if self.mode == p.Mode.LIVE and self.last_frame_ms is not None:
            if now - self.last_frame_ms > self._hold_ms():
                self.mode = p.Mode.FALLBACK
                self.fallback_start_ms = now
        own = self.universe or 0
        if self.mode == p.Mode.FALLBACK and now - self._radio_last_ms >= 25:
            for u in range(p.MAX_UNIVERSES):  # every universe: its own look, or black
                if u != own and not self._active(u, now):
                    continue
                frame = p.render_fallback(self.fallbacks.get(u), now - self.fallback_start_ms)
                if u == own:
                    self._send_dmx(frame)
                self._radio_frame(u, frame, now)
        elif self.mode != p.Mode.FALLBACK and now - self._radio_last_ms >= 100:  # keep-alive
            for u in range(p.MAX_UNIVERSES):
                if u == own or self._active(u, now):
                    self._radio_frame(u, self.frames.get(u, bytearray(p.DMX_CHANNELS)), now)
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
            receivers_online=sum(1 for r in self.receivers if r.online and r.channel == self.channel),
            flags=p.FLAG_DEV_KEY if self.dev_key else 0,
            channel=self.channel,
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
            loss_pct=r.take_loss() if r.last_data_ms is not None else None,
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
