"""Network DMX: Art-Net and sACN (E1.31) over UDP, for off-the-shelf network nodes, visualisers
and other lighting software. Standard library only.

    outputs:
      - {driver: artnet, host: 2.255.255.255}               # broadcast; engine universe n -> Art-Net n
      - {driver: artnet, host: 192.168.1.50, universes: {0: "0:0:1", 1: 2}}   # net:subnet:universe or a number
      - {driver: sacn}                                      # multicast; engine universe n -> sACN n + 1
      - {driver: sacn, host: 192.168.1.60, universes: {0: 10}, priority: 120}

`universes` maps the engine's universes (0-15) to the network's; only mapped universes are sent
(no map = all of them, Art-Net n -> n, sACN n -> n + 1). Sending a UDP packet doesn't wait on
anything, so these drivers don't need a sender thread.
"""

from __future__ import annotations

import socket
import struct
import time
import uuid
from typing import Any

from .base import OutputDriver

ARTNET_PORT = 6454
SACN_PORT = 5568
OP_DMX = 0x5000


def artnet_address(v: Any) -> int:
    """Port-address 0-32767 from a number or "net:subnet:universe"."""
    if isinstance(v, str) and ":" in v:
        parts = v.split(":")
        if len(parts) != 3:
            raise ValueError(f"Art-Net universe {v!r}: use net:subnet:universe")
        net, sub, uni = (int(x) for x in parts)
        if not (0 <= net <= 127 and 0 <= sub <= 15 and 0 <= uni <= 15):
            raise ValueError(f"Art-Net universe {v!r}: net 0-127, subnet 0-15, universe 0-15")
        return (net << 8) | (sub << 4) | uni
    a = int(v)
    if not 0 <= a <= 32767:
        raise ValueError(f"Art-Net universe {v!r} must be 0-32767")
    return a


def artdmx_packet(address: int, seq: int, frame: bytes) -> bytes:
    data = bytes(frame)[:512].ljust(512, b"\x00")
    return (b"Art-Net\x00" + struct.pack("<H", OP_DMX) + struct.pack(">H", 14) + bytes([seq, 0])
            + struct.pack("<H", address) + struct.pack(">H", len(data)) + data)


def sacn_packet(universe: int, seq: int, frame: bytes, cid: bytes, source: str, priority: int) -> bytes:
    data = b"\x00" + bytes(frame)[:512].ljust(512, b"\x00")  # start code 0 + 512 slots
    dmp = struct.pack(">HBBHHH", 0x7000 | (10 + len(data)), 0x02, 0xA1, 0, 1, len(data)) + data
    name = source.encode("utf-8")[:63].ljust(64, b"\x00")
    framing_len = 77 + len(dmp)
    framing = (struct.pack(">HI", 0x7000 | framing_len, 0x00000002) + name
               + struct.pack(">BHBBH", priority, 0, seq, 0, universe) + dmp)
    root_len = 22 + len(framing)
    root = struct.pack(">HH", 0x0010, 0x0000) + b"ASC-E1.17\x00\x00\x00" + struct.pack(">HI", 0x7000 | root_len, 0x00000004) + cid
    return root + framing


def sacn_multicast(universe: int) -> str:
    return f"239.255.{universe >> 8}.{universe & 0xFF}"


class _UdpDriver(OutputDriver):
    label = ""

    def __init__(self, universes: dict[Any, Any] | None, default: Any, bind: str | None) -> None:
        self.map = {int(k): self._address(v) for k, v in universes.items()} if universes else None
        self._default = default
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.setblocking(False)  # never wait on the network
        if bind:
            self.sock.bind((bind, 0))
        self.seq: dict[int, int] = {}
        self.packets = 0
        self.errors = 0
        self.last_error = ""
        self.ok_at: float | None = None

    def _address(self, v: Any) -> int:
        raise NotImplementedError

    def target(self, universe: int) -> int | None:
        if self.map is None:
            return self._default(universe)
        return self.map.get(universe)

    def next_seq(self, universe: int) -> int:
        s = self.seq.get(universe, 0) % 255 + 1  # 1-255 (0 would mean "no sequencing")
        self.seq[universe] = s
        return s

    def _send(self, packet: bytes, dest: tuple[str, int]) -> None:
        try:
            self.sock.sendto(packet, dest)
            self.packets += 1
            self.ok_at = time.monotonic()
        except OSError as e:  # no network, cable out: count it, the show carries on
            self.errors += 1
            self.last_error = str(e) or type(e).__name__

    def close(self) -> None:
        self.sock.close()

    def status(self) -> dict[str, Any]:
        return {"driver": self.name, "packets": self.packets, "errors": self.errors}

    def describe(self) -> str:
        raise NotImplementedError

    def state(self) -> dict[str, Any]:
        fresh = self.ok_at is not None and time.monotonic() - self.ok_at < 1.0
        if fresh:
            return {"kind": "output", "name": self.label, "state": "ok", "detail": self.describe()}
        if self.errors:
            return {"kind": "output", "name": self.label, "state": "bad", "detail": f"{self.describe()} · {self.last_error}"}
        return {"kind": "output", "name": self.label, "state": "warn", "detail": f"{self.describe()} · nothing sent yet"}


class ArtNetDriver(_UdpDriver):
    name = "artnet"
    label = "Art-Net"

    def __init__(self, host: str = "255.255.255.255", port: int = ARTNET_PORT, universes: dict[Any, Any] | None = None,
                 bind: str | None = None) -> None:
        super().__init__(universes, lambda u: u, bind)
        self.dest = (host, int(port))

    def _address(self, v: Any) -> int:
        return artnet_address(v)

    def send(self, universe: int, frame: bytes) -> None:
        addr = self.target(universe)
        if addr is not None:
            self._send(artdmx_packet(addr, self.next_seq(universe), frame), self.dest)

    def describe(self) -> str:
        return f"{self.dest[0]}"


class SacnDriver(_UdpDriver):
    name = "sacn"
    label = "sACN"

    def __init__(self, host: str | None = None, port: int = SACN_PORT, universes: dict[Any, Any] | None = None,
                 priority: int = 100, source_name: str = "0.05 DMX Suite", ttl: int = 4, bind: str | None = None) -> None:
        super().__init__(universes, lambda u: u + 1, bind)
        if not 0 <= int(priority) <= 200:
            raise ValueError("sACN priority must be 0-200")
        self.host, self.port, self.priority, self.source = host, int(port), int(priority), source_name
        # the same sender id every time on this computer, so receivers see one source across restarts
        self.cid = uuid.uuid5(uuid.NAMESPACE_DNS, f"dmx-suite.{socket.gethostname()}.{source_name}").bytes
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, int(ttl))

    def _address(self, v: Any) -> int:
        u = int(v)
        if not 1 <= u <= 63999:
            raise ValueError(f"sACN universe {v!r} must be 1-63999")
        return u

    def send(self, universe: int, frame: bytes) -> None:
        u = self.target(universe)
        if u is not None:
            pkt = sacn_packet(u, self.next_seq(universe), frame, self.cid, self.source, self.priority)
            self._send(pkt, (self.host or sacn_multicast(u), self.port))

    def describe(self) -> str:
        return self.host or "multicast"
