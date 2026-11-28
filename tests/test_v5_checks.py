"""v5 item 2: USB DMX (Open) health checks against a fake OS probe: driver type, latency timer, port held
by another program, 250k 8N2, USB selective suspend, timing; status bar / alerts, routing table, API, MCP."""

import shutil
import time
from pathlib import Path

import pytest
import yaml

from dmx_suite.output import make_driver
from dmx_suite.output.enttec import EnttecOpenDriver
from dmx_suite.output.ftdi import FTDIBUS, USB, Probe, check_interface
from tests.test_open_dmx import RecordingSerial, wait_frames

SHOWS = Path(__file__).resolve().parents[1] / "shows"
INFO = {"vid_pid": "0403:6001", "serial_number": "EN123456"}


class FakeProbe(Probe):
    def __init__(self, platform="win32", latency=16, suspend_plan=True, dev_suspend=None, procs=(), files=None):
        self.platform = platform
        self.latency, self.plan, self.dev_suspend, self.procs = latency, suspend_plan, dev_suspend, list(procs)
        self.files = files or {}

    def reg_subkeys(self, path):
        return ["VID_0403+PID_6001+EN123456A"] if path == FTDIBUS else None

    def reg_values(self, path):
        if path == rf"{FTDIBUS}\VID_0403+PID_6001+EN123456A\0000\Device Parameters":
            return {"PortName": "COM3", "LatencyTimer": self.latency} if self.latency is not None else {"PortName": "COM3"}
        if path == rf"{USB}\VID_0403&PID_6001\EN123456\Device Parameters" and self.dev_suspend is not None:
            return {"SelectiveSuspendEnabled": int(self.dev_suspend)}
        return None

    def read(self, path):
        return self.files.get(path)

    def processes(self):
        return self.procs

    def usb_suspend_plan(self):
        return self.plan


class FakeRegistry:
    """The device registry with one FTDI interface on `port`."""

    def __init__(self, port):
        self.port, self.on_change = port, []

    def get(self, dev):
        return None

    def all(self):
        return [{**INFO, "port": self.port, "name": "DMX USB", "kind": "serial", "id": "usb:0403:6001:EN123456"}]

    def port_for(self, dev):
        return None


class SerialAttrs(RecordingSerial):
    baudrate, bytesize, parity, stopbits = 250000, 8, "N", 2


def by_key(r):
    return {c["key"]: c for c in r["checks"]}


@pytest.fixture
def running_drv():
    ser = SerialAttrs()
    d = EnttecOpenDriver("COM3", serial_factory=lambda *a: ser, d2xx_available=lambda: False)
    wait_frames(ser, 4)
    yield d, ser
    d.close()


def test_latency_over_1ms_is_amber_with_the_fix(running_drv):
    d, _ = running_drv
    r = check_interface("COM3", INFO, d, FakeProbe(latency=16, suspend_plan=False))
    c = by_key(r)
    assert c["latency"]["result"] == "warn" and c["latency"]["detail"] == "16 ms"
    assert "Latency Timer = 1" in c["latency"]["fix"] and "COM3" in c["latency"]["fix"]
    assert r["result"] == "warn" and r["latency_ms"] == 16
    r = check_interface("COM3", INFO, d, FakeProbe(latency=1, suspend_plan=False))
    assert by_key(r)["latency"]["result"] == "pass"


def test_all_pass(running_drv):
    d, _ = running_drv
    r = check_interface("COM3", INFO, d, FakeProbe(latency=1, suspend_plan=False, dev_suspend=False))
    assert r["result"] == "pass", r
    c = by_key(r)
    assert r["driver_type"] == "vcp" and "VCP (COM port COM3)" in c["driver"]["detail"]
    assert "D2XX not installed" in c["driver"]["detail"]
    assert c["serial"]["result"] == "pass" and c["exclusive"]["result"] == "pass"
    assert c["timing"]["result"] == "pass" and "break" in c["timing"]["detail"]


def test_port_held_by_another_program_names_it():
    def busy(*a):
        raise PermissionError(13, "Access is denied.")

    d = EnttecOpenDriver("COM3", serial_factory=busy, d2xx_available=lambda: False)
    try:
        end = time.monotonic() + 2
        while not d._p.last_error:
            assert time.monotonic() < end
            time.sleep(0.01)
        r = check_interface("COM3", INFO, d, FakeProbe(procs=["explorer.exe", "Daslight5.exe", "qlcplus.exe"]))
    finally:
        d.close()
    c = by_key(r)["exclusive"]
    assert c["result"] == "fail" and "Daslight" in c["detail"] and "QLC+" in c["detail"]
    assert r["result"] == "fail" and "Close Daslight / QLC+" in c["fix"]


def test_missing_port_is_not_an_exclusivity_fail():
    d = EnttecOpenDriver("COM_NONE", d2xx_available=lambda: False)
    try:
        time.sleep(0.2)
        assert by_key(check_interface("COM_NONE", None, d, FakeProbe()))["exclusive"]["result"] == "unknown"
    finally:
        d.close()


def test_wrong_serial_settings_fail(running_drv):
    d, ser = running_drv
    ser.stopbits = 1
    c = by_key(check_interface("COM3", INFO, d, FakeProbe(latency=1, suspend_plan=False)))["serial"]
    assert c["result"] == "fail" and "1 stop bits" in c["detail"]


def test_selective_suspend_warns(running_drv):
    d, _ = running_drv
    c = by_key(check_interface("COM3", INFO, d, FakeProbe(latency=1, suspend_plan=False, dev_suspend=True)))["power"]
    assert c["result"] == "warn" and "this interface" in c["detail"] and "Disabled" in c["fix"]
    c = by_key(check_interface("COM3", INFO, d, FakeProbe(latency=1, suspend_plan=True)))["power"]
    assert c["result"] == "warn" and "power plan" in c["detail"]
    c = by_key(check_interface("COM3", INFO, d, FakeProbe(latency=1, suspend_plan=None)))["power"]
    assert c["result"] == "unknown"


def test_linux_latency_from_sysfs(running_drv):
    d, _ = running_drv
    p = FakeProbe(platform="linux", files={"/sys/bus/usb-serial/devices/ttyUSB0/latency_timer": "16"}, suspend_plan=None)
    assert by_key(check_interface("/dev/ttyUSB0", INFO, d, p))["latency"]["detail"] == "16 ms"


def test_d2xx_latency_read_and_set():
    class D2(SerialAttrs):
        latency_timer = 16

    port = D2()
    d = EnttecOpenDriver("COM3", serial_factory=lambda *a: pytest.fail("COM used"), serial_number="SN",
                         d2xx_factory=lambda sn: port, d2xx_available=lambda: True)
    try:
        wait_frames(port, 2)
        r = check_interface("COM3", INFO, d, FakeProbe(latency=None, suspend_plan=False))
        assert r["driver_type"] == "d2xx" and r["latency_ms"] == 16 and "Set latency" in by_key(r)["latency"]["fix"]
        assert d.set_latency(1) == 1 and port.latency_timer == 1
    finally:
        d.close()


def test_set_latency_refused_without_d2xx(running_drv):
    d, _ = running_drv
    with pytest.raises(ValueError, match="Device Manager"):
        d.set_latency(1)


# ---------------------------------------------------------------- app: status bar, alerts, routing, API, MCP


@pytest.fixture
def open_app(tmp_path):
    from dmx_suite.app import App
    from dmx_suite.showfiles import load_show

    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json"))
    p = root / "rigs" / "full.yaml"
    rig = yaml.safe_load(p.read_text())
    rig["outputs"] = [{"driver": "usb_dmx_open", "port": "COM3", "universe": 0, "alias": "Stage DMX"}]
    p.write_text(yaml.safe_dump(rig))
    files = load_show(root)
    ser = SerialAttrs()
    drv = make_driver(files.rig.outputs[0])
    drv.close()
    drv = EnttecOpenDriver("COM3", serial_factory=lambda *a: ser, d2xx_available=lambda: False)
    drv.cfg = {**files.rig.outputs[0], "driver": "usb_dmx_open"}
    app = App(files, [drv], state_path=root / ".state.json")
    app.health_probe = FakeProbe(latency=16, suspend_plan=False)
    app.registry = FakeRegistry("COM3")
    wait_frames(ser, 3)
    yield app, root
    app.engine.stop()
    drv.close()


def test_status_bar_alerts_and_routing(open_app):
    app, _ = open_app
    r = app.check_outputs()
    assert r[0]["interface"] == "Stage DMX" and r[0]["result"] == "warn"
    tile = next(d for d in app.devices() if d["kind"] == "dmx_check")
    assert tile["state"] == "warn" and tile["detail"].startswith("Latency timer: 16 ms") and "Fix:" in tile["detail"]
    assert any(a["kind"] == "dmx_check" and a["severity"] == "warning" for a in app.alerts_view()["list"])
    row = app.routing()["rows"][0]
    assert row["checks"]["driver_type"] == "vcp" and row["checks"]["latency_ms"] == 16
    assert app.frame_view(0)["checks"]["latency_ms"] == 16
    app.health_probe = FakeProbe(latency=1, suspend_plan=False)
    app.check_outputs()
    assert not any(d["kind"] == "dmx_check" for d in app.devices())


def test_background_checks_run_and_rerun(open_app):
    app, _ = open_app
    app.start_health_checks(every_s=0.1)
    end = time.monotonic() + 3
    while not app.output_health:
        assert time.monotonic() < end
        time.sleep(0.02)
    first = app.output_health[0]["checked"]
    while app.output_health.get(0, {}).get("checked", first) == first:
        assert time.monotonic() < end + 3
        time.sleep(0.05)


def test_api_and_mcp(open_app):
    from test_web import CLAUDE, TOKEN, call

    from dmx_suite.claude_tools import DmxTools
    from dmx_suite.store import StoreError
    from dmx_suite.web.server import WebServer

    app, root = open_app
    web = WebServer(app, "127.0.0.1", 0, token=TOKEN, claude_token=CLAUDE)
    web.start()
    try:
        url = f"http://127.0.0.1:{web.port}"
        assert call(f"{url}/api/outputs/check")[1]["outputs"][0]["latency_ms"] == 16
        t = DmxTools(shows=root, url=url, token=CLAUDE)
        r = yaml.safe_load(t.check_outputs())
        assert {c["key"] for c in r[0]["checks"]} == {"driver", "latency", "exclusive", "serial", "power", "timing"}
        with pytest.raises(StoreError, match="not available to Claude"):  # a person confirms that one
            t._live("POST", "/api/outputs/latency", {"output": 0, "ms": 1})
        status, body = call(f"{url}/api/outputs/latency", "POST", {"output": 0, "ms": 1})
        assert status == 400 and "Device Manager" in body["error"]
    finally:
        web.stop()
