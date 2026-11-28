"""v4 item 14: haze settings per mode, live apply, save, test, presets. Rule 5 unchanged."""

import shutil
from pathlib import Path

import pytest
import yaml
from test_haze import cfg
from test_web import CLAUDE, TOKEN, call

from dmx_suite.app import App
from dmx_suite.claude_tools import DmxTools
from dmx_suite.fixtures import ConfigError
from dmx_suite.haze import Haze, HazeMode
from dmx_suite.midi.map import Mapping
from dmx_suite.output import LogDriver
from dmx_suite.rig import parse_haze
from dmx_suite.showfiles import load_show
from dmx_suite.store import StoreError
from dmx_suite.web.server import WebServer

SHOWS = Path(__file__).resolve().parents[1] / "shows"


def test_pulse_has_its_own_level():
    h = Haze(cfg(level=0.6, pulse_level=0.3), 0)
    h.set_mode("pulse", 0)
    assert h.tick(1) == 0.3
    h.set_mode("manual", 10)
    assert h.tick(11) == 0.6
    assert Haze(cfg(level=0.6), 0).pulse_level == 0.6  # not set: same as level


def test_presets_parse_and_apply():
    c = parse_haze({"level": 60, "presets": [{"name": "Haze 4 Med", "mode": "manual", "level": 41}]})
    assert c.presets == [{"name": "Haze 4 Med", "mode": "manual", "level": 0.41}]
    assert c.to_dict()["presets"] == [{"name": "Haze 4 Med", "mode": "manual", "level": 41.0}]
    h = Haze(c, 0)
    h.apply_preset("Haze 4 Med", 0)
    assert h.mode == HazeMode.MANUAL and h.tick(1) == 0.41 and h.status(1).preset == "Haze 4 Med"
    with pytest.raises(ValueError, match="no haze preset"):
        h.apply_preset("nope", 2)
    for bad in ({"presets": [{"name": "x", "mode": "strobe"}]}, {"presets": [{"name": "x"}, {"name": "x"}]},
                {"pulse_level": 120}, {"colour": 1}):
        with pytest.raises(ConfigError):
            parse_haze(bad)


def test_test_runs_one_cycle_and_respects_safety():
    h = Haze(cfg(level=0.5, max_on_s=2, rest_s=10), 0)
    assert h.test("manual", 0) == 2  # min(3 s, max on)
    assert h.tick(0.5) == 0.5 and h.status(0.5).testing == "manual"
    assert h.tick(2.5) == 0  # max on reached: resting
    assert h.status(2.6).testing is None and h.mode == HazeMode.OFF  # the mode never changed
    h2 = Haze(cfg(pulse_on_s=1, pulse_level=0.2), 0)
    assert h2.test("pulse", 0) == 1 and h2.tick(0.5) == 0.2 and h2.tick(1.5) == 0
    with pytest.raises(ValueError):
        Haze(cfg(enabled=False), 0).test("manual", 0)


def test_reconfigure_keeps_the_mode():
    h = Haze(cfg(level=0.5), 0)
    h.set_mode("manual", 0)
    h.reconfigure(cfg(level=0.8), 1)
    assert h.mode == HazeMode.MANUAL and h.tick(2) == 0.8


@pytest.fixture
def running(tmp_path):
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json"))
    app = App(load_show(root), [LogDriver()], state_path=root / ".state.json")
    web = WebServer(app, "127.0.0.1", 0, token=TOKEN, claude_token=CLAUDE)
    web.start()
    yield app, f"http://127.0.0.1:{web.port}", root
    web.stop()
    app.engine.stop()


def test_settings_live_save_revert_and_gig_lock(running):
    app, url, root = running
    app.engine.haze_mode("manual")
    status, r = call(f"{url}/api/haze/settings", "POST", {"changes": {"level": 41}, "save": False})
    assert status == 200 and r["applied"] and app.engine.haze.cfg.level == 0.41
    assert yaml.safe_load((root / "rigs" / "full.yaml").read_text())["haze"]["level"] == 60  # not written
    assert app.engine.haze.mode == HazeMode.MANUAL
    status, r = call(f"{url}/api/haze/revert", "POST", {})
    assert app.engine.haze.cfg.level == 0.6
    status, r = call(f"{url}/api/haze/settings", "POST", {"changes": {"level": 41, "pulse_level": 25,
                     "presets": [{"name": "Haze 4 Med", "mode": "manual", "level": 41}]}, "save": True})
    assert status == 200 and r["backup"]
    text = (root / "rigs" / "full.yaml").read_text()
    assert yaml.safe_load(text)["haze"]["level"] == 41 and "# Full rig" in text  # comments kept
    assert app.engine.haze.mode == HazeMode.MANUAL  # saving didn't drop the mode
    assert app.snapshot()["haze"]["settings"]["pulse_level"] == 25.0
    status, r = call(f"{url}/api/haze/settings", "POST", {"changes": {"pulse_on_s": 200, "pulse_every_s": 100}, "save": False})
    assert status == 400 and "shorter" in r["error"]
    status, r = call(f"{url}/api/control", "POST", {"cmd": "haze", "action": "preset", "preset": "Haze 4 Med"})
    assert status == 200 and app.engine.haze.preset == "Haze 4 Med"
    status, r = call(f"{url}/api/haze/test", "POST", {"mode": "pulse"})
    assert status == 200 and r["seconds"] > 0
    app.set_gig_lock(True)
    assert call(f"{url}/api/haze/test", "POST", {"mode": "manual"})[0] == 423
    assert call(f"{url}/api/haze/settings", "POST", {"changes": {"level": 50}, "save": True})[0] == 423


def test_claude_haze_settings(running):
    app, url, root = running
    t = DmxTools(shows=root, url=url, token=CLAUDE)
    assert t.save_haze_settings("{pulse_on_s: 1, pulse_every_s: 61}").startswith("saved")
    assert app.engine.haze.cfg.pulse_every_s == 61
    assert "settings" in t.now_playing() and "pulse_every_s: 61" in t.now_playing()
    with pytest.raises(StoreError):
        t.save_haze_settings("{level: 500}")


def test_claude_haze_settings_offline(tmp_path):
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json"))
    t = DmxTools(shows=root, url="http://127.0.0.1:9", token=CLAUDE)
    assert "rigs/full.yaml" in t.save_haze_settings("{level: 41}")
    assert yaml.safe_load((root / "rigs" / "full.yaml").read_text())["haze"]["level"] == 41


def test_midi_haze_preset(running):
    app, url, root = running
    call(f"{url}/api/haze/settings", "POST", {"changes": {"presets": [{"name": "low", "mode": "pulse", "level": 20}]},
                                               "save": True})
    app.router.map.add(Mapping("note", 1, 70, "haze_preset", {"preset": "low"}))
    import mido

    app.router.handle_mido(mido.Message("note_on", channel=0, note=70, velocity=100), "port")
    assert app.engine.haze.mode == HazeMode.PULSE and app.engine.haze.pulse_level == 0.2


def test_rule5_scenes_still_cant_set_haze():
    from dmx_suite.look import LookError
    from dmx_suite.scenes import parse_scene

    files = load_show(SHOWS)
    with pytest.raises((LookError, ConfigError)):
        parse_scene({"layers": [{"fixtures": ["smoke"], "haze": 1}]}, files.patch, files.palettes, "x")
