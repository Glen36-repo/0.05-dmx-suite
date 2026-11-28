import threading
import time

import pytest

from dmx_suite.output import LogDriver, NodeSerialDriver, make_driver
from dmx_suite.output.enttec import WIRE_MARGIN_S, WIRE_S, EnttecOpenDriver, EnttecProDriver, pro_packet


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

    rts = dtr = True  # what pyserial does on open

    def reset_input_buffer(self):
        pass

    def reset_output_buffer(self):
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
    assert d.flush()  # written by its own thread, not the caller's
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
            # as soon as the line is free: at most the last frame's wire time, plus slack for the runner
            assert time.perf_counter() - t0 < WIRE_S + WIRE_MARGIN_S + 0.012, "new frame not sent promptly"
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
    art = make_driver({"driver": "artnet"})  # built since v2 R4
    assert art.name == "artnet"
    art.close()
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


# ------------------------------------------------------------------ outputs never hold up the engine (v2 R4)


def test_slow_device_never_blocks_the_engine():
    import threading
    import time

    from dmx_suite.output.base import SenderThread

    release = threading.Event()
    written = []

    def slow_write(u, f):
        release.wait(2)  # a USB write stuck for a while
        written.append((u, f))

    s = SenderThread(slow_write, "slow")
    t0 = time.perf_counter()
    for i in range(50):
        s.put(0, bytes([i]) * 512)
    assert time.perf_counter() - t0 < 0.05  # the caller (the engine) never waited
    release.set()
    assert s.flush()
    assert written[-1][1][0] == 49  # the newest frame always gets out
    assert len(written) <= 3 and s.dropped >= 47  # stale frames skipped, not queued up
    s.close()


def test_sender_survives_write_errors():
    from dmx_suite.output.base import SenderThread

    calls = []

    def flaky(u, f):
        calls.append(u)
        if len(calls) == 1:
            raise OSError("USB hiccup")

    s = SenderThread(flaky, "flaky")
    s.put(0, bytes(512))
    s.flush()
    s.put(0, bytes(512))
    assert s.flush() and s.errors == 1 and len(calls) == 2
    s.close()


def test_engine_tick_doesnt_wait_for_a_stuck_enttec():
    import threading
    import time

    gate = threading.Event()

    class Stuck(FakeSerial):
        def write(self, data):
            gate.wait(2)
            return super().write(data)

    ser = Stuck()
    d = EnttecProDriver("COM9", serial_factory=lambda *a: ser)
    from dmx_suite.engine import Engine
    from dmx_suite.fixtures import parse_patch
    from dmx_suite.look import parse_look
    from dmx_suite.rig import parse_rig

    from conftest import LOOK, PATCH, RIG

    patch = parse_patch(PATCH)
    e = Engine(parse_rig(RIG, patch), [d], parse_look(LOOK, patch))
    t0 = time.perf_counter()
    for _ in range(20):
        e.tick()
    assert time.perf_counter() - t0 < 0.5  # 20 frames rendered while the device was stuck
    gate.set()
    assert d.flush() and ser.writes
    d.close()
