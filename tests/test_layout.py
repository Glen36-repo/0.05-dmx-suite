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
    rig = parse_rig({"stage": {"width": 8, "depth": 5}, "layout": {"mh_a": {"x": 2, "y": 4.5, "rot": 370}}}, patch)
    assert rig.stage == (8.0, 5.0)
    assert rig.layout["mh_a"] == Placement(2.0, 4.5, 10.0)  # rotation wraps
    full = full_layout(rig)
    assert set(full) == set(rig.present)  # every fixture has a spot
    assert full["mh_a"] == Placement(2.0, 4.5, 10.0)  # placed ones kept
    for p in full.values():
        assert 0 <= p.x <= 8 and 0 <= p.y <= 5


@pytest.mark.parametrize("data, msg", [
    ({"layout": {"nope": {"x": 1, "y": 1}}}, "unknown fixture"),
    ({"layout": {"mh_a": {"x": 1}}}, "needs x and y"),
    ({"layout": {"mh_a": {"x": 99, "y": 1}}}, "out of range"),
    ({"stage": {"width": 0.5, "depth": 4}}, "1-50"),
    ({"stage": {"width": 6}}, "width and depth"),
])
def test_layout_validation(patch, data, msg):
    with pytest.raises(ConfigError, match=msg):
        parse_rig(data, patch)


def test_default_layout_shape():
    rig = load_show(SHOWS).rig
    full = full_layout(rig)
    w, d = rig.stage
    heads = [full[f.id].y for f in rig.fixtures if f.kind.value == "head"]
    washes = [full[f.id] for f in rig.fixtures if f.kind.value == "wash"]
    assert min(heads) > d / 2  # heads towards the back
    assert all(p.y < d / 4 for p in washes)  # washes at the front
    assert washes[0].x < w / 2 < washes[1].x  # one each side


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
    status, r = put(url, {"stage": {"width": 7, "depth": 4.5}, "layout": {"kick": {"x": 3.5, "y": 2.2, "rot": 0},
                                                                           "wash_l": {"x": 1.0, "y": 0.4, "rot": 30}}})
    assert status == 200 and r["backup"]
    data = yaml.safe_load((root / "rigs" / "full.yaml").read_text())
    assert data["stage"] == {"width": 7.0, "depth": 4.5}
    assert data["layout"]["wash_l"] == {"x": 1.0, "y": 0.4, "rot": 30}
    assert app.engine.rig.stage == (7.0, 4.5)  # live, no restart
    cat = app.catalogue()
    assert cat["layout"]["kick"] == {"x": 3.5, "y": 2.2, "rot": 0.0}
    assert len(cat["layout"]) == 12  # the rest filled with defaults
    assert data["haze"]["level"] == 60  # the rest of the rig file kept


def test_bad_layout_rejected_and_gig_lock(running):
    app, url, _ = running
    status, r = put(url, {"layout": {"ghost": {"x": 1, "y": 1}}})
    assert status == 400 and "unknown fixture" in r["error"]
    app.set_gig_lock(True)
    assert put(url, {"layout": {"kick": {"x": 1, "y": 1}}})[0] == 423
