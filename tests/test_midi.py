import pytest

from dmx_suite.fixtures import ConfigError
from dmx_suite.midi.inputs import FakeMidiIn
from dmx_suite.midi.map import Mapping, MidiMap, load_map, parse_map, save_map
from dmx_suite.midi.monitor import MidiMonitor
from dmx_suite.midi.router import MidiRouter

MAP = {
    "mappings": [
        {"type": "program_change", "channel": 1, "number": 0, "action": "master_toggle"},
        {"type": "program_change", "channel": 1, "number": 9, "action": "blackout_toggle"},
        {"type": "program_change", "channel": 1, "number": 3, "action": "select_show", "show": "opera"},
        {"type": "note", "channel": 10, "number": 38, "action": "flash", "fixtures": ["bars"], "length_ms": 120},
        {"type": "control_change", "channel": 1, "number": 7, "action": "grand_master"},
        {"type": "control_change", "channel": 1, "number": 80, "action": "haze_boost"},
        {"type": "program_change", "channel": 1, "number": 5, "action": "haze_manual"},
    ]
}


@pytest.fixture
def router(engine):
    return MidiRouter(engine, parse_map(MAP), MidiMonitor())


@pytest.fixture
def midi(router):
    return FakeMidiIn(router.handle_mido)


def test_program_change_toggles_master(engine, midi):
    assert midi.program(0) == "MASTER off"
    assert not engine.master
    assert midi.program(0) == "MASTER on"


def test_drum_hit_flashes_with_velocity(engine, midi, view, clock):
    midi.program(0)  # MASTER off
    assert midi.note(38, 127).startswith("flash bars")
    assert view("bar_1", "blue", 0) == 255
    assert midi.note_off(38) == "release"


def test_drum_hit_ignored_with_master_on(midi):
    assert midi.note(38, 100) == "flash ignored (MASTER on)"


def test_wrong_channel_is_unmapped(midi):
    assert midi.note(38, 100, channel=9) == "unmapped"


def test_cc_grand_master(engine, midi):
    assert midi.cc(7, 64) == "grand_master 50%"
    assert engine.masters.grand.target == pytest.approx(64 / 127)


def test_haze_boost_held_on_cc(engine, midi, view):
    assert midi.cc(80, 127) == "haze boost on"
    assert view("smoke", "haze") == 255
    assert midi.cc(80, 0) == "haze boost release"
    assert view("smoke", "haze") == 0
    assert midi.cc(80, 127).startswith("haze boost refused")  # cooldown


def test_show_actions_without_show_control(midi):
    assert "no show control" in midi.program(3)


def test_monitor_records_results(router, midi):
    midi.program(0)
    midi.note(60, 10)
    e = list(router.monitor.entries)
    assert [x.result for x in e] == ["MASTER off", "unmapped"]
    assert e[0].type == "program_change" and e[0].channel == 1
    assert e[1].type == "note_on" and e[1].channel == 10 and e[1].value == 10
    assert len(router.monitor.filtered(channel=10)) == 1
    router.monitor.paused = True
    midi.note(61, 10)
    assert len(router.monitor.entries) == 2
    router.monitor.clear()
    assert not router.monitor.entries


def test_learn_maps_next_message(router, midi, tmp_path, engine):
    learned = []
    router.learn("flash", {"fixtures": ["wash"], "colour": "white"}, learned.append)
    assert router.learning == "flash"
    assert midi.note(42, 90).startswith("learned: flash")
    assert router.learning is None
    # v3: learn names the input (GM drum name for ch 10) and maps the action to it
    assert learned[0].input == "hihat" and router.new_inputs == ["hihat"]
    assert router.inputs.get("hihat").describe() == "note 42 ch10"
    midi.program(0)  # MASTER off
    assert midi.note(42, 127).startswith("flash wash")
    path = tmp_path / "map.yaml"
    save_map(router.map, path)
    again = load_map(path)
    assert again.get_input("hihat").params == {"fixtures": ["wash"], "colour": "white"}


def test_learn_continuous_needs_cc(router, midi):
    router.learn("grand_master")
    assert "needs a CC" in midi.note(1, 100)
    assert midi.cc(11, 10).startswith("learned")


def test_learn_replaces_existing_input(router, midi):
    router.learn("blackout_toggle")
    midi.program(0)
    assert router.map.get("program_change", 1, 0) is None  # the raw mapping gives way
    assert router.map.get_input("pc_0").action == "blackout_toggle"
    assert midi.program(0) == "blackout on"


def test_learn_rejects_bad_params(router):
    with pytest.raises(ConfigError):
        router.learn("flash", {})  # no fixtures
    with pytest.raises(ValueError):
        router.learn("explode")


@pytest.mark.parametrize(
    "bad",
    [
        {"type": "note", "channel": 10, "number": 1, "action": "flash"},
        {"type": "note", "channel": 10, "number": 1, "action": "grand_master"},
        {"type": "note", "channel": 17, "number": 1, "action": "master_on"},
        {"type": "note", "channel": 1, "number": 1, "action": "flash", "fixtures": ["x"], "colour": "red"},
        {"type": "note", "channel": 1, "number": 1, "action": "master_on", "fixtures": ["x"]},
        {"type": "control_change", "channel": 1, "number": 1, "action": "sub_master", "kind": "lasers"},
    ],
)
def test_map_validation(bad):
    with pytest.raises(ConfigError):
        parse_map({"mappings": [bad]})


def test_map_replace_same_input():
    m = MidiMap()
    m.add(Mapping("note", 10, 38, "master_on"))
    old = m.add(Mapping("note", 10, 38, "master_off"))
    assert old.action == "master_on" and len(m.mappings) == 1
