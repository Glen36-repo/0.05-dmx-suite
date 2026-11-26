"""Crossfades and show steps (repeats, holds, beats, fades), with the rules held throughout."""

import pytest

from dmx_suite.engine import Engine
from dmx_suite.fade import Crossfade, mix_looks
from dmx_suite.fixtures import ConfigError, parse_patch
from dmx_suite.look import FixtureLook, Look, parse_look
from dmx_suite.output import LogDriver
from dmx_suite.palettes import parse_palettes
from dmx_suite.rig import parse_rig
from dmx_suite.scenes import parse_scene
from dmx_suite.shows import ShowPlayer, parse_show
from dmx_suite.tempo import TempoClock

from conftest import LOOK, PATCH, RIG, Clock, View

PAL = {"colours": {"red": [1, 0, 0], "blue": [0, 0, 1], "white": [1, 1, 1]},
       "positions": {"left": {"pan": 0.2, "tilt": 0.5}, "right": {"pan": 0.8, "tilt": 0.5}}}


@pytest.fixture
def setup():
    patch = parse_patch(PATCH)
    pal = parse_palettes(PAL, patch)
    rig = parse_rig(RIG, patch)
    scenes = {
        "red": parse_scene({"layers": [{"fixtures": ["wash"], "colour": "red"}]}, patch, pal, "red"),
        "blue": parse_scene({"layers": [{"fixtures": ["wash"], "colour": "blue"}]}, patch, pal, "blue"),
        "chase": parse_scene({"layers": [{"fixtures": ["bars"], "effect": "colour_chase", "colours": ["red", "blue"],
                                          "period_s": 2}]}, patch, pal, "chase"),
        "left": parse_scene({"layers": [{"fixtures": ["mh_a"], "colour": "white", "position": "left"}]}, patch, pal, "left"),
        "right": parse_scene({"layers": [{"fixtures": ["mh_a"], "colour": "white", "position": "right"}]}, patch, pal, "right"),
    }
    return patch, pal, rig, scenes


def show(setup, sets):
    patch, pal, rig, scenes = setup
    return parse_show("s", {"sets": sets}, pal, scenes)


def player(setup, sets, set_name="a", now=0.0, tempo=None):
    patch, pal, rig, scenes = setup
    return ShowPlayer(show(setup, sets), set_name, rig, pal, scenes, tempo or TempoClock(now), now)


# ------------------------------------------------------------------ crossfades


def test_mix_halfway_and_ends():
    a = Look(fixtures={"w": FixtureLook(colour={"red": 1.0})})
    b = Look(fixtures={"w": FixtureLook(colour={"blue": 1.0})})
    assert mix_looks(a, b, 0) is a and mix_looks(a, b, 1) is b
    c = mix_looks(a, b, 0.5).fixtures["w"].colour
    assert c == {"red": 0.5, "blue": 0.5}


def test_heads_move_dark_in_a_fade():
    a = Look(fixtures={"h": FixtureLook(colour={"red": 1.0}, pan=0.2, tilt=0.5, gobo=10)})
    b = Look(fixtures={"h": FixtureLook(colour={"red": 1.0}, pan=0.8, tilt=0.5, gobo=40)})
    early, mid, late = (mix_looks(a, b, f).fixtures["h"] for f in (0.25, 0.5, 0.75))
    assert (early.pan, early.colour["red"], early.gobo) == (0.2, 0.5, 10)  # dimming where it was
    assert mid.colour.get("red", 0) == 0 and mid.pan == 0.8  # dark as it moves
    assert (late.pan, late.colour["red"], late.gobo) == (0.8, 0.5, 40)  # fading in at the new spot


def test_pixels_fade_against_a_plain_colour():
    a = Look(fixtures={"b": FixtureLook(pixels=[{"red": 1.0}, {"red": 0.0}])})
    b = Look(fixtures={"b": FixtureLook(colour={"blue": 1.0})})
    px = mix_looks(a, b, 0.5).fixtures["b"].pixels
    assert px == [{"red": 0.5, "blue": 0.5}, {"red": 0.0, "blue": 0.5}]


def test_crossfade_source_ends_on_the_new_look():
    old = lambda now: Look(fixtures={"w": FixtureLook(colour={"red": 1.0})})  # noqa: E731
    new = lambda now: Look(fixtures={"w": FixtureLook(colour={"blue": 1.0})})  # noqa: E731
    xf = Crossfade(old, new, 10.0, 2.0)
    assert xf(11.0).fixtures["w"].colour == {"red": 0.5, "blue": 0.5}
    assert xf(12.0).fixtures["w"].colour == {"blue": 1.0} and xf.done(12.0)


@pytest.mark.parametrize("profile", ["generic", "0.05_band"])
def test_engine_fade_keeps_the_rules(setup, profile):
    patch, pal, _, scenes = setup
    rig = parse_rig({**RIG, "profile": profile}, patch)
    clock = Clock()
    e = Engine(rig, [LogDriver()], parse_look(LOOK, patch), clock=clock)
    view = View(e)
    e.haze.set_mode("manual", clock())
    from dmx_suite.scenes import ScenePlayer

    e.set_source(ScenePlayer(scenes["red"], rig, clock()), scenes["red"])
    e.set_source(ScenePlayer(scenes["blue"], rig, clock()), scenes["blue"], fade_s=2.0)
    clock.advance(1.0)
    e.tick()
    assert view("wash", "red") == 128 and view("wash", "blue") == 128  # halfway, through colour
    assert view("wash", "dimmer") == 255  # rule 1: a fade never touches the dimmer
    assert view.emitters("bar_1") == [0] * 6  # rule 4: in neither look, so fully off
    assert view("smoke", "haze") == 128  # rule 5: haze untouched
    clock.advance(1.5)
    e.tick()
    assert view("wash", "red") == 0 and view("wash", "blue") == 255
    assert not isinstance(e.source, Crossfade)  # the fade is dropped once done
    if profile == "0.05_band":
        e.set_master(False)
        assert view.emitters("wash") == [0, 0, 0, 0]  # MASTER still owns on/off


# ------------------------------------------------------------------ steps


def test_repeats_hold_and_order(setup):
    p = player(setup, {"a": {"steps": [{"scene": "chase", "repeats": 2}, {"scene": "red", "hold_s": 3}]}})
    assert p.scene.name == "chase" and p.repeat(0.0) == (1, 2)
    p(3.9)
    assert p.repeat(3.9) == (2, 2) and p.scene.name == "chase"  # two 2-second cycles
    p(4.0)
    assert p.scene.name == "red" and p.time_left(4.0) == 3.0
    p(7.0)
    assert p.scene.name == "chase"  # loops round


def test_hold_bars_follow_the_tempo(setup):
    tempo = TempoClock(0.0)
    tempo.set_bpm(60, 0.0)  # half the 120 BPM reference: a bar takes 4 s
    p = player(setup, {"a": {"steps": [{"scene": "red", "hold_bars": 1}, {"scene": "blue", "hold_beats": 2}]}}, tempo=tempo)
    p(3.9)
    assert p.scene.name == "red" and p.time_left(3.9) == pytest.approx(0.1)
    p(4.0)
    assert p.scene.name == "blue"
    p(6.0)
    assert p.scene.name == "red"


def test_fades_between_steps(setup):
    p = player(setup, {"a": {"fade_s": 1, "steps": [{"scene": "red", "hold_s": 2}, {"scene": "blue", "hold_s": 2, "fade_s": 0}]}})
    p(2.0)  # into blue: that step says no fade
    c = p(2.0).fixtures["wash"].colour
    assert (c.get("red"), c.get("blue")) == (0, 1)
    p(4.0)  # back to red with the set's 1 s fade
    c = p(4.5).fixtures["wash"].colour
    assert c.get("red") == pytest.approx(0.5) and c.get("blue") == pytest.approx(0.5)
    assert p(5.0).fixtures["wash"].colour.get("red") == 1


def test_loop_false_stays_on_the_last_step(setup):
    p = player(setup, {"a": {"loop": False, "steps": [{"scene": "red", "hold_s": 1}, {"scene": "blue", "hold_s": 1}]}})
    p(1.0)
    p(50.0)
    assert p.scene.name == "blue"


def test_jump_to_a_step(setup):
    p = player(setup, {"a": {"steps": ["red", "blue", "chase"]}})
    p.go(2, 0.5)
    assert p.scene.name == "chase" and p.index == 2
    with pytest.raises(ConfigError):
        p.go(9, 0.5)


def test_v1_sets_still_play_as_before(setup):
    p = player(setup, {"a": {"step_s": 5, "scenes": ["red", "blue"]}})
    assert [s.hold_s for s in p.set.steps] == [5, 5]
    p(5.0)
    assert p.scene.name == "blue"


@pytest.mark.parametrize("sets, msg", [
    ({"a": {"steps": [{"scene": "nope"}]}}, "unknown scene"),
    ({"a": {"steps": [{"scene": "red", "repeats": 2}]}}, "no moving effect"),
    ({"a": {"steps": [{"scene": "chase", "repeats": 0}]}}, "1 or more"),
    ({"a": {"steps": [{"scene": "chase", "repeats": 2, "hold_s": 3}]}}, "one of repeats"),
    ({"a": {"steps": [{"scene": "red", "colour": "x"}]}}, "unknown keys"),
    ({"a": {"steps": ["red"], "scenes": ["blue"]}}, "one of steps"),
    ({"a": {"steps": ["red"], "fade_s": -1}}, "fade_s"),
])
def test_step_validation(setup, sets, msg):
    with pytest.raises(ConfigError, match=msg):
        show(setup, sets)


def test_heads_move_dark_between_steps(setup):
    p = player(setup, {"a": {"fade_s": 2, "steps": [{"scene": "left", "hold_s": 1}, {"scene": "right", "hold_s": 9}]}})
    p(1.0)
    mid = p(2.0).fixtures["mh_a"]
    assert mid.pan == pytest.approx(0.8) and not any(mid.colour.values())
