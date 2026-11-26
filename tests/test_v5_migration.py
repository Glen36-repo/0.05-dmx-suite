"""File format 5 (v3.1): a format 4 show folder upgrades once, with backups; raw MIDI mappings
become named inputs and palette positions become head points, and nothing the band sees changes:
the same frames for every scene and show, the same reaction to every MIDI message."""

import json
import shutil
from pathlib import Path

import pytest
import yaml

from dmx_suite.engine import Engine
from dmx_suite.midi.inputs import FakeMidiIn
from dmx_suite.midi.monitor import MidiMonitor
from dmx_suite.midi.router import MidiRouter
from dmx_suite.migrate import mappings_to_inputs, positions_to_points
from dmx_suite.output import LogDriver
from dmx_suite.showfiles import check_all, load_show
from dmx_suite.store import ShowStore
from dmx_suite.versions import FORMAT

from golden import GOLDEN, capture

DATA = Path(__file__).parent / "data" / "v4_shows"


def v4_folder(tmp_path: Path) -> Path:
    """The shipped shows as they were in file format 4 (v2 R8)."""
    root = tmp_path / "shows"
    shutil.copytree(DATA, root)
    return root


def test_format_is_5():
    assert FORMAT == 5


def test_v4_folder_still_loads_as_it_is(tmp_path):
    """Before the upgrade is written (e.g. running the last good backup), format 4 loads in memory."""
    files = load_show(v4_folder(tmp_path))
    assert files.midimap.get("note", 10, 38).action == "flash"
    assert "drum_kit" in files.palettes.positions


def test_upgrade_moves_mappings_and_positions(tmp_path):
    root = v4_folder(tmp_path)
    bid, names = ShowStore(root).upgrade()
    assert bid and "midi/default.yaml" in names
    assert (root / ".backups" / bid / "midi" / "default.yaml").exists()  # originals kept
    inputs = yaml.safe_load((root / "inputs.yaml").read_text())
    assert inputs["version"] == 5
    drums = inputs["devices"]["drums"]["inputs"]
    assert drums["snare"] == {"name": "Snare", "type": "note", "notes": [38], "roles": ["snare", "activity"]}
    midi = yaml.safe_load((root / "midi" / "default.yaml").read_text())
    assert {"input": "snare", "action": "flash", "fixtures": ["bars"], "length_ms": 120, "colour": "show"} in midi["mappings"]
    assert all("input" in m for m in midi["mappings"])
    assert "# FCB1010" in (root / "midi" / "default.yaml").read_text()  # comments kept
    pal = yaml.safe_load((root / "palettes.yaml").read_text())
    assert "positions" not in pal
    full = yaml.safe_load((root / "rigs" / "full.yaml").read_text())
    assert full["positions"]["drum_kit"]["heads"] == {"mh_a": {"pan": 0.42, "tilt": 0.3}, "mh_b": {"pan": 0.58, "tilt": 0.3}}
    assert full["positions"]["centre"]["heads"]["mh_b"] == {"pan": 0.5, "tilt": 0.5}  # same-for-all written per head
    small = yaml.safe_load((root / "rigs" / "small.yaml").read_text())
    assert "positions" not in small  # no heads in the small rig
    assert [p for p in check_all(root) if not p.startswith("warning")] == []


def test_upgrade_is_done_once(tmp_path):
    root = v4_folder(tmp_path)
    s = ShowStore(root)
    s.upgrade()
    assert s.upgrade() == (None, [])


def test_frames_identical_after_upgrade(tmp_path):
    """Every scene and show renders the same frames before and after (golden v1 frames)."""
    root = v4_folder(tmp_path)
    before = capture(root=root)
    ShowStore(root).upgrade()
    assert capture(root=root) == before
    assert before == json.loads(GOLDEN.read_text(encoding="utf-8"))


MESSAGES = [("program", 0), ("note", 38), ("note", 40), ("note", 48), ("note", 45), ("note", 49), ("note", 51),
            ("cc", 7), ("program", 1), ("program", 9), ("program", 9), ("program", 0), ("note", 38), ("note", 99),
            ("program", 13), ("cc", 80), ("program", 5), ("program", 7)]


def replay(root: Path) -> list[tuple[str, str]]:
    files = load_show(root)
    t = [1000.0]
    e = Engine(files.rig, [LogDriver()], files.look, clock=lambda: t[0])
    from dmx_suite.showctl import ShowController

    r = MidiRouter(e, files.midimap, MidiMonitor(), ShowController(e, files), files.inputs)
    m = FakeMidiIn(r.handle_mido)
    out = []
    for kind, n in MESSAGES:
        res = m.program(n) if kind == "program" else m.note(n, 100) if kind == "note" else m.cc(n, 100)
        e.tick()
        out.append((res.split(": ", 1)[-1] if res.startswith(("Snare", "Crash")) else res,
                    bytes(e.frames[0]).hex()))
        t[0] += 0.05
    return out


def test_midi_behaviour_identical_after_upgrade(tmp_path):
    root = v4_folder(tmp_path)
    before = replay(root)
    ShowStore(root).upgrade()
    after = replay(root)
    assert [f for _, f in after] == [f for _, f in before]  # every frame the same
    assert [r for r, _ in after] == [r for r, _ in before]


def test_kick_note_gets_an_input():
    inputs, maps = mappings_to_inputs({}, {"m": {"mappings": []}}, [36])
    kick = inputs["devices"]["tempo"]["inputs"]["kick"]
    assert kick["notes"] == [36] and "kick" in kick["roles"] and kick["channel"] == "any"
    # a kick note that's already mapped gets the role on that input instead
    inputs, maps = mappings_to_inputs({}, {"m": {"mappings": [
        {"type": "note", "channel": 10, "number": 36, "action": "master_on"}]}}, [36])
    assert set(inputs["devices"]) == {"drums"}
    assert inputs["devices"]["drums"]["inputs"]["kick"]["roles"] == ["kick", "activity"]


def test_same_message_in_two_maps_is_one_input():
    m = {"mappings": [{"type": "note", "channel": 10, "number": 38, "action": "master_on"}]}
    inputs, maps = mappings_to_inputs({}, {"a": m, "b": m})
    assert maps["a"]["mappings"] == maps["b"]["mappings"] == [{"input": "snare", "action": "master_on"}]


def test_port_mappings_get_their_own_device():
    inputs, maps = mappings_to_inputs({}, {"a": {"mappings": [
        {"type": "note", "channel": 10, "number": 38, "action": "master_on"},
        {"type": "note", "channel": 10, "number": 38, "port": "H2MIDI", "action": "master_off"},
        {"type": "osc", "address": "/dmx/grand", "action": "grand_master"}]}})
    assert inputs["devices"]["drums_h2midi"]["port"] == "H2MIDI"
    assert [m["input"] for m in maps["a"]["mappings"]] == ["snare", "snare_h2midi", "osc_dmx_grand"]
    from dmx_suite.midi.named import parse_inputs

    ins = parse_inputs(inputs)
    assert [i.id for i in ins.match("note", 10, 38, "H2MIDI PRO 0")] == ["snare_h2midi"]


def test_positions_keep_existing_rig_points():
    pal = {"positions": {"a": {"pan": 0.1, "tilt": 0.2}, "b": {"mh_a": {"pan": 0.3, "tilt": 0.4}, "uk": {"pan": 0, "tilt": 0}}}}
    rigs = {"r": {"positions": {"a": {"heads": {"mh_a": {"pan": 0.9, "tilt": 0.9}}}}}}
    pal2, rigs2 = positions_to_points(pal, rigs, {"r": ["mh_a"]})
    assert "positions" not in pal2
    assert rigs2["r"]["positions"]["a"]["heads"]["mh_a"] == {"pan": 0.9, "tilt": 0.9}  # kept
    assert rigs2["r"]["positions"]["b"]["heads"] == {"mh_a": {"pan": 0.3, "tilt": 0.4}}  # colour-only uk dropped


@pytest.mark.parametrize("starter", [True])
def test_upgrade_of_a_folder_with_no_midi_or_positions(tmp_path, starter):
    root = tmp_path / "s"
    shutil.copytree(DATA, root)
    for p in (root / "midi").glob("*.yaml"):
        p.write_text("version: 4\nmappings: []\n")
    ShowStore(root).upgrade()
    assert not (root / "inputs.yaml").exists()
