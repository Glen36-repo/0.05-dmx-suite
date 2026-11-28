"""v7 C1 head exclusion zones (rule 8 with the head limits): the head is held at a zone's edge on the side
it came from (never flipping across), slides round it no faster than the zone speed, and a `black` zone
turns its colour off instead. Rule tests under both profiles."""

import math

import pytest

from dmx_suite.engine import Engine
from dmx_suite.fixtures import ConfigError, parse_patch
from dmx_suite.look import parse_look
from dmx_suite.output import LogDriver
from dmx_suite.rig import parse_rig
from dmx_suite.zones import Zone, ZoneFollower, enters, parse_zone

from conftest import PATCH, RIG, Clock
from rulecheck import _axis, _emitters, build, rule_matrix

CIRCLE = {"name": "Mirror", "shape": "ellipse", "centre": [50, 40], "radius": [10, 10]}
FPS = 40


def sweep(f, start, end, frames, t0=0.0, tilt=0.4):
    """A pan sweep straight across at a steady speed: [(target, output)] per frame."""
    out = []
    for k in range(frames + 1):
        x = start + (end - start) * k / frames
        out.append(((x, tilt), f.step((x, tilt), t0 + k / FPS)))
    return out


# ------------------------------------------------------------------ settings


def test_parse_zones():
    z = parse_zone(CIRCLE, "z")
    assert z.shape == "ellipse" and z.centre == (0.5, 0.4) and z.radius == (0.1, 0.1) and not z.black
    r = parse_zone({"name": "Truss", "shape": "rect", "pan": [20, 30], "tilt": [0, 10], "black": True}, "z")
    assert r.pan == (0.2, 0.3) and r.black
    assert parse_zone(r.to_dict(), "z").to_dict() == r.to_dict()


@pytest.mark.parametrize("bad, msg", [
    ({"name": "x", "shape": "star"}, "rect or ellipse"),
    ({"shape": "rect", "pan": [1, 2], "tilt": [1, 2]}, "needs a name"),
    ({"name": "x", "shape": "rect", "pan": [30, 20], "tilt": [0, 10]}, "low below high"),
    ({"name": "x", "shape": "rect", "pan": [0, 120], "tilt": [0, 10]}, "0-100"),
    ({"name": "x", "shape": "ellipse", "centre": [50, 50], "radius": [0, 5]}, "0.5-100"),
    ({"name": "x", "shape": "rect", "centre": [5, 5], "pan": [0, 1], "tilt": [0, 1]}, "a rect has"),
    ({"name": "x", "shape": "rect", "pan": [0, 1], "tilt": [0, 1], "black": "yes"}, "true or false"),
])
def test_bad_zone(bad, msg):
    with pytest.raises(ConfigError, match=msg):
        parse_zone(bad, "z")


def test_rig_zones_only_on_moving_heads():
    p = parse_patch(PATCH)
    r = parse_rig({**RIG, "head_zones": {"mh_a": [CIRCLE]}}, p)
    assert r.head_zones["mh_a"][0].name == "Mirror"
    with pytest.raises(ConfigError, match="isn't a moving head"):
        parse_rig({**RIG, "head_zones": {"uk": [CIRCLE]}}, p)  # rule 7: U'Kings never move
    with pytest.raises(ConfigError, match="must differ"):
        parse_rig({**RIG, "head_zones": {"mh_a": [CIRCLE, CIRCLE]}}, p)
    with pytest.raises(ConfigError, match="zone_speed"):
        parse_rig({**RIG, "zone_speed": 1}, p)


# ------------------------------------------------------------------ geometry


def test_ellipse_polygon_is_outside_the_ellipse():
    z = parse_zone({"name": "e", "shape": "ellipse", "centre": [50, 50], "radius": [20, 8]}, "z")
    for i in range(len(z.poly)):
        a, b = z.poly[i], z.poly[(i + 1) % len(z.poly)]
        for k in range(11):  # every point of every edge
            p = (a[0] + (b[0] - a[0]) * k / 10, a[1] + (b[1] - a[1]) * k / 10)
            assert not z.inside(p, margin=0)


def test_segment_enters():
    sq = [(0.4, 0.4), (0.6, 0.4), (0.6, 0.6), (0.4, 0.6)]
    assert enters(sq, (0.2, 0.5), (0.8, 0.5)) == pytest.approx(1 / 3)
    assert enters(sq, (0.2, 0.3), (0.8, 0.3)) is None  # passes below
    assert enters(sq, (0.2, 0.4), (0.8, 0.4)) is None  # along the edge: touching isn't inside


# ------------------------------------------------------------------ the follower


def test_target_inside_holds_at_the_entry_side():
    z = parse_zone({"name": "r", "shape": "rect", "pan": [40, 60], "tilt": [30, 50]}, "z")
    f = ZoneFollower([z])
    f.step((0.2, 0.4), 0.0)
    pad = 0.55 / FPS  # the ring it goes round is half a frame's longest step outside the zone
    out = f.step((0.45, 0.4), 0.025)  # jumps in from the left
    assert out == pytest.approx((0.4 - pad, 0.4), abs=1e-3) and f.holding == "r"
    out = f.step((0.45, 0.4), 0.05)
    assert out == pytest.approx((0.4 - pad, 0.4), abs=1e-3)  # stays on the left edge while the target stays in


def test_pan_sweep_straight_through_a_circle_never_crosses_or_jumps():
    """The review's case: straight through the middle. Never inside, never faster than the zone speed."""
    z = parse_zone(CIRCLE, "z")
    f = ZoneFollower([z], speed=1.0)
    limit = 1.0 / FPS
    there = sweep(f, 0.2, 0.8, 200)  # 0.6 of the range in 5 s, through the centre
    back = sweep(f, 0.8, 0.2, 200, t0=5.0 + 1 / FPS)
    outs = [o for _, o in there + back]
    assert not any(z.inside(o) for o in outs)
    steps = [math.dist(a, b) for a, b in zip(outs, outs[1:])]
    assert max(steps) <= limit + 1e-9
    # no line between two frames passes through the zone either
    assert not any(enters(z.poly, a, b) is not None for a, b in zip(outs, outs[1:]))
    for run in (there, back):  # one side per pass: no flip at the centre
        sides = {math.copysign(1, o[1] - 0.4) for t, o in run if abs(o[1] - 0.4) > 1e-6}
        assert len(sides) == 1
    assert outs[-1] == pytest.approx((0.2, 0.4))  # caught up again at the end


def test_without_zones_a_sweep_is_untouched():
    f = ZoneFollower([])
    assert all(t == o for t, o in sweep(f, 0.2, 0.8, 50))


def test_away_from_the_zone_the_target_passes_straight_through():
    z = parse_zone(CIRCLE, "z")
    f = ZoneFollower([z])
    run = sweep(f, 0.2, 0.8, 100, tilt=0.8)  # well below the circle
    assert all(t == o for t, o in run)


def test_leaving_on_the_far_side_releases_and_catches_up():
    z = parse_zone({"name": "r", "shape": "rect", "pan": [40, 60], "tilt": [30, 50]}, "z")
    f = ZoneFollower([z], speed=1.0)
    f.step((0.2, 0.4), 0.0)
    f.step((0.5, 0.4), 0.025)  # in from the left
    outs = [f.step((0.7, 0.4), 0.025 + k / FPS) for k in range(1, 120)]  # target now out on the right
    assert not any(z.inside(o) for o in outs)
    assert outs[-1] == pytest.approx((0.7, 0.4)) and f.holding is None


def test_black_zone_lets_the_head_through_with_colour_off():
    z = parse_zone({**CIRCLE, "black": True}, "z")
    f = ZoneFollower([z])
    assert f.step((0.5, 0.4), 0.0) == (0.5, 0.4) and f.black((0.5, 0.4)) and not f.black((0.2, 0.4))


def test_two_zones_side_by_side():
    a = Zone("a", "rect", pan=(0.3, 0.4), tilt=(0.3, 0.5))
    b = Zone("b", "rect", pan=(0.6, 0.7), tilt=(0.3, 0.5))
    f = ZoneFollower([a, b])
    outs = [o for _, o in sweep(f, 0.1, 0.9, 300)] + [o for _, o in sweep(f, 0.9, 0.1, 300, t0=8.0)]
    assert not any(a.inside(o) or b.inside(o) for o in outs)


# ------------------------------------------------------------------ in the rule layer, both profiles


def zone_engine(profile, zone, look_pan):
    e, _, clock = build(profile, {"head_zones": {"mh_a": [zone]}})
    e.set_look(parse_look({"fixtures": {"mh_a": {"colour": [1, 0, 0], "pan": look_pan, "tilt": 0.4}}}, e.rig.patch))
    return e, clock


@pytest.mark.parametrize("profile", ["0.05_band", "generic"])
def test_rule_layer_holds_heads_out_of_zones(profile):
    e, clock = zone_engine(profile, CIRCLE, 0.2)
    z = e.rig.head_zones["mh_a"][0]
    for k in range(240):  # the look sweeps the head straight through, 40 fps
        x = 0.2 + 0.6 * k / 240
        e.set_look(parse_look({"fixtures": {"mh_a": {"colour": [1, 0, 0], "pan": x, "tilt": 0.4}}}, e.rig.patch))
        clock.advance(1 / FPS)
        e.tick()
        pan, tilt = _axis(e, "mh_a", "pan"), _axis(e, "mh_a", "tilt")
        assert not z.inside((pan, tilt), margin=2 / 65535), (k, pan, tilt)  # 16-bit output
        assert 0.1 - 1e-4 <= pan <= 0.9 + 1e-4 and tilt <= 0.75 + 1e-4  # the limits still apply


@pytest.mark.parametrize("profile", ["0.05_band", "generic"])
def test_black_zone_colour_off_dimmer_off(profile):
    e, clock = zone_engine(profile, {**CIRCLE, "black": True}, 0.5)
    clock.advance(1 / FPS)
    e.tick()
    assert not any(_emitters(e, "mh_a"))
    assert _axis(e, "mh_a", "pan") == pytest.approx(0.5, abs=1e-4)  # it went there, dark
    e.set_look(parse_look({"fixtures": {"mh_a": {"colour": [1, 0, 0], "pan": 0.2, "tilt": 0.4}}}, e.rig.patch))
    clock.advance(1 / FPS)
    e.tick()
    assert _emitters(e, "mh_a")[0] > 0  # out of the zone: lit again


def test_rule_matrix_with_zones():
    rig = {"head_zones": {"mh_a": [CIRCLE, {"name": "Eyes", "shape": "rect", "pan": [10, 30], "tilt": [60, 75], "black": True}]}}
    rule_matrix(lambda e, c: None, seconds=1.0, rig=rig)


def test_no_zones_output_unchanged():
    """A rig without zones renders exactly as before (the follower isn't even made)."""
    p = parse_patch(PATCH)
    e = Engine(parse_rig(RIG, p), [LogDriver()], parse_look({"fixtures": {"mh_a": {"pan": 0.5, "tilt": 0.5}}}, p),
               clock=Clock())
    e.tick()
    assert e.rules.zones == {} and _axis(e, "mh_a", "pan") == pytest.approx(0.5, abs=1e-4)


def test_points_inside_a_zone_are_flagged():
    p = parse_patch(PATCH)
    r = parse_rig({**RIG, "head_zones": {"mh_a": [CIRCLE]},
                   "positions": {"mirror": {"heads": {"mh_a": {"pan": 0.5, "tilt": 0.4}}}}}, p)
    probs = r.point_problems()
    assert any("inside exclusion zone Mirror" in x for x in probs)


# ------------------------------------------------------------------ saving, the API and Claude


@pytest.fixture
def show(tmp_path):
    import shutil
    from pathlib import Path

    root = tmp_path / "shows"
    shutil.copytree(Path(__file__).resolve().parents[1] / "shows", root, ignore=shutil.ignore_patterns(".backups"))
    return root


def test_store_zone_per_head_and_per_type(show):
    import yaml

    from dmx_suite.store import ShowStore, StoreError

    s = ShowStore(show)
    s.put_head_zone("full", "mh_a", CIRCLE)
    s.put_head_zone("full", "mh_a", {"name": "Truss", "shape": "rect", "pan": [0, 10], "tilt": [0, 5]}, scope="type")
    z = yaml.safe_load((show / "rigs" / "full.yaml").read_text())["head_zones"]
    assert [x["name"] for x in z["mh_a"]] == ["Mirror", "Truss"] and [x["name"] for x in z["mh_b"]] == ["Truss"]
    s.put_head_zone("full", "mh_a", {**CIRCLE, "name": "Glass"}, old_name="Mirror")  # rename
    z = yaml.safe_load((show / "rigs" / "full.yaml").read_text())["head_zones"]
    assert [x["name"] for x in z["mh_a"]] == ["Truss", "Glass"]
    s.delete_head_zone("full", "mh_a", "Truss", scope="type")
    z = yaml.safe_load((show / "rigs" / "full.yaml").read_text())["head_zones"]
    assert "mh_b" not in z and [x["name"] for x in z["mh_a"]] == ["Glass"]
    with pytest.raises(StoreError, match="no exclusion zone"):
        s.delete_head_zone("full", "mh_a", "nope")
    with pytest.raises(ConfigError, match="rect or ellipse"):
        s.put_head_zone("full", "mh_a", {"name": "x", "shape": "star"})
    with pytest.raises(ConfigError):
        s.put_head_zone("full", "uking_l", CIRCLE)  # colour only: no zones (rule 7)


def test_app_validate_scene_flags_a_zone(show):
    from dmx_suite.app import App
    from dmx_suite.showfiles import load_show
    from dmx_suite.store import ShowStore

    ShowStore(show).put_head_zone("full", "mh_a", {"name": "All", "shape": "rect", "pan": [0, 100], "tilt": [0, 100]})
    app = App(load_show(show), [LogDriver()])
    scene = {"name": "aim", "layers": [{"fixtures": ["mh_a"], "colour": "red", "position": {"pan": 0.5, "tilt": 0.5}}]}
    v = app.validate_scene(scene)
    assert v["ok"] and any(p.get("zone") == "All" and "rule 8" in p["message"] for p in v["problems"])
    app.engine.tick()
    assert app.zones_view()["zones"]["mh_a"][0]["name"] == "All"
    assert app.snapshot()["zones_held"].get("mh_a") == "All"  # held at the edge of a zone over everything


def test_claude_zone_tools_offline(show):
    import yaml

    from dmx_suite.claude_tools import DmxTools

    t = DmxTools(shows=show)
    t.save_head_zone("full", "mh_a", "{name: Mirror, shape: ellipse, centre: [50, 40], radius: [10, 10]}", scope="type")
    assert "Mirror" in t.list_head_zones() and "mh_b" in yaml.safe_load(t.list_head_zones())["full"]
    t.delete_head_zone("full", "mh_b", "Mirror")
    assert "mh_b" not in yaml.safe_load(t.list_head_zones())["full"]


def test_zone_api_and_gig_lock(show):
    from test_web import TOKEN, call

    from dmx_suite.app import App
    from dmx_suite.showfiles import load_show
    from dmx_suite.web.server import WebServer

    app = App(load_show(show), [LogDriver()])
    web = WebServer(app, "127.0.0.1", 0, token=TOKEN)
    web.start()
    try:
        url = f"http://127.0.0.1:{web.port}"
        assert call(f"{url}/api/store/zone", "POST", {"action": "put", "head": "mh_a", "zone": CIRCLE})[0] == 200
        status, body = call(f"{url}/api/zones")
        assert status == 200 and body["zones"]["mh_a"][0]["name"] == "Mirror"
        app.set_gig_lock(True)
        assert call(f"{url}/api/store/zone", "POST", {"action": "delete", "head": "mh_a", "name": "Mirror"})[0] != 200
    finally:
        app.set_gig_lock(False)
        web.stop()


def test_mcp_registers_zone_tools():
    pytest.importorskip("mcp")
    import asyncio
    from pathlib import Path

    from dmx_suite.claude_tools import DmxTools
    from dmx_suite.mcp_server import build_server

    server = build_server(DmxTools(shows=Path(__file__).resolve().parents[1] / "shows"))
    names = {x.name for x in asyncio.run(server.list_tools())}
    assert {"save_head_zone", "delete_head_zone", "list_head_zones"} <= names
