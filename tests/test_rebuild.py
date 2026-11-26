"""v4: outputs are rebuilt live; swapping a missing interface for a plugged-in one works under gig lock
(mid-gig recovery) while every other output / device change stays locked."""

import shutil
from pathlib import Path

import pytest
import yaml
from test_devices import CLONE, GENUINE, Fake

from dmx_suite import output
from dmx_suite.app import App
from dmx_suite.devices import DeviceRegistry
from dmx_suite.output import make_driver
from dmx_suite.output.base import OutputDriver
from dmx_suite.showfiles import load_show
from dmx_suite.store import LockedError

SHOWS = Path(__file__).resolve().parents[1] / "shows"


class FakeUsb(OutputDriver):
    """Stands in for a USB DMX interface: records frames, opens nothing."""

    name = "fake_usb"
    opened: list[str] = []

    def __init__(self, port: str, universe: int = 0) -> None:
        self.port, self.universe, self.closed = port, universe, False
        FakeUsb.opened.append(port)

    def send(self, universe: int, frame: bytes) -> None:
        if universe == self.universe:
            self.wire.record(universe, frame)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def rig_app(tmp_path, monkeypatch):
    monkeypatch.setitem(output.DRIVERS, "usb_dmx_pro", FakeUsb)
    monkeypatch.setitem(output.DRIVERS, "usb_dmx_open", FakeUsb)
    FakeUsb.opened = []
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json"))
    p = root / "rigs" / "full.yaml"
    rig = yaml.safe_load(p.read_text())
    rig["outputs"] = [{"driver": "usb_dmx_pro", "device": "usb:0403:6001:EN123456", "port": "COM3", "universe": 0,
                       "alias": "Stage DMX"}]
    p.write_text(yaml.safe_dump(rig))
    files = load_show(root)
    f = Fake()
    f.ports = [GENUINE, CLONE]
    reg = DeviceRegistry(f.serial, f.midi)
    drivers = [make_driver(o) for o in files.rig.outputs]
    app = App(files, drivers)
    app.registry = reg
    yield app, root, f
    app.engine.stop()


def test_set_output_rebuilds_live(rig_app):
    app, root, f = rig_app
    first = app.engine.drivers[0]
    r = app.set_output(0, {"universe": 0, "port": "COM3", "alias": "Front"})
    assert any("rebuilt" in n for n in r["notes"])
    assert app.engine.drivers[0] is not first and first.closed  # new one in, old one closed
    assert app.engine.drivers[0].wire.frame(0) is not None  # got a frame straight away
    assert app.engine.drivers[0].cfg["alias"] == "Front"


def test_use_this_instead_under_gig_lock(rig_app):
    app, root, f = rig_app
    f.ports = [CLONE]  # the Pro has gone; a clone is plugged in
    app.registry.scan()
    assert [m["device"] for m in app.devices_view()["missing"]] == ["usb:0403:6001:EN123456"]
    app.set_gig_lock(True)
    with pytest.raises(LockedError):
        app.set_output(0, {"universe": 1})
    with pytest.raises(LockedError):
        app.set_device("usb:0403:6001:A1B2C3", alias="x")
    r = app.replace_device("usb:0403:6001:EN123456", "usb:0403:6001:A1B2C3")
    out = yaml.safe_load((root / "rigs" / "full.yaml").read_text())["outputs"][0]
    assert out == {"driver": "usb_dmx_open", "device": "usb:0403:6001:A1B2C3", "port": "COM4", "universe": 0,
                   "alias": "Stage DMX"}
    assert app.engine.drivers[0].port == "COM4" and app.engine.drivers[0].universe == 0
    assert r["backup"] and app.devices_view()["missing"] == []
    with pytest.raises(LockedError):  # the lock is back for everything else
        app.set_output(0, {"universe": 1})
    with pytest.raises(ValueError, match="isn't plugged in"):
        app.replace_device("usb:0403:6001:A1B2C3", "usb:0403:6001:NOPE")


def test_replace_over_the_api_under_gig_lock(rig_app):
    from test_web import CLAUDE, TOKEN, call

    from dmx_suite.web.server import WebServer

    app, root, f = rig_app
    f.ports = [CLONE]
    app.registry.scan()
    app.set_gig_lock(True)
    web = WebServer(app, "127.0.0.1", 0, token=TOKEN, claude_token=CLAUDE)
    web.start()
    try:
        url = f"http://127.0.0.1:{web.port}"
        assert call(f"{url}/api/routing/output", "POST", {"index": 0, "set": {"universe": 1}})[0] == 423
        assert call(f"{url}/api/devices/set", "POST", {"id": "usb:0403:6001:A1B2C3", "alias": "x"})[0] == 423
        swap = {"missing": "usb:0403:6001:EN123456", "use": "usb:0403:6001:A1B2C3"}
        status, r = call(f"{url}/api/devices/replace", "POST", swap)
        assert status == 200 and r["ok"]
        # Claude can't do the recovery swap (it's the people at the laptop's call)
        assert call(f"{url}/api/devices/replace", "POST", {"missing": "x", "use": "y"}, token=CLAUDE)[0] == 403
    finally:
        web.stop()


def test_simulator_outputs_are_left_alone():
    from dmx_suite.output import LogDriver

    app = App(load_show(SHOWS), [LogDriver()])
    assert app.rebuild_outputs([{"driver": "null"}]) == ["simulator: outputs aren't rebuilt (no hardware)"]
    assert isinstance(app.engine.drivers[0], LogDriver)
