"""Autopilot (v3.4): energy from named-input roles, moods, timed look changes, no repeats,
fill + crash, build and breakdown, between songs and count-ins, walk-on/off, hold, control
priority, the decision log, determinism, and the rules (haze untouched, heads dark between points)."""

import json
import shutil
from pathlib import Path

import pytest

from dmx_suite.autopilot import DEFAULTS, Energy, parse_config
from dmx_suite.drums import DrumBus
from dmx_suite.fixtures import ConfigError
from dmx_suite.output import LogDriver
from dmx_suite.showfiles import load_show

from conftest import Clock

SHOWS = Path(__file__).resolve().parents[1] / "shows"


@pytest.fixture
def app(tmp_path):
    from dmx_suite.app import App

    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups"))
    clock = Clock()
    a = App(load_show(root), [LogDriver()], log_dir=tmp_path / "logs", clock=clock)
    a.bus = DrumBus()
    a.autopilot.bus = a.bus
    a.autopilot.energy.bus = a.bus
    a.t = clock
    a.engine.tick()
    return a


def hits(bus, start, n, every, roles=("snare", "activity"), strength=0.8):
    for k in range(n):
        bus.add("x", list(roles), strength, start + k * every)


def run(app, seconds, step=0.25, drums=None):
    out = []
    end = app.t.t + seconds
    while app.t.t < end:
        app.t.advance(step)
        if drums:
            drums(app.t.t)
        d = app.autopilot.tick(app.t.t)
        app.engine.tick()
        if d:
            out.append(d)
    return out


# ------------------------------------------------------------------ settings


def test_defaults_and_rig_settings():
    c = parse_config(None)
    assert c["moods"] == {"low": 60.0, "mid": 40.0, "high": 20.0} and c["gap_s"] == 4.0
    c = parse_config({"moods": {"high": 15}, "no_repeat": 6})
    assert c["moods"]["high"] == 15 and c["moods"]["low"] == 60.0 and c["no_repeat"] == 6


@pytest.mark.parametrize("bad, msg", [
    ({"tempo": 1}, "settings are"),
    ({"moods": {"low": 1}}, "2 or more"),
    ({"variation": 2}, "0-0.9"),
    ({"count_in": 12}, "2-8"),
    ({"talking": {"move": "laser"}}, "unknown FX item"),
])
def test_bad_settings(bad, msg):
    with pytest.raises(ConfigError, match=msg):
        parse_config(bad)


# ------------------------------------------------------------------ energy


def test_energy_from_roles():
    bus = DrumBus()
    e = Energy(bus, DEFAULTS)
    assert e.level(100) == 0.0
    hits(bus, 90, 8, 0.5, strength=0.3)  # quiet: 2 a second, soft
    quiet = e.level(94)
    bus2 = DrumBus()
    hits(bus2, 90, 30, 0.13, strength=1.0)
    hits(bus2, 90, 15, 0.26, roles=("kick", "activity"))
    loud = Energy(bus2, DEFAULTS).level(94)
    assert 0 < quiet < 0.5 < loud <= 1.0


def test_any_device_can_drive_energy():
    """A keyboard's notes with the activity role count the same as drums."""
    bus = DrumBus()
    hits(bus, 0, 24, 0.15, roles=("activity",), strength=0.9)
    assert Energy(bus, DEFAULTS).level(3.6) > 0.5


def test_fill_then_crash_detected():
    bus = DrumBus()
    e = Energy(bus, DEFAULTS)
    hits(bus, 10, 6, 0.1, roles=("tom", "activity"))
    bus.add("crash", ["cymbal", "activity"], 1.0, 10.7)
    assert e.fill_then_crash(10.8, 10.0)
    assert not e.fill_then_crash(10.8, 10.75)  # already seen
    bus2 = DrumBus()
    bus2.add("crash", ["cymbal"], 1.0, 5.0)  # a crash on its own: no fill
    assert not Energy(bus2, DEFAULTS).fill_then_crash(5.1, 4.0)


def test_count_in():
    bus = DrumBus()
    e = Energy(bus, DEFAULTS)
    hits(bus, 0, 4, 0.5, roles=("count_in", "activity"))
    assert e.count_in(1.6)
    bus2 = DrumBus()
    for t in (0, 0.2, 1.3, 1.5):  # uneven: not a count-in
        bus2.add("s", ["count_in"], 1.0, t)
    assert not Energy(bus2, DEFAULTS).count_in(1.6)


# ------------------------------------------------------------------ changes


def test_changes_land_on_the_mood_timer(app):
    ap = app.autopilot
    ap.cfg["variation"] = 0.0
    ap.set_mood("high", app.t.t)
    ap.set_on(True, app.t.t)
    run(app, 61, drums=lambda t: app.bus.add("x", ["activity"], 0.9, t))
    ds = list(ap.decisions)
    gaps = [b.time - a.time for a, b in zip(ds, ds[1:]) if b.trigger == "timer"]
    assert len(gaps) >= 2 and all(abs(g - 20) < 0.3 for g in gaps)  # each timer change 20 s after the change before


def test_variation_within_bounds(app):
    ap = app.autopilot
    ap.cfg["variation"] = 0.2
    ap.set_mood("high", app.t.t)
    ap.set_on(True, app.t.t)
    ds = run(app, 200, step=0.5, drums=lambda t: app.bus.add("x", ["activity"], 0.9, t))
    gaps = [b.time - a.time for a, b in zip(ds, ds[1:]) if b.trigger == "timer"]
    assert gaps and all(16 - 0.6 <= g <= 24 + 0.6 for g in gaps) and len({round(g, 1) for g in gaps}) > 1


def test_no_repeat_within_the_last_looks(app):
    ap = app.autopilot
    ap.cfg["no_repeat"] = 4
    ap.set_mood("mid", app.t.t)
    ap.set_on(True, app.t.t)
    for _ in range(15):
        ap.next(app.t.t)
        app.t.advance(1)
    keys = [p.key() for p in ap.st.history]
    for i in range(1, len(keys)):
        assert keys[i] not in keys[max(0, i - 4):i]


def test_every_change_follows_the_quality_rules(app):
    ap = app.autopilot
    q = app.quality()
    pals = {k: v["resolved"] for k, v in app.files.palettes.sets.items()}
    for mood in ("low", "mid", "high"):
        ap.set_mood(mood, app.t.t)
        ap.set_on(True, app.t.t)
        prev = None
        for _ in range(10):
            d = ap.change(app.t.t, "timer")
            app.t.advance(1)
            from dmx_suite.fxbanks import Pick

            p = Pick.from_dict(d.look)
            assert q.combo_issues(p, mood) == [], (mood, d.look)
            assert q.contrast_ok(prev, p, pals)
            prev = p


def test_fill_and_crash_forces_an_early_change_with_a_colour_hit(app):
    ap = app.autopilot
    ap.set_mood("mid", app.t.t)
    ap.set_on(True, app.t.t)
    app.t.advance(5)
    ap.tick(app.t.t)
    hits(app.bus, app.t.t, 6, 0.1, roles=("snare", "activity"))
    app.bus.add("crash", ["cymbal", "activity"], 1.0, app.t.t + 0.65)
    app.t.advance(0.8)
    d = ap.tick(app.t.t)
    assert d is not None and d.trigger == "fill_crash" and "fill" in d.why
    assert any(o.key == "flashfx/colour_hit" for o in app.engine.overrides)


def test_mood_follows_energy_unless_set(app):
    ap = app.autopilot
    ap.set_on(True, app.t.t)
    ap.set_mood(None, app.t.t)
    run(app, 6, drums=lambda t: [app.bus.add("x", ["snare", "activity"], 1.0, t + k * 0.05) for k in range(3)])
    assert ap.st.mood == "high"
    run(app, 12, drums=lambda t: app.bus.add("x", ["activity"], 0.2, t) if int(t * 4) % 6 == 0 else None)
    assert ap.st.mood in ("low", "mid")
    ap.set_mood("high", app.t.t)  # pedal: stays put
    run(app, 6, drums=lambda t: app.bus.add("x", ["activity"], 0.1, t) if int(t * 4) % 8 == 0 else None)
    assert ap.st.mood == "high"


def test_manual_mood_only_without_drums(app):
    ap = app.autopilot
    ap.set_on(True, app.t.t)
    run(app, 5)
    assert ap.st.mood == "mid" and ap.energy.level(app.t.t) == 0.0


# ------------------------------------------------------------------ between songs


def test_silence_then_count_in(app):
    ap = app.autopilot
    ap.set_on(True, app.t.t)
    run(app, 6, drums=lambda t: app.bus.add("x", ["snare", "activity"], 0.8, t))
    t_last = app.t.t
    ds = run(app, 6)  # silence
    ended = [d for d in ds if d.trigger == "song_end"]
    assert ended and ended[0].time - t_last >= 4 - 0.3 and ap.st.between
    assert ended[0].look["palette"] == "white"  # the talking look
    start = app.t.t
    hits(app.bus, start + 0.1, 4, 0.5, roles=("count_in", "activity"))
    ds = run(app, 2)
    started = [d for d in ds if d.trigger == "song_start"]
    assert started and not ap.st.between and "count-in" in started[0].why or "first hit" in started[0].why


def test_walk_on_and_off_from_the_setlist(app):
    ap = app.autopilot
    ap.set_on(True, app.t.t)
    key = next(iter(app.files.setlists))
    app.ctl.load_setlist(key)  # setlist start: walk-on (then the song's show takes over)
    assert any(d.trigger == "walk_on" for d in ap.decisions)


def test_walk_buttons(app):
    ap = app.autopilot
    app.ride_action("walk_off", {})
    assert ap.decisions[-1].trigger == "walk_off" and ap.st.between


# ------------------------------------------------------------------ hold, priority, MASTER


def test_hold_stops_changes(app):
    ap = app.autopilot
    ap.cfg["variation"] = 0.0
    ap.set_mood("high", app.t.t)
    ap.set_on(True, app.t.t)
    app.ride_action("hold", {})
    ds = run(app, 45, drums=lambda t: app.bus.add("x", ["activity"], 0.9, t))
    assert ds == [] and app.priority()["top"] == "hold"
    app.ride_action("hold", {})
    ds = run(app, 25, drums=lambda t: app.bus.add("x", ["activity"], 0.9, t))
    assert any(d.trigger == "timer" for d in ds)


def test_master_off_pauses_the_autopilot(app):
    ap = app.autopilot
    ap.set_on(True, app.t.t)
    app.engine.set_master(False)
    assert app.priority()["top"] == "drum_flash"
    ds = run(app, 70, drums=lambda t: app.bus.add("x", ["activity"], 0.9, t))
    assert ds == [] and ap.status(app.t.t)["paused"]


def test_priority_levels(app):
    app.autopilot.set_on(True, app.t.t)
    assert app.priority()["top"] == "autopilot"
    app.flash_fx("blinder", True)
    assert app.priority()["top"] == "flash_busk"
    app.engine.set_blackout(True)
    assert app.priority()["top"] == "blackout" and app.priority()["levels"][:2] == ["blackout", "flash_busk"]


def test_release_crossfades_back(app):
    """With release_fade_s set, MASTER back on fades the show in instead of cutting."""
    app.engine.rig.release_fade_s = 1.0
    app.ride_play({"colour": "static", "palette": "white"}, 0)
    app.engine.tick()
    fx = app.engine.rig.patch.fixtures["bar_1"]
    full = max(app.engine.frames[fx.universe][fx.slot(c)] for c in fx.type.channels)
    app.engine.set_master(False)
    app.engine.tick()
    app.engine.set_master(True)
    app.t.advance(0.5)
    app.engine.tick()
    half = max(app.engine.frames[fx.universe][fx.slot(c)] for c in fx.type.channels)
    assert 0 < half < full
    app.t.advance(0.6)
    app.engine.tick()
    assert max(app.engine.frames[fx.universe][fx.slot(c)] for c in fx.type.channels) == full


def test_picking_a_show_by_hand_turns_the_autopilot_off(app):
    app.autopilot.set_on(True, app.t.t)
    app.ctl.select_show(next(iter(app.files.shows)))
    assert not app.autopilot.st.on


def test_previous_look(app):
    ap = app.autopilot
    ap.set_on(True, app.t.t)
    first = ap.st.pick.key()
    ap.next(app.t.t)
    assert ap.st.pick.key() != first
    ap.previous(app.t.t)
    assert ap.st.pick.key() == first


# ------------------------------------------------------------------ decision log and determinism


def test_every_change_is_logged_with_a_reason(app, tmp_path):
    ap = app.autopilot
    ap.cfg["variation"] = 0.0
    ap.set_mood("high", app.t.t)
    ap.set_on(True, app.t.t)
    run(app, 45, drums=lambda t: app.bus.add("x", ["activity"], 0.9, t))
    lines = [json.loads(x) for p in (tmp_path / "logs").glob("decisions-*.jsonl") for x in p.read_text().splitlines()]
    assert len(lines) == len(ap.decisions) >= 3
    for x in lines:
        assert x["why"] and x["trigger"] and x["mood"] and x["look"]["colour"]
    assert app.autopilot.log_since(2)[-1]["time"] == lines[-1]["time"]


def session(seed="gig"):
    """A recorded session: the same seed and drums give the same looks."""
    from dmx_suite.app import App

    clock = Clock()
    a = App(load_show(SHOWS), [LogDriver()], clock=clock)
    a.bus = DrumBus()
    a.autopilot.bus = a.autopilot.energy.bus = a.bus
    a.autopilot.cfg["seed"] = seed
    import random
    import zlib

    a.autopilot.rng = random.Random(zlib.crc32(seed.encode()))
    a.t = clock
    a.autopilot.set_on(True, clock.t)
    run(a, 120, step=0.5, drums=lambda t: [a.bus.add("x", ["snare", "activity"], 0.7, t)] if int(t * 2) % 3 else None)
    return [(round(d.time, 2), d.trigger, json.dumps(d.look, sort_keys=True)) for d in a.autopilot.decisions]


def test_recorded_session_replays_identically():
    assert session() == session()
    assert session("a") != session("b")


# ------------------------------------------------------------------ rules


def test_autopilot_never_touches_haze_and_keeps_the_rules(app):
    ap = app.autopilot
    ap.set_mood("high", app.t.t)
    app.engine.tick()
    slot = next(iter(app.engine.haze_slots()))
    for mood in ("low", "mid", "high"):
        ap.set_mood(mood, app.t.t)
        ap.set_on(True, app.t.t)
        for _ in range(8):
            ap.next(app.t.t)
            for _ in range(10):
                app.t.advance(0.1)
                app.engine.tick()
                assert app.engine.frames[slot[0]][slot[1]] == 0  # rule 5
                for fid in ("mh_a", "mh_b"):
                    fx = app.engine.rig.patch.fixtures[fid]
                    lim = app.engine.rig.limit(fid)
                    tilt = next(app.engine.frames[fx.universe][fx.slot(c)] for c in fx.type.channels if c.role == "tilt")
                    assert tilt / 255 <= lim.tilt[1] + 1 / 255  # rule 8
    from dmx_suite.fxbanks import Pick

    for d in ap.decisions:  # the kick light keeps its own rules (rule 3): never in an autopilot look
        _, scene = app.compose(Pick.from_dict(d.look))
        assert all("kick" not in ly["fixtures"] and "smoke" not in ly["fixtures"] for ly in scene["layers"])


def test_ride_controls_over_the_api(app):
    app.ride_action("ride_fx", {"bank": "colour", "item": "colour_chase"})
    app.ride_action("ride_palette", {"palette": "fire"})
    app.ride_action("ride_speed", {}, 1.0)  # fader at the top: 4x
    assert app.ride_pick.colour == "colour_chase" and app.ride_pick.palette == "fire" and app.ride_pick.ride.speed == 4.0
    app.ride_action("ride_fan", {"bank": "colour", "value": 0.9})
    assert app.ride_pick.bank_ride["colour"].fan == 0.9
    app.ride_action("palette_lock", {})
    app.autopilot.set_on(True, app.t.t)
    for _ in range(5):
        app.autopilot.next(app.t.t)
        assert app.autopilot.st.pick.palette == "fire" or app.ctl.describe().endswith("fire")
    with pytest.raises(ValueError):
        app.ride_action("ride_fx", {"bank": "move", "item": "laser"})


def test_midi_ride_actions(app):
    from dmx_suite.midi.inputs import FakeMidiIn
    from dmx_suite.midi.map import parse_map
    from dmx_suite.midi.monitor import MidiMonitor
    from dmx_suite.midi.named import parse_inputs
    from dmx_suite.midi.router import MidiRouter

    ins = parse_inputs({"devices": {"p": {"channel": 1, "inputs": {
        "ap": {"type": "program_change", "number": 60}, "up": {"type": "program_change", "number": 61},
        "hold": {"type": "program_change", "number": 62}, "sp": {"type": "control_change", "number": 30}}}}})
    r = MidiRouter(app.engine, parse_map({"mappings": [
        {"input": "ap", "action": "autopilot"}, {"input": "up", "action": "mood", "mood": "up"},
        {"input": "hold", "action": "hold"}, {"input": "sp", "action": "ride_speed"}]}), MidiMonitor(), app.ctl, ins)
    r.ride = app.ride_action
    m = FakeMidiIn(r.handle_mido)
    assert m.program(60) == "autopilot on"
    assert m.program(61) == "mood high"
    assert m.program(62) == "hold on"
    m.cc(30, 0)
    assert app.ride_pick.ride.speed == 0.25
    with pytest.raises(ConfigError, match="mood needs"):
        parse_map({"mappings": [{"input": "up", "action": "mood", "mood": "loud"}]})
