"""v4 item 18: devices by what they report, kept by USB identity; nothing hard-coded to a model."""

import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from dmx_suite.app import App, device_label
from dmx_suite.cli import resolve_output
from dmx_suite.devices import DeviceRegistry, describe_serial, midi_base
from dmx_suite.output import LogDriver, make_driver
from dmx_suite.rig import parse_midi_inputs
from dmx_suite.showfiles import load_show

SHOWS = Path(__file__).resolve().parents[1] / "shows"


def port(device, **kw):
    base = {"description": "", "manufacturer": "", "product": "", "serial_number": "", "vid": None, "pid": None}
    return SimpleNamespace(device=device, **{**base, **kw})


GENUINE = port("COM3", description="DMX USB PRO", manufacturer="ENTTEC", product="DMX USB PRO", serial_number="EN123456",
               vid=0x0403, pid=0x6001)
CLONE = port("COM4", description="FT232R USB UART", manufacturer="FTDI", product="FT232R USB UART", serial_number="A1B2C3",
             vid=0x0403, pid=0x6001)
NO_SERIAL = port("COM7", description="USB Serial Port", vid=0x1A86, pid=0x7523)


def test_names_come_from_the_device():
    g, c, n = describe_serial(GENUINE), describe_serial(CLONE), describe_serial(NO_SERIAL)
    assert g["name"] == "DMX USB PRO" and g["driver"] == "usb_dmx_pro" and g["id"] == "usb:0403:6001:EN123456"
    assert c["name"] == "USB DMX interface (FTDI, SN A1B2C3)" and c["driver"] == "usb_dmx_open"  # chip default name
    assert c["vid_pid"] == "0403:6001" and c["serial_number"] == "A1B2C3" and c["stable"]
    assert n["id"] == "port:COM7" and not n["stable"]  # no serial number: falls back to the port
    assert midi_base("UM-ONE 2") == "UM-ONE" and midi_base("TD-25") == "TD-25"
    assert device_label("usb:0403:6001:A1B2") == "FTDI SN A1B2"


class Fake:
    def __init__(self):
        self.ports = [GENUINE]
        self.ins = ["UM-ONE 0"]
        self.outs = []

    def serial(self):
        return list(self.ports)

    def midi(self):
        return list(self.ins), list(self.outs)


def test_registry_hot_plug_and_renumbered_port():
    f = Fake()
    reg = DeviceRegistry(f.serial, f.midi)
    events = []
    reg.on_change.append(lambda d, what: events.append((d["id"], what)))
    assert reg.port_for("usb:0403:6001:EN123456") == "COM3"
    assert {d["id"] for d in reg.all()} == {"usb:0403:6001:EN123456", "midi-in:UM-ONE"}
    f.ports = []  # unplugged
    reg.scan()
    assert ("usb:0403:6001:EN123456", "removed") in events and reg.port_for("usb:0403:6001:EN123456") is None
    f.ports = [SimpleNamespace(**{**vars(GENUINE), "device": "COM9"})]  # back on another COM number
    reg.scan()
    assert reg.port_for("usb:0403:6001:EN123456") == "COM9" and ("usb:0403:6001:EN123456", "added") in events
    out = resolve_output({"driver": "usb_dmx_pro", "device": "usb:0403:6001:EN123456", "port": "COM3", "universe": 1}, reg)
    assert out["port"] == "COM9" and out["universe"] == 1  # keeps its universe
    gone = resolve_output({"driver": "usb_dmx_pro", "device": "usb:0403:6001:NOPE", "port": "COM3"}, reg)
    assert gone["port"] == "COM3"  # not found: the rig's port is the fallback
    assert make_driver({"driver": "log", "device": "x", "alias": "y"}).__class__ is LogDriver


def test_midi_inputs_as_devices():
    assert parse_midi_inputs(["UM-ONE"]) == (["UM-ONE"], {})
    got = parse_midi_inputs([{"device": "midi-in:TD-25", "alias": "Drums"}, "H2MIDI"])
    assert got == (["TD-25", "H2MIDI"], {"TD-25": "Drums"})
    assert parse_midi_inputs("all") == ([], {})


@pytest.fixture
def app_with_devices(tmp_path):
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json"))
    p = root / "rigs" / "full.yaml"
    rig = yaml.safe_load(p.read_text())
    rig["outputs"] = [{"driver": "usb_dmx_pro", "device": "usb:0403:6001:EN123456", "port": "COM3", "universe": 0,
                       "alias": "Stage DMX"},
                      {"driver": "usb_dmx_open", "device": "usb:0403:6001:GONE99", "port": "COM5", "universe": 0,
                       "alias": "Spare"}]
    rig["midi_inputs"] = [{"device": "midi-in:UM-ONE", "alias": "Pedalboard"}]
    p.write_text(yaml.safe_dump(rig))
    f = Fake()
    f.ports = [GENUINE, CLONE]
    f.ins = ["UM-ONE 0", "TD-25 1"]
    log = LogDriver()
    log.cfg = {"driver": "usb_dmx_pro", "device": "usb:0403:6001:EN123456", "alias": "Stage DMX", "universe": 0}
    app = App(load_show(root), [log])
    app.registry = DeviceRegistry(f.serial, f.midi)
    return app, root, f


def test_devices_view_missing_new_and_aliases(app_with_devices):
    app, root, f = app_with_devices
    v = app.devices_view()
    by = {d["id"]: d for d in v["devices"]}
    assert by["usb:0403:6001:EN123456"]["use"]["universe"] == 0 and by["usb:0403:6001:EN123456"]["alias"] == "Stage DMX"
    assert by["midi-in:UM-ONE"]["alias"] == "Pedalboard"
    assert [m["alias"] for m in v["missing"]] == ["Spare"] and v["missing"][0]["label"] == "FTDI SN GONE99"
    assert {d["id"] for d in v["new"]} == {"usb:0403:6001:A1B2C3", "midi-in:TD-25"}
    tiles = app.devices()
    assert any(t["kind"] == "output" and t["name"] == "Stage DMX" for t in tiles)  # alias, not a model name
    assert any(t["kind"] == "device" and "missing: Spare (FTDI SN GONE99)" in t["detail"] for t in tiles)
    assert any(t["kind"] == "device_new" and "New MIDI device: TD-25" in t["detail"] for t in tiles)
    assert not any("Enttec" in str(t) for t in tiles)


def test_set_device_writes_by_identity(app_with_devices):
    app, root, f = app_with_devices
    app.set_device("usb:0403:6001:A1B2C3", alias="Side DMX", universe=1)
    outs = yaml.safe_load((root / "rigs" / "full.yaml").read_text())["outputs"]
    side = next(o for o in outs if o.get("device") == "usb:0403:6001:A1B2C3")
    assert side == {"driver": "usb_dmx_open", "universe": 1, "device": "usb:0403:6001:A1B2C3", "port": "COM4",
                    "alias": "Side DMX"}
    app.set_device("midi-in:TD-25", alias="Drums")
    ins = yaml.safe_load((root / "rigs" / "full.yaml").read_text())["midi_inputs"]
    assert {"device": "midi-in:TD-25", "alias": "Drums"} in ins
    app.set_device("usb:0403:6001:A1B2C3", use=False)
    outs = yaml.safe_load((root / "rigs" / "full.yaml").read_text())["outputs"]
    assert not any(o.get("device") == "usb:0403:6001:A1B2C3" for o in outs)
    with pytest.raises(ValueError):
        app.set_device("laser:1")
    app.set_gig_lock(True)
    with pytest.raises(Exception, match="gig lock"):
        app.set_device("midi-in:TD-25", alias="x")


def test_devices_api_and_tools(app_with_devices):
    from test_web import CLAUDE, TOKEN, call

    from dmx_suite.claude_tools import DmxTools
    from dmx_suite.web.server import WebServer

    app, root, f = app_with_devices
    web = WebServer(app, "127.0.0.1", 0, token=TOKEN, claude_token=CLAUDE)
    web.start()
    try:
        url = f"http://127.0.0.1:{web.port}"
        status, v = call(f"{url}/api/devices/list")
        assert status == 200 and v["scanning"]
        t = DmxTools(shows=root, url=url, token=CLAUDE)
        assert "DMX USB PRO" in t.list_devices()
        assert t.set_device("midi-in:TD-25", alias="Drums").startswith("saved")
    finally:
        web.stop()
        app.engine.stop()


def test_simulator_reports_no_scan():
    app = App(load_show(SHOWS), [LogDriver()])
    assert app.devices_view() == {"devices": [], "missing": [], "new": [], "scanning": False}
