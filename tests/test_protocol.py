import random
import struct

import pytest

from dmx_suite.node import protocol as p


def test_crc16_check_value():
    assert p.crc16(b"123456789") == 0x29B1  # CRC-16/CCITT-FALSE check value


def test_encode_layout():
    pkt = p.ping(0x12345678)
    assert pkt[0] == p.START
    assert pkt[1] == p.MsgType.PING
    assert struct.unpack_from("<H", pkt, 2)[0] == 4
    assert pkt[4:8] == bytes.fromhex("78563412")
    assert struct.unpack_from("<H", pkt, 8)[0] == p.crc16(pkt[1:8])


def test_record_sizes():
    assert p.HEARTBEAT_SIZE == 37
    assert p.STATUS_SIZE == 20  # v1.1 (firmware 0.2 adds flags + radio channel)


def test_roundtrip_all_node_messages():
    hb = p.Heartbeat(bytes(range(6)), p.NodeType.DMX_RX, (0, 1, 2), 99, -70, 4, 25, 0, "Left bars")
    st = p.Status(1000, 40, 39.5, 1, 2, p.Mode.LIVE, 3)
    stream = (
        p.heartbeat_msg(hb)
        + p.heartbeat_msg(hb, announce=True)
        + p.status_msg(st)
        + p.pong_msg(7)
        + p.ack_msg(p.MsgType.ASSIGN, p.AckCode.UNKNOWN_TARGET)
        + p.log_msg("hello")
    )
    msgs = [p.decode(x) for x in p.Parser().feed(stream)]
    assert msgs[0] == hb
    assert msgs[1] == p.Announce(hb)
    assert msgs[2] == st
    assert msgs[3] == p.Pong(7)
    assert msgs[4] == p.Ack(p.MsgType.ASSIGN, p.AckCode.UNKNOWN_TARGET)
    assert msgs[5] == p.Log("hello")


def test_heartbeat_not_applicable_values():
    hb = p.Heartbeat(bytes(6), p.NodeType.DMX_TX, (0, 1, 0), 0, None, None, None, None, "")
    assert p.Heartbeat.unpack(hb.pack()) == hb


def test_parser_byte_at_a_time():
    data = p.dmx_frame(bytes(range(256)) * 2) + p.ping(1)
    parser = p.Parser()
    got = []
    for b in data:
        got += parser.feed(bytes([b]))
    assert [g.type for g in got] == [p.MsgType.DMX_FRAME, p.MsgType.PING]
    assert got[0].payload[1:] == bytes(range(256)) * 2


def test_parser_resyncs_after_garbage_and_corruption():
    bad = bytearray(p.ping(5))
    bad[5] ^= 0xFF
    stream = b"\x00\xa5\x99" + bytes(bad) + p.ping(6) + p.status_req()
    parser = p.Parser()
    got = parser.feed(stream)
    assert [g.type for g in got] == [p.MsgType.PING, p.MsgType.STATUS_REQ]
    assert got[0].payload == struct.pack("<I", 6)
    assert parser.crc_errors >= 2


def test_stray_start_does_not_stall():
    # 0xA5 followed by a known type and a huge-but-legal length: must recover once CRC fails,
    # and a following good frame must not be lost.
    stream = bytes([p.START, p.MsgType.PING, 0x00, 0x04]) + p.ping(9) * 200
    got = p.Parser().feed(stream)
    assert len(got) >= 199


def test_parser_random_noise_never_crashes():
    rng = random.Random(1)
    parser = p.Parser()
    good = p.ping(42)
    found = 0
    for _ in range(200):
        noise = bytes(rng.randrange(256) for _ in range(rng.randrange(40)))
        found += sum(1 for m in parser.feed(noise + good) if m.payload == struct.pack("<I", 42))
    assert found >= 190


def test_short_frame_and_limits():
    assert len(p.Parser().feed(p.dmx_frame(b"\x10"))[0].payload) == 2
    with pytest.raises(p.ProtocolError):
        p.dmx_frame(b"")
    with pytest.raises(p.ProtocolError):
        p.dmx_frame(bytes(513))
    with pytest.raises(p.ProtocolError):
        p.assign(b"\x00" * 6, 0, "x" * 17)


def test_fallback_pack_roundtrip_and_validation():
    base = bytearray(512)
    base[9] = 255
    look = p.FallbackLook(1500, 6, 200, [1, 4, 100], bytes(base))
    assert p.FallbackLook.unpack(look.pack()) == look
    with pytest.raises(p.ProtocolError):
        p.FallbackLook(rgb_addr=[511]).pack()  # needs 3 channels
    with pytest.raises(p.ProtocolError):
        p.FallbackLook(rgb_addr=list(range(1, 34))).pack()


def test_fallback_render():
    base = bytearray(512)
    base[9] = 255
    look = p.FallbackLook(1500, 6, 200, [1, 4], bytes(base))
    f0 = p.render_fallback(look, 0)
    assert f0[0:6] == bytes([200, 0, 0, 200, 0, 0])  # red at hue 0
    assert f0[9] == 255  # base kept
    assert sum(f0) == 200 * 2 + 255  # nothing else lit (no background glow)
    assert p.render_fallback(look, 6000) == f0  # period wraps
    assert p.render_fallback(None, 1234) == bytes(512)


def test_hue_wheel_is_continuous():
    prev = p.hue_rgb(0)
    for h in range(1, p.HUE_STEPS + 1):
        cur = p.hue_rgb(h)
        assert max(abs(a - b) for a, b in zip(cur, prev)) <= 1
        prev = cur
