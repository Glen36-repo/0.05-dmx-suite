"""v7 D1 drum flash = a gate on the playing scene: with MASTER off a hit opens only the ticked lights,
showing what the playing look has on each of them at that moment (colour, pixels, shutter); nothing is
added. Level from the pad's min level (default 0.6) to full. Format 7 drops the old flash `colour`."""

import logging

import pytest

from dmx_suite.engine import FLASH_MIN_LEVEL, Engine, flash_level
from dmx_suite.fixtures import ConfigError, parse_patch
from dmx_suite.kits import parse_kits
from dmx_suite.look import FixtureLook, Look, parse_look
from dmx_suite.output import LogDriver
from dmx_suite.palettes import parse_palettes
from dmx_suite.rig import parse_rig
from dmx_suite.scenes import ScenePlayer, parse_scene
from dmx_suite.versions import upgrade

from conftest import PATCH, RIG, Clock
from rulecheck import _emitters, _value, build, rule_matrix


def test_level_from_min_to_full():
    assert FLASH_MIN_LEVEL == 0.6
    levels = [flash_level(v) for v in range(1, 128)]
    assert levels[0] == 0.6 and levels[-1] == 1.0
    steps = [b - a for a, b in zip(levels, levels[1:])]
    assert max(steps) - min(steps) < 1e-12  # a straight line
    assert flash_level(64, 0.3) == pytest.approx(0.3 + 0.7 * 63 / 126)


@pytest.mark.parametrize("profile", ["0.05_band"])
def test_hit_shows_a_chase_as_it_is_at_that_moment(profile):
    e, view, clock = build(profile)
    patch, pal = e.rig.patch, parse_palettes({}, e.rig.patch)
    sc = parse_scene({"layers": [{"fixtures": ["bars", "wash"], "effect": "colour_chase", "colours": ["#ff0000", "#0000ff"],
                                  "period_s": 1.0}]}, patch, pal, "chase")
    player = ScenePlayer(sc, e.rig, clock())
    e.set_source(player, sc)
    e.set_master(False)
    for k in range(6):  # hits at different moments of the chase
        clock.advance(0.17)
        e.tick()
        assert _emitters(e, "bar_1") == [0] * 6  # dark between hits
        e.flash(["bar_1", "bar_2", "wash"], 127, length_ms=50)
        look = player(clock())
        for fid in ("bar_1", "bar_2"):
            fl = look.fixtures[fid]
            want = [round(px.get(r, 0) * 255) for px in fl.pixels for r in ("red", "green", "blue")] if fl.pixels else \
                [round(fl.colour.get(r, 0) * 255) for _ in range(2) for r in ("red", "green", "blue")]
            assert _emitters(e, fid) == want, (k, fid)
        w = look.fixtures["wash"].colour
        assert [view("wash", r) for r in ("red", "green", "blue")] == [round(w.get(r, 0) * 255) for r in ("red", "green", "blue")]
        clock.advance(0.06)
        e.tick()


def test_nothing_added_unticked_dark_and_master_on_unchanged():
    e, view, clock = build("0.05_band")
    e.set_look(parse_look({"fixtures": {"bar_1": {"colour": [0, 1, 0]}}}, e.rig.patch))  # wash not in the look
    e.set_master(False)
    e.flash(["bar_1", "wash"], 127)
    assert view("bar_1", "green", 0) == 255
    assert not any(_emitters(e, "wash")) and _value(e, "wash", "dimmer") == 0  # the look leaves it off: no light
    assert not any(_emitters(e, "bar_2"))  # not ticked: dark
    e.set_master(True)
    e.tick()
    before = {u: bytes(f) for u, f in e.frames.items()}
    assert not e.flash(["bar_1", "wash"], 127)  # MASTER on: a hit changes nothing on lit lights
    e.tick()
    assert {u: bytes(f) for u, f in e.frames.items()} == before


def test_head_shutter_opens_for_the_hit():
    e, view, clock = build("0.05_band")
    e.set_look(Look(fixtures={"mh_a": FixtureLook(colour={"red": 1.0}, strobe=200)}))
    e.set_master(False)
    assert view("mh_a", "dimmer") == 0 and view("mh_a", "strobe") == 7  # dark: shutter at its default
    e.flash(["mh_a"], 127, length_ms=40)
    assert view("mh_a", "dimmer") == 255 and view("mh_a", "red") == 255 and view("mh_a", "strobe") == 200
    clock.advance(0.05)
    e.tick()
    assert view("mh_a", "dimmer") == 0 and view("mh_a", "strobe") == 7
    e.set_look(Look(fixtures={"mh_a": FixtureLook(colour={"red": 1.0})}))  # the look sets no shutter: default (open)
    e.flash(["mh_a"], 127)
    assert view("mh_a", "dimmer") == 255 and view("mh_a", "strobe") == 7


def test_kick_never_flashed_and_rules_hold_under_both_profiles():
    def hits(e, clock):
        e.set_master(False)
        for k in range(10):
            clock.advance(0.05)
            e.flash([f.id for f in e.rig.fixtures], 30 + 9 * k, length_ms=30)
    rule_matrix(hits, seconds=1.0)
    e, view, clock = build("0.05_band")
    e.set_master(False)
    kick = _emitters(e, "kick")
    e.flash([f.id for f in e.rig.fixtures], 127)
    assert _emitters(e, "kick") == kick  # rule 3


# ------------------------------------------------------------------ settings and format 7


def test_map_and_kit_settings():
    from dmx_suite.midi.map import parse_map, validate

    def one(**p):
        return parse_map({"mappings": [{"input": "snare", "action": "flash", "fixtures": ["bars"], **p}]}).mappings[0]

    validate(one(min_level=0.4, length_ms=120))
    with pytest.raises(ConfigError, match="doesn't take"):
        validate(one(colour="white"))
    with pytest.raises(ConfigError, match="min_level 0-1"):
        validate(one(min_level=2))
    def kit(flash):
        zone = {"notes": [38], "role": "snare", "flash": {"fixtures": ["bars"], **flash}}
        return {"k": {"name": "K", "pieces": {"snare": {"zones": {"head": zone}}}}}

    parse_kits(kit({"min_level": 0.3}))
    with pytest.raises(ConfigError, match="min_level"):
        parse_kits(kit({"min_level": 1.5}))
    with pytest.raises(ConfigError, match="length_ms, min_level"):
        parse_kits(kit({"colour": "white"}))


def test_format_step_drops_flash_colour(caplog):
    with caplog.at_level(logging.WARNING):
        midi = upgrade({"version": 6, "mappings": [
            {"input": "snare", "action": "flash", "fixtures": ["bars"], "colour": "show"},
            {"input": "crash", "action": "flash", "fixtures": ["all"], "colour": "white", "length_ms": 250},
            {"input": "pc_0", "action": "master_toggle"}]}, "midi")
    assert midi["mappings"][0] == {"input": "snare", "action": "flash", "fixtures": ["bars"]}
    assert midi["mappings"][1] == {"input": "crash", "action": "flash", "fixtures": ["all"], "length_ms": 250}
    assert "white" in caplog.text and "crash" in caplog.text  # a white flash is now the look: said once
    inputs = upgrade({"version": 6, "kits": {"band_kit": {"pieces": {"snare": {"zones": {"head": {
        "notes": [38], "role": "snare", "flash": {"fixtures": ["bars"], "colour": "show", "length_ms": 120}}}}}}}}, "inputs")
    assert inputs["kits"]["band_kit"]["pieces"]["snare"]["zones"]["head"]["flash"] == {"fixtures": ["bars"], "length_ms": 120}


def test_kit_flash_gets_the_default_min_level():
    from types import SimpleNamespace

    from dmx_suite.midi.map import parse_map
    from dmx_suite.showfiles import add_kit_flashes

    kits = parse_kits({"k": {"name": "K", "pieces": {
        "snare": {"zones": {"head": {"notes": [38], "role": "snare", "flash": {"fixtures": ["bars"]}}}},
        "tom": {"zones": {"head": {"notes": [48], "role": "tom", "flash": {"fixtures": ["bars"], "min_level": 0.2}}}}}}})
    mp = parse_map({"mappings": []})
    add_kit_flashes(mp, SimpleNamespace(kits=kits, active_kit="k", inputs={"snare": 1, "tom": 1}))
    got = {m.input: m.params for m in mp.mappings}
    assert got["snare"]["min_level"] == FLASH_MIN_LEVEL and got["tom"]["min_level"] == 0.2
    assert "colour" not in got["snare"]


def test_engine_flash_has_no_colour_argument():
    p = parse_patch(PATCH)
    e = Engine(parse_rig(RIG, p), [LogDriver()], parse_look({"fixtures": {}}, p), clock=Clock())
    e.set_master(False)
    with pytest.raises(TypeError):
        e.flash(["bar_1"], 127, "white")  # the v6 colour is gone: a hit shows the look
