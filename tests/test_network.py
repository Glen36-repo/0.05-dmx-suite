"""Art-Net and sACN: packets decoded off a loopback socket, byte by byte."""

import socket
import struct

import pytest

from dmx_suite.output import make_driver
from dmx_suite.output.network import artdmx_packet, artnet_address, sacn_multicast, sacn_packet


@pytest.fixture
def rx():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    s.settimeout(2)
    yield s
    s.close()


def frame(seed=1):
    return bytes((i * seed) % 256 for i in range(512))


def test_artnet_packet_layout(rx):
    d = make_driver({"driver": "artnet", "host": "127.0.0.1", "port": rx.getsockname()[1],
                     "universes": {0: "1:2:3", 1: 7}})
    d.send(0, frame(1))
    d.send(1, frame(3))
    d.send(2, frame(5))  # not in the map: not sent
    a, b = rx.recv(1000), rx.recv(1000)
    for pkt in (a, b):
        assert pkt[:8] == b"Art-Net\x00" and struct.unpack("<H", pkt[8:10])[0] == 0x5000
        assert struct.unpack(">H", pkt[10:12])[0] == 14 and struct.unpack(">H", pkt[16:18])[0] == 512
    assert struct.unpack("<H", a[14:16])[0] == (1 << 8) | (2 << 4) | 3 and a[18:] == frame(1)
    assert struct.unpack("<H", b[14:16])[0] == 7 and b[18:] == frame(3)
    rx.settimeout(0.2)
    with pytest.raises(socket.timeout):
        rx.recv(1000)
    assert d.packets == 2 and d.state()["state"] == "ok"
    d.close()


def test_artnet_sequence_wraps_1_to_255(rx):
    d = make_driver({"driver": "artnet", "host": "127.0.0.1", "port": rx.getsockname()[1]})
    seqs = []
    for _ in range(256):
        d.send(0, frame())
        seqs.append(rx.recv(1000)[12])
    assert seqs[0] == 1 and seqs[254] == 255 and seqs[255] == 1 and 0 not in seqs
    d.close()


@pytest.mark.parametrize("v, a", [(0, 0), (32767, 32767), ("0:0:1", 1), ("127:15:15", 32767)])
def test_artnet_addresses(v, a):
    assert artnet_address(v) == a


@pytest.mark.parametrize("v", [-1, 32768, "1:2", "128:0:0", "0:16:0"])
def test_bad_artnet_addresses(v):
    with pytest.raises(ValueError):
        artnet_address(v)


def test_sacn_packet_layout(rx):
    d = make_driver({"driver": "sacn", "host": "127.0.0.1", "port": rx.getsockname()[1],
                     "universes": {0: 10}, "priority": 150, "source_name": "Test rig"})
    d.send(0, frame(7))
    pkt = rx.recv(1000)
    assert len(pkt) == 638
    assert pkt[0:2] == b"\x00\x10" and pkt[4:16] == b"ASC-E1.17\x00\x00\x00"
    assert struct.unpack(">H", pkt[16:18])[0] == 0x7000 | 622 and struct.unpack(">I", pkt[18:22])[0] == 4
    assert pkt[22:38] == d.cid
    assert struct.unpack(">H", pkt[38:40])[0] == 0x7000 | 600 and struct.unpack(">I", pkt[40:44])[0] == 2
    assert pkt[44:108].rstrip(b"\x00") == b"Test rig"
    assert pkt[108] == 150 and pkt[111] == 1 and struct.unpack(">H", pkt[113:115])[0] == 10  # priority, seq, universe
    assert struct.unpack(">H", pkt[115:117])[0] == 0x7000 | 523 and pkt[117] == 0x02 and pkt[118] == 0xA1
    assert struct.unpack(">HHH", pkt[119:125]) == (0, 1, 513)
    assert pkt[125] == 0 and pkt[126:] == frame(7)  # start code, then the 512 channels
    d.close()


def test_sacn_defaults_and_cid_is_stable():
    a = make_driver({"driver": "sacn"})
    b = make_driver({"driver": "sacn"})
    assert a.target(0) == 1 and a.target(3) == 4  # engine universe n -> sACN n + 1
    assert a.cid == b.cid  # the same source to receivers after a restart
    assert sacn_multicast(1) == "239.255.0.1" and sacn_multicast(300) == "239.255.1.44"
    assert len(sacn_packet(1, 1, bytes(512), a.cid, "x", 100)) == 638
    a.close()
    b.close()
    with pytest.raises(ValueError, match="1-63999"):
        make_driver({"driver": "sacn", "universes": {0: 0}})
    with pytest.raises(ValueError, match="priority"):
        make_driver({"driver": "sacn", "priority": 201})


def test_network_trouble_doesnt_stop_the_show():
    d = make_driver({"driver": "artnet", "host": "203.0.113.1", "port": 6454})

    class Broken:
        def sendto(self, *a):
            raise OSError("Network is unreachable")

        def close(self):
            pass

    d.sock = Broken()
    d.send(0, frame())  # no exception
    assert d.errors == 1 and d.state()["state"] == "bad" and "unreachable" in d.state()["detail"]


def test_artdmx_packet_pads_short_frames():
    assert len(artdmx_packet(0, 1, b"\x01\x02")) == 18 + 512
