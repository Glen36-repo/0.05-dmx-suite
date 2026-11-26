"""v4 item 10 (backend): edit one step without rewriting the scene; what each light shows at a step
(set here or tracked); errors and head-limit problems pinned to the step."""

import shutil
from pathlib import Path

import pytest
import yaml
from test_web import CLAUDE, TOKEN, call

from dmx_suite.app import App
from dmx_suite.claude_tools import DmxTools
from dmx_suite.output import LogDriver
from dmx_suite.showfiles import load_show
from dmx_suite.steps import track_view
from dmx_suite.store import StoreError
from dmx_suite.web.server import WebServer

SHOWS = Path(__file__).resolve().parents[1] / "shows"
SCENE = {"name": "Chase", "type": "steps", "step_s": 2, "steps": [
    {"name": "red", "set": {"bars": {"colour": "red"}, "movers": {"position": "drum_kit"}}},
    {"name": "tips", "set": {"bars:px1,8": {"colour": "white"}}},
    {"name": "blue", "set": {"bars": {"colour": "blue"}}, "fade_s": 0.5},
]}


@pytest.fixture
def running(tmp_path):
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json"))
    (root / "scenes" / "chase.yaml").write_text(yaml.safe_dump({"version": 6, **SCENE}, sort_keys=False))
    app = App(load_show(root), [LogDriver()], state_path=root / ".state.json")
    web = WebServer(app, "127.0.0.1", 0, token=TOKEN, claude_token=CLAUDE)
    web.start()
    yield app, f"http://127.0.0.1:{web.port}", root
    web.stop()
    app.engine.stop()


def scene_file(root):
    return yaml.safe_load((root / "scenes" / "chase.yaml").read_text())


def test_track_view_says_set_or_tracked():
    patch = load_show(SHOWS).patch
    v = track_view(SCENE, 1, patch)
    bar = v["fixtures"]["bar_1"]
    assert bar["colour"] == {"value": "red", "from_step": 0, "via": "bars", "source": "tracked"}
    assert bar["colour@px1,8"]["source"] == "set" and bar["colour@px1,8"]["pixels"] == [1, 8]
    assert v["fixtures"]["mh_a"]["position"]["source"] == "tracked"
    v2 = track_view(SCENE, 2, patch)
    assert v2["fixtures"]["bar_1"]["colour"]["source"] == "set" and "colour@px1,8" not in v2["fixtures"]["bar_1"]
    with pytest.raises(Exception, match="no step 4"):
        track_view(SCENE, 3, patch)


def test_step_view_api(running):
    app, url, root = running
    status, v = call(f"{url}/api/steps/view", "POST", {"scene": "chase", "index": 1})
    assert status == 200 and v["name"] == "tips"
    status, v = call(f"{url}/api/steps/view", "POST", {"scene": SCENE, "index": 0})  # unsaved data works too
    assert v["fixtures"]["bar_1"]["colour"]["source"] == "set"


def test_step_tools_online(running):
    app, url, root = running
    t = DmxTools(shows=root, url=url, token=CLAUDE)
    assert t.add_step("chase", "{name: green, set: {washes: {colour: green}}}", at=2).startswith("saved")
    assert [s["name"] for s in scene_file(root)["steps"]] == ["red", "green", "tips", "blue"]
    assert t.update_step("chase", "green", "{bars: {colour: white}}", "{step_s: 1.5}").startswith("saved")
    st = scene_file(root)["steps"][1]
    assert st["set"] == {"washes": {"colour": "green"}, "bars": {"colour": "white"}} and st["step_s"] == 1.5
    t.update_step("chase", 2, "{washes: null}", "{step_s: null}")  # take washes out: they track again
    assert scene_file(root)["steps"][1] == {"name": "green", "set": {"bars": {"colour": "white"}}}
    assert t.move_step("chase", "blue", 1).startswith("saved")
    assert scene_file(root)["steps"][0]["name"] == "blue"
    assert t.delete_step("chase", 2).startswith("saved")
    assert [s["name"] for s in scene_file(root)["steps"]] == ["blue", "green", "tips"]
    assert "Chase" in app.files.scenes["chase"].name  # reloaded live
    with pytest.raises(StoreError, match="rule 1|dimmer"):
        t.update_step("chase", 1, "{bars: {dimmer: 1}}")
    with pytest.raises(StoreError, match="colour only"):
        t.add_step("chase", "{set: {'bar_1:px2': {intensity: 0.5}}}")
    with pytest.raises(StoreError, match="no step 9"):
        t.delete_step("chase", 9)
    with pytest.raises(StoreError, match="needs set_yaml"):
        t.update_step("chase", 1)
    assert "previewing" in t.preview_scene("chase", 2, step=2)
    app.set_gig_lock(True)
    with pytest.raises(StoreError, match="gig lock"):
        t.add_step("chase", "{set: {bars: {colour: red}}}")


def test_step_tools_offline(tmp_path):
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json"))
    (root / "scenes" / "chase.yaml").write_text(yaml.safe_dump({"version": 6, **SCENE}, sort_keys=False))
    t = DmxTools(shows=root, url="http://127.0.0.1:9", token=CLAUDE)
    assert "engine isn't running" in t.update_step("chase", "tips", "{'bars:px4-5': {colour: red}}")
    assert "bars:px4-5" in scene_file(root)["steps"][1]["set"]
    with pytest.raises(StoreError, match="isn't a step scene"):
        t.add_step("opera", "{set: {bars: {colour: red}}}")


def test_validation_pins_errors_and_limits_to_the_step(running):
    app, url, root = running
    bad = {**SCENE, "steps": [*SCENE["steps"], {"set": {"ukings": {"position": "drum_kit"}}}]}
    v = app.validate_scene(bad)
    assert not v["ok"] and v["step"] == 3 and v["target"] == "ukings" and "rule 7" in v["error"]
    rig = app.store.read("rig", "full")
    rig["head_limits"]["mh_a"]["tilt"] = [0, 20]
    app.store.put("rig", "full", rig)
    app.reload()
    v = app.validate_scene(SCENE)
    assert v["ok"] and any(p["step"] == 0 and p["fixture"] == "mh_a" and "rule 8" in p["message"] for p in v["problems"])
