"""File format 6 (v4): Ride -> Autopilot (pick `ride` -> `feel`), busking -> Override, driver ids
by what the interface does. A format 5 folder upgrades once with backups and comments kept; the
v3 names still load in memory; behaviour doesn't change."""

import shutil
from pathlib import Path

import yaml

from dmx_suite.fxbanks import Pick, norm_pick
from dmx_suite.midi.map import Mapping, canonical, parse_map
from dmx_suite.output import DRIVERS, driver_id, make_driver
from dmx_suite.showfiles import load_show
from dmx_suite.store import ShowStore
from dmx_suite.versions import FORMAT, upgrade

SHOWS = Path(__file__).resolve().parents[1] / "shows"


def v5_folder(tmp_path: Path) -> Path:
    """The shipped shows written the v3 way (format 5)."""
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json", ".giglock"))
    for p in root.rglob("*.yaml"):
        p.write_text(p.read_text(encoding="utf-8").replace(f"version: {FORMAT}", "version: 5"), encoding="utf-8")
    rig = root / "rigs" / "full.yaml"
    text = rig.read_text(encoding="utf-8").replace("{driver: usb_dmx_open, port: COM3, universe: 0}",
                                                   "{driver: enttec_open, port: COM3}")
    text += "\nautopilot:\n  talking: {colour: static, palette: white, ride: {speed: 0.4, fade: 1.0}}   # quiet between songs\n"
    rig.write_text(text, encoding="utf-8")
    (root / "presets.yaml").write_text(
        "version: 5\npresets:\n  slow:   # my slow one\n    name: Slow\n    tags: [low]\n"
        "    pick: {colour: static, palette: warm, ride: {speed: 0.5}, bank_ride: {colour: {fan: 0.2}}}\n", encoding="utf-8")
    midi = root / "midi" / "default.yaml"
    midi.write_text(midi.read_text(encoding="utf-8").replace(
        "  - {input: expression, action: grand_master}     # expression pedal",
        "  - {input: expression, action: ride_speed}     # expression pedal"), encoding="utf-8")
    return root


def test_format_is_6_or_later():
    assert FORMAT >= 6


def test_v3_names_load_in_memory(tmp_path):
    files = load_show(v5_folder(tmp_path))
    assert files.midimap.get_input("expression").action == "feel_speed"
    assert files.rig.autopilot["between"]["look"]["feel"] == {"speed": 0.4, "fade": 1.0}  # v7: in between
    assert files.presets["slow"]["pick"]["feel"] == {"speed": 0.5}


def test_upgrade_writes_v4_names_and_keeps_comments(tmp_path):
    root = v5_folder(tmp_path)
    bid, names = ShowStore(root).upgrade()
    assert bid and {"rigs/full.yaml", "presets.yaml", "midi/default.yaml"} <= set(names)
    assert (root / ".backups" / bid / "presets.yaml").exists()
    rig_text = (root / "rigs" / "full.yaml").read_text(encoding="utf-8")
    rig = yaml.safe_load(rig_text)
    assert rig["version"] == FORMAT
    assert rig["outputs"] == [{"driver": "usb_dmx_open", "port": "COM3"}]  # no universe: written: the loader warns
    look = rig["autopilot"]["between"]["look"]  # v7 moved talking into between
    assert look["feel"] == {"speed": 0.4, "fade": 1.0} and "ride" not in look
    assert "# Head position points" in rig_text  # (v7 moves `talking` into `between:`; its own comment goes with the old key)
    pre_text = (root / "presets.yaml").read_text(encoding="utf-8")
    pick = yaml.safe_load(pre_text)["presets"]["slow"]["pick"]
    assert pick["feel"] == {"speed": 0.5} and pick["bank_feel"] == {"colour": {"fan": 0.2}}
    assert "ride" not in pick and "# my slow one" in pre_text
    midi_text = (root / "midi" / "default.yaml").read_text(encoding="utf-8")
    assert "action: feel_speed" in midi_text and "ride_speed" not in midi_text and "# expression pedal" in midi_text
    assert "{input: ride, action: flash" in midi_text  # the ride cymbal keeps its name
    load_show(root)  # still loads
    assert ShowStore(root).upgrade() == (None, [])  # once only


def test_aliases():
    assert canonical("busk") == "override" and canonical("ride_fx") == "autopilot_fx" and canonical("flash") == "flash"
    assert Mapping("note", 1, 60, "busk", {"panel": "p", "widget": "w"}).action == "override"
    m = parse_map({"mappings": [{"input": "x", "action": "ride_palette", "palette": "fire"}]}).mappings[0]
    assert m.action == "autopilot_palette"
    assert norm_pick({"ride": {"speed": 2}})["feel"] == {"speed": 2}
    assert Pick.from_dict({"ride": {"speed": 2.0}}).to_dict()["feel"]["speed"] == 2.0
    assert driver_id("enttec_open") == "usb_dmx_open" and driver_id("node_serial") == "node"
    assert {"usb_dmx_open", "usb_dmx_pro", "node"} <= set(DRIVERS)
    assert make_driver({"driver": "log", "universe": 0}).__class__.__name__ == "LogDriver"


def test_upgrade_step_only_touches_v3_keys():
    data = upgrade({"version": 5, "mappings": [{"input": "a", "action": "busk", "panel": "p", "widget": "w"}]}, "midi")
    assert data["mappings"][0]["action"] == "override"
