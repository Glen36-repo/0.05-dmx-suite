"""Auto-show generator: every generated scene must obey the rules on every rig."""

from pathlib import Path

import pytest

from dmx_suite.auto import AutoStyle, RigGroups, contrast_of, generate, parse_style
from dmx_suite.engine import Engine
from dmx_suite.fixtures import EMITTERS, ConfigError, Kind
from dmx_suite.output import LogDriver
from dmx_suite.rig import load_rig
from dmx_suite.showfiles import load_show

SHOWS = Path(__file__).resolve().parents[1] / "shows"


@pytest.fixture(scope="module")
def files():
    return load_show(SHOWS)


def rigs(files):
    return [load_rig(SHOWS / "rigs" / f"{r}.yaml", files.patch) for r in ("full", "small")]


@pytest.mark.parametrize("energy", ["low", "mid", "high"])
def test_generated_scenes_render_within_rules(files, energy):
    style = AutoStyle(colours=["blue", "red", "amber", "purple"], energy=energy, flash=True)
    for rig in rigs(files):
        g = RigGroups.of(rig)
        for step in range(40):
            sc = generate(style, rig, files.palettes, step, "t")
            e = Engine(rig, [LogDriver()])
            e.set_scene(sc)
            frame = e.frames[0]
            smoke = rig.patch.fixtures["smoke"]
            assert frame[smoke.address - 1] == 0  # rule 5: scenes never haze
            for layer in sc.layers:
                if layer.effect in ("sweep", "random_move") or "position" in layer.params:
                    assert set(layer.fixtures) <= set(g.movers)  # rule 7: U'Kings never moved
            assert all(f in rig.present for ly in sc.layers for f in ly.fixtures)  # only what's there


def test_small_rig_gets_no_head_layers(files):
    small = load_rig(SHOWS / "rigs" / "small.yaml", files.patch)
    style = AutoStyle(colours=["blue", "red"], energy="high")
    for step in range(30):
        sc = generate(style, small, files.palettes, step)
        assert "heads_only" not in sc.name and "kit" not in sc.name
        for ly in sc.layers:
            assert all(small.patch.fixtures[f].kind in (Kind.BAR, Kind.KICK) for f in ly.fixtures)


def test_deterministic_per_seed_and_step(files):
    rig = rigs(files)[0]
    style = AutoStyle(colours=["blue", "red", "amber"], energy="mid")
    a = generate(style, rig, files.palettes, 3, "x")
    b = generate(style, rig, files.palettes, 3, "x")
    c = generate(style, rig, files.palettes, 4, "x")
    assert a.name == b.name and [ly.params for ly in a.layers] == [ly.params for ly in b.layers]
    assert [ly.params for ly in a.layers] != [ly.params for ly in c.layers]


def test_patterns_heads_only_and_bars_only(files):
    rig = rigs(files)[0]
    for pattern in ("heads_only", "bars_only"):
        style = AutoStyle(colours=["blue", "red"], energy="mid", patterns=[pattern])
        sc = generate(style, rig, files.palettes, 0)
        e = Engine(rig, [LogDriver()])
        e.set_scene(sc)
        def lit(fid):
            fx = rig.patch.fixtures[fid]
            return any(e.frames[0][fx.slot(c)] for c in fx.type.channels if c.role in EMITTERS)
        if pattern == "heads_only":
            assert lit("mh_a") and not lit("bar_1") and not lit("wash_l")
        else:
            assert lit("bar_1") and not lit("mh_a") and not lit("uking_l")


def test_kit_pattern_is_static_on_the_kit(files):
    rig = rigs(files)[0]
    sc = generate(AutoStyle(colours=["blue"], energy="low", patterns=["kit"]), rig, files.palettes, 0)
    pos = [ly for ly in sc.layers if "position" in ly.params]
    assert pos and pos[0].params["position"]["mh_a"] == files.palettes.position("drum_kit", "mh_a", "")
    assert not any(ly.effect in ("sweep", "random_move") for ly in sc.layers)


def test_head_mix_and_sync(files):
    rig = rigs(files)[0]
    # matching + chase: heads run the same chase as the bars (in sync)
    seen_sync = False
    for step in range(60):
        sc = generate(AutoStyle(colours=["blue", "red"], energy="mid", head_mix=["matching"], patterns=["all"]),
                      rig, files.palettes, step)
        bars = [ly for ly in sc.layers if "bar_1" in ly.fixtures and ly.effect == "colour_chase"]
        heads = [ly for ly in sc.layers if "mh_a" in ly.fixtures and ly.effect == "colour_chase"]
        if bars and heads:
            assert bars[0].params == heads[0].params
            seen_sync = True
    assert seen_sync
    sc = generate(AutoStyle(colours=["blue", "red"], energy="mid", head_mix=["white"], patterns=["all"]),
                  rig, files.palettes, 1)
    head = [ly for ly in sc.layers if "mh_a" in ly.fixtures and "colour" in ly.params]
    assert head[0].params["colour"] == files.palettes.colours["white"]


def test_contrast_colour(files):
    pal = files.palettes
    assert contrast_of("blue", ["blue", "amber", "cyan"], pal) == "amber"  # opposite side of the wheel
    assert contrast_of("blue", ["blue"], pal) == "white"


def test_opera_only_uses_its_colours(files):
    rig = rigs(files)[0]
    st = files.shows["opera"].sets["main"].auto
    allowed = [files.palettes.colours[c] for c in ("warm_white", "incandescent", "white")] + [{}]
    for step in range(30):
        sc = generate(st, rig, files.palettes, step)
        for ly in sc.layers:
            for key in ("colour",):
                if key in ly.params:
                    assert ly.params[key] in allowed, ly.params[key]
            assert ly.effect not in ("flash", "random_move", "pixel_chase")  # minimal, slow


def test_style_validation(files):
    with pytest.raises(ConfigError, match="colours"):
        parse_style({}, files.palettes, "x")
    with pytest.raises(ConfigError, match="energy"):
        parse_style({"colours": ["blue"], "energy": "mental"}, files.palettes, "x")
    with pytest.raises(ConfigError, match="head_mix"):
        parse_style({"colours": ["blue"], "head_mix": ["rainbow"]}, files.palettes, "x")
    with pytest.raises(Exception, match="unknown colour"):
        parse_style({"colours": ["chartreuse"]}, files.palettes, "x")
