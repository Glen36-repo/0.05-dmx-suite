"""File format 7 (v7): between songs gets its own `autopilot: between:` block. A format 6 rig with
gap_s / count_in / talking upgrades once with a backup and comments kept; old keys still read in
memory; behaviour doesn't change."""

import shutil
from pathlib import Path

import pytest
import yaml

from dmx_suite.autopilot import fold_between, parse_config
from dmx_suite.fixtures import ConfigError
from dmx_suite.showfiles import load_show
from dmx_suite.store import ShowStore
from dmx_suite.versions import FORMAT, upgrade

SHOWS = Path(__file__).resolve().parents[1] / "shows"

V6_AUTOPILOT = ("\nautopilot:\n  gap_s: 6   # long talks\n  count_in: 3\n"
                "  talking: {colour: static, palette: warm, move: kit}\n  moods: {low: 70}\n")


def v6_folder(tmp_path: Path) -> Path:
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json", ".giglock"))
    for p in root.rglob("*.yaml"):
        p.write_text(p.read_text(encoding="utf-8").replace(f"version: {FORMAT}", "version: 6"), encoding="utf-8")
    rig = root / "rigs" / "full.yaml"
    rig.write_text(rig.read_text(encoding="utf-8") + V6_AUTOPILOT, encoding="utf-8")
    return root


def test_format_is_7_or_later():
    assert FORMAT >= 7  # v8: 8


def test_rig_step_moves_between_keys():
    out = upgrade({"version": 6, "autopilot": {"gap_s": 6, "count_in": 3, "talking": {"colour": "static"},
                                               "moods": {"low": 70}}}, "rig")
    assert out["autopilot"] == {"moods": {"low": 70},
                                "between": {"gap_s": 6, "count_in": 3, "look": {"colour": "static"}}}


def test_rig_step_leaves_other_rigs_alone():
    assert upgrade({"version": 6, "profile": "generic"}, "rig") == {"profile": "generic"}
    assert upgrade({"version": 6, "autopilot": {"moods": {"low": 70}}}, "rig") == {"autopilot": {"moods": {"low": 70}}}


def test_fold_between_keeps_a_value_already_in_between():
    assert fold_between({"gap_s": 9, "between": {"gap_s": 5}}) == {"between": {"gap_s": 5}}


def test_old_keys_still_read_by_parse_config():
    c = parse_config({"gap_s": 6, "count_in": 3, "talking": {"palette": "warm"}})
    assert c["between"]["gap_s"] == 6 and c["between"]["count_in"] == 3
    assert c["between"]["look"]["palette"] == "warm" and c["between"]["look"]["colour"] == "static"  # merged as v6


def test_scene_looks_replace_the_default():
    c = parse_config({"between": {"look": {"scene": "talk"}}, "walk_on": {"scene": "intro"}})
    assert c["between"]["look"] == {"scene": "talk"} and c["walk_on"] == {"scene": "intro"}
    assert c["walk_off"]["palette"] == "warm"


def test_defaults():
    b = parse_config(None)["between"]
    assert b == {"on": True, "gap_s": 4.0, "start": "first_hit", "count_in": 4, "min_song_s": 20.0,
                 "fade_in": None, "fade_out": None, "ignore": [],
                 "look": {"colour": "static", "palette": "white", "move": "kit", "feel": {"speed": 0.5, "fade": 1.0}}}


@pytest.mark.parametrize("bad", [{"between": {"look": {"scene": ""}}}, {"walk_off": {"scene": 3}}])
def test_bad_scene_look(bad):
    with pytest.raises(ConfigError, match="scene"):
        parse_config(bad)


def test_v6_folder_loads_and_upgrades_with_comments(tmp_path):
    root = v6_folder(tmp_path)
    files = load_show(root)
    assert files.rig.autopilot["between"]["gap_s"] == 6
    bid, names = ShowStore(root).upgrade()
    assert bid and "rigs/full.yaml" in names
    assert (root / ".backups" / bid / "rigs" / "full.yaml").exists()
    text = (root / "rigs" / "full.yaml").read_text(encoding="utf-8")
    rig = yaml.safe_load(text)
    assert rig["version"] == FORMAT
    assert rig["autopilot"]["between"] == {"gap_s": 6, "count_in": 3, "look": {"colour": "static", "palette": "warm",
                                                                                "move": "kit"}}
    assert "gap_s" not in rig["autopilot"] or "between" in rig["autopilot"]
    assert set(rig["autopilot"]) == {"between", "moods"}
    assert load_show(root).rig.autopilot["between"]["count_in"] == 3


def test_newer_format_refused():
    from dmx_suite.versions import FormatError

    with pytest.raises(FormatError, match="newer"):
        upgrade({"version": FORMAT + 1}, "rig")
