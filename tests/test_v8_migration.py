"""File format 8 (v8 Part A): the FX settings panel. Format 7's `auto: exclude_fx / exclude_palettes`
become priority 0 under `autopilot:`; the bank ids `sweep` / `sweep_dark` are Directional wave
(`dir_wave` / `dir_wave_dark`) wherever they're named; Chase hit and Rig split hit mappings fire
Colour hit with a note. Upgraded once with a backup, comments kept; frames don't change."""

import logging
import shutil
from pathlib import Path

import pytest
import yaml

from dmx_suite.autopilot import parse_config
from dmx_suite.fxbanks import BY_ID
from dmx_suite.showfiles import load_show
from dmx_suite.store import ShowStore
from dmx_suite.versions import FORMAT, FormatError, upgrade

SHOWS = Path(__file__).resolve().parents[1] / "shows"

V7_RIG = ("\nauto:\n  exclude_fx: [static, police, sweep]   # too plain for us\n  exclude_palettes: [ice]\n"
          "autopilot:\n  moods: {low: 70}\n  walk_on: {colour: sweep_dark, palette: band}\n")


def v7_folder(tmp_path: Path) -> Path:
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json", ".giglock"))
    for p in root.rglob("*.yaml"):
        p.write_text(p.read_text(encoding="utf-8").replace(f"version: {FORMAT}", "version: 7"), encoding="utf-8")
    rig = root / "rigs" / "full.yaml"
    rig.write_text(rig.read_text(encoding="utf-8") + V7_RIG, encoding="utf-8")
    (root / "presets.yaml").write_text("version: 7\npresets:\n  waves: {name: Waves, pick: {colour: sweep, palette: cool}}\n",
                                       encoding="utf-8")
    (root / "ratings.yaml").write_text("version: 7\nlooks:\n  'pan_sweep|sweep|-|cool': 1\n  'kit|sweep_dark|-|warm': -2\n",
                                       encoding="utf-8")
    return root


def test_format_is_8():
    assert FORMAT == 8


def test_rig_exclude_lists_become_priority_0():
    d = upgrade({"version": 7, "auto": {"classes": {"uk_a": "wash"}, "exclude_fx": ["static", "sweep"],
                                        "exclude_palettes": ["ice"]},
                 "autopilot": {"fx": {"static": {"darkness": "exempt"}}}}, "rig")
    assert d["auto"] == {"classes": {"uk_a": "wash"}}
    assert d["autopilot"]["fx"] == {"static": {"darkness": "exempt", "priority": 0}, "dir_wave": {"priority": 0}}
    assert d["autopilot"]["palette_settings"] == {"ice": {"priority": 0}}
    parse_config(d["autopilot"])


def test_rig_with_only_exclude_lists_loses_auto():
    d = upgrade({"version": 7, "auto": {"exclude_fx": ["police"]}}, "rig")
    assert "auto" not in d and d["autopilot"] == {"fx": {"police": {"priority": 0}}}


def test_rig_looks_renamed():
    d = upgrade({"version": 7, "autopilot": {"walk_off": {"colour": "sweep"},
                                             "between": {"look": {"colour": "sweep_dark", "move": "kit"}}}}, "rig")
    assert d["autopilot"]["walk_off"] == {"colour": "dir_wave"}
    assert d["autopilot"]["between"]["look"] == {"colour": "dir_wave_dark", "move": "kit"}


def test_presets_and_ratings_renamed():
    p = upgrade({"version": 7, "presets": {"x": {"name": "X", "pick": {"colour": "sweep", "move": "fan"}}}}, "presets")
    assert p["presets"]["x"]["pick"] == {"colour": "dir_wave", "move": "fan"}
    r = upgrade({"version": 7, "looks": {"pan_sweep|sweep|-|cool": 1, "kit|sweep_dark|-|warm": -2}}, "ratings")
    assert r["looks"] == {"pan_sweep|dir_wave|-|cool": 1, "kit|dir_wave_dark|-|warm": -2}  # pan_sweep is a move: kept


def test_removed_flash_fx_become_colour_hit_with_a_note(caplog):
    with caplog.at_level(logging.WARNING):
        m = upgrade({"version": 7, "mappings": [
            {"input": "pad_3", "action": "flash_fx", "fx": "chase_hit"},
            {"input": "pad_4", "action": "flash_fx", "fx": "split_hit", "side": "right"},
            {"input": "pad_5", "action": "flash_fx", "fx": "strobe"},
            {"input": "pedal_1", "action": "autopilot_fx", "bank": "colour", "item": "sweep"}]}, "midi")
    fx = m["mappings"]
    assert [x.get("fx") for x in fx[:3]] == ["colour_hit", "colour_hit", "strobe"]
    assert "side" not in fx[1]
    assert fx[3]["item"] == "dir_wave"
    notes = [r.getMessage() for r in caplog.records]
    assert any("pad_3" in n and "Chase hit is now Colour hit" in n for n in notes)
    assert any("pad_4" in n and "Rig split hit is now Colour hit" in n for n in notes)
    assert len(notes) == 2


def test_kit_trigger_flash_fx_moved():
    d = upgrade({"version": 7, "kits": {"td25": {"pieces": {"snare": {"zones": {
        "head": {"input": "snare", "trigger": {"flash_fx": "chase_hit"}}}}}}}}, "inputs")
    assert d["kits"]["td25"]["pieces"]["snare"]["zones"]["head"]["trigger"] == {"flash_fx": "colour_hit"}


def test_renamed_ids_exist_and_old_ones_gone():
    assert BY_ID["dir_wave"].label == "Directional wave" and "sweep" not in BY_ID
    assert BY_ID["dir_wave_dark"].layer["effect"] == "dir_sweep"
    assert "chase_hit" not in BY_ID and "split_hit" not in BY_ID


def test_v7_folder_upgrades_once_with_backup_and_comments(tmp_path):
    root = v7_folder(tmp_path)
    files = load_show(root)  # in memory first
    assert {k for k, v in files.rig.autopilot["fx"].items() if v.get("priority") == 0} == {"static", "police", "dir_wave"}
    bid, names = ShowStore(root).upgrade()
    assert bid and {"rigs/full.yaml", "presets.yaml", "ratings.yaml"} <= set(names)
    assert (root / ".backups" / bid / "rigs" / "full.yaml").exists()
    text = (root / "rigs" / "full.yaml").read_text(encoding="utf-8")
    rig = yaml.safe_load(text)
    assert rig["version"] == 8 and "auto" not in rig
    assert rig["autopilot"]["fx"] == {"static": {"priority": 0}, "police": {"priority": 0}, "dir_wave": {"priority": 0}}
    assert rig["autopilot"]["palette_settings"] == {"ice": {"priority": 0}}
    assert rig["autopilot"]["walk_on"]["colour"] == "dir_wave_dark"
    assert yaml.safe_load((root / "presets.yaml").read_text())["presets"]["waves"]["pick"]["colour"] == "dir_wave"
    again = load_show(root)
    assert again.rig.autopilot["fx"]["dir_wave"]["priority"] == 0
    assert ShowStore(root).upgrade() == (None, []) or not ShowStore(root).upgrade()[1]  # nothing left to do


def test_newer_format_refused():
    with pytest.raises(FormatError, match="newer"):
        upgrade({"version": FORMAT + 1}, "rig")


def test_excluded_after_upgrade_never_picked(tmp_path):
    from dmx_suite.classify import auto_rig
    from dmx_suite.fxbanks import available

    files = load_show(v7_folder(tmp_path))
    ar = auto_rig(files.rig)
    assert {"static", "police", "dir_wave"} <= ar.excluded_fx and ar.excluded_palettes == {"ice"}
    assert not {i.id for i in available(ar, "colour", skip_excluded=True)} & {"static", "police", "dir_wave"}
