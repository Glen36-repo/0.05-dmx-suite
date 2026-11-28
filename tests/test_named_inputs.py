"""Named MIDI inputs (v3.1): inputs.yaml, devices, roles, velocity curves, learn, references,
the store and the API; every rule still holds when inputs drive the rig."""

import shutil
from pathlib import Path

import pytest
import yaml

from dmx_suite.fixtures import ConfigError
from dmx_suite.midi.inputs import FakeMidiIn
from dmx_suite.midi.map import parse_map
from dmx_suite.midi.monitor import MidiMonitor
from dmx_suite.midi.named import (
    InputDef,
    Inputs,
    device_profiles,
    load_device_profile,
    parse_inputs,
    refs,
    rename_refs,
    suggest,
)
from dmx_suite.midi.router import MidiRouter
from dmx_suite.showctl import ShowController
from dmx_suite.showfiles import check_all, load_show
from dmx_suite.store import ShowStore, StoreError

from rulecheck import rule_matrix

SHOWS = Path(__file__).resolve().parents[1] / "shows"

INPUTS = {
    "devices": {
        "kit": {
            "name": "Kit",
            "channel": 10,
            "inputs": {
                "kick": {"name": "Kick", "type": "note", "notes": [36], "roles": ["kick", "activity"]},
                "snare": {"name": "Snare", "type": "note", "notes": [38, 40], "roles": ["snare", "activity"]},
                "crash": {"type": "note", "notes": [49], "roles": ["cymbal"], "curve": {"quiet": 20, "normal": 60, "loud": 100}},
            },
        },
        "pedals": {
            "name": "Pedals",
            "channel": 1,
            "inputs": {
                "master": {"type": "program_change", "number": 0},
                "grand": {"type": "control_change", "number": 7},
            },
        },
        "osc": {"name": "OSC", "inputs": {"btn": {"type": "osc", "address": "/btn/1"}}},
    }
}

MAP = {"mappings": [
    {"input": "master", "action": "master_toggle"},
    {"input": "snare", "action": "flash", "fixtures": ["bars"], "length_ms": 120},
    {"input": "crash", "action": "flash", "fixtures": ["wash"], "length_ms": 120},
    {"input": "grand", "action": "grand_master"},
    {"input": "btn", "action": "blackout_toggle"},
]}


@pytest.fixture
def inputs():
    return parse_inputs(INPUTS)


@pytest.fixture
def router(engine, inputs):
    return MidiRouter(engine, parse_map(MAP), MidiMonitor(), inputs=inputs)


@pytest.fixture
def midi(router):
    return FakeMidiIn(router.handle_mido)


# ------------------------------------------------------------------ parsing


def test_parse_devices_and_inputs(inputs):
    assert set(inputs.devices) == {"kit", "pedals", "osc"}
    snare = inputs.get("snare")
    assert (snare.type, snare.channel, snare.numbers, snare.device) == ("note", 10, [38, 40], "kit")
    assert snare.describe() == "note 38/40 ch10"
    assert inputs.get("master").describe() == "PC 0 ch1"
    assert inputs.get("btn").describe() == "OSC /btn/1"
    assert [i.id for i in inputs.by_role("activity")] == ["kick", "snare"]


def test_round_trip(inputs):
    again = parse_inputs(inputs.to_dict())
    assert again.to_dict() == inputs.to_dict()
    assert again.to_dict()["devices"]["kit"]["inputs"]["snare"] == {
        "name": "Snare", "type": "note", "notes": [38, 40], "roles": ["snare", "activity"]}


@pytest.mark.parametrize("bad, msg", [
    ({"devices": {"k": {"inputs": {"x": {"type": "drum"}}}}}, "type must be"),
    ({"devices": {"k": {"inputs": {"x": {"type": "note"}}}}}, "needs notes"),
    ({"devices": {"k": {"inputs": {"x": {"notes": [200]}}}}}, "0-127"),
    ({"devices": {"k": {"inputs": {"x": {"notes": [1], "channel": 17}}}}}, "channel 1-16"),
    ({"devices": {"k": {"inputs": {"x": {"notes": [1], "roles": ["bass"]}}}}}, "roles are"),
    ({"devices": {"k": {"inputs": {"x": {"notes": [1], "velocity": [90, 10]}}}}}, "velocity"),
    ({"devices": {"k": {"inputs": {"x": {"notes": [1], "curve": {"quiet": 90, "loud": 10}}}}}}, "must rise"),
    ({"devices": {"k": {"inputs": {"x": {"type": "osc", "address": "btn"}}}}}, "starts with /"),
    ({"devices": {"k": {"inputs": {"Bad Name": {"notes": [1]}}}}}, "lower case"),
    ({"devices": {"k": {"inputs": {"x": {"notes": [1], "colour": "red"}}}}}, "#rrggbb"),
    ({"devices": {"a": {"inputs": {"x": {"notes": [1]}}}, "b": {"inputs": {"x": {"notes": [2]}}}}}, "two devices"),
    ({"other": {}}, "unknown sections"),
])
def test_bad_inputs(bad, msg):
    with pytest.raises(ConfigError, match=msg):
        parse_inputs(bad)


def test_two_inputs_on_one_message_need_shared():
    two = {"devices": {"k": {"channel": 10, "inputs": {"a": {"notes": [38]}, "b": {"notes": [38]}}}}}
    with pytest.raises(ConfigError, match="both claim"):
        parse_inputs(two)
    for i in ("a", "b"):
        two["devices"]["k"]["inputs"][i]["shared"] = True
    assert len(parse_inputs(two)) == 2
    # split by velocity: soft and hard hits are different inputs, no clash
    vel = {"devices": {"k": {"channel": 10, "inputs": {"soft": {"notes": [38], "velocity": [1, 63]},
                                                       "hard": {"notes": [38], "velocity": [64, 127]}}}}}
    ins = parse_inputs(vel)
    assert [i.id for i in ins.match("note", 10, 38, "", 30)] == ["soft"]
    assert [i.id for i in ins.match("note", 10, 38, "", 100)] == ["hard"]
    # different ports never clash (a port-specific input wins)
    ports = {"devices": {"k": {"channel": 10, "inputs": {"td": {"notes": [38]}, "pad": {"notes": [38], "port": "H2MIDI"}}}}}
    ins = parse_inputs(ports)
    assert [i.id for i in ins.match("note", 10, 38, "H2MIDI PRO 0")] == ["pad"]
    assert [i.id for i in ins.match("note", 10, 38, "UM-ONE")] == ["td"]


def test_any_channel():
    ins = parse_inputs({"devices": {"k": {"inputs": {"x": {"notes": [36], "channel": "any"}}}}})
    assert [i.id for i in ins.match("note", 3, 36)] == ["x"] and [i.id for i in ins.match("note", 10, 36)] == ["x"]


def test_velocity_curve():
    i = InputDef("x", "x", "d", "note", 10, [1])
    assert i.strength(127) == 1.0 and i.strength(0) == 0.0 and i.strength(64) == pytest.approx(64 / 127)
    i.curve = {"quiet": 20, "normal": 60, "loud": 100}
    assert i.strength(20) == pytest.approx(0.25)
    assert i.strength(60) == pytest.approx(0.6)
    assert i.strength(100) == 1.0 and i.strength(127) == 1.0
    assert 0.25 < i.strength(40) < 0.6


# ------------------------------------------------------------------ routing


def test_mappings_by_name(engine, midi, view):
    assert midi.program(0) == "MASTER off"
    assert midi.note(38, 127).startswith("flash bars")  # snare head
    assert view("bar_1", "blue", 0) == 255
    assert midi.note(40, 127).startswith("flash bars")  # snare rim: same input
    assert midi.cc(7, 64) == "grand_master 50%"
    assert midi.note(38, 100, channel=9) == "unmapped"


def test_monitor_shows_input_name(router, midi):
    midi.note(38, 98)
    e = router.monitor.entries[-1]
    assert e.input == "Snare" and "Snare, vel 98" in e.format()
    midi.note(99, 1)
    assert router.monitor.entries[-1].input == ""


def test_changing_a_note_in_one_place_moves_every_use(engine, inputs, view):
    """The snare moves to note 39: the flash follows with no change to the MIDI map."""
    data = inputs.to_dict()
    data["devices"]["kit"]["inputs"]["snare"]["notes"] = [39]
    r = MidiRouter(engine, parse_map(MAP), MidiMonitor(), inputs=parse_inputs(data))
    m = FakeMidiIn(r.handle_mido)
    engine.set_master(False)
    assert m.note(38, 127) == "unmapped"
    assert m.note(39, 127).startswith("flash bars")


def test_calibrated_curve_sets_flash_level(engine, midi, view):
    engine.set_master(False)
    midi.note(49, 20)  # crash: quiet hit -> 25 % (on the wash's dimmer)
    assert abs(view("wash", "dimmer") - 0.25 * 255) <= 2
    midi.note(49, 100)  # loud -> full
    assert view("wash", "dimmer") == 255


def test_osc_named_input(engine, router):
    assert router.handle_osc("/btn/1", []).startswith("blackout")
    assert engine.blackout


def test_raw_mappings_still_work_alongside(engine, inputs):
    r = MidiRouter(engine, parse_map({"mappings": [{"type": "program_change", "channel": 1, "number": 5,
                                                    "action": "blackout_toggle"}]}), MidiMonitor(), inputs=inputs)
    assert FakeMidiIn(r.handle_mido).program(5) == "blackout on"


def test_input_listeners_get_every_named_hit(router, midi):
    got = []
    router.input_listeners.append(lambda i, m, now: got.append((i.id, m.value)))
    midi.note(36, 90)
    midi.note(38, 70)
    midi.note(1, 1)
    assert got == [("kick", 90), ("snare", 70)]


def test_kick_role_drives_tempo_from_any_device(engine, tmp_path):
    """A keyboard's note with the kick role taps the tempo; the rig's kick note isn't used."""
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups"))
    rig = yaml.safe_load((root / "rigs" / "full.yaml").read_text())
    rig["tempo"] = {"source": "kick", "kick_note": 36}
    (root / "rigs" / "full.yaml").write_text(yaml.safe_dump(rig))
    files = load_show(root)
    ins = parse_inputs({"devices": {"keys": {"channel": 2, "inputs": {"low_c": {"notes": [48], "roles": ["kick"]}}}}})
    from dmx_suite.engine import Engine
    from dmx_suite.output import LogDriver

    clock_t = [100.0]
    e = Engine(files.rig, [LogDriver()], files.look, clock=lambda: clock_t[0])
    ctl = ShowController(e, files)
    r = MidiRouter(e, files.midimap, MidiMonitor(), ctl, ins)
    m = FakeMidiIn(r.handle_mido)
    ctl.tempo.tap(clock_t[0])
    ctl.tempo.tap(clock_t[0] + 0.52)  # v6: the drums tracker starts from a tap (115)
    clock_t[0] += 0.52
    # what app._input_hit does for role hits:
    r.input_listeners.append(lambda inp, msg, now: ctl.tempo.hit(inp.roles, msg.value, now) if msg.pressed else None)
    for _ in range(24):
        m.note(48, 100, channel=2)
        m.note(36, 100, channel=10)  # the drum kick note: no kick role here, ignored
        clock_t[0] += 0.5
        ctl.tempo.eff(clock_t[0])
    assert ctl.tempo.bpm == pytest.approx(120, abs=1)


# ------------------------------------------------------------------ learn


def test_learn_an_input(router, midi):
    got = []
    router.learn_input("kick", got.append)
    assert router.learning == "input kick"
    assert midi.note(35, 90) == "learned input kick"
    assert got == [{"type": "note", "channel": 10, "number": 35, "port": "sim", "address": ""}]
    assert router.learning is None


def test_learn_action_reuses_an_input(router, midi):
    router.learn("blackout_toggle")
    midi.note(36, 100)  # kick already exists
    assert router.map.get_input("kick").action == "blackout_toggle" and router.new_inputs == []


def test_suggest_names():
    assert suggest("note", 10, 38) == ("snare", "Snare", ["snare", "activity"])
    assert suggest("note", 10, 38, taken={"snare"})[0] == "snare_2"
    assert suggest("program_change", 1, 5)[:2] == ("pc_5", "PC 5")
    assert suggest("control_change", 2, 7)[0] == "cc_7_ch2"
    assert suggest("osc", 0, 0, "/fader/3")[0] == "osc_fader_3"
    assert suggest("note", 10, 38, port="H2MIDI")[0] == "snare_h2midi"


# ------------------------------------------------------------------ references and the store


def test_refs_and_rename():
    data = {"mappings": [{"input": "snare", "action": "x"}, {"input": "kick"}], "advance": {"inputs": ["snare", "x"]}}
    assert refs(data, "snare") == 2 and refs(data, "tom") == 0
    assert refs(rename_refs(data, "snare", "sn"), "sn") == 2


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups"))
    return ShowStore(root)


def test_shipped_inputs_load():
    files = load_show(SHOWS)
    assert files.inputs.get("snare").numbers == [38]
    assert {m.input for m in files.midimap.mappings} <= set(files.inputs.inputs)
    assert files.inputs.has_role("kick")


def test_store_put_rename_delete(store):
    store.put_input("td25", "cowbell", {"name": "Cowbell", "type": "note", "notes": [56], "roles": ["activity"]})
    assert load_show(store.root).inputs.get("cowbell").numbers == [56]
    with pytest.raises(StoreError, match="still used"):
        store.delete_input("snare")
    assert "midi/default.yaml (1)" in store.input_users("snare")
    store.rename_input("snare", "snare_head")
    files = load_show(store.root)
    assert files.midimap.get_input("snare_head").action == "flash" and "snare" not in files.inputs
    store.delete_input("cowbell")
    assert "cowbell" not in load_show(store.root).inputs


def test_store_refuses_clashes_and_missing_inputs(store):
    with pytest.raises(StoreError, match="both claim"):
        store.put_input("td25", "snare_again", {"type": "note", "notes": [38]})
    with pytest.raises(StoreError, match="no such input"):
        store.put("midi", "default", {"mappings": [{"input": "nope", "action": "master_toggle"}]})
    with pytest.raises(StoreError, match="needs a control_change or OSC"):
        store.put("midi", "default", {"mappings": [{"input": "snare", "action": "grand_master"}]})


def test_change_one_input_note_updates_every_use(store):
    """Scope: change an input's note once; every flash, busk widget and select follows."""
    data = store.read("inputs")
    data["devices"]["td25"]["inputs"]["crash"]["notes"] = [57]
    store.put("inputs", "", data)
    files = load_show(store.root)
    from dmx_suite.engine import Engine
    from dmx_suite.output import LogDriver

    e = Engine(files.rig, [LogDriver()], files.look)
    e.set_master(False)
    r = MidiRouter(e, files.midimap, MidiMonitor(), inputs=files.inputs)
    m = FakeMidiIn(r.handle_mido)
    assert m.note(49, 127) == "unmapped"
    assert m.note(57, 127).startswith("flash all")


def test_device_profiles(store):
    names = {p["id"] for p in device_profiles(store.root)}
    assert {"td25", "samplepad4", "fcb1010", "gm_drums"} <= names
    data = load_device_profile(store.root, "samplepad4")
    data["port"] = "H2MIDI"
    store.put_device("samplepad", data)
    files = load_show(store.root)
    assert files.inputs.get("pad_1").port == "H2MIDI"
    store.export_device("samplepad")
    assert (store.root / "devices" / "samplepad.yaml").exists()
    assert any(p["id"] == "samplepad" and p["from"] == "show" for p in device_profiles(store.root))
    assert check_all(store.root) == [p for p in check_all(store.root) if p.startswith("warning")]


def test_device_profiles_all_parse():
    for p in device_profiles():
        load_device_profile(None, p["id"])


def test_put_device_refuses_dropping_used_inputs(store):
    data = store.read("inputs")["devices"]["td25"]
    data = {**data, "inputs": {k: v for k, v in data["inputs"].items() if k != "snare"}}
    with pytest.raises(StoreError, match="still used"):
        store.put_device("td25", data)


def test_gig_lock_blocks_input_edits(tmp_path):
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups"))
    s = ShowStore(root, lambda: True)
    with pytest.raises(StoreError, match="gig lock"):
        s.put_input("td25", "cowbell", {"type": "note", "notes": [56]})


# ------------------------------------------------------------------ rules


def test_named_inputs_keep_every_rule():
    ins = parse_inputs(INPUTS)

    def drive(e, clock):
        r = MidiRouter(e, parse_map(MAP), MidiMonitor(), inputs=ins)
        m = FakeMidiIn(r.handle_mido)
        m.program(0)  # MASTER off (0.05 band: drum flash on)
        for n in (38, 40, 49, 36):
            m.note(n, 127)
        m.cc(7, 100)
        m.program(0)  # MASTER back on

    rule_matrix(drive, seconds=1.0)


def test_inputs_never_reach_haze_without_haze_actions(engine, view):
    """Every non-haze action on every input: the haze channel stays at 0 (rule 5)."""
    ins = parse_inputs(INPUTS)
    r = MidiRouter(engine, parse_map(MAP), MidiMonitor(), inputs=ins)
    m = FakeMidiIn(r.handle_mido)
    for _ in range(3):
        m.program(0)
        for n in (36, 38, 40, 49):
            m.note(n, 127)
        m.cc(7, 127)
        engine.tick()
        assert view("smoke", "haze") == 0


def test_empty_inputs_object():
    assert len(Inputs()) == 0 and Inputs().match("note", 10, 38) == []
