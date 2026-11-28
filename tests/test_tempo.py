"""Beat sync: tap, kick and MIDI clock tempo, losing the source, speed, and layers in beats."""

import pytest

from dmx_suite.fixtures import ConfigError
from dmx_suite.midi.inputs import FakeMidiIn
from dmx_suite.midi.map import parse_map
from dmx_suite.midi.monitor import MidiMonitor
from dmx_suite.midi.router import MidiRouter
from dmx_suite.palettes import parse_palettes
from dmx_suite.rig import parse_rig
from dmx_suite.scenes import parse_scene
from dmx_suite.tempo import BEAT_S, TempoClock, TempoConfig

from conftest import RIG


def test_kick_averages_and_ignores_fills():
    t = TempoClock(0.0, TempoConfig("kick"))
    now = 0.0
    for gap in (0.5, 0.5, 0.25, 0.25, 0.5, 0.5, 0.5):  # 120 BPM with a double kick in the middle
        now += gap
        t.kick(now)
    assert t.bpm == pytest.approx(120, abs=0.6)


def test_kick_follows_a_change_of_tempo():
    t = TempoClock(0.0, TempoConfig("kick"))
    now = 0.0
    for _ in range(6):
        now += 0.5
        t.kick(now)
    for _ in range(8):
        now += 60 / 140
        t.kick(now)
    assert t.bpm == pytest.approx(140, abs=1)


def test_midi_clock_sets_the_tempo():
    t = TempoClock(0.0, TempoConfig("midi_clock"))
    now = 0.0
    for _ in range(60):  # 2.5 beats of clock at 100 BPM
        now += 60 / 100 / 24
        t.clock_tick(now)
    assert t.bpm == pytest.approx(100, abs=0.5)
    assert t.rate == pytest.approx(100 / 120, abs=0.01)


def test_clock_start_lines_up_the_beat():
    t = TempoClock(0.0, TempoConfig("midi_clock"))
    t.set_bpm(120, 0.0)
    t.clock_start(1.3)
    assert t.eff(1.3) % BEAT_S == pytest.approx(0, abs=1e-9)


def test_lost_source_keeps_tempo_then_goes_back_to_timers():
    """MIDI clock only (v6: the drums source freewheels instead, test_v6_tempo)."""
    t = TempoClock(0.0, TempoConfig("midi_clock", timeout_s=10))
    now = 0.0
    for _ in range(60):
        now += 0.4 / 24  # 150 BPM
        t.clock_tick(now)
    assert t.bpm == pytest.approx(150, abs=1)
    e1 = t.eff(now + 5)
    assert t.bpm and not t.lost  # quiet for 5 s: still the band's tempo
    e2 = t.eff(now + 11)
    assert t.bpm is None and t.lost and t.rate == 1.0  # back to fixed timers
    assert e2 > e1  # no jump backwards


def test_tap_never_times_out():
    t = TempoClock(0.0)
    t.tap(0.0)
    t.tap(0.5)
    t.eff(1000.0)
    assert t.bpm == pytest.approx(120)


def test_speed_multiplies_any_tempo():
    t = TempoClock(0.0)
    t.set_speed(2.0, 0.0)
    assert t.eff(1.0) == pytest.approx(2.0)
    t.set_bpm(60, 1.0)
    assert t.rate == pytest.approx(1.0)  # half tempo x double speed
    with pytest.raises(ValueError):
        t.set_speed(10, 1.0)


def test_status_has_bpm_source_and_beat():
    t = TempoClock(0.0, TempoConfig("midi_clock"))
    s = t.status(1.6)
    assert s == {"bpm": None, "source": "midi_clock", "speed": 1.0, "beat": 3, "lost": False}


def test_rig_tempo_setting(patch):
    assert parse_rig(RIG, patch).tempo.source == "tap"
    r = parse_rig({**RIG, "tempo": {"source": "kick", "kick_note": 35, "timeout_s": 12}}, patch)
    assert (r.tempo.source, r.tempo.kick_note, r.tempo.timeout_s) == ("drums", 35, 12)  # v6: kick means drums
    for bad in ({"source": "link"}, {"kick_note": 200}, {"timeout_s": 0}, {"bogus": 1}):
        with pytest.raises(ConfigError):
            parse_rig({**RIG, "tempo": bad}, patch)


def router_for(engine, source, mappings=()):
    from dmx_suite.showctl import ShowController
    from dmx_suite.showfiles import ShowFiles

    engine.rig.tempo = TempoConfig(source)
    files = ShowFiles(None, engine.rig.patch, engine.rig, engine.look, parse_map({}), None, None, {}, {}, {})
    ctl = ShowController(engine, files)
    return MidiRouter(engine, parse_map({"mappings": list(mappings)}), MidiMonitor(), ctl), ctl


def test_kick_notes_drive_the_tempo_and_still_flash(engine, clock):
    """No named kick input: the rig's kick note feeds the drums tracker (v6), after a tap seed."""
    r, ctl = router_for(engine, "kick", [{"type": "note", "channel": 10, "number": 36, "action": "flash", "fixtures": ["bars"]}])
    midi = FakeMidiIn(r.handle_mido)
    ctl.tempo.tap(clock())
    clock.advance(0.52)
    ctl.tempo.tap(clock())  # seeded a little slow (115)
    for _ in range(24):
        clock.advance(0.5)
        midi.note(36, 100, channel=10)
        ctl.tempo.eff(clock())
    assert ctl.tempo.bpm == pytest.approx(120, abs=1)
    assert list(r.monitor.entries)[-1].result.startswith("flash")  # the kick still does its mapped job


def test_midi_clock_through_the_router_stays_out_of_the_monitor(engine, clock):
    import mido

    r, ctl = router_for(engine, "midi_clock")
    r.handle_mido(mido.Message("start"))
    for _ in range(50):
        clock.advance(60 / 90 / 24)
        r.handle_mido(mido.Message("clock"))
    assert ctl.tempo.bpm == pytest.approx(90, abs=0.5)
    assert not r.monitor.entries  # 24 messages a beat would bury everything else


def test_speed_fader_from_midi(engine):
    r, ctl = router_for(engine, "tap", [{"type": "control_change", "channel": 1, "number": 20, "action": "speed"}])
    FakeMidiIn(r.handle_mido).cc(20, 127)
    assert ctl.tempo.speed == pytest.approx(4)
    FakeMidiIn(r.handle_mido).cc(20, 0)
    assert ctl.tempo.speed == pytest.approx(0.25)


def test_layer_in_beats(patch):
    pal = parse_palettes({"colours": {"red": [1, 0, 0], "blue": [0, 0, 1]}}, patch)
    sc = parse_scene({"layers": [
        {"fixtures": ["bars"], "effect": "colour_chase", "colours": ["red", "blue"], "beats": 2},
        {"fixtures": ["wash"], "effect": "flash", "beats": 0.5}]}, patch, pal, "b")
    assert sc.layers[0].params["period_s"] == pytest.approx(2 * BEAT_S)
    assert sc.layers[1].params["rate_hz"] == pytest.approx(1 / (0.5 * BEAT_S))
    with pytest.raises(ConfigError, match="beats"):
        parse_scene({"layers": [{"fixtures": ["wash"], "colour": "red", "beats": 2}]}, patch, pal, "b")
