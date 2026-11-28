"""Phase 2 hardware prep: second universe, SamplePad (port-specific MIDI), MIDI hot-plug."""

import pytest

from dmx_suite.engine import Engine
from dmx_suite.fixtures import ConfigError, parse_patch
from dmx_suite.look import parse_look
from dmx_suite.midi.inputs import FakeMidiIn, MidiInputs
from dmx_suite.midi.map import Mapping, MidiMap, load_map, parse_map, save_map
from dmx_suite.midi.router import MidiRouter
from dmx_suite.output import LogDriver, NodeSerialDriver
from dmx_suite.output.enttec import EnttecProDriver
from dmx_suite.rig import parse_rig
from dmx_suite.setup import patch_report

PATCH = {
    "types": {
        "par": {"kind": "wash", "channels": ["dimmer", "red", "green", "blue"]},
        "smoke": {"kind": "haze", "channels": ["haze"]},
    },
    "fixtures": [
        {"id": "a", "type": "par", "address": 1, "universe": 0, "groups": ["pars"]},
        {"id": "b", "type": "par", "address": 1, "universe": 1, "groups": ["pars"]},  # receiver-per-light
        {"id": "c", "type": "par", "address": 5, "universe": 1, "groups": ["pars"]},
        {"id": "smoke", "type": "smoke", "address": 9, "universe": 1},
    ],
}


@pytest.fixture
def two():
    patch = parse_patch(PATCH)
    rig = parse_rig({"fixtures": ["all"]}, patch)
    look = parse_look({"fixtures": {"a": {"colour": [1, 0, 0]}, "b": {"colour": [0, 1, 0]}, "c": {"colour": [0, 0, 1]}}}, patch)
    return patch, rig, look


# ------------------------------------------------------------------ second universe


def test_same_address_on_two_universes_is_fine(two):
    patch, rig, _ = two
    assert rig.universes == [0, 1]


def test_universe_range_checked():
    bad = {"types": PATCH["types"], "fixtures": [{"id": "x", "type": "par", "address": 1, "universe": 16}]}
    with pytest.raises(ConfigError, match="universe"):
        parse_patch(bad)


def test_renders_and_sends_both_universes(two):
    _, rig, look = two
    out = LogDriver()
    e = Engine(rig, [out], look)
    e.tick()
    assert out.last[0][:4] == bytes([255, 255, 0, 0])  # a: red
    assert out.last[1][:4] == bytes([255, 0, 255, 0])  # b: green at address 1 of universe 1
    assert out.last[1][4:8] == bytes([255, 0, 0, 255])  # c: blue
    assert out.last[1][8] == 0  # haze untouched (rule 5)


def test_drum_flash_on_second_universe_is_immediate(two):
    _, rig, look = two
    out = LogDriver()
    e = Engine(rig, [out], look)
    e.set_master(False)
    before = out.frames
    e.flash(["b"], 127, "white")
    assert out.frames == before + 2  # both universes sent in the same instant
    assert out.last[1][0] == 255 and out.last[0][0] == 0


def test_enttec_sends_only_its_universe(two):
    _, rig, look = two
    writes = []

    class Ser:
        def write(self, d):
            writes.append(d)

        def close(self):
            pass

    drv = EnttecProDriver("COM9", universe=1, serial_factory=lambda *a: Ser())
    e = Engine(rig, [drv], look)
    e.tick()
    drv.flush()
    assert len(writes) == 1 and writes[0][5:9] == bytes([255, 0, 255, 0])  # universe 1's frame


def test_node_relays_second_universe_to_its_receivers(two):
    _, rig, look = two
    drv = NodeSerialDriver("sim")
    node = drv.link.t.node
    rx0, rx1 = node.receivers[0], node.receivers[1]
    rx1.universe = 1
    e = Engine(rig, [drv], look)
    e.tick()
    assert bytes(node.output[:4]) == bytes([255, 255, 0, 0])  # node's own wired output: universe 0
    assert bytes(rx0.frame[:4]) == bytes([255, 255, 0, 0])  # unassigned receiver follows universe 0
    assert bytes(rx1.frame[:4]) == bytes([255, 0, 255, 0])  # receiver on universe 1
    drv.close()


def test_setup_tools_on_second_universe(two):
    _, rig, look = two
    e = Engine(rig, [LogDriver()], look)
    e.test_channel(100, 42, universe=1)
    assert e.frames[1][99] == 42 and e.frames[0][99] == 0
    with pytest.raises(ValueError, match="rule 5"):
        e.test_channel(9, 255, universe=1)  # smoke lives on universe 1
    e.test_channel(9, 255, universe=0)  # same number on universe 0 is just a channel
    e.find_fixture("c")
    assert e.frames[1][4] == 255 and e.frames[1][0] == 0


def test_address_report_per_universe(two):
    patch, rig, _ = two
    _, notes = patch_report(patch, rig)
    assert any(n.startswith("universe 0:") for n in notes) and any(n.startswith("universe 1:") for n in notes)


# ------------------------------------------------------------------ SamplePad: port-specific mappings


@pytest.fixture
def router(engine):
    m = parse_map({"mappings": [
        {"type": "note", "channel": 10, "number": 38, "action": "flash", "fixtures": ["bar_1"]},
        {"type": "note", "channel": 10, "number": 38, "port": "H2MIDI", "action": "flash", "fixtures": ["wash"],
         "colour": "white"},
    ]})
    return MidiRouter(engine, m)


def test_port_specific_mapping_wins(router, engine, view):
    engine.set_master(False)
    midi = FakeMidiIn(router.handle_mido)
    assert midi.note(38, 127, port="UM-ONE 1").startswith("flash bar_1")  # TD-25
    assert midi.note(38, 127, port="H2MIDI PRO 0").startswith("flash wash")  # SamplePad
    assert midi.note(38, 127, port="h2midi pro 3").startswith("flash wash")  # case and index don't matter
    assert router.monitor.entries[-1].port == "h2midi pro 3"


def test_learn_bound_to_port(router):
    router.learn("blackout_toggle", {"port": "this"})
    FakeMidiIn(router.handle_mido).note(60, 100, port="H2MIDI PRO 0")
    m = router.map.get("note", 10, 60, "H2MIDI PRO 0")
    assert m.action == "blackout_toggle" and m.port == "H2MIDI PRO 0"
    assert router.map.get("note", 10, 60, "UM-ONE 1") is None  # TD-25 note 60 stays unmapped


def test_port_mapping_roundtrip(tmp_path):
    m = MidiMap("x", [Mapping("note", 10, 38, "master_on", port="H2MIDI"), Mapping("note", 10, 38, "master_off")])
    assert len(m.mappings) == 2
    save_map(m, tmp_path / "m.yaml")
    again = load_map(tmp_path / "m.yaml")
    assert again.get("note", 10, 38, "H2MIDI PRO").action == "master_on"
    assert again.get("note", 10, 38, "UM-ONE").action == "master_off"
    again.remove(("note", 10, 38, "H2MIDI"))
    assert again.get("note", 10, 38, "H2MIDI PRO").action == "master_off"
    with pytest.raises(ConfigError, match="port"):
        parse_map({"mappings": [{"type": "note", "channel": 1, "number": 1, "action": "master_on", "port": "  "}]})


# ------------------------------------------------------------------ MIDI hot-plug


class FakePort:
    def __init__(self, name, cb):
        self.name, self.cb, self.closed = name, cb, False

    def close(self):
        self.closed = True


def test_inputs_reconnect_after_unplug():
    available = ["UM-ONE 1", "Microsoft GS Wavetable Synth 0"]
    opened = []
    got = []

    def opener(name, cb):
        p = FakePort(name, cb)
        opened.append(p)
        return p

    ins = MidiInputs(["um-one", "H2MIDI"], lambda msg, port: got.append(port), lister=lambda: list(available),
                     opener=opener, watch=False)
    assert list(ins.open) == ["UM-ONE 1"]  # only wanted ports
    assert ins.status() == [{"name": "um-one", "connected": True, "port": "UM-ONE 1"},
                            {"name": "H2MIDI", "connected": False, "port": None}]
    opened[0].cb("hit")
    assert got == ["UM-ONE 1"]

    available.remove("UM-ONE 1")  # unplugged
    ins.rescan()
    assert opened[0].closed and not ins.open and not ins.status()[0]["connected"]

    available += ["UM-ONE 2", "H2MIDI PRO 0"]  # plugged back in under a new name, plus the SamplePad
    ins.rescan()
    assert set(ins.open) == {"UM-ONE 2", "H2MIDI PRO 0"}
    assert all(s["connected"] for s in ins.status())
    ins.close()
    assert all(p.closed for p in opened)


def test_inputs_survive_open_failure():
    def opener(name, cb):
        raise OSError("port busy")

    ins = MidiInputs(None, lambda *a: None, lister=lambda: ["X"], opener=opener, watch=False)
    assert ins.errors == 1 and not ins.open
    ins.close()


def test_rig_midi_inputs(patch):
    assert parse_rig({"midi_inputs": ["UM-ONE", "H2MIDI"]}, patch).midi_inputs == ["UM-ONE", "H2MIDI"]
