"""v4 item 11: pixel (segment) selections - `bar_1:px3`, `bars:px1,8`, `bars:odd`, saved pixel groups -
in scene layers and step `set:` keys; colour only; the rules under both profiles."""

import shutil
from pathlib import Path

import pytest
import screenshot_rig
import yaml

from dmx_suite.engine import Engine
from dmx_suite.fixtures import ConfigError, parse_patch, parse_pixels
from dmx_suite.look import LookError
from dmx_suite.output import LogDriver
from dmx_suite.palettes import Palettes
from dmx_suite.rig import parse_rig
from dmx_suite.scenes import ScenePlayer, parse_scene
from dmx_suite.showfiles import load_show
from dmx_suite.store import ShowStore

from conftest import PATCH, RIG
from rulecheck import rule_matrix

SHOWS = Path(__file__).resolve().parents[1] / "shows"
RED, BLUE = {"red": 1.0}, {"blue": 1.0}


def hue(c):
    """The lit emitters of a colour, e.g. {'red': 1.0}."""
    return {k: v for k, v in c.items() if v}


def test_selector_grammar():
    assert parse_pixels("px3", 8, "x") == {2}
    assert parse_pixels("px1-4", 8, "x") == {0, 1, 2, 3}
    assert parse_pixels("px1,8", 8, "x") == {0, 7}
    assert parse_pixels("px1-2,7-8", 8, "x") == {0, 1, 6, 7}
    assert parse_pixels("odd", 8, "x") == {0, 2, 4, 6} and parse_pixels("even", 8, "x") == {1, 3, 5, 7}
    assert parse_pixels("first3", 8, "x") == {0, 1, 2} and parse_pixels("last2", 8, "x") == {6, 7}
    for bad in ("px9", "px0", "px4-2", "pxa", "middle", "first9"):
        with pytest.raises(ConfigError):
            parse_pixels(bad, 8, "x")


def files():
    return load_show(SHOWS)


def test_resolve_targets_and_pixel_groups():
    p = files().patch
    got = p.resolve_targets(["bars:px1,8", "bar_1:px3", "wash_l"])
    assert got["bar_1"] == {0, 2, 7} and got["bar_2"] == {0, 7} and got["wash_l"] is None
    assert p.resolve_targets(["bar_1:px1", "bar_1"])["bar_1"] is None  # named whole too: whole
    assert p.resolve(["bars:odd"]) == ["bar_1", "bar_2", "bar_3", "bar_4"]  # whole-light callers
    with pytest.raises(ConfigError, match="no pixel lights"):
        p.resolve_targets(["washes:px1"])
    data = yaml.safe_load((SHOWS / "fixtures.yaml").read_text())
    data["pixel_groups"] = {"bar_tips": "bars:px1,8", "bars_centre": ["bars:px4-5"]}
    pg = parse_patch(data)
    assert pg.resolve_targets(["bar_tips"])["bar_3"] == {0, 7} and pg.resolve_targets(["bars_centre"])["bar_1"] == {3, 4}
    for bad in ({"bars": "bars:px1"}, {"x": "bars"}, {"x": "bars:px20"}):
        with pytest.raises(ConfigError):
            parse_patch({**data, "pixel_groups": bad})


def play(data, f=None, t=0.0):
    f = f or files()
    sc = parse_scene({"name": "s", **data}, f.patch, f.palettes, "s")
    return ScenePlayer(sc, f.rig, 0.0)(t)


def test_static_colour_on_selected_pixels_only():
    look = play({"layers": [{"fixtures": ["bar_1:px1-4"], "colour": "#ff0000"}]})
    px = look.fixtures["bar_1"].pixels
    assert [p.get("red", 0) for p in px] == [1, 1, 1, 1, 0, 0, 0, 0]  # the rest fully off (rule 4)
    look = play({"layers": [{"fixtures": ["bars"], "colour": "#0000ff"}, {"fixtures": ["bars:px1,8"], "colour": "#ff0000"}]})
    px = look.fixtures["bar_2"].pixels
    assert hue(px[0]) == RED and hue(px[7]) == RED and hue(px[3]) == BLUE  # unselected keep the layer underneath


def test_effects_run_over_the_selected_pixels():
    look = play({"layers": [{"fixtures": ["bar_1:px1-4"], "effect": "linear_wave", "colour": "red", "period_s": 2}]}, t=0.3)
    px = look.fixtures["bar_1"].pixels
    assert all(p == {} or not any(p.values()) for p in px[4:])  # nothing outside the selection
    assert any(any(p.values()) for p in px[:4])


def test_step_set_keys_take_selectors_and_track():
    data = {"type": "steps", "step_s": 1, "steps": [
        {"set": {"bars": {"colour": "#0000ff"}}},
        {"set": {"bars:odd": {"colour": "#ff0000"}}},  # only odd pixels change; even ones track blue
    ]}
    f = files()
    sc = parse_scene({"name": "s", **data}, f.patch, f.palettes, "s")
    player = ScenePlayer(sc, f.rig, 0.0)
    look = player(1.5)
    px = look.fixtures["bar_4"].pixels
    assert hue(px[0]) == RED and hue(px[1]) == BLUE and hue(px[2]) == RED


def test_pixel_selections_are_colour_only():
    f = files()
    for layer in ({"fixtures": ["bar_1:px1"], "intensity": 0.5}, {"fixtures": ["bar_1:px1"], "position": "drum_kit"}):
        with pytest.raises((LookError, ConfigError), match="colour only|pan/tilt|rule 1"):
            parse_scene({"name": "s", "layers": [layer]}, f.patch, f.palettes, "s")


def test_rules_hold_with_pixel_selections_both_profiles():
    def act(e, clock):
        p = e.rig.patch
        pal = Palettes()
        sc = parse_scene({"name": "s", "layers": [{"fixtures": ["bars:px1"], "effect": "linear_wave", "colour": "#ff0000"},
                                                 {"fixtures": ["bar_2:px2"], "colour": "#0000ff"}]}, p, pal, "s")
        e.set_source(ScenePlayer(sc, e.rig, clock()))

    rule_matrix(act, seconds=1.0, unused=("wash", "uk"))


def test_master_drives_every_segment_dimmer(tmp_path):
    """The 48-channel LCB803 (8 x dimmer/R/G/B/strobe/fixed): MASTER on lights all 8 segment dimmers, so a
    pixel-only look isn't dark under 0.05 band; MASTER off darkens all 8; segment strobes stay open."""
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json"))
    f = load_show(screenshot_rig.make(root))
    assert f.rig.profile.master_gate
    bar = f.patch.fixtures["bar_1"]
    dimmers = [bar.slot(c) for c in bar.type.channels if c.role == "dimmer"]
    strobes = [bar.slot(c) for c in bar.type.channels if c.role == "strobe"]
    reds = [bar.slot(c) for c in bar.type.channels if c.role == "red"]
    assert len(dimmers) == 8 and len(strobes) == 8
    log = LogDriver()
    e = Engine(f.rig, [log], f.look)
    sc = parse_scene({"name": "s", "layers": [{"fixtures": ["bar_1:px2,7"], "colour": "#ff0000"}]}, f.patch, f.palettes, "s")
    e.set_source(ScenePlayer(sc, f.rig, e.clock()))
    e.set_master(True)
    e.output()
    frame = e.frames[0]
    assert all(frame[s] == 255 for s in dimmers)  # not just px1
    assert [frame[s] for s in reds] == [0, 255, 0, 0, 0, 0, 255, 0]
    assert all(frame[s] == 0 for s in strobes)  # open (default)
    e.set_master(False)
    e.output()
    assert all(e.frames[0][s] == 0 for s in dimmers) and all(e.frames[0][s] == 0 for s in reds)


def test_renaming_a_group_rewrites_pixel_selectors_and_step_keys(tmp_path):
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json"))
    store = ShowStore(root)
    store.put("scene", "px", {"name": "px", "type": "steps", "steps": [{"set": {"bars:px1,8": {"colour": "#ff0000"}}},
                                                                        {"set": {"bars": {"colour": "#0000ff"}}}],
                              "layers": [{"fixtures": ["bars:odd"], "effect": "sparkle", "colour": "white"}]})
    store.edit_group("rename", "bars", new_name="strips")
    data = yaml.safe_load((root / "scenes" / "px.yaml").read_text())
    assert list(data["steps"][0]["set"]) == ["strips:px1,8"] and list(data["steps"][1]["set"]) == ["strips"]
    assert data["layers"][0]["fixtures"] == ["strips:odd"]


def test_conftest_patch_still_resolves():
    p = parse_patch(PATCH)
    r = parse_rig(RIG, p)
    assert r.patch.resolve(["bars"]) == ["bar_1", "bar_2"]
