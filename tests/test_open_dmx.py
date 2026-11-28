"""Open DMX (FTDI) driver against a recording fake port: port settings, break / MAB / data order and
timing, start code and slot order, no DMX USB Pro framing, continuous sending on its own thread,
Enttec's setup (RTS low, purge) and honest error counting."""

import threading
import time

import pytest

from dmx_suite.output import enttec
from dmx_suite.output.enttec import BREAK_S, MAB_S, WIRE_S, EnttecOpenDriver

BREAK_MIN = 88e-6
MAB_MIN = 8e-6
SLACK = 0.9  # timing tolerance for a loaded runner (the spin is a floor, so this is belt and braces)


class RecordingSerial:
    """Logs (perf_counter, event, value) for everything the driver does to the port."""

    def __init__(self, *args, write_s=0.0, short=False, fail=False):
        self.args = args
        self.log: list[tuple[float, str, object]] = []
        self.write_s, self.short, self.fail = write_s, short, fail
        self._rts = self._dtr = True  # pyserial raises both on open
        self.lock = threading.Lock()
        self.closed = False

    def _rec(self, ev, v=None):
        with self.lock:
            self.log.append((time.perf_counter(), ev, v))

    @property
    def break_condition(self):
        return None

    @break_condition.setter
    def break_condition(self, v):
        self._rec("break", bool(v))

    @property
    def rts(self):
        return self._rts

    @rts.setter
    def rts(self, v):
        self._rts = v
        self._rec("rts", v)

    @property
    def dtr(self):
        return self._dtr

    @dtr.setter
    def dtr(self, v):
        self._dtr = v
        self._rec("dtr", v)

    def reset_input_buffer(self):
        self._rec("purge_in")

    def reset_output_buffer(self):
        self._rec("purge_out")

    def write(self, data):
        if self.fail:
            raise OSError("device gone")
        self._rec("write", bytes(data))
        if self.write_s:
            time.sleep(self.write_s)
        return len(data) - 10 if self.short else len(data)

    def flush(self):
        self._rec("flush")

    def close(self):
        self.closed = True

    def events(self, name):
        with self.lock:
            return [(t, v) for t, e, v in self.log if e == name]

    def frames(self):
        """(break on, break off, write time, data) for each complete frame."""
        with self.lock:
            log = list(self.log)
        out, on, off = [], None, None
        for t, e, v in log:
            if e == "break" and v:
                on, off = t, None
            elif e == "break" and not v:
                off = t
            elif e == "write" and on is not None and off is not None:
                out.append((on, off, t, v))
                on = off = None
        return out


def driver(ser, **kw):
    calls = []

    def factory(*args):
        calls.append((threading.current_thread().name, args))
        return ser

    return EnttecOpenDriver("COM9", serial_factory=factory, **kw), calls


def wait_frames(ser, n, timeout=2.0):
    end = time.monotonic() + timeout
    while len(ser.frames()) < n:
        assert time.monotonic() < end, f"only {len(ser.frames())} frames"
        time.sleep(0.005)


# ---------------------------------------------------------------- 1. port settings


def test_port_settings(monkeypatch):
    serial = pytest.importorskip("serial")
    seen = {}

    class Captured:
        def __init__(self):
            self.is_open = False

        def __setattr__(self, k, v):
            if k != "is_open":
                seen.setdefault("order", []).append(k)
            object.__setattr__(self, k, v)

        def open(self):
            seen["at_open"] = dict(self.__dict__)
            self.is_open = True

    monkeypatch.setattr(serial, "Serial", Captured)
    enttec._open_dmx_serial("COM9", enttec.DMX_BAUD, 2)
    s = seen["at_open"]
    assert s["baudrate"] == 250000 and s["bytesize"] == 8 and s["parity"] == "N" and s["stopbits"] == 2
    assert s["rtscts"] is False and s["xonxoff"] is False and s["dsrdtr"] is False  # flow control off
    assert s["rts"] is False and s["dtr"] is False  # set before open, so RTS is never raised
    assert s["port"] == "COM9"


def test_driver_asks_for_250k_8n2():
    ser = RecordingSerial()
    d, calls = driver(ser)
    try:
        wait_frames(ser, 1)
        assert calls[0][1] == ("COM9", 250000, 2)
    finally:
        d.close()


# ---------------------------------------------------------------- 2. break, MAB, data


def test_break_then_mab_then_data_and_wire_time():
    ser = RecordingSerial()
    d, _ = driver(ser)
    try:
        stop = time.monotonic() + 0.4
        while time.monotonic() < stop:  # flood it: drum hits on every engine tick and more
            d.send(0, bytes(512))
            time.sleep(0.001)
        frames = ser.frames()
    finally:
        d.close()
    assert len(frames) >= 8
    # order: break on, break off, write; nothing else in between
    for on, off, w, _ in frames:
        assert on < off < w
    # timing: a little slack for a loaded runner; most frames must be well inside it
    breaks = [off - on for on, off, _, _ in frames]
    mabs = [w - off for _, off, w, _ in frames]
    assert min(breaks) >= BREAK_MIN * SLACK and min(mabs) >= MAB_MIN * SLACK
    assert sorted(breaks)[len(breaks) // 2] >= BREAK_S * SLACK and sorted(mabs)[len(mabs) // 2] >= MAB_S * SLACK
    # hard rule: never break into the previous frame while it's still on the wire
    for (_, _, w_prev, _), (on, _, _, _) in zip(frames, frames[1:]):
        assert on - w_prev >= WIRE_S, f"break {1000 * (on - w_prev):.2f} ms after the last write"


# ---------------------------------------------------------------- 3. start code and slot order


def test_start_code_then_channel_1_at_index_1():
    ser = RecordingSerial()
    d, _ = driver(ser)
    frame = bytes((i % 250) + 1 for i in range(512))  # channel c holds (c - 1) % 250 + 1
    try:
        d.send(0, frame)
        end = time.monotonic() + 1
        while not any(v == b"\x00" + frame for _, v in ser.events("write")):
            assert time.monotonic() < end
            time.sleep(0.005)
    finally:
        d.close()
    data = b"\x00" + frame
    assert len(data) == 513 and data[0] == 0
    assert data[1] == frame[0] == 1  # channel 1
    assert all(data[c] == frame[c - 1] for c in range(1, 513))


@pytest.mark.parametrize("n", [24, 100, 600])
def test_frames_are_always_512_slots(n):
    ser = RecordingSerial()
    d, _ = driver(ser)
    try:
        d.send(0, bytes([7]) * n)
        end = time.monotonic() + 1
        while not any(v[1:2] == b"\x07" for _, v in ser.events("write")):
            assert time.monotonic() < end
            time.sleep(0.005)
        last = [v for _, v in ser.events("write") if v[1:2] == b"\x07"][-1]
    finally:
        d.close()
    assert len(last) == 513
    assert last[1:min(n, 512) + 1] == bytes([7]) * min(n, 512) and last[min(n, 512) + 1:] == bytes(512 - min(n, 512))


# ---------------------------------------------------------------- 4. not the DMX USB Pro protocol


def test_no_pro_framing():
    ser = RecordingSerial()
    d, _ = driver(ser)
    try:
        d.send(0, bytes([0x7E]) + bytes(510) + bytes([0xE7]))
        wait_frames(ser, 4)
    finally:
        d.close()
    for _, v in ser.events("write"):
        assert len(v) == 513 and v[0] == 0x00  # start code, never 0x7E label / length / 0xE7 framing


# ---------------------------------------------------------------- 5. continuous, its own thread, never blocking


def test_sends_continuously_without_changes():
    ser = RecordingSerial()
    d, _ = driver(ser)
    try:
        wait_frames(ser, 1)
        t0 = len(ser.frames())
        time.sleep(0.5)  # no send() at all
        n = len(ser.frames()) - t0
    finally:
        d.close()
    assert 25 * 0.5 <= n <= 44 * 0.5, f"{n / 0.5:.1f} fps"


def test_never_blocks_the_caller():
    ser = RecordingSerial(write_s=0.05)  # a stuck USB write
    d, calls = driver(ser)
    try:
        assert all(name != threading.current_thread().name for name, _ in calls)  # not opened by the caller
        wait_frames(ser, 1)
        t0 = time.perf_counter()
        for _ in range(20):
            d.send(0, bytes(512))
        assert (time.perf_counter() - t0) / 20 < 0.001
    finally:
        d.close()
    assert all(name == "enttec-open" for name, _ in calls)


# ---------------------------------------------------------------- 6-8. setup, errors, counting


def test_enttec_setup_on_open():
    ser = RecordingSerial()
    d, _ = driver(ser)
    try:
        wait_frames(ser, 1)
    finally:
        d.close()
    first_write = ser.events("write")[0][0]
    assert any(v is False for t, v in ser.events("rts") if t < first_write)
    assert ser.events("purge_in") and ser.events("purge_out")
    assert ser.events("purge_out")[0][0] < first_write


@pytest.mark.parametrize("kind", ["fail", "short"])
def test_errors_counted_not_packets(kind):
    ser = RecordingSerial(**{kind: True})

    def factory(*args):  # like a real unplug: once dropped, the port can't be opened again
        if ser.closed:
            raise OSError("could not open port COM9")
        return ser

    d = EnttecOpenDriver("COM9", serial_factory=factory)
    try:
        end = time.monotonic() + 2
        while d.errors == 0:
            assert time.monotonic() < end
            time.sleep(0.005)
        st = d.status()
        assert d.packets == 0 and st["errors"] >= 1 and st["last_error"]
        assert d.state()["state"] == "bad" and st["last_error"] in d.state()["detail"]
        assert ser.closed  # dropped, to be reopened
    finally:
        d.close()


def test_packets_count_good_writes_only():
    ser = RecordingSerial()
    d, _ = driver(ser)
    try:
        wait_frames(ser, 3)
        assert d.state()["state"] == "ok"
    finally:
        d.close()
    assert d.packets == len(ser.events("write")) and d.errors == 0
