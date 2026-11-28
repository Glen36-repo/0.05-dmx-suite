"""v5 item 4: test patterns straight to the interface, bypassing scenes, masters and MASTER; head limits,
U'King home position and haze (rule 5) still hold; strobe off in all full; timeout; one interface only;
gig lock allows keep-alive only; API and MCP."""

import shutil
from pathlib import Path

import pytest
import yaml

from dmx_suite.output import LogDriver
from dmx_suite.testpattern import TestPattern

SHOWS = Path(__file__).resolve().parents[1] / "shows"


def sent(out, engine, fid, role, pixel=None):
    fx = engine.rig.patch.fixtures[fid]
    frame = out.last[fx.universe]
    for ch in fx.type.channels:
        if ch.role == role and (pixel is None or ch.pixel == pixel):
            return frame[fx.slot(ch)]
    raise KeyError(role)


def emitters(out, engine, fid):
    fx = engine.rig.patch.fixtures[fid]
    return [out.last[fx.universe][fx.slot(c)] for c in fx.type.channels if c.role in ("red", "green", "blue", "dimmer")]


@pytest.fixture
def dark(engine):
    """MASTER off, blackout on, grand master 0: the show itself sends nothing lit."""
    engine.set_master(False)
    engine.set_blackout(True)
    engine.set_grand(0.0)
    engine.masters.tick(10)
    engine.tick()
    return engine


def test_all_full_bypasses_master_blackout_and_grand(dark, out):
    e = dark
    assert all(v == 0 for v in emitters(out, e, "wash"))
    e.run_test(TestPattern("all_full"))
    e.tick()
    for fid in ("mh_a", "bar_1", "bar_2", "wash", "uk", "kick"):
        assert all(v == 255 for v in emitters(out, e, fid)), fid
    # the engine's own frame (what the show renders) is untouched
    fx = e.rig.patch.fixtures["wash"]
    assert e.frames[0][fx.slot(fx.type.channels[0])] == 0


def test_all_full_strobe_off_haze_zero_limits_held(dark, out):
    e = dark
    e.run_test(TestPattern("all_full"))
    e.tick()
    assert sent(out, e, "mh_a", "strobe") == 7  # the type's default (open), never 255
    assert sent(out, e, "mh_a", "fixed") == 42 and sent(out, e, "mh_a", "gobo") == 0
    assert sent(out, e, "smoke", "haze") == 0  # rule 5
    assert round(0.10 * 255) - 1 <= sent(out, e, "mh_a", "pan") <= round(0.90 * 255) + 1  # rule 8
    assert sent(out, e, "mh_a", "tilt") <= round(0.75 * 255) + 1  # rule 8
    assert sent(out, e, "uk", "pan") == round(0.25 * 255) and sent(out, e, "uk", "tilt") == round(0.75 * 255)  # rule 7


def test_all_full_unpatched_channels(engine, out):
    engine.run_test(TestPattern("all_full"))
    engine.tick()
    assert out.last[0][300] == 255
    engine.run_test(TestPattern("all_full", patched_only=True))
    engine.tick()
    assert out.last[0][300] == 0


def test_chase_one_light_at_a_time(dark, out, clock):
    e = dark
    e.run_test(TestPattern("chase", dwell_s=1.0))
    seen = []
    for _ in range(6):
        e.tick()
        lit = [f for f in ("mh_a", "bar_1", "bar_2", "wash", "uk", "kick") if any(emitters(out, e, f))]
        assert len(lit) == 1
        seen.append(lit[0])
        assert e.test_status()["now"] == lit[0]
        clock.advance(1.0)
    assert seen == ["mh_a", "bar_1", "bar_2", "wash", "uk", "kick"]  # haze never in the chase


def test_find_flashes_and_nods_inside_limits(dark, out, clock):
    e = dark
    e.run_test(TestPattern("find", fixture="mh_a"))
    on, tilts = [], []
    for _ in range(8):
        e.tick()
        on.append(sent(out, e, "mh_a", "red") == 255)
        tilts.append(sent(out, e, "mh_a", "tilt"))
        assert not any(emitters(out, e, "wash"))
        clock.advance(0.25)
    assert on == [True, True, False, False, True, True, False, False]  # 1 Hz
    assert len(set(tilts)) > 1 and max(tilts) <= round(0.75 * 255) + 1
    with pytest.raises(ValueError, match="rule 5"):
        e.run_test(TestPattern("find", fixture="smoke"))


def test_ramp_and_hold(dark, out, clock):
    e = dark
    fx = e.rig.patch.fixtures["wash"]
    e.run_test(TestPattern("ramp", fixture="wash", extra={"role": "red"}))
    vals = []
    for _ in range(5):
        e.tick()
        vals.append(sent(out, e, "wash", "red"))
        clock.advance(1.0)
    assert vals == [0, 128, 255, 128, 0]
    e.run_test(TestPattern("ramp", channel=fx.address, value=99))
    e.tick()
    assert sent(out, e, "wash", "dimmer") == 99
    with pytest.raises(ValueError, match="rule 5"):
        e.run_test(TestPattern("ramp", channel=70))
    with pytest.raises(ValueError, match="rule 8"):
        e.run_test(TestPattern("ramp", channel=3))  # mh_a tilt


def test_keep_alive(engine, out):
    engine.run_test(TestPattern("keep_alive", value=10))
    engine.tick()
    assert set(emitters(out, engine, "wash")) == {10} and sent(out, engine, "smoke", "haze") == 0


def test_timeout_and_stop_restore_the_show(dark, out, clock):
    e = dark
    e.run_test(TestPattern("all_full", timeout_s=5))
    e.tick()
    assert sent(out, e, "wash", "red") == 255
    clock.advance(5.1)
    e.tick()
    assert e.test is None and sent(out, e, "wash", "red") == 0
    assert [x["what"] for x in e.test_log] == ["start", "timed out"]
    e.run_test(TestPattern("all_full"))
    assert e.stop_test() and not e.stop_test()
    e.tick()
    assert sent(out, e, "wash", "red") == 0


def test_one_interface_only(rig, look, clock):
    from dmx_suite.engine import Engine

    a, b = LogDriver(), LogDriver()
    e = Engine(rig, [a, b], look, clock=clock)
    e.set_master(False)
    e.tick()
    e.run_test(TestPattern("all_full", output=1))
    e.tick()
    assert all(v == 255 for v in emitters(b, e, "wash")) and not any(emitters(a, e, "wash"))
    with pytest.raises(ValueError, match="no output"):
        e.run_test(TestPattern("all_full", output=5))


def test_bad_requests(engine):
    for tp, msg in ((TestPattern("disco"), "pattern"), (TestPattern("find"), "fixture"),
                    (TestPattern("ramp"), "channel"), (TestPattern("all_full", timeout_s=0), "timeout"),
                    (TestPattern("keep_alive", value=300), "value")):
        with pytest.raises(ValueError, match=msg):
            engine.run_test(tp)
    assert engine.test is None


# ---------------------------------------------------------------- app, API, MCP, gig lock


@pytest.fixture
def running(tmp_path):
    from test_web import CLAUDE, TOKEN

    from dmx_suite.app import App
    from dmx_suite.showfiles import load_show
    from dmx_suite.web.server import WebServer

    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json"))
    out = LogDriver()
    app = App(load_show(root), [out], state_path=root / ".state.json", log_dir=tmp_path / "logs")
    web = WebServer(app, "127.0.0.1", 0, token=TOKEN, claude_token=CLAUDE)
    web.start()
    yield app, f"http://127.0.0.1:{web.port}", root, out, CLAUDE
    web.stop()
    app.engine.stop()


def test_api_status_tile_and_monitor_label(running):
    from test_web import call

    app, url, _, _, _ = running
    status, body = call(f"{url}/api/test/run", "POST", {"pattern": "all_full", "timeout_s": 30})
    assert status == 200 and body["test"]["pattern"] == "all_full"
    assert any(d["kind"] == "test" for d in app.devices())
    assert call(f"{url}/api/frame?u=0")[1]["test"]["name"] == "All full"
    assert call(f"{url}/api/test")[1]["test"]["pattern"] == "all_full"
    assert call(f"{url}/api/state")[1]["test"]["pattern"] == "all_full"
    assert call(f"{url}/api/test/stop", "POST", {})[1]["stopped"]
    assert call(f"{url}/api/test")[1]["test"] is None and not any(d["kind"] == "test" for d in app.devices())


def test_gig_lock_keep_alive_only(running):
    from test_web import call

    app, url, _, _, _ = running
    app.set_gig_lock(True)
    status, body = call(f"{url}/api/test/run", "POST", {"pattern": "all_full"})
    assert status == 423
    assert call(f"{url}/api/test/run", "POST", {"pattern": "keep_alive"})[0] == 200
    assert call(f"{url}/api/test/stop", "POST", {})[0] == 200  # stop always works


def test_mcp_tools(running):
    from dmx_suite.claude_tools import DmxTools

    app, url, root, out, claude = running
    t = DmxTools(shows=root, url=url, token=claude)
    r = yaml.safe_load(t.run_test_pattern("chase", dwell_s=1))
    assert r["running"]["pattern"] == "chase" and r["running"]["by"] == "claude"
    assert t.stop_test_pattern().startswith("stopped") and t.stop_test_pattern().startswith("no test")
    assert app.engine.test_log[-1]["by"] == "claude"


def test_mcp_registers_test_tools():
    pytest.importorskip("mcp")
    import asyncio

    from dmx_suite.claude_tools import DmxTools
    from dmx_suite.mcp_server import build_server

    names = {x.name for x in asyncio.run(build_server(DmxTools(shows=SHOWS)).list_tools())}
    assert {"run_test_pattern", "stop_test_pattern"} <= names
