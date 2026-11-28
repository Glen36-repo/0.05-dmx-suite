"""v6 Part B in the app: the drums source fed by named-input hits through the router, tap / count-in
seeds, consumers (step_beats, effect time), source off, live params, API and MCP."""

import shutil
from pathlib import Path

import pytest
import yaml
from groove import groove

from dmx_suite.output import LogDriver
from dmx_suite.showfiles import load_show
from dmx_suite.tempo import TempoClock, TempoConfig

SHOWS = Path(__file__).resolve().parents[1] / "shows"
NOTES = {"kick": 36, "snare": 38, "hat": 42, "tom": 48}


@pytest.fixture
def app(tmp_path):
    from dmx_suite.app import App

    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json"))
    p = root / "rigs" / "full.yaml"
    rig = yaml.safe_load(p.read_text())
    rig["tempo"] = {"source": "drums"}
    p.write_text(yaml.safe_dump(rig))
    t = [1000.0]
    a = App(load_show(root), [LogDriver()], state_path=root / ".state.json")
    a.engine.clock = lambda: t[0]
    a.t = t
    yield a
    a.engine.stop()


def play(app, hits, start):
    """Send a groove through the router as MIDI notes on channel 10, the tempo read at 40 Hz."""
    import mido

    t = app.t
    i = 0
    end = start + hits[-1][0] + 0.5
    while t[0] < end:
        while i < len(hits) and start + hits[i][0] <= t[0]:
            _, roles, vel = hits[i]
            app.router.handle_mido(mido.Message("note_on", channel=9, note=NOTES[roles[0]], velocity=vel), "TD-25")
            i += 1
        app.ctl.tempo.eff(t[0])
        t[0] += 0.025


def test_drums_follow_a_groove_from_a_tap(app):
    tc = app.ctl.tempo
    assert tc.source == "drums"
    tc.tap(app.t[0])
    app.t[0] += 0.53
    tc.tap(app.t[0])  # ~113
    play(app, groove(120, 12), app.t[0])
    st = tc.status(app.t[0])
    assert abs(st["bpm"] - 120) <= 1 and st["confidence"] >= 0.4 and st["seed_source"] == "tap"
    assert st["bar_beat"] in (1, 2, 3, 4)


def test_count_in_pad_seeds(app):
    import mido

    tc = app.ctl.tempo
    for _ in range(4):  # hi-hat pedal (count_in role) after silence, 100 BPM
        app.router.handle_mido(mido.Message("note_on", channel=9, note=44, velocity=90), "TD-25")
        app.t[0] += 0.6
    st = tc.status(app.t[0])
    assert st["bpm"] == pytest.approx(100, abs=0.5) and st["seed_source"] == "count-in"


def test_step_beats_follow_the_beat_clock(app):
    tc = app.ctl.tempo
    tc.set_bpm(150, app.t[0])
    tc.eff(app.t[0])
    from dmx_suite.scenes import ScenePlayer, parse_scene

    sc = parse_scene({"type": "steps", "step_beats": 2, "steps": [{"set": {"bars": {"colour": "red"}}},
                                                                   {"set": {"bars": {"colour": "blue"}}}]},
                     app.files.patch, app.files.palettes, "s")
    pl = ScenePlayer(sc, app.engine.rig, app.t[0], tc.eff)
    assert pl.runner.beat_s() == pytest.approx(0.4)  # 150 BPM


def test_effect_time_follows_and_never_jumps(app):
    tc = app.ctl.tempo
    tc.tap(app.t[0])
    app.t[0] += 0.5
    tc.tap(app.t[0])
    prev = tc.eff(app.t[0])
    for _ in range(400):
        app.t[0] += 0.025
        e = tc.eff(app.t[0])
        assert 0 < e - prev < 0.025 * 1.5  # forward, about real time at 120 (plus a nudge)
        prev = e
    tc.tap(app.t[0])
    app.t[0] += 0.4
    tc.tap(app.t[0])  # re-seed at 150
    e1 = tc.eff(app.t[0])
    app.t[0] += 0.025
    assert 0 < tc.eff(app.t[0]) - e1 < 0.025 * 1.5 * 150 / 120


def test_source_off_keeps_last_bpm_or_120():
    t = TempoClock(0.0, TempoConfig("drums"))
    t.set_source("off", 0.0)
    assert t.bpm == 120
    t2 = TempoClock(0.0, TempoConfig("tap"))
    t2.tap(0.0)
    t2.tap(0.6)  # 100
    t2.set_source("off", 1.0)
    t2.tap(2.0)
    t2.tap(2.3)
    assert t2.bpm == pytest.approx(100)


def test_switch_sources_without_a_jump():
    t = TempoClock(0.0, TempoConfig("tap"))
    t.tap(0.0)
    t.tap(0.5)
    e = t.eff(1.0)
    t.set_source("drums", 1.0)
    assert t.eff(1.0) == pytest.approx(e, abs=0.01) and t.bpm == pytest.approx(120)
    e2 = t.eff(3.0)
    t.set_source("tap", 3.0)
    assert t.eff(3.0) == pytest.approx(e2, abs=0.01)


def test_live_params_and_save(app):
    r = app.set_tempo_params({"deadband_pct": 2.5, "weights": {"hat": 0.3}})
    assert r["params"]["deadband_pct"] == 2.5 and app.ctl.tempo.tracker.p.weights["hat"] == 0.3
    app.set_tempo_params({"hold_beats": 6}, save=True)
    saved = yaml.safe_load((app.files.root / "rigs" / "full.yaml").read_text())["tempo"]
    assert saved["hold_beats"] == 6 and saved["source"] == "drums"
    with pytest.raises(ValueError):
        app.set_tempo_params({"deadband_pct": 99})


def test_api_and_mcp(app):
    from test_web import CLAUDE, TOKEN, call

    from dmx_suite.claude_tools import DmxTools
    from dmx_suite.web.server import WebServer

    web = WebServer(app, "127.0.0.1", 0, token=TOKEN, claude_token=CLAUDE)
    web.start()
    try:
        url = f"http://127.0.0.1:{web.port}"
        call(f"{url}/api/tempo", "POST", {"action": "tap"})
        app.t[0] += 0.5
        r = call(f"{url}/api/tempo", "POST", {"action": "tap"})[1]
        assert r["bpm"] == pytest.approx(120)
        d = call(f"{url}/api/tempo?debug=1")[1]
        assert "grid" in d["debug"] and "history" in d["debug"] and d["status"]["source"] == "drums"
        t = DmxTools(shows=app.files.root, url=url, token=CLAUDE)
        st = yaml.safe_load(t.tempo_status())
        assert st["bpm"] == pytest.approx(120) and "freewheel" in st and st["params"]["lock_pct"] == 15
        assert t.tap_tempo().startswith("tap")
        assert yaml.safe_load(t.set_tempo_source("off"))["source"] == "off"
        assert yaml.safe_load(t.set_tempo_params("{velocity_floor: 40}"))["params"]["velocity_floor"] == 40
    finally:
        web.stop()


def test_mcp_registers_tempo_tools():
    pytest.importorskip("mcp")
    import asyncio

    from dmx_suite.claude_tools import DmxTools
    from dmx_suite.mcp_server import build_server

    names = {x.name for x in asyncio.run(build_server(DmxTools(shows=SHOWS)).list_tools())}
    assert {"tempo_status", "tap_tempo", "set_tempo_source", "set_tempo_params"} <= names
