"""v5 item 3: "Rig not responding" fault-find: checks first (stop on fail), the auto/sound-mode question,
both branches in the brief's order, the live-frame zero flag, tests per step, gig lock, summary and log,
API and MCP walking the same tree."""

import logging
import shutil
from pathlib import Path

import pytest
import yaml
from test_v5_checks import FakeProbe, FakeRegistry, SerialAttrs

from dmx_suite.faultfind import DMX_ARRIVES, NO_DMX
from dmx_suite.output import LogDriver
from dmx_suite.output.enttec import EnttecOpenDriver
from tests.test_open_dmx import wait_frames

SHOWS = Path(__file__).resolve().parents[1] / "shows"


@pytest.fixture
def app(tmp_path):
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
    drv = EnttecOpenDriver("COM3", serial_factory=lambda *a: ser, d2xx_available=lambda: False)
    drv.cfg = {**files.rig.outputs[0], "driver": "usb_dmx_open"}
    a = App(files, [drv], state_path=root / ".state.json")
    a.registry = FakeRegistry("COM3")
    a.health_probe = FakeProbe(latency=1, suspend_plan=False)
    wait_frames(ser, 3)
    a.engine.output()
    yield a
    if a.cycle is not None:
        a.cycle.stop()
    a.stop_test()
    a.engine.stop()
    drv.close()


def walk(app, *answers):
    v = app.fault_find("start")
    for ans in answers:
        v = app.fault_find("answer", ans)
    return v


def test_checks_fail_stops_with_the_fix(app):
    app.health_probe = FakeProbe(latency=1, suspend_plan=False)
    drv = app.engine.drivers[0]
    drv._ser.stopbits = 1
    v = app.fault_find("start")
    assert v["stage"] == "done" and "250k 8N2" in v["outcome"] and "Fix:" in v["outcome"]
    assert v["history"][0]["result"] == "fail"


def test_question_then_no_dmx_branch_in_order(app):
    v = walk(app)
    assert v["stage"] == "question" and v["answers"] == ["yes", "no"] and v["history"][0]["result"] == "pass"
    v = app.fault_find("answer", "yes")
    seen = []
    while v["stage"] == "steps":
        seen.append(v["step"])
        v = app.fault_find("answer", "fail")
    assert seen == ["cycle", "wireless", "lead", "in_thru", "other_app"]
    assert v["stage"] == "done" and "RS-485" in v["outcome"]
    assert [s["id"] for s in NO_DMX] == seen + ["interface"]


def test_other_app_works_points_at_timing(app):
    v = walk(app, "yes", "fail", "fail", "fail", "fail", "pass")
    assert v["stage"] == "done" and "timing" in v["outcome"] and "Cycle break methods" in v["outcome"]


def test_pass_ends_there(app):
    v = walk(app, "yes", "fail", "pass")
    assert v["stage"] == "done" and v["outcome"].startswith("found at 'wireless'")
    assert [h["step"] for h in v["history"]][-2:] == ["cycle", "wireless"]


def test_cycle_step_skipped_without_open_dmx(app):
    app.engine.drivers.append(LogDriver())
    od = app.engine.drivers.pop(0)
    try:
        v = walk(app, "yes")
        assert v["step"] == "wireless"
    finally:
        app.engine.drivers.insert(0, od)
        app.engine.drivers.pop()


def test_dmx_arrives_branch_with_fixture_details(app):
    import time

    from dmx_suite.testpattern import TestPattern

    fid = next(f.id for f in app.engine.rig.fixtures if f.type.kind.value == "bar")
    fx = app.engine.rig.patch.fixtures[fid]
    app.engine.run_test(TestPattern("all_full", timeout_s=60))  # the interface really sends it lit
    app.engine.output()
    end = time.monotonic() + 2
    while not (app.engine.drivers[0].wire.frame(fx.universe) or bytes(1))[fx.address - 1]:
        assert time.monotonic() < end
        time.sleep(0.01)
    v = walk(app, "no")
    assert v["stage"] == "pick" and fid in v["answers"]
    v = app.fault_find("answer", fid)
    assert v["stage"] == "steps" and v["step"] == "find" and v["test"] == "find" and not v["flag"]
    seen = []
    while v["stage"] == "steps":
        seen.append(v["step"])
        if v["step"] == "address":
            assert f"start address to {fx.address}" in v["instruction"]
        if v["step"] == "mode":
            assert f"{fx.type.footprint} channels" in v["instruction"]
        v = app.fault_find("answer", "fail")
    assert seen == [s["id"] for s in DMX_ARRIVES if s.get("kind") != "auto"]
    assert v["stage"] == "done" and "Live frame" in v["outcome"] and "grand master" in v["outcome"]


def test_app_sending_zero_is_flagged_before_hardware(app):
    app.engine.set_master(False)
    app.engine.set_blackout(False)
    app.engine.output()
    fid = next(f.id for f in app.engine.rig.fixtures if f.type.kind.value == "bar")
    v = walk(app, "no", fid)
    assert v["stage"] == "done" and "sending 0" in v["outcome"] and "MASTER is off" in v["outcome"]


def test_tests_per_step_and_gig_lock(app):
    v = walk(app, "yes")
    assert v["test"] == "cycle" and v["test_allowed"]
    r = app.fault_find("test")
    assert r["cycle"]["state"] == "running"
    app.cycle.stop()
    v = app.fault_find("answer", "fail")
    r = app.fault_find("test")
    assert r["test"]["pattern"] == "all_full"
    app.stop_test()
    app.set_gig_lock(True)
    assert not app.fault_find("status")["test_allowed"]
    from dmx_suite.store import LockedError

    with pytest.raises(LockedError):
        app.fault_find("test")
    app.set_gig_lock(False)


def test_summary_logged_and_restart(app, caplog):
    with caplog.at_level(logging.INFO, logger="dmx_suite.faultfind"):
        v = walk(app, "yes", "fail", "pass")
    assert "Fault-find" in v["summary"] and "- wireless: pass" in v["summary"] and "Result: found" in v["summary"]
    assert any("Fault-find" in r.message for r in caplog.records)
    assert app.fault_find("answer", "restart")["stage"] == "question"


def test_bad_answers(app):
    walk(app)
    with pytest.raises(ValueError, match="yes"):
        app.fault_find("answer", "maybe")
    app.fault_find("answer", "no")
    with pytest.raises(ValueError, match="pick a light"):
        app.fault_find("answer", "nope")


def test_api_and_mcp(app):
    from test_web import CLAUDE, TOKEN, call

    from dmx_suite.claude_tools import DmxTools
    from dmx_suite.web.server import WebServer

    web = WebServer(app, "127.0.0.1", 0, token=TOKEN, claude_token=CLAUDE)
    web.start()
    try:
        url = f"http://127.0.0.1:{web.port}"
        assert call(f"{url}/api/faultfind", "POST", {"action": "start"})[1]["stage"] == "question"
        t = DmxTools(shows=SHOWS, url=url, token=CLAUDE)
        r = yaml.safe_load(t.fault_find("answer", "yes"))
        assert r["step"] == "cycle" and r["answers"] == ["pass", "fail"]
        assert call(f"{url}/api/faultfind")[1]["step"] == "cycle"  # same tree as the UI
        r = yaml.safe_load(t.fault_find("answer", "pass"))
        assert r["stage"] == "done" and "summary" in r
    finally:
        web.stop()
