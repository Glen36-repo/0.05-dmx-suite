"""v5 item 1: the break-method cycle test — steps, all full on that output, "Lights responded" saves the
step to the rig, no tap puts the output back, gig lock, API and MCP."""

import shutil
import time
from pathlib import Path

import pytest
import yaml

from dmx_suite.dmxcheck import cycle_steps
from dmx_suite.output import make_driver
from dmx_suite.output.enttec import EnttecOpenDriver
from dmx_suite.store import LockedError

SHOWS = Path(__file__).resolve().parents[1] / "shows"


@pytest.fixture
def open_app(tmp_path):
    from dmx_suite.app import App
    from dmx_suite.showfiles import load_show

    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json"))
    p = root / "rigs" / "full.yaml"
    rig = yaml.safe_load(p.read_text())
    rig["outputs"] = [{"driver": "usb_dmx_open", "port": "COM_NONE", "universe": 0, "mab_us": 20}]
    p.write_text(yaml.safe_dump(rig))
    files = load_show(root)
    app = App(files, [make_driver(o) for o in files.rig.outputs], state_path=root / ".state.json")
    yield app, p
    if app.cycle is not None:
        app.cycle.stop()
    app.engine.stop()
    for d in app.engine.drivers:
        d.close()


def wait(cond, s=5.0):
    end = time.monotonic() + s
    while not cond():
        assert time.monotonic() < end
        time.sleep(0.01)


def test_steps_with_and_without_d2xx():
    d = EnttecOpenDriver("COM_NONE", d2xx_available=lambda: False)
    try:
        assert [s["label"] for s in cycle_steps(d)] == ["Serial break, 176 µs", "Baud drop, 176 µs",
                                                        "Serial break, 500 µs (long)"]
        d.serial_number, d._d2xx_available = "SN1", lambda: True
        assert [s["break_method"] for s in cycle_steps(d)] == ["d2xx", "serial_break", "baud_drop", "d2xx"]
    finally:
        d.close()


def test_confirm_saves_the_live_step(open_app):
    app, p = open_app
    app.engine.drivers[0]._d2xx_available = lambda: False
    c = app.start_cycle(0, step_s=0.3)
    assert c["state"] == "running" and app.engine.test.pattern == "all_full" and app.engine.test.output == 0
    wait(lambda: app.cycle.current == 1)  # baud drop
    assert app.engine.drivers[0].method == "baud_drop"
    v = app.cycle_confirm()
    assert v["state"] == "confirmed" and v["result"]["break_method"] == "baud_drop"
    saved = yaml.safe_load(p.read_text())["outputs"][0]
    assert saved["break_method"] == "baud_drop" and saved["break_us"] == 176 and saved["mab_us"] == 20
    assert app.engine.drivers[0].settings["break_method"] == "baud_drop"  # rebuilt with it
    wait(lambda: app.engine.test is None)


def test_no_tap_puts_the_output_back(open_app):
    app, p = open_app
    before = p.read_text()
    app.start_cycle(0, step_s=0.05)
    app.cycle.wait(5)
    assert app.cycle.state == "no_response"
    assert app.engine.drivers[0].settings["break_method"] == "auto" and app.engine.test is None
    assert p.read_text() == before


def test_stopping_the_test_stops_the_cycle(open_app):
    app, _ = open_app
    app.start_cycle(0, step_s=1)
    app.stop_test()
    assert app.cycle.state == "stopped" and app.engine.drivers[0].settings["break_method"] == "auto"


def test_gig_lock_and_wrong_output(open_app):
    app, _ = open_app
    with pytest.raises(ValueError, match="USB DMX \\(Open\\)"):
        app.start_cycle(3)
    app.set_gig_lock(True)
    with pytest.raises(LockedError):
        app.start_cycle(0)
    app.set_gig_lock(False)


def test_save_step_afterwards(open_app):
    app, p = open_app
    app.engine.drivers[0]._d2xx_available = lambda: False
    r = app.save_cycle_step(0, 3)
    assert r["break_us"] == 500 and yaml.safe_load(p.read_text())["outputs"][0]["break_us"] == 500


def test_mcp_cycle(open_app, monkeypatch):
    from test_web import CLAUDE, TOKEN

    from dmx_suite import dmxcheck
    from dmx_suite.claude_tools import DmxTools
    from dmx_suite.web.server import WebServer

    app, p = open_app
    monkeypatch.setattr(dmxcheck, "STEP_S", 0.1)
    web = WebServer(app, "127.0.0.1", 0, token=TOKEN, claude_token=CLAUDE)
    web.start()
    try:
        t = DmxTools(shows=p.parents[1], url=f"http://127.0.0.1:{web.port}", token=CLAUDE)
        r = yaml.safe_load(t.test_output_methods(0))
        assert r["state"] == "no_response" and "save_step" in r["note"]
        r = yaml.safe_load(t.test_output_methods(0, save_step=2))
        assert r["saved"]["break_method"] == "baud_drop"
    finally:
        web.stop()
