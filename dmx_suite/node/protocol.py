"""0.05 node link wire protocol (USB serial). Spec: docs/PROTOCOL.md."""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from enum import IntEnum

START = 0xA5
MAX_PAYLOAD = 1100
DMX_CHANNELS = 512
NAME_LEN = 16
MAX_FALLBACK_RGB = 32

RSSI_NA = 127
LOSS_NA = 255
AGE_NEVER = 0xFFFFFFFF
UNIVERSE_NONE = 0xFF
UNIVERSE_ALL = 0xFF


class MsgType(IntEnum):
    # laptop -> node
    DMX_FRAME = 0x01
    BLACKOUT = 0x02
    PING = 0x03
    SET_FALLBACK = 0x04
    ASSIGN = 0x05
    IDENTIFY = 0x06
    STATUS_REQ = 0x07
    # node -> laptop
    STATUS = 0x81
    HEARTBEAT = 0x82
    ANNOUNCE = 0x83
    PONG = 0x84
    ACK = 0x85
    LOG = 0x86


class AckCode(IntEnum):
    OK = 0
    BAD_LENGTH = 1
    BAD_VALUE = 2
    UNKNOWN_TARGET = 3
    STORAGE_ERROR = 4
    UNKNOWN_TYPE = 5


class NodeType(IntEnum):
    DMX_TX = 1
    DMX_RX = 2
    MIDI = 3


class Mode(IntEnum):
    LIVE = 0
    FALLBACK = 1
    BLACKOUT = 2


KNOWN_TYPES = frozenset(int(t) for t in MsgType)


class ProtocolError(ValueError):
    pass


# --------------------------------------------------------------------------- framing


def crc16(data: bytes, crc: int = 0xFFFF) -> int:
    """CRC-16/CCITT-FALSE."""
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc


def encode(msg_type: int, payload: bytes = b"") -> bytes:
    if len(payload) > MAX_PAYLOAD:
        raise ProtocolError(f"payload {len(payload)} > {MAX_PAYLOAD}")
    body = struct.pack("<BH", msg_type, len(payload)) + payload
    return bytes([START]) + body + struct.pack("<H", crc16(body))


@dataclass
class Packet:
    type: int
    payload: bytes


class Parser:
    """Stream decoder with resync. Feed bytes, get complete packets."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self.crc_errors = 0

    def feed(self, data: bytes) -> list[Packet]:
        self._buf += data
        out: list[Packet] = []
        buf = self._buf
        while True:
            i = buf.find(START)
            if i < 0:
                buf.clear()
                break
            if i:
                del buf[:i]
            # reject unknown types at the header so a stray START can't stall us on a bogus length
            if len(buf) >= 2 and buf[1] not in KNOWN_TYPES:
                self.crc_errors += 1
                del buf[0]
                continue
            if len(buf) < 4:
                break
            msg_type, length = struct.unpack_from("<BH", buf, 1)
            if length > MAX_PAYLOAD:
                self.crc_errors += 1
                del buf[0]
                continue
            total = 1 + 3 + length + 2
            if len(buf) < total:
                break
            (crc,) = struct.unpack_from("<H", buf, 4 + length)
            if crc != crc16(bytes(buf[1 : 4 + length])):
                self.crc_errors += 1
                del buf[0]
                continue
            out.append(Packet(msg_type, bytes(buf[4 : 4 + length])))
            del buf[:total]
        return out


# --------------------------------------------------------------------------- helpers


def mac_str(mac: bytes) -> str:
    return ":".join(f"{b:02X}" for b in mac)


def parse_mac(text: str) -> bytes:
    parts = text.replace("-", ":").split(":")
    if len(parts) != 6:
        raise ProtocolError(f"bad MAC {text!r}")
    return bytes(int(p, 16) for p in parts)


def _check_mac(mac: bytes) -> None:
    if len(mac) != 6:
        raise ProtocolError("MAC must be 6 bytes")


def pack_name(name: str) -> bytes:
    raw = name.encode("utf-8")
    if len(raw) > NAME_LEN:
        raise ProtocolError(f"name longer than {NAME_LEN} bytes: {name!r}")
    return raw.ljust(NAME_LEN, b"\0")


def unpack_name(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("utf-8", errors="replace")


# --------------------------------------------------------------------------- laptop -> node


def dmx_frame(channels: bytes | bytearray | list[int], universe: int = 0) -> bytes:
    data = bytes(channels)
    if not 1 <= len(data) <= DMX_CHANNELS:
        raise ProtocolError(f"frame must be 1-{DMX_CHANNELS} channels, got {len(data)}")
    return encode(MsgType.DMX_FRAME, bytes([universe]) + data)


def blackout(universe: int = UNIVERSE_ALL) -> bytes:
    return encode(MsgType.BLACKOUT, bytes([universe]))


def ping(token: int) -> bytes:
    return encode(MsgType.PING, struct.pack("<I", token & 0xFFFFFFFF))


def status_req() -> bytes:
    return encode(MsgType.STATUS_REQ)


def assign(mac: bytes, universe: int, name: str) -> bytes:
    _check_mac(mac)
    if not 0 <= universe <= 0xFF:
        raise ProtocolError("universe 0-255")
    return encode(MsgType.ASSIGN, mac + bytes([universe]) + pack_name(name))


def identify(mac: bytes, seconds: int = 5) -> bytes:
    _check_mac(mac)
    return encode(MsgType.IDENTIFY, mac + bytes([max(0, min(255, seconds))]))


@dataclass
class FallbackLook:
    hold_ms: int = 2000
    period_s: int = 60
    level: int = 255
    rgb_addr: list[int] = field(default_factory=list)  # 1-based red channel addresses
    base: bytes = bytes(DMX_CHANNELS)

    def pack(self) -> bytes:
        if len(self.rgb_addr) > MAX_FALLBACK_RGB:
            raise ProtocolError(f"max {MAX_FALLBACK_RGB} RGB addresses")
        for a in self.rgb_addr:
            if not 1 <= a <= DMX_CHANNELS - 2:
                raise ProtocolError(f"RGB address {a} out of range")
        if len(self.base) != DMX_CHANNELS:
            raise ProtocolError("base must be 512 bytes")
        return (
            struct.pack("<HHBB", self.hold_ms, self.period_s, self.level, len(self.rgb_addr))
            + struct.pack(f"<{len(self.rgb_addr)}H", *self.rgb_addr)
            + bytes(self.base)
        )

    @classmethod
    def unpack(cls, payload: bytes) -> "FallbackLook":
        if len(payload) < 6:
            raise ProtocolError("short fallback")
        hold, period, level, n = struct.unpack_from("<HHBB", payload)
        if n > MAX_FALLBACK_RGB or len(payload) != 6 + 2 * n + DMX_CHANNELS:
            raise ProtocolError("bad fallback length")
        addrs = list(struct.unpack_from(f"<{n}H", payload, 6))
        look = cls(hold, period, level, addrs, payload[6 + 2 * n :])
        look.pack()  # range checks
        return look


def set_fallback(look: FallbackLook) -> bytes:
    return encode(MsgType.SET_FALLBACK, look.pack())


# --------------------------------------------------------------------------- node -> laptop

_STATUS = struct.Struct("<IIHIHBB")
_HEARTBEAT = struct.Struct("<6sB3sIbBIB16s")


@dataclass
class Status:
    uptime_ms: int
    frames_rx: int
    frame_rate: float
    crc_errors: int
    other_errors: int
    mode: Mode
    receivers_online: int

    def pack(self) -> bytes:
        return _STATUS.pack(
            self.uptime_ms,
            self.frames_rx,
            round(self.frame_rate * 10),
            self.crc_errors,
            self.other_errors,
            int(self.mode),
            self.receivers_online,
        )

    @classmethod
    def unpack(cls, payload: bytes) -> "Status":
        if len(payload) != _STATUS.size:
            raise ProtocolError("bad STATUS length")
        up, frames, rate, crc, other, mode, rx = _STATUS.unpack(payload)
        return cls(up, frames, rate / 10, crc, other, Mode(mode), rx)


@dataclass
class Heartbeat:
    mac: bytes
    node_type: NodeType
    fw: tuple[int, int, int]
    uptime_s: int
    rssi: int | None  # dBm, None = n/a
    loss_pct: int | None  # None = n/a
    last_data_age_ms: int | None  # None = never
    universe: int | None  # None = unassigned
    name: str

    @property
    def mac_str(self) -> str:
        return mac_str(self.mac)

    @property
    def fw_str(self) -> str:
        return ".".join(map(str, self.fw))

    def pack(self) -> bytes:
        return _HEARTBEAT.pack(
            self.mac,
            int(self.node_type),
            bytes(self.fw),
            self.uptime_s,
            RSSI_NA if self.rssi is None else self.rssi,
            LOSS_NA if self.loss_pct is None else self.loss_pct,
            AGE_NEVER if self.last_data_age_ms is None else self.last_data_age_ms,
            UNIVERSE_NONE if self.universe is None else self.universe,
            pack_name(self.name),
        )

    @classmethod
    def unpack(cls, payload: bytes) -> "Heartbeat":
        if len(payload) != _HEARTBEAT.size:
            raise ProtocolError("bad HEARTBEAT length")
        mac, typ, fw, up, rssi, loss, age, uni, name = _HEARTBEAT.unpack(payload)
        try:
            node_type = NodeType(typ)
        except ValueError as e:
            raise ProtocolError(f"unknown node type {typ}") from e
        return cls(
            mac,
            node_type,
            (fw[0], fw[1], fw[2]),
            up,
            None if rssi == RSSI_NA else rssi,
            None if loss == LOSS_NA else loss,
            None if age == AGE_NEVER else age,
            None if uni == UNIVERSE_NONE else uni,
            unpack_name(name),
        )


HEARTBEAT_SIZE = _HEARTBEAT.size
STATUS_SIZE = _STATUS.size


@dataclass
class Ack:
    acked_type: int
    code: AckCode


@dataclass
class Pong:
    token: int


@dataclass
class Log:
    text: str


@dataclass
class Announce:
    heartbeat: Heartbeat


Message = Status | Heartbeat | Announce | Ack | Pong | Log


def decode(pkt: Packet) -> Message:
    """Decode a node -> laptop packet."""
    t, p = pkt.type, pkt.payload
    if t == MsgType.STATUS:
        return Status.unpack(p)
    if t == MsgType.HEARTBEAT:
        return Heartbeat.unpack(p)
    if t == MsgType.ANNOUNCE:
        return Announce(Heartbeat.unpack(p))
    if t == MsgType.PONG:
        if len(p) != 4:
            raise ProtocolError("bad PONG length")
        return Pong(struct.unpack("<I", p)[0])
    if t == MsgType.ACK:
        if len(p) != 2:
            raise ProtocolError("bad ACK length")
        try:
            code = AckCode(p[1])
        except ValueError as e:
            raise ProtocolError(f"unknown ACK code {p[1]}") from e
        return Ack(p[0], code)
    if t == MsgType.LOG:
        return Log(p.decode("utf-8", errors="replace"))
    raise ProtocolError(f"unknown node message type 0x{t:02X}")


# --------------------------------------------------------------------------- node-side encoders (sim + tests)


def status_msg(s: Status) -> bytes:
    return encode(MsgType.STATUS, s.pack())


def heartbeat_msg(hb: Heartbeat, announce: bool = False) -> bytes:
    return encode(MsgType.ANNOUNCE if announce else MsgType.HEARTBEAT, hb.pack())


def pong_msg(token: int) -> bytes:
    return encode(MsgType.PONG, struct.pack("<I", token))


def ack_msg(acked_type: int, code: AckCode = AckCode.OK) -> bytes:
    return encode(MsgType.ACK, bytes([acked_type, int(code)]))


def log_msg(text: str) -> bytes:
    return encode(MsgType.LOG, text.encode("utf-8")[:MAX_PAYLOAD])


# --------------------------------------------------------------------------- shared look maths


def fnv1a32(data: bytes) -> int:
    h = 0x811C9DC5
    for b in data:
        h = ((h ^ b) * 0x01000193) & 0xFFFFFFFF
    return h


HUE_STEPS = 1536  # 6 sectors x 256


def hue_rgb(h: int) -> tuple[int, int, int]:
    """Hue step 0-1535 -> full-saturation RGB 0-255. Identical to firmware."""
    sector, f = divmod(h % HUE_STEPS, 256)
    up, down = f, 255 - f
    return [
        (255, up, 0),
        (down, 255, 0),
        (0, 255, up),
        (0, down, 255),
        (up, 0, 255),
        (255, 0, down),
    ][sector]


def render_fallback(look: FallbackLook | None, elapsed_ms: int) -> bytes:
    """Fallback frame at `elapsed_ms` since fallback started. Matches firmware."""
    if look is None:
        return bytes(DMX_CHANNELS)
    frame = bytearray(look.base)
    if look.period_s:
        period_ms = look.period_s * 1000
        h = (elapsed_ms % period_ms) * HUE_STEPS // period_ms
    else:
        h = 0
    r, g, b = hue_rgb(h)
    r, g, b = (r * look.level // 255, g * look.level // 255, b * look.level // 255)
    for a in look.rgb_addr:
        frame[a - 1 : a + 2] = bytes((r, g, b))
    return bytes(frame)
