"""Effect registry, layer blending, spread controls, spatial (matrix) mapping, the new effects,
and every effect against the rules under both shipped profiles."""

import json
import math

import pytest

from dmx_suite import effects
from dmx_suite.effects.base import Unit, hue, place_units, wave
from dmx_suite.engine import Engine
from dmx_suite.fixtures import parse_patch
from dmx_suite.look import LookError, parse_look
from dmx_suite.output import LogDriver
from dmx_suite.palettes import parse_palettes
from dmx_suite.rig import parse_rig
from dmx_suite.scenes import ScenePlayer, parse_scene

from conftest import LOOK, PATCH, RIG, Clock, View

PAL = {
    "colours": {"blue": [0, 0, 1], "red": [1, 0, 0], "white": [1, 1, 1]},
    "positions": {"left": {"pan": 0.2, "tilt": 0.5}, "centre": {"pan": 0.5, "tilt": 0.5}},
}

# a layout with known places: bars side by side, wash under bar_1, heads above
LAYOUT = {
    "mh_a": {"x": 4, "y": 1}, "uk": {"x": 12, "y": 1},
    "bar_1": {"x": 4.5, "y": 4}, "bar_2": {"x": 14.5, "y": 4},
    "wash": {"x": 1, "y": 8}, "kick": {"x": 20, "y": 8}, "smoke": {"x": 24, "y": 8},
}


@pytest.fixture
def patch():
    return parse_patch(PATCH)


@pytest.fixture
def pal(patch):
    return parse_palettes(PAL, patch)


@pytest.fixture
def rig(patch):
    return parse_rig({**RIG, "profile": "generic", "layout": LAYOUT}, patch)


def scene(patch, pal, *layers, **kw):
    return parse_scene({"layers": list(layers), **kw}, patch, pal, "test")


def play(sc, rig, t):
    return ScenePlayer(sc, rig, 0.0)(t)


# ------------------------------------------------------------------ registry


def test_registry_has_old_and_new_effects():
    names = set(effects.REGISTRY)
    assert {"colour_chase", "pixel_chase", "flash", "sweep", "random_move"} <= names  # v1
    assert {"rainbow", "sparkle", "wave", "strobe", "circle", "figure8"} <= names
    assert {"linear_wave", "radial", "gradient", "bars", "noise"} <= names  # matrix
    for e in effects.REGISTRY.values():
        assert e.label and e.help and e.params
    json.dumps(effects.schemas())  # what the scene builder gets
    assert "linear_wave" in effects.guide()


def test_schema_describes_settings():
    wave_schema = next(s for s in effects.schemas() if s["name"] == "wave")
    keys = {p["key"]: p for p in wave_schema["params"]}
    assert keys["waveform"]["choices"] == ["sine", "square", "saw", "triangle", "pulse"]
    assert keys["period_s"]["lo"] == 0.05 and keys["period_s"]["default"] == 2.0
    assert {"mapping", "direction", "angle", "groups_of"} <= set(keys)


# ------------------------------------------------------------------ layers: static + effect, blend, level, mute, length


def test_static_settings_alongside_an_effect(patch, pal, rig):
    sc = scene(patch, pal, {"fixtures": ["mh_a"], "effect": "sweep", "from": "left", "to": "centre", "colour": "red"})
    fl = play(sc, rig, 1.0).fixtures["mh_a"]
    assert fl.colour == {"red": 1, "green": 0, "blue": 0} and fl.pan is not None


@pytest.mark.parametrize("blend, level, expect", [
    ("replace", 1.0, {"red": 1.0, "blue": 0.0}),
    ("replace", 0.5, {"red": 0.5, "blue": 0.5}),
    ("max", 0.5, {"red": 0.5, "blue": 1.0}),
    ("add", 1.0, {"red": 1.0, "blue": 1.0}),
])
def test_blend_and_level(patch, pal, rig, blend, level, expect):
    sc = scene(patch, pal, {"fixtures": ["wash"], "colour": "blue"},
               {"fixtures": ["wash"], "colour": "red", "blend": blend, "level": level})
    c = play(sc, rig, 0).fixtures["wash"].colour
    assert {k: round(c.get(k, 0), 3) for k in ("red", "blue")} == expect


def test_blend_onto_pixels(patch, pal, rig):
    sc = scene(patch, pal, {"fixtures": ["bar_1"], "effect": "pixel_chase", "colour": "blue", "width": 1, "period_s": 2},
               {"fixtures": ["bar_1"], "colour": "red", "blend": "max", "level": 1})
    px = play(sc, rig, 0).fixtures["bar_1"].pixels
    assert px[0]["blue"] == 1 and all(p["red"] == 1 for p in px)  # the chase still there under the red


def test_mute_skips_a_layer(patch, pal, rig):
    sc = scene(patch, pal, {"fixtures": ["wash"], "colour": "blue"}, {"fixtures": ["wash"], "colour": "red", "mute": True})
    assert play(sc, rig, 0).fixtures["wash"].colour["blue"] == 1


def test_scene_length(patch, pal):
    chase = {"fixtures": ["bars"], "effect": "colour_chase", "colours": ["red", "blue"], "period_s": 3}
    flash = {"fixtures": ["wash"], "effect": "flash", "rate_hz": 0.25}
    assert scene(patch, pal, chase, flash).length == 4.0  # longest cycle
    assert scene(patch, pal, chase, length_s=8).length == 8.0
    assert scene(patch, pal, {"fixtures": ["wash"], "colour": "red"}).length is None
    with pytest.raises(LookError, match="length_s"):
        scene(patch, pal, chase, length_s=0)


# ------------------------------------------------------------------ spread: direction, groups, waveforms


def units(n):
    return [Unit(f"f{i}", None, i) for i in range(n)]


@pytest.mark.parametrize("direction, expect", [
    ("forward", [0, 0.25, 0.5, 0.75]),
    ("reverse", [0.75, 0.5, 0.25, 0]),
    ("centre_out", [0.75, 0.25, 0.25, 0.75]),
    ("out_centre", [0.25, 0.75, 0.75, 0.25]),
])
def test_order_directions(direction, expect):
    us = units(4)
    place_units(us, {"direction": direction}, "x")
    assert [round(u.u, 3) for u in us] == expect


def test_random_direction_is_fixed_per_scene():
    a, b, c = units(6), units(6), units(6)
    place_units(a, {"direction": "random"}, "scene-1")
    place_units(b, {"direction": "random"}, "scene-1")
    place_units(c, {"direction": "random"}, "scene-2")
    assert [u.u for u in a] == [u.u for u in b] != [u.u for u in c]
    assert sorted(u.u for u in a) == [i / 6 for i in range(6)]  # each light its own step


def test_groups_of_moves_blocks_together():
    us = units(6)
    place_units(us, {"groups_of": 2}, "x")
    assert [round(u.u, 3) for u in us] == [0, 0, 0.333, 0.333, 0.667, 0.667]


def test_spatial_angle_and_centre():
    us = [Unit("a", None, 0, x=0, y=0), Unit("b", None, 1, x=1, y=0), Unit("c", None, 2, x=0, y=1)]
    place_units(us, {"mapping": "spatial", "direction": "angle", "angle": 0}, "x")
    assert [u.u for u in us] == [0, 1, 0]  # left to right
    place_units(us, {"mapping": "spatial", "direction": "angle", "angle": 90}, "x")
    assert [u.u for u in us] == pytest.approx([0, 0, 1])  # top to bottom
    place_units(us, {"mapping": "spatial", "direction": "centre_out"}, "x")
    assert us[0].u == us[1].u == us[2].u == 1.0  # all corners equally far from the middle


@pytest.mark.parametrize("form, phase, level", [
    ("sine", 0, 0), ("sine", 0.5, 1), ("square", 0.2, 1), ("square", 0.7, 0),
    ("saw", 0.25, 0.25), ("triangle", 0.25, 0.5), ("pulse", 0, 1), ("pulse", 0.6, 0),
])
def test_waveforms(form, phase, level):
    assert wave(form, phase, 0.5) == pytest.approx(level)


def test_hue_wheel():
    assert hue(0) == {"red": 1, "green": 0, "blue": 0}
    assert hue(1 / 3)["green"] == 1 and hue(2 / 3)["blue"] == 1


def test_direction_and_groups_change_old_effects_too(patch, pal, rig):
    base = {"fixtures": ["bar_1", "bar_2", "wash"], "effect": "colour_chase", "colours": ["red", "blue"],
            "period_s": 2, "spread": 1}
    fwd = play(scene(patch, pal, base), rig, 0.1)
    rev = play(scene(patch, pal, {**base, "direction": "reverse"}), rig, 0.1)
    assert fwd.fixtures["bar_1"].colour != rev.fixtures["bar_1"].colour
    assert fwd.fixtures["bar_1"].colour == rev.fixtures["wash"].colour  # ends swapped


# ------------------------------------------------------------------ spatial: golden frames on a known layout


def test_linear_wave_crosses_the_layout_left_to_right(patch, pal, rig):
    def frame(order, t):
        sc = scene(patch, pal, {"fixtures": order, "effect": "linear_wave", "colour": "white",
                                "waveform": "square", "width": 0.5, "period_s": 1, "count": 0.5})
        fx = play(sc, rig, t).fixtures
        return [p.get("red", 0) for f in ("bar_1", "bar_2") for p in fx[f].pixels]

    assert frame(["bar_1", "bar_2"], 0.3) == frame(["bar_2", "bar_1"], 0.3)  # one picture, whatever the order
    assert frame(["bar_2", "bar_1"], 0.3) == [1, 1, 0, 0]  # the left bar (bar_1) lights first
    assert frame(["bar_2", "bar_1"], 0.6) == [0, 0, 1, 1]  # then the wave reaches the right


def test_linear_wave_golden(patch, pal, rig):
    """Exact pixel values for a wave at 30° across both bars, at three times."""
    sc = scene(patch, pal, {"fixtures": ["bars"], "effect": "linear_wave", "colour": "white", "angle": 30,
                            "period_s": 2, "count": 1.5})
    got = []
    for t in (0.0, 0.4, 1.3):
        fx = play(sc, rig, t).fixtures
        got.append([round(p["red"], 3) for f in ("bar_1", "bar_2") for p in fx[f].pixels])
    # each bar has 2 pixels in the test patch: four points along a line, u = 0, 1/9, 8/9, 1 (projection)
    xs = [4.0, 5.0, 14.0, 15.0]
    us = [(x - 4) / 11 for x in xs]
    expect = [[round(0.5 - 0.5 * math.cos(2 * math.pi * (t / 2 - 1.5 * u)), 3) for u in us] for t in (0.0, 0.4, 1.3)]
    assert got == expect


def test_radial_spreads_from_the_middle(patch, pal, rig):
    sc = scene(patch, pal, {"fixtures": ["mh_a", "uk", "wash", "kick"], "effect": "radial", "colour": "white",
                            "waveform": "square", "width": 0.3, "period_s": 1, "count": 1})
    runner = ScenePlayer(sc, rig, 0.0)
    us = {un.fid: round(un.u, 3) for un in runner._units_for(0, True)}
    assert us["mh_a"] < us["kick"] and us["wash"] == 1.0  # wash is the furthest from the middle
    inward = ScenePlayer(scene(patch, pal, {"fixtures": ["mh_a", "uk", "wash", "kick"], "effect": "radial",
                                            "colour": "white", "inward": True}), rig, 0.0)
    assert {un.fid: round(un.u, 3) for un in inward._units_for(0, True)}["wash"] == 0.0


def test_pixels_sit_where_the_layout_puts_them(patch, pal):
    rig = parse_rig({**RIG, "layout": {**LAYOUT, "bar_1": {"x": 4.5, "y": 4, "rot": 90}}}, patch)  # bar_1 stood upright
    sc = scene(patch, pal, {"fixtures": ["bar_1"], "effect": "linear_wave", "colour": "white", "angle": 90})
    us = ScenePlayer(sc, rig, 0.0)._units_for(0, True)
    assert [(round(u.x, 3), round(u.y, 3)) for u in us] == [(0, 0), (0, 1)]  # one above the other


def test_smaller_rig_drops_lights_from_the_picture(patch, pal):
    small = parse_rig({**RIG, "fixtures": ["bar_1", "kick"], "layout": LAYOUT}, patch)
    sc = scene(patch, pal, {"fixtures": ["all"], "effect": "noise", "colours": ["red", "blue"]},
               {"fixtures": ["all"], "effect": "gradient", "colours": ["red", "blue"], "blend": "max"})
    look = play(sc, small, 2.0)
    assert set(look.fixtures) == {"bar_1", "kick"}


# ------------------------------------------------------------------ every effect against the rules, both profiles


def minimal(e):
    d = {"fixtures": ["mh_a"] if e.movement else ["all"], "effect": e.name}
    for prm in e.params:
        if prm.default is None and prm.kind == "colours":
            d[prm.key] = ["red", "blue"]
        elif prm.default is None and prm.kind == "position":
            d[prm.key] = "left" if prm.key != "to" else "centre"
    if not e.movement:
        d["fixtures"] = ["bars", "wash", "uk", "kick"]
    return d


@pytest.mark.parametrize("profile", ["generic", "0.05_band"])
@pytest.mark.parametrize("name", sorted(effects.REGISTRY))
def test_every_effect_obeys_the_rules(patch, pal, profile, name):
    e = effects.REGISTRY[name]
    r = parse_rig({**RIG, "profile": profile, "layout": LAYOUT}, patch)
    sc = scene(patch, pal, minimal(e))
    clock = Clock()
    eng = Engine(r, [LogDriver()], parse_look(LOOK, patch), clock=clock)
    eng.set_scene(sc)
    view = View(eng)
    eng.haze.set_mode("manual", clock())
    for _ in range(40):
        clock.advance(0.137)
        eng.tick()
        assert view("smoke", "haze") == round(0.5 * 255)  # rule 5: haze only from the haze controls
        if e.movement:
            pan = (view("mh_a", "pan") << 8 | view("mh_a", "pan_fine")) / 65535
            tilt = (view("mh_a", "tilt") << 8 | view("mh_a", "tilt_fine")) / 65535
            assert 0.10 - 1e-3 <= pan <= 0.90 + 1e-3 and tilt <= 0.75 + 1e-3  # rule 8: head limits
            assert view.emitters("bar_1") == [0] * 6  # rule 4: not in the scene = fully off
        else:
            assert view("uk", "pan") == round(0.25 * 255)  # rule 7: colour-only head stays home
            assert view.emitters("mh_a")[:1] == [0]  # rule 4: mh_a isn't in this layer: dimmer off


def test_movement_effects_refuse_colour_only_heads(patch, pal):
    for name in ("circle", "figure8", "sweep", "random_move"):
        d = minimal(effects.REGISTRY[name])
        d["fixtures"] = ["heads"]  # mh_a and the colour-only uk
        with pytest.raises(LookError, match="rule 7"):
            scene(patch, pal, d)


def test_circle_spreads_heads_round_the_circle(patch, pal):
    p2 = parse_patch({**PATCH, "fixtures": PATCH["fixtures"] + [{"id": "mh_b", "type": "head", "address": 80}]})
    r = parse_rig({**RIG, "layout": LAYOUT}, p2)
    sc = parse_scene({"layers": [{"fixtures": ["mh_a", "mh_b"], "effect": "circle", "centre": "centre", "size": 0.2,
                                  "spread": 1}]}, p2, parse_palettes(PAL, p2), "c")
    look = ScenePlayer(sc, r, 0.0)(0.0)
    a, b = look.fixtures["mh_a"], look.fixtures["mh_b"]
    assert (a.pan, a.tilt) == pytest.approx((0.7, 0.5)) and (b.pan, b.tilt) == pytest.approx((0.3, 0.5))  # opposite sides
