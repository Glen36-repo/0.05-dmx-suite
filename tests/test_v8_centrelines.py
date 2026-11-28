# ruff: noqa: F811 - pytest fixtures imported from test_autopilot are used as arguments
"""v8 Part A item 12: stage centrelines per rig (`layout: centre: {x, y}`, grid cells). Effects that run from
the centre (spatial centre_out / out_centre, Radial), Split's two sides and the Autopilot's left / right
lists use the rig's lines, not the middle of whichever lights a layer runs on. Missing = the middle of all
the lights (no format step)."""

from pathlib import Path

import pytest
import yaml
from test_autopilot import app  # noqa: F401 - pytest fixture

from dmx_suite.classify import auto_rig
from dmx_suite.effects.base import Unit, place_units
from dmx_suite.fixtures import ConfigError, Kind
from dmx_suite.layout import full_layout, layout_view
from dmx_suite.scenes import ScenePlayer, parse_scene
from dmx_suite.showfiles import load_show

SHOWS = Path(__file__).resolve().parents[1] / "shows"


@pytest.fixture
def files():
    return load_show(SHOWS)


def with_centre(files, centre):
    from dmx_suite.rig import parse_rig

    data = yaml.safe_load((SHOWS / "rigs" / "full.yaml").read_text(encoding="utf-8"))
    data.pop("version", None)
    data["layout"] = {**(data.get("layout") or {}), "centre": centre}
    return parse_rig(data, files.patch)


def test_auto_centre_is_the_middle_of_all_lights(files):
    rig = files.rig
    assert rig.centre is None
    lay = full_layout(rig)
    pts = [lay[f.id] for f in rig.fixtures if f.kind != Kind.HAZE]
    want = ((min(p.x for p in pts) + max(p.x for p in pts)) / 2, (min(p.y for p in pts) + max(p.y for p in pts)) / 2)
    assert rig.layout_centre() == want


def test_parse_and_refuse(files):
    rig = with_centre(files, {"x": 7.3, "y": 2})
    assert rig.centre == (7.5, 2.0) and rig.layout_centre() == (7.5, 2.0)  # snapped to half cells
    assert "centre" not in rig.layout  # not a light
    assert with_centre(files, None).centre is None
    for bad, msg in (({"x": 1}, "both x and y"), ({"x": "a", "y": 1}, "grid cells"), ({"x": 999, "y": 1}, "0-200"),
                     ({"x": 1, "y": 1, "z": 2}, "{x, y}"), (5, "{x, y}")):
        with pytest.raises(ConfigError, match=msg):
            with_centre(files, bad)


def units_along(xs, cx):
    us = [Unit("f", None, i, x, 0.5, cx=cx, cy=0.5) for i, x in enumerate(xs)]
    place_units(us, {"mapping": "spatial", "direction": "centre_out"}, "t")
    return [u.u for u in us]


def test_centre_out_runs_from_the_rig_centre():
    xs = [0.0, 0.25, 0.5, 0.75, 1.0]
    mid = units_along(xs, None)  # no rig centre: the layer's middle (as v7)
    assert mid.index(0.0) == 2
    left = units_along(xs, 0.25)
    assert left.index(0.0) == 1 and left != mid  # the light on the line is lit first
    assert left[4] == max(left)  # furthest from the line: last


def bars_split(files, rig):
    sc = parse_scene({"layers": [{"fixtures": ["bars"], "effect": "split", "colours": ["red", "blue"]}]},
                     files.patch, files.palettes, "t")
    look = ScenePlayer(sc, rig, 0.0)(0.0)
    reds = blues = 0
    for f in ("bar_1", "bar_2", "bar_3", "bar_4"):
        for px in look.fixtures[f].pixels or [look.fixtures[f].colour]:
            reds += px.get("red", 0) > 0.5
            blues += px.get("blue", 0) > 0.5
    return reds, blues


def test_split_sides_follow_the_vertical_line(files):
    r0, b0 = bars_split(files, files.rig)
    assert r0 and b0
    lay = full_layout(files.rig)
    far_left = min(lay[f].x for f in ("bar_1", "bar_2", "bar_3", "bar_4")) - 3
    r1, b1 = bars_split(files, with_centre(files, {"x": max(0, far_left), "y": 1}))
    assert r1 == 0 and b1 == r0 + b0  # every bar is right of the line


def test_autopilot_sides_follow_the_line(files):
    lay = full_layout(files.rig)
    base = auto_rig(files.rig)
    placed = base.left + base.right
    ar = auto_rig(with_centre(files, {"x": max(lay[f].x for f in placed) + 1, "y": 1}))
    assert sorted(ar.left) == sorted(placed) and ar.right == []  # all left of a line past the rig
    x = sorted({lay[f].x for f in placed})[1]  # just right of the leftmost column
    ar = auto_rig(with_centre(files, {"x": x, "y": 1}))
    assert set(ar.left) == {f for f in placed if lay[f].x < x}


def test_layout_view_and_positions(files):
    v = layout_view(files.rig)
    assert v["centre"]["set"] is False
    v = layout_view(with_centre(files, {"x": 10, "y": 3}))
    assert v["centre"] == {"x": 10.0, "y": 3.0, "set": True}


def rig_file(app):
    return yaml.safe_load((app.files.root / "rigs" / f"{app.names[0]}.yaml").read_text(encoding="utf-8"))


def test_save_layout_keeps_sets_and_clears_the_centre(app):
    cat = app.catalogue()
    assert cat["centre"] is None and cat["centre_auto"] is not None
    lay = cat["layout"]
    app.save_layout(lay, {"x": 9, "y": 4})
    assert rig_file(app)["layout"]["centre"] == {"x": 9, "y": 4}
    assert app.engine.rig.layout_centre() == (9.0, 4.0)
    assert app.catalogue()["centre"] == {"x": 9.0, "y": 4.0}
    app.save_layout(lay)  # no centre given: kept
    assert rig_file(app)["layout"]["centre"] == {"x": 9, "y": 4}
    app.save_layout(lay, None)  # Reset to middle
    assert "centre" not in rig_file(app)["layout"] and app.engine.rig.centre is None


def test_set_positions_moves_the_centre(app):
    app.set_positions({"centre": {"x": 6}})
    c = app.engine.rig.centre
    assert c is not None and c[0] == 6.0
    app.set_positions({"centre": None})
    assert app.engine.rig.centre is None
    with pytest.raises(ConfigError):
        app.set_positions({"centre": {"x": 1, "rot": 3}})


def test_mcp_layout_tools(app, tmp_path):
    from dmx_suite.claude_tools import DmxTools

    t = DmxTools(shows=app.files.root)
    t.set_layout("centre: {x: 8, y: 2}", "full")
    out = yaml.safe_load(t.get_layout("full"))
    assert out["centre"] == {"x": 8.0, "y": 2.0, "set": True}
