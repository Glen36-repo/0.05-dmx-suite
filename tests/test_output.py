import threading
import time

import pytest

from dmx_suite.output import LogDriver, NodeSerialDriver, make_driver
from dmx_suite.output.enttec import EnttecOpenDriver, EnttecProDriver, pro_packet


class FakeSerial:
    def __init__(self, *args):
        self.args = args
        self.writes: list[bytes] = []
        self.breaks: list[bool] = []
        self.wrote = threading.Event()
        self.closed = False

    @property
    def break_condition(self):
        return self.breaks[-1] if self.breaks else False

    @break_condition.setter
    def break_condition(self, v):
        self.breaks.append(v)

    def write(self, data):
        self.writes.append(bytes(data))
        self.wrote.set()

    def flush(self):
        pass

    def close(self):
        self.closed = True


def test_pro_packet_format():
    pkt = pro_packet(bytes(range(256)) * 2)
    assert pkt[:4] == bytes([0x7E, 6, 0x01, 0x02])  # label 6, length 513
    assert pkt[4] == 0  # start code
    assert pkt[5:517] == bytes(range(256)) * 2
    assert pkt[-1] == 0xE7
    assert len(pkt) == 518


def test_enttec_pro_sends_each_frame():
    ser = FakeSerial()
    d = EnttecProDriver("COM9", serial_factory=lambda *a: ser)
    d.send(0, bytes(512))
    d.send(1, bytes(512))  # other universe: ignored
    assert len(ser.writes) == 1 and d.packets == 1
    d.close()
    assert ser.closed


def test_enttec_open_streams_with_break_and_wakes_on_new_frame():
    ser = FakeSerial()
    d = EnttecOpenDriver("COM9", serial_factory=lambda *a: ser)
    try:
        assert ser.wrote.wait(1)
        assert ser.breaks[:2] == [True, False]  # break then mark-after-break
        assert ser.writes[0] == bytes(513)  # start code + 512
        time.sleep(0.03)  # let it settle into waiting for the refresh tick
        frame = bytes([255]) + bytes(511)
        t0 = time.perf_counter()
        d.send(0, frame)
        while ser.writes[-1] != b"\x00" + frame:
            assert time.perf_counter() - t0 < 0.02, "new frame not sent promptly"
            time.sleep(0.0005)
    finally:
        d.close()


def test_enttec_open_refreshes_continuously():
    ser = FakeSerial()
    d = EnttecOpenDriver("COM9", serial_factory=lambda *a: ser)
    time.sleep(0.2)
    d.close()
    assert 5 <= len(ser.writes) <= 12  # ~40 Hz


def test_node_driver_against_sim():
    d = NodeSerialDriver("sim")
    frame = bytes([1, 2, 3]) + bytes(509)
    d.send(0, frame)
    node = d.link.t.node
    assert bytes(node.output) == frame
    assert node.mode.name == "LIVE"
    d.close()


def test_make_driver():
    assert isinstance(make_driver({"driver": "log"}), LogDriver)
    with pytest.raises(ValueError, match="later"):
        make_driver({"driver": "artnet"})
    with pytest.raises(ValueError, match="unknown"):
        make_driver({"driver": "nope"})


def test_engine_survives_driver_error(rig, look, clock):
    from dmx_suite.engine import Engine

    class Broken(LogDriver):
        def send(self, u, f):
            raise OSError("unplugged")

    ok = LogDriver()
    e = Engine(rig, [Broken(), ok], look, clock=clock)
    e.tick()
    assert e.driver_errors == 1 and ok.frames == 1
