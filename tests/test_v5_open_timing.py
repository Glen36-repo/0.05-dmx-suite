"""v5 item 1: Open DMX break methods (serial_break, baud_drop, d2xx), configurable timings, measured
timing with warnings, `channels: patched`, and the rig `outputs:` keys."""

import time

import pytest

from dmx_suite.output import d2xx, make_driver
from dmx_suite.output.enttec import DMX_BAUD, EnttecOpenDriver, check_timing
from dmx_suite.rig import ConfigError, parse_outputs
from tests.test_open_dmx import RecordingSerial, wait_frames


class BaudSerial(RecordingSerial):
    """Also logs baud changes (baud_drop)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._baud = DMX_BAUD

    @property
    def baudrate(self):
        return self._baud

    @baudrate.setter
    def baudrate(self, v):
        self._baud = v
        self._rec("baud", v)


def make(ser, **kw):
    kw.setdefault("d2xx_available", lambda: False)
    return EnttecOpenDriver("COM9", serial_factory=lambda *a: ser, **kw)


# ---------------------------------------------------------------- settings


def test_defaults_and_ranges():
    assert check_timing() == {"break_method": "auto", "break_us": 176, "mab_us": 12, "fps": 40, "channels": 512}
    assert check_timing("baud_drop", 500, 50, 30, "patched")["channels"] == "patched"
    for bad in ({"break_method": "magic"}, {"break_us": 87}, {"break_us": 1001}, {"mab_us": 7}, {"mab_us": 101},
                {"fps": 0}, {"fps": 45}, {"channels": 23}, {"channels": 513}, {"channels": True}):
        with pytest.raises(ValueError):
            check_timing(**bad)


def test_rig_outputs_take_the_new_keys():
    outs, warn = parse_outputs([{"driver": "usb_dmx_open", "port": "COM3", "universe": 0, "break_method": "baud_drop",
                                 "break_us": 300, "mab_us": 20, "fps": 30, "channels": "patched"}])
    assert outs[0]["break_method"] == "baud_drop" and not warn
    outs, warn = parse_outputs([{"driver": "enttec_open", "port": "COM3", "universe": 0}])  # missing: defaults, no warning
    assert not warn
    with pytest.raises(ConfigError, match="break_us"):
        parse_outputs([{"driver": "usb_dmx_open", "port": "COM3", "universe": 0, "break_us": 50}])
    with pytest.raises(ConfigError, match="only apply to usb_dmx_open"):
        parse_outputs([{"driver": "usb_dmx_pro", "port": "COM3", "universe": 0, "fps": 30}])


def test_make_driver_passes_timing_and_serial_number():
    d = make_driver({"driver": "usb_dmx_open", "port": "COM_NONE", "universe": 0, "device": "usb:0403:6001:A1B2C3",
                     "break_method": "serial_break", "break_us": 250})
    try:
        assert d.serial_number == "A1B2C3" and d.settings["break_us"] == 250 and d.method == "serial_break"
    finally:
        d.close()


# ---------------------------------------------------------------- serial_break timing


def test_serial_break_honours_break_and_mab():
    ser = RecordingSerial()
    d = make(ser, break_method="serial_break", break_us=600, mab_us=80)
    try:
        wait_frames(ser, 5)
    finally:
        d.close()
    frames = ser.frames()
    assert min(off - on for on, off, _, _ in frames) >= 600e-6 * 0.95
    assert min(w - off for _, off, w, _ in frames) >= 80e-6 * 0.95
    t = d.timing()
    assert t["method"] == "serial_break" and t["measured"]["break_us"] >= 570 and t["measured"]["basis"] == "measured"


def test_fps_target():
    ser = RecordingSerial()
    d = make(ser, break_method="serial_break", fps=20)
    try:
        wait_frames(ser, 2)
        n0 = len(ser.frames())
        time.sleep(0.5)
        n = len(ser.frames()) - n0
        t = d.timing()
    finally:
        d.close()
    assert 8 <= n <= 11, n
    assert 16 <= t["measured"]["fps"] <= 21 and not t["warnings"]


def test_new_frame_still_goes_straight_away_at_low_fps():
    """Hard rule 2: a drum hit goes now, not on the next refresh."""
    ser = RecordingSerial()
    d = make(ser, break_method="serial_break", fps=5)
    try:
        wait_frames(ser, 1)
        time.sleep(0.05)  # past the first frame's wire time
        t0 = time.perf_counter()
        d.send(0, bytes([255]) * 512)
        end = time.monotonic() + 1
        while not any(v[1] == 255 for _, v in ser.events("write")):
            assert time.monotonic() < end
            time.sleep(0.001)
        at = next(t for t, v in ser.events("write") if v[1] == 255)
    finally:
        d.close()
    assert at - t0 < 0.03


# ---------------------------------------------------------------- baud_drop


def test_baud_drop_sequence():
    ser = BaudSerial()
    d = make(ser, break_method="baud_drop", break_us=176)
    try:
        wait_frames_bd(ser, 3)
        t = d.timing()
    finally:
        d.close()
    log = [(e, v) for _, e, v in ser.log if e in ("baud", "write", "break")]
    assert not any(e == "break" for e, _ in log)  # no break requests at all
    low = round(9 / 176e-6)
    i = log.index(("baud", low))
    assert log[i + 1] == ("write", b"\x00") and log[i + 2] == ("baud", DMX_BAUD)
    assert log[i + 3][0] == "write" and len(log[i + 3][1]) == 513 and log[i + 3][1][0] == 0
    assert t["measured"]["basis"] == "computed" and 170 <= t["measured"]["break_us"] <= 182


def wait_frames_bd(ser, n, timeout=2.0):
    end = time.monotonic() + timeout
    while sum(1 for _, v in ser.events("write") if len(v) > 1) < n:
        assert time.monotonic() < end
        time.sleep(0.005)


# ---------------------------------------------------------------- d2xx / auto


def test_auto_picks_d2xx_when_installed_and_serial_known():
    opened = []
    port = RecordingSerial()

    def d2xx_factory(sn):
        opened.append(sn)
        return port

    d = EnttecOpenDriver("COM9", serial_factory=lambda *a: pytest.fail("COM port used"), serial_number="SN1",
                         d2xx_factory=d2xx_factory, d2xx_available=lambda: True)
    try:
        wait_frames(port, 2)
        assert d.method == "d2xx" and opened == ["SN1"] and d.timing()["backend"] == "d2xx"
    finally:
        d.close()


def test_auto_falls_back_to_serial_break():
    ser = RecordingSerial()
    d = make(ser, serial_number="SN1")  # D2XX not installed
    try:
        wait_frames(ser, 1)
        assert d.method == "serial_break" and not d.timing()["d2xx_available"]
    finally:
        d.close()


def test_configure_live_switches_backend():
    ser, port = RecordingSerial(), RecordingSerial()
    d = EnttecOpenDriver("COM9", serial_factory=lambda *a: ser, serial_number="SN1", break_method="serial_break",
                         d2xx_factory=lambda sn: port, d2xx_available=lambda: True)
    try:
        wait_frames(ser, 1)
        d.configure(break_method="d2xx", break_us=500)
        wait_frames(port, 2)
        assert ser.closed and d.method == "d2xx" and d.settings["break_us"] == 500
        with pytest.raises(ValueError):
            d.configure(break_us=5)
        assert d.settings["break_us"] == 500  # a bad change leaves it as it was
    finally:
        d.close()


# ---------------------------------------------------------------- channels


def test_channels_patched_and_fixed():
    ser = RecordingSerial()
    d = make(ser, break_method="serial_break", channels="patched")
    d.patched_slots = {0: 40}
    try:
        wait_frames(ser, 2)
        assert len(ser.events("write")[-1][1]) == 41
        d.configure(channels=100)
        end = time.monotonic() + 1
        while len(ser.events("write")[-1][1]) != 101:
            assert time.monotonic() < end
            time.sleep(0.005)
    finally:
        d.close()


def test_patched_never_under_24_slots():
    d = make(RecordingSerial(), channels="patched")
    d.patched_slots = {0: 3}
    try:
        assert d.slots() == 24
    finally:
        d.close()


def test_engine_tells_drivers_the_last_patched_channel(engine):
    d = make(RecordingSerial(), channels="patched")
    try:
        engine.drivers = [d]
        engine.hint_drivers()
        last = max(f.address + f.type.footprint - 1 for f in engine.rig.fixtures if f.universe == 0)
        assert d.patched_slots[0] == last
    finally:
        d.close()


# ---------------------------------------------------------------- warnings


def test_timing_warnings_and_state():
    ser = RecordingSerial()
    d = make(ser, break_method="serial_break")
    try:
        wait_frames(ser, 1)
        now = time.perf_counter()
        d._stop.set()  # freeze measurement
        d._thread.join(1)
        d._meas.clear()
        for i in range(10):  # 10 fps against 40, break 60 us, MAB 5 us
            d._meas.append((now - 1 + i * 0.1, 60e-6, 5e-6, 0.001))
        t = d.timing()
        assert len(t["warnings"]) == 3 and "under 88" in t["warnings"][0]
        d._p.wrote()
        assert d.state()["state"] == "warn" and "under 88" in d.state()["detail"]
        assert "best effort" in t["note"]
    finally:
        d.close()


# ---------------------------------------------------------------- D2XX wrapper


class FakeD2xx:
    def __init__(self):
        self.calls = []
        self.tx = 0

    def __getattr__(self, name):
        def fn(*args):
            self.calls.append(name)
            if name == "FT_Write":
                args[3]._obj.value = args[2]
            if name == "FT_GetLatencyTimer":
                args[1]._obj.value = 16
            if name == "FT_GetComPortNumber":
                args[1]._obj.value = 3
            if name == "FT_OpenEx":
                args[2]._obj.value = 1234
            return 0
        return fn


def test_d2xx_port_setup_and_io():
    lib = FakeD2xx()
    p = d2xx.D2xxPort("SN1", lib=lib)
    assert lib.calls[:4] == ["FT_OpenEx", "FT_SetBaudRate", "FT_SetDataCharacteristics", "FT_SetFlowControl"]
    p.break_condition = True
    p.break_condition = False
    assert p.write(b"\x00" * 513) == 513
    p.flush()
    assert p.latency_timer == 16 and p.com_port() == "COM3"
    p.close()
    assert lib.calls[4:7] == ["FT_SetBreakOn", "FT_SetBreakOff", "FT_Write"] and lib.calls[-1] == "FT_Close"


def test_d2xx_errors_name_the_cause():
    class Busy(FakeD2xx):
        def __getattr__(self, name):
            return (lambda *a: 3) if name == "FT_OpenEx" else super().__getattr__(name)

    with pytest.raises(OSError, match="in use by another program"):
        d2xx.D2xxPort("SN1", lib=Busy())


def test_d2xx_not_installed_here():
    d2xx.load(False)
    try:
        assert not d2xx.available() and d2xx.devices() == []
        with pytest.raises(OSError, match="isn't installed"):
            d2xx.D2xxPort("SN1")
    finally:
        d2xx._tried = False


# ---------------------------------------------------------------- set_output / list_outputs / node_health (MCP)


def test_tools_set_and_report_timing(tmp_path):
    import shutil
    from pathlib import Path

    import yaml
    from test_web import CLAUDE, TOKEN

    from dmx_suite.app import App
    from dmx_suite.claude_tools import DmxTools
    from dmx_suite.showfiles import load_show
    from dmx_suite.store import StoreError
    from dmx_suite.web.server import WebServer

    shows = Path(__file__).resolve().parents[1] / "shows"
    root = tmp_path / "shows"
    shutil.copytree(shows, root, ignore=shutil.ignore_patterns(".backups", ".state.json"))
    p = root / "rigs" / "full.yaml"
    rig = yaml.safe_load(p.read_text())
    rig["outputs"] = [{"driver": "usb_dmx_open", "port": "COM_NONE", "universe": 0}]
    p.write_text(yaml.safe_dump(rig))
    files = load_show(root)
    app = App(files, [make_driver(o) for o in files.rig.outputs], state_path=root / ".state.json")
    web = WebServer(app, "127.0.0.1", 0, token=TOKEN, claude_token=CLAUDE)
    web.start()
    try:
        t = DmxTools(shows=root, url=f"http://127.0.0.1:{web.port}", token=CLAUDE)
        assert t.set_output(0, break_method="baud_drop", break_us=300, channels="patched").startswith("saved")
        saved = yaml.safe_load(p.read_text())["outputs"][0]
        assert saved["break_method"] == "baud_drop" and saved["break_us"] == 300 and saved["channels"] == "patched"
        row = yaml.safe_load(t.list_outputs())["rows"][0]
        assert row["timing"]["method"] == "baud_drop" and row["timing"]["target"]["break_us"] == 300
        assert yaml.safe_load(t.node_health())["usb_dmx"][0]["timing"]["target"]["channels"] == "patched"
        with pytest.raises(StoreError, match="break_us"):
            t.set_output(0, break_us=20)
    finally:
        web.stop()
        app.engine.stop()
