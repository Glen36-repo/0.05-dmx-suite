"""Step scenes (v3.2): hand-programmed steps with step and fade times, tracking, playback modes,
heads moving dark or gliding lit inside the head limits, live speed and fade, named-input and
pedal advance, capture; and every rule on every frame, mid-fade too."""

import shutil
from pathlib import Path

import pytest

from dmx_suite.fixtures import parse_patch
from dmx_suite.look import LookError
from dmx_suite.midi.inputs import FakeMidiIn
from dmx_suite.midi.map import parse_map
from dmx_suite.midi.monitor import MidiMonitor
from dmx_suite.midi.named import parse_inputs
from dmx_suite.midi.router import MidiRouter
from dmx_suite.palettes import Palettes
from dmx_suite.rig import parse_rig
from dmx_suite.scenes import ScenePlayer, parse_scene
from dmx_suite.showfiles import load_show
from dmx_suite.steps import glide_path, path_ok

from conftest import PATCH, RIG
from rulecheck import rule_matrix

SHOWS = Path(__file__).resolve().parents[1] / "shows"
POINTS = {"a": {"heads": {"mh_a": {"pan": 0.2, "tilt": 0.2}}}, "b": {"heads": {"mh_a": {"pan": 0.8, "tilt": 0.6}}}}


def setup(profile="0.05_band", **rig):
    patch = parse_patch(PATCH)
    r = parse_rig({**RIG, "profile": profile, "positions": POINTS, **rig}, patch)
    return patch, r, Palettes().with_points(r.points)


def scene(data, profile="0.05_band", **rig):
    patch, r, pal = setup(profile, **rig)
    return parse_scene({"name": "s", "type": "steps", **data}, patch, pal, "s"), r


THREE = {"step_s": 2, "fade_s": 0, "steps": [
    {"name": "red", "set": {"bars": {"colour": "#ff0000"}}},
    {"name": "green", "set": {"bars": {"colour": "#00ff00"}}},
    {"name": "blue", "set": {"bars": {"colour": "#0000ff"}}, "step_s": 1},
]}


def colour(look, fid="bar_1"):
    c = look.fixtures[fid].colour
    return tuple(round(c.get(k, 0.0), 3) for k in ("red", "green", "blue"))


# ------------------------------------------------------------------ parsing


def test_parse_defaults_and_overrides():
    sc, _ = scene({**THREE, "playback": "bounce", "advance": {"input": "snare"}, "move": "lit", "dark_s": 0.5})
    s = sc.steps
    assert [st.name for st in s.steps] == ["red", "green", "blue"]
    got = (s.step_s, s.fade_s, s.playback, s.advance, s.advance_input, s.move, s.dark_s)
    assert got == (2, 0, "bounce", "input", "snare", "lit", 0.5)
    assert s.hold(2, 0.5) == 1 and s.hold(0, 0.5) == 2
    assert sc.length is None  # input advance: no fixed length


@pytest.mark.parametrize("bad, msg", [
    ({"steps": []}, "needs steps"),
    ({"steps": [{"set": {"bars": {"dimmer": 1}}}]}, "dimmer"),
    ({"steps": [{"set": {"smoke": {"haze": 1}}}]}, "haze"),
    ({"steps": [{"set": {"uk": {"position": "a"}}}]}, "colour only"),
    ({"steps": [{"set": {"bars": {"colour": "#ff0000"}}}], "playback": "shuffle"}, "playback"),
    ({"steps": [{"set": {"bars": {"colour": "#ff0000"}}}], "advance": "drum"}, "advance"),
    ({"steps": [{"set": {"bars": {"colour": "#ff0000"}}, "move": "fly"}]}, "dark or lit"),
    ({"steps": [{"set": {"bars": {"colour": "#ff0000"}}, "hold": 3}]}, "unknown keys"),
    ({"steps": [{"set": {"bars": {}}}]}, "what to set"),
    ({"steps": [{"set": {"mh_a": {"position": "nowhere"}}}]}, "unknown position"),
])
def test_bad_step_scenes(bad, msg):
    with pytest.raises(LookError, match=msg):
        scene(bad)


def test_intensity_only_under_generic():
    sc, _ = scene({"steps": [{"set": {"wash": {"colour": "white", "intensity": 0.5}}}]})
    assert sc.uses_intensity  # refused by the 0.05 band rigs at validation (rule 1)


# ------------------------------------------------------------------ timing


def test_step_times_hold_to_the_frame():
    sc, r = scene(THREE)
    p = ScenePlayer(sc, r, 0.0)
    for t, want in [(0, 0), (1.975, 0), (2.0, 1), (3.975, 1), (4.0, 2), (4.975, 2), (5.0, 0)]:
        p(t)
        assert p.runner.index == want, t


def test_fade_into_a_step():
    sc, r = scene({**THREE, "fade_s": 1})
    p = ScenePlayer(sc, r, 0.0)
    p(0)
    assert colour(p(2.0)) == (1.0, 0.0, 0.0)
    assert colour(p(2.5)) == (0.5, 0.5, 0.0)
    assert colour(p(3.0)) == (0.0, 1.0, 0.0)


def test_per_step_fade_override():
    data = {**THREE, "fade_s": 1}
    data["steps"] = [dict(s) for s in THREE["steps"]]
    data["steps"][1]["fade_s"] = 0
    sc, r = scene(data)
    p = ScenePlayer(sc, r, 0.0)
    p(0)
    assert colour(p(2.0)) == (0.0, 1.0, 0.0)  # cut


def test_speed_and_fade_faders_scale_steps():
    sc, r = scene({**THREE, "fade_s": 1})
    p = ScenePlayer(sc, r, 0.0)
    p(0)
    p.runner.set_speed(2.0)  # twice as fast: 2 s steps last 1 s
    p(0.9)
    assert p.runner.index == 0
    p(1.0)
    assert p.runner.index == 1
    p.runner.set_fade_scale(0.0)  # fades off
    p(1.0)
    p.runner.go(2)
    assert colour(p(1.0)) == (0.0, 0.0, 1.0)


def test_beats_follow_the_tempo():
    from dmx_suite.tempo import TempoClock

    sc, r = scene({"step_beats": 4, "steps": THREE["steps"][:2]})
    tempo = TempoClock(0.0, r.tempo)
    tempo.set_bpm(120, 0.0)  # 4 beats = 2 s
    p = ScenePlayer(sc, r, 0.0, tempo.eff)
    p(0)
    p(1.99)
    assert p.runner.index == 0
    p(2.0)
    assert p.runner.index == 1
    tempo.set_bpm(60, 2.0)  # now 4 s
    p(5.9)
    assert p.runner.index == 1
    p(6.0)
    assert p.runner.index == 0


@pytest.mark.parametrize("playback, order", [
    ("loop", [0, 1, 2, 0, 1, 2]),
    ("once", [0, 1, 2, 2, 2, 2]),
    ("bounce", [0, 1, 2, 1, 0, 1]),
])
def test_playback(playback, order):
    data = {**THREE, "playback": playback}
    data["steps"] = [dict(s, step_s=1) for s in THREE["steps"]]
    sc, r = scene(data)
    p = ScenePlayer(sc, r, 0.0)
    got = []
    for t in range(6):
        p(float(t))
        got.append(p.runner.index)
    assert got == order


def test_tracking_keeps_what_a_step_doesnt_change():
    sc, r = scene({"step_s": 1, "steps": [
        {"set": {"bars": {"colour": "#ff0000"}, "wash": {"colour": "#0000ff"}}},
        {"set": {"bars": {"colour": "#00ff00"}}},
    ]})
    p = ScenePlayer(sc, r, 0.0)
    p(0)
    look = p(1.0)
    assert colour(look) == (0.0, 1.0, 0.0) and colour(look, "wash") == (0.0, 0.0, 1.0)


def test_manual_advance_waits():
    sc, r = scene({**THREE, "advance": "manual"})
    p = ScenePlayer(sc, r, 0.0)
    p(0)
    p(100)
    assert p.runner.index == 0
    p.runner.next()
    p(100)
    assert p.runner.index == 1
    p.runner.back()
    p(100)
    assert p.runner.index == 0


# ------------------------------------------------------------------ heads: dark or lit


MOVE = {"step_s": 4, "fade_s": 2, "steps": [
    {"set": {"mh_a": {"colour": "white", "position": "a"}}},
    {"set": {"mh_a": {"position": "b"}}},
]}


def head(look):
    fl = look.fixtures["mh_a"]
    return fl.pan, fl.tilt, round(max(fl.colour.values(), default=0.0), 3), fl.speed


def test_move_dark_by_default_under_the_band_profile():
    sc, r = scene(MOVE)
    p = ScenePlayer(sc, r, 0.0)
    p(0)
    p(4.0)
    pan, tilt, lvl, _ = head(p(4.5))  # first half: dimming where it was
    assert (pan, tilt) == (0.2, 0.2) and lvl == 0.5
    pan, tilt, lvl, _ = head(p(5.0))  # halfway: dark, moved
    assert (pan, tilt) == (0.8, 0.6) and lvl == 0.0
    pan, tilt, lvl, _ = head(p(6.0))
    assert (pan, tilt, lvl) == (0.8, 0.6, 1.0)


def test_glide_lit_by_default_under_generic():
    sc, r = scene(MOVE, profile="generic")
    p = ScenePlayer(sc, r, 0.0)
    p(0)
    p(4.0)
    pans = []
    for t in (4.25, 4.5, 5.0, 5.5, 5.75):
        pan, tilt, lvl, speed = head(p(t))
        assert lvl == 1.0 and speed == 1.0  # lit all the way; motor at fastest
        pans.append(pan)
    assert pans == sorted(pans) and 0.2 < pans[0] < pans[-1] < 0.8  # smooth, in between
    assert head(p(6.0))[:2] == (0.8, 0.6)


def test_move_per_step_overrides_profile():
    data = {**MOVE, "steps": [MOVE["steps"][0], {**MOVE["steps"][1], "move": "lit"}]}
    sc, r = scene(data)  # band profile, but this step glides
    p = ScenePlayer(sc, r, 0.0)
    p(0)
    p(4.0)
    assert head(p(5.0))[2] == 1.0


def test_dark_move_on_a_cut_still_gets_dark_time():
    data = {**MOVE, "fade_s": 0, "dark_s": 0.4}
    sc, r = scene(data)
    p = ScenePlayer(sc, r, 0.0)
    p(0)
    p(4.0)
    assert head(p(4.05))[2] < 1  # dimming where it was
    assert head(p(4.2))[:3] == (0.8, 0.6, 0.0)  # moved, dark
    assert head(p(4.4))[2] == 1.0


def test_glide_stays_inside_head_limits():
    _, r, _ = setup("generic")  # mh_a pan 10-90 %, tilt 0-75 %
    assert path_ok(r, "mh_a", (0.2, 0.2), (0.8, 0.6))
    assert not path_ok(r, "mh_a", (0.2, 0.2), (0.5, 0.95))  # a point from before the limits changed
    for i in range(11):
        pan, tilt = glide_path(r, "mh_a", (0.05, 0.2), (0.5, 0.95), i / 10)
        assert 0.1 <= pan <= 0.9 and 0.0 <= tilt <= 0.75  # rerouted along the edge


def test_glide_uses_fine_channels(engine, view):
    """16-bit pan mid-glide: the fine channel moves too, so slow glides are smooth."""
    _, r, pal = setup("generic")
    sc = parse_scene({"name": "g", "type": "steps", "step_s": 10, "fade_s": 10, "move": "lit", "steps": MOVE["steps"]},
                     r.patch, pal, "g")
    engine.rig.profile = r.profile
    clock = engine.clock
    engine.set_source(ScenePlayer(sc, engine.rig, clock()))
    engine.tick()
    clock.advance(10)
    engine.tick()
    fines = set()
    for _ in range(20):
        clock.advance(0.05)
        engine.tick()
        fines.add(view("mh_a", "pan_fine"))
    assert len(fines) > 5


def test_rules_hold_through_every_step_and_fade():
    data = {"step_s": 0.5, "fade_s": 0.4, "steps": [
        {"set": {"mh_a": {"colour": "white", "position": "a", "gobo": 30}, "bars": {"colour": "#ff0000"}}},
        {"set": {"mh_a": {"position": "b", "gobo": 60}, "bars": {"colour": "#0000ff"}}, "move": "lit"},
        {"set": {"mh_a": {"position": "a"}, "wash": {"colour": "white"}}},
    ], "layers": [{"fixtures": ["bars"], "effect": "sparkle", "colour": "white", "level": 0.4, "blend": "max"}]}

    def play(e, clock):
        r = parse_rig({**RIG, "positions": POINTS}, e.rig.patch)
        sc = parse_scene({"name": "s", "type": "steps", **data}, e.rig.patch, Palettes().with_points(r.points), "s")
        e.set_source(ScenePlayer(sc, e.rig, clock()))

    rule_matrix(play, seconds=3.0, unused=("uk",))


def test_wheels_and_gobos_snap_halfway():
    sc, r = scene({"step_s": 4, "fade_s": 2, "steps": [
        {"set": {"mh_a": {"colour": "white", "gobo": 30}}}, {"set": {"mh_a": {"gobo": 90}}}]})
    p = ScenePlayer(sc, r, 0.0)
    p(0)
    p(4.0)
    assert p(4.9).fixtures["mh_a"].gobo == 30
    assert p(5.1).fixtures["mh_a"].gobo == 90


# ------------------------------------------------------------------ in the app: pedals, inputs, shows


@pytest.fixture
def app(tmp_path):
    from dmx_suite.app import App
    from dmx_suite.output import LogDriver

    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups"))
    (root / "scenes" / "hits.yaml").write_text("""version: 5
name: Hits
type: steps
step_s: 2
advance: {input: snare}
steps:
  - {name: red bars, set: {bars: {colour: red}}}
  - {name: blue heads, set: {movers: {colour: blue, position: drum_kit}}, fade_s: 0}
  - {name: all white, set: {all: {colour: white}}}
""", encoding="utf-8")
    t = [1000.0]
    a = App(load_show(root), [LogDriver()], clock=lambda: t[0])
    a.t = t
    return a


def test_snare_moves_the_step_scene_on(app):
    app.ctl.select_scene("hits")
    app.engine.tick()
    assert app.ctl.now().steps["index"] == 0
    m = FakeMidiIn(app.router.handle_mido)
    m.note(38, 100)  # snare (also a drum flash; MASTER is on so no flash)
    assert app.ctl.now().steps["index"] == 1
    m.note(36, 100)  # kick: not the advance input
    assert app.ctl.now().steps["index"] == 1
    assert "store" not in app.store.input_users("snare")[0] and any("hits" in u for u in app.store.input_users("snare"))


def test_step_pedals_and_faders(app):
    app.ctl.select_scene("hits")
    app.engine.tick()
    ins = parse_inputs({"devices": {"p": {"channel": 1, "inputs": {"nx": {"type": "program_change", "number": 50},
                                                                   "bk": {"type": "program_change", "number": 51},
                                                                   "sp": {"type": "control_change", "number": 20}}}}})
    r = MidiRouter(app.engine, parse_map({"mappings": [{"input": "nx", "action": "step_next"},
                                                       {"input": "bk", "action": "step_back"},
                                                       {"input": "sp", "action": "step_speed"}]}),
                   MidiMonitor(), app.ctl, ins)
    m = FakeMidiIn(r.handle_mido)
    assert m.program(50).startswith("step 2")
    assert m.program(51).startswith("step 1")
    m.cc(20, 127)
    assert app.ctl.now().steps["speed"] == pytest.approx(4.0)


def test_play_from_any_step_and_status(app):
    app.ctl.select_scene("hits", step=2)
    app.engine.tick()
    st = app.ctl.now().steps
    assert st["index"] == 2 and st["name"] == "all white" and st["of"] == 3 and st["input"] == "snare"
    assert st["names"] == ["red bars", "blue heads", "all white"]


def test_step_scene_in_a_show_repeats_by_its_length(app):
    sc = app.files.scenes["hits"]
    assert sc.length is None  # waits on the snare
    app.store.put("scene", "timed", {"name": "Timed", "type": "steps", "step_s": 1.5,
                                     "steps": [{"set": {"bars": {"colour": "red"}}}, {"set": {"bars": {"colour": "blue"}}}]})
    app.reload()
    assert app.files.scenes["timed"].length == 3.0
    app.store.put("show", "steppy", {"name": "Steppy", "sets": {"main": {"steps": [{"scene": "timed", "repeats": 2}]}}})
    app.reload()
    app.ctl.select_show("steppy")
    app.engine.tick()
    assert app.ctl.player.time_left(app.t[0]) == pytest.approx(6.0)


def test_capture_the_lights_as_a_step(app):
    app.ctl.select_scene("hits", step=1)
    app.engine.tick()
    got = app.capture_step(["movers", "bar_1"])
    assert got["mh_a"]["position"] == {"pan": 0.42, "tilt": 0.3} and "colour" in got["mh_a"]
    assert got["bar_1"]["colour"]["red"] == 1.0  # tracked from step 1
    # it round-trips: the captured set is a valid step
    app.store.put("scene", "cap", {"name": "Cap", "type": "steps", "steps": [{"set": got}]})


def test_store_rejects_bad_step_scene(app):
    from dmx_suite.store import StoreError

    with pytest.raises(StoreError, match="haze"):
        app.store.put("scene", "bad", {"name": "Bad", "type": "steps", "steps": [{"set": {"smoke": {"haze": 1}}}]})
    with pytest.raises(StoreError, match="no input"):
        app.store.put("scene", "bad", {"name": "Bad", "type": "steps", "advance": {"input": "cowbell"},
                                       "steps": [{"set": {"bars": {"colour": "#ff0000"}}}]})
