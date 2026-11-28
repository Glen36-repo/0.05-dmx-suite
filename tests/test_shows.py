import json
import time
from pathlib import Path

import pytest

from dmx_suite.engine import Engine
from dmx_suite.fixtures import ConfigError
from dmx_suite.midi.inputs import FakeMidiIn
from dmx_suite.midi.map import parse_map
from dmx_suite.midi.router import MidiRouter
from dmx_suite.output import LogDriver
from dmx_suite.scenes import ScenePlayer, parse_scene
from dmx_suite.showctl import ShowController
from dmx_suite.showfiles import load_show
from dmx_suite.shows import ShowPlayer, parse_setlist, parse_show
from dmx_suite.tempo import TempoClock

SHOWS = Path(__file__).resolve().parents[1] / "shows"


@pytest.fixture
def files():
    return load_show(SHOWS)


class Clock:
    def __init__(self):
        self.t = 5000.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def ctl(files, clock, tmp_path):
    e = Engine(files.rig, [LogDriver()], files.look, clock=clock)
    return ShowController(e, files, tmp_path / "state.json")


# ------------------------------------------------------------------ show player


@pytest.mark.parametrize("set_name, step", [("low", 60), ("mid", 40), ("high", 20)])
def test_fixed_timer_steps(files, clock, set_name, step):
    tempo = TempoClock(clock())
    p = ShowPlayer(files.shows["band"], set_name, files.rig, files.palettes, files.scenes, tempo, clock())
    p(clock())
    assert p.step == 0
    clock.t += step - 0.1
    p(clock())
    assert p.step == 0
    clock.t += 0.2
    p(clock())
    assert p.step == 1


def test_tempo_does_not_stretch_step_timers(files, clock):
    tempo = TempoClock(clock())
    tempo.set_bpm(240, clock())
    p = ShowPlayer(files.shows["band"], "high", files.rig, files.palettes, files.scenes, tempo, clock())
    clock.t += 15
    p(clock())
    assert p.step == 0


def test_random_scene_order_never_repeats(files, clock):
    p = ShowPlayer(files.shows["band"], "cues", files.rig, files.palettes, files.scenes, TempoClock(0), clock(), seed="s")
    names = []
    for _ in range(30):
        names.append(p.scene.name)
        p.next_step(clock())
    assert all(a != b for a, b in zip(names, names[1:]))
    assert len(set(names)) == 3


def test_show_validation(files):
    pal, scenes = files.palettes, files.scenes
    with pytest.raises(ConfigError, match="one of steps, scenes or auto"):
        parse_show("x", {"sets": {"a": {"step_s": 10}}}, pal, scenes)
    with pytest.raises(ConfigError, match="unknown scene"):
        parse_show("x", {"sets": {"a": {"scenes": ["nope"]}}}, pal, scenes)
    with pytest.raises(ConfigError, match="default_set"):
        parse_show("x", {"default_set": "z", "sets": {"a": {"scenes": ["opera"]}}}, pal, scenes)
    with pytest.raises(ConfigError, match="no set"):
        parse_setlist("x", {"songs": [{"show": "band", "set": "huge"}]}, files.shows, scenes)
    with pytest.raises(ConfigError, match="either show or scene"):
        parse_setlist("x", {"songs": [{"name": "a"}]}, files.shows, scenes)


# ------------------------------------------------------------------ controller


def test_select_show_set_and_next(ctl):
    ctl.select_show("band")
    assert ctl.now().set == "mid"  # default set
    ctl.select_set("high")
    n = ctl.now()
    assert (n.show, n.set, n.step) == ("band", "high", 1)
    ctl.next_step()
    assert ctl.now().step == 2
    assert ctl.e.scene is ctl.player.scene


def test_setlist_steps(ctl):
    ctl.load_setlist("example")
    assert ctl.now().song_name == "Intro" and ctl.now().mode == "scene"
    ctl.next_song()
    assert (ctl.now().show, ctl.now().set) == ("band", "high")
    ctl.prev_song()
    ctl.prev_song()  # clamps at the first song
    assert ctl.song == 0
    ctl.go_song(4)  # drum feature: master off
    assert not ctl.e.master
    for _ in range(10):
        ctl.next_song()  # clamps at the last song
    assert ctl.now().song_name == "Unplugged" and ctl.e.master


def test_resume_after_restart(files, clock, tmp_path):
    path = tmp_path / "state.json"
    e1 = Engine(files.rig, [LogDriver()], files.look, clock=clock)
    c1 = ShowController(e1, files, path)
    c1.load_setlist("example")
    c1.go_song(3)
    e1.set_master(False)
    c1.save()

    e2 = Engine(files.rig, [LogDriver()], files.look, clock=clock)  # "reboot"
    c2 = ShowController(e2, files, path)
    assert c2.restore()
    assert c2.now().song_name == "Ballad" and (c2.now().show, c2.now().set) == ("band", "low")
    assert not e2.master


def test_resume_ignores_stale_or_broken_state(files, clock, tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"saved": time.time() - 13 * 3600, "mode": "scene", "scene": "opera"}))
    c = ShowController(Engine(files.rig, [LogDriver()], clock=clock), files, path)
    assert not c.restore()
    path.write_text("{not json")
    assert not c.restore()
    path.write_text(json.dumps({"saved": time.time(), "mode": "show", "show": "deleted_show"}))
    assert not c.restore()


def test_show_output_obeys_master(ctl):
    ctl.select_show("band", "high")
    ctl.e.set_master(False)
    rig = ctl.e.rig
    frame = ctl.e.frames[0]
    for fx in rig.fixtures:
        if fx.kind.value in ("head", "bar", "wash"):
            assert not any(frame[fx.slot(c)] for c in fx.type.channels if c.role in ("red", "green", "blue", "white", "dimmer"))


# ------------------------------------------------------------------ MIDI show actions


def test_midi_show_actions(ctl):
    router = MidiRouter(ctl.e, parse_map({"mappings": [
        {"type": "program_change", "channel": 1, "number": 1, "action": "select_set", "set": "low"},
        {"type": "program_change", "channel": 1, "number": 4, "action": "select_show", "show": "opera"},
        {"type": "program_change", "channel": 1, "number": 10, "action": "next_song"},
        {"type": "program_change", "channel": 1, "number": 12, "action": "next_step"},
        {"type": "program_change", "channel": 1, "number": 13, "action": "tap_tempo"},
        {"type": "program_change", "channel": 1, "number": 14, "action": "select_scene", "scene": "nope"},
    ]}), shows=ctl)
    midi = FakeMidiIn(router.handle_mido)
    assert "Main band show / low" in midi.program(1)
    assert "Opera" in midi.program(4)
    assert "step 2" in midi.program(12)
    assert "no setlist" in midi.program(10)  # reported, doesn't crash the show
    assert "failed" in midi.program(14)
    assert midi.program(13) == "tap"


def test_map_requires_show_params():
    with pytest.raises(ConfigError, match="needs show"):
        parse_map({"mappings": [{"type": "program_change", "channel": 1, "number": 1, "action": "select_show"}]})


# ------------------------------------------------------------------ tempo


def test_tap_tempo_bpm_and_rate():
    t = TempoClock(0.0)
    assert t.eff(10) == 10  # no tempo: real time
    for i in range(4):
        bpm = t.tap(100 + i * 0.5)  # 120 BPM
    assert bpm == pytest.approx(120)
    for i in range(4):
        bpm = t.tap(200 + i * 0.25)  # 240 BPM after a long gap restarts the count
    assert bpm == pytest.approx(240)
    a = t.eff(300)
    assert t.eff(301) - a == pytest.approx(2.0)  # effects run twice as fast


def test_tempo_change_is_continuous_and_tap_snaps_to_beat():
    t = TempoClock(0.0)
    t.set_bpm(90, 10)
    before = t.eff(20)
    t.set_bpm(150, 20)
    assert t.eff(20) == pytest.approx(before)  # no jump in effect time
    t.set_bpm(None, 30)
    t.tap(40.1)
    t.tap(40.6)
    assert (t.eff(40.6) / 0.5) == pytest.approx(round(t.eff(40.6) / 0.5))  # on a beat


def test_tempo_limits():
    t = TempoClock(0)
    with pytest.raises(ValueError):
        t.set_bpm(400, 0)
    t.tap(0)
    assert t.tap(0.05) is None  # 1200 BPM: ignored


def test_chases_follow_tempo(files, clock):
    pal = files.palettes
    sc = parse_scene({"layers": [{"fixtures": ["wash_l"], "effect": "flash", "colour": "red", "rate_hz": 1, "duty": 0.5}]},
                     files.patch, pal)
    tempo = TempoClock(0.0)
    p = ScenePlayer(sc, files.rig, 0.0, tempo.eff)
    assert p(0.75).fixtures["wash_l"].colour == {}  # real time: off half of the cycle
    tempo.set_bpm(240, 0.0)  # double speed from t=0
    assert p(0.3).fixtures["wash_l"].colour == {}  # 0.6 s of effect time: off
    assert p(0.55).fixtures["wash_l"].colour  # 1.1 s: second cycle, on


# ------------------------------------------------------------------ fallback layers (rig adapts)


def test_layer_fallback_moves_to_whats_there(files):
    from dmx_suite.rig import parse_rig

    sc = parse_scene({"layers": [{"fixtures": ["washes"], "colour": "red", "fallback": ["bars"]},
                                 {"fixtures": ["movers"], "colour": "blue", "fallback": ["bar_1"]}]},
                     files.patch, files.palettes)
    small = parse_rig({"fixtures": ["bars", "kick"]}, files.patch)
    lk = ScenePlayer(sc, small, 0)(1)
    assert lk.fixtures["bar_2"].colour["red"] == 1  # washes missing -> bars
    assert lk.fixtures["bar_1"].colour["blue"] == 1  # movers missing -> bar_1 (later layer wins)
    full = ScenePlayer(sc, files.rig, 0)(1)
    assert "bar_2" not in full.fixtures  # fallback unused when the fixtures are there


def test_fallback_still_checks_rule7(files):
    from dmx_suite.look import LookError

    with pytest.raises(LookError, match="rule 7"):
        parse_scene({"layers": [{"fixtures": ["movers"], "position": "centre", "fallback": ["ukings"]}]},
                    files.patch, files.palettes)


def test_set_pedal_switches_to_a_show_that_has_the_set(ctl):
    ctl.select_show("opera")
    ctl.select_set("low")
    assert (ctl.now().show, ctl.now().set) == ("band", "low")
    with pytest.raises(ConfigError, match="no show has"):
        ctl.select_set("encore")
