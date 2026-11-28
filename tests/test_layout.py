import json
import shutil
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml

from dmx_suite.app import App
from dmx_suite.fixtures import ConfigError
from dmx_suite.layout import full_layout
from dmx_suite.output import LogDriver
from dmx_suite.rig import Placement, parse_rig
from dmx_suite.showfiles import load_show
from dmx_suite.web.server import WebServer

SHOWS = Path(__file__).resolve().parents[1] / "shows"
TOKEN = "test-token-0123456789abcdef"


def test_layout_parsed_and_defaults_filled(patch):
    rig = parse_rig({"layout": {"mh_a": {"x": 2.3, "y": 4, "rot": 370},
                                "bar_1": {"x": 10, "y": 6, "shape": "ring"}}}, patch)
    assert rig.layout["mh_a"] == Placement(2.5, 4.0, 10.0)  # half cells, rotation wraps
    assert rig.layout["bar_1"].shape == "ring"
    full = full_layout(rig)
    assert set(full) == set(rig.present)  # every light has a spot
    assert full["mh_a"] == Placement(2.5, 4.0, 10.0)  # placed ones kept
    spots = [(p.x, p.y) for p in full.values()]
    assert len(set(spots)) == len(spots)  # defaults don't sit on top of each other


@pytest.mark.parametrize("data, msg", [
    ({"layout": {"nope": {"x": 1, "y": 1}}}, "unknown fixture"),
    ({"layout": {"mh_a": {"x": 1}}}, "needs x and y"),
    ({"layout": {"mh_a": {"x": 999, "y": 1}}}, "0-200 cells"),
    ({"layout": {"mh_a": {"x": 1, "y": 1, "shape": "star"}}}, "shape must be"),
    ({"layout": {"mh_a": {"x": 1, "y": 1, "shape": "grid", "cols": 99}}}, "cols must be"),
    ({"layout": [1, 2]}, "fixture: {x, y}"),
])
def test_layout_validation(patch, data, msg):
    with pytest.raises(ConfigError, match=msg):
        parse_rig(data, patch)


def test_default_layout_shape():
    rig = load_show(SHOWS).rig
    full = full_layout(rig)
    heads = [full[f.id].y for f in rig.fixtures if f.kind.value == "head"]
    bars = [full[f.id] for f in rig.fixtures if f.kind.value == "bar"]
    washes = [full[f.id].y for f in rig.fixtures if f.kind.value == "wash"]
    assert max(heads) < min(b.y for b in bars) < min(washes)  # heads at the back (top), washes at the front
    xs = sorted(b.x for b in bars)
    assert all(b - a >= 9 for a, b in zip(xs, xs[1:]))  # 8-pixel bars end to end, not overlapping


def test_metre_stage_plan_upgrades_to_grid(tmp_path):
    from dmx_suite.versions import upgrade

    old = {"version": 2, "stage": {"width": 6, "depth": 4},
           "layout": {"mh_a": {"x": 1.5, "y": 3.5, "rot": 90}, "kick": {"x": 3.0, "y": 0.0}}}
    new = upgrade(old, "rig")
    assert "stage" not in new
    assert new["layout"]["mh_a"] == {"x": 7.0, "y": 3.0, "rot": 90}  # back of the stage near the top
    assert new["layout"]["kick"] == {"x": 13.0, "y": 17.0, "rot": 0}  # front edge at the bottom


@pytest.fixture
def running(tmp_path):
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json"))
    app = App(load_show(root), [LogDriver()])
    web = WebServer(app, "127.0.0.1", 0, token=TOKEN)
    web.start()
    yield app, f"http://127.0.0.1:{web.port}", root
    web.stop()
    app.engine.stop()


def put(url, body):
    req = urllib.request.Request(url + "/api/layout", data=json.dumps(body).encode(), method="PUT",
                                 headers={"Content-Type": "application/json", "X-DMX-Token": TOKEN})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_save_layout_writes_rig_file_and_applies_live(running):
    app, url, root = running
    status, r = put(url, {"layout": {"kick": {"x": 14, "y": 9.5, "rot": 0},
                                     "bar_1": {"x": 4, "y": 3, "rot": 30, "shape": "ring"}}})
    assert status == 200 and r["backup"]
    data = yaml.safe_load((root / "rigs" / "full.yaml").read_text())
    assert "stage" not in data
    assert data["layout"]["bar_1"] == {"x": 4.0, "y": 3.0, "rot": 30.0, "shape": "ring"}
    assert app.engine.rig.layout["kick"].x == 14.0  # live, no restart
    cat = app.catalogue()
    assert cat["layout"]["kick"] == {"x": 14.0, "y": 9.5, "rot": 0.0, "shape": "row", "cols": 0}
    assert len(cat["layout"]) == 12  # the rest filled with defaults
    assert data["haze"]["level"] == 60  # the rest of the rig file kept


def test_bad_layout_rejected_and_gig_lock(running):
    app, url, _ = running
    status, r = put(url, {"layout": {"ghost": {"x": 1, "y": 1}}})
    assert status == 400 and "unknown fixture" in r["error"]
    app.set_gig_lock(True)
    assert put(url, {"layout": {"kick": {"x": 1, "y": 1}}})[0] == 423
