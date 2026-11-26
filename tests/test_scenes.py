import pytest

from dmx_suite.engine import Engine
from dmx_suite.fixtures import ConfigError
from dmx_suite.look import LookError
from dmx_suite.output import LogDriver
from dmx_suite.palettes import parse_palettes
from dmx_suite.rig import parse_rig
from dmx_suite.scenes import ScenePlayer, parse_scene

PAL = {
    "colours": {"blue": [0, 0, 1], "red": [1, 0, 0], "amber": {"red": 1.0, "green": 0.5}},
    "positions": {
        "kit": {"mh_a": {"pan": 0.4, "tilt": 0.3}},
        "left": {"pan": 0.2, "tilt": 0.5},
        "right": {"pan": 0.8, "tilt": 0.5},
    },
    "gobos": {"dots": {"head": 40}, "open": 0},
}


@pytest.fixture
def pal(patch):
    return parse_palettes(PAL, patch)


def scene(patch, pal, *layers, **kw):
    return parse_scene({"layers": list(layers), **kw}, patch, pal, "test")


def play(sc, rig, t):
    return ScenePlayer(sc, rig, 0.0)(t)


# ------------------------------------------------------------------ palettes


def test_palette_lookups(pal):
    assert pal.colour("blue", "x") == {"red": 0, "green": 0, "blue": 1}
    assert pal.colour("off", "x") == {}
    assert pal.colour("#ff0000", "x")["red"] == 1
    assert pal.position("kit", "mh_a", "x") == (0.4, 0.3)
    assert pal.position("left", "mh_a", "x") == (0.2, 0.5)
    assert pal.gobo("dots", "head", "x") == 40
    with pytest.raises(LookError, match="unknown colour"):
        pal.colour("chartreuse", "x")
    with pytest.raises(LookError, match="no value for fixture type"):
        pal.gobo("dots", "bar", "x")


def test_palette_rejects_position_for_colour_only(patch):
    with pytest.raises(ConfigError, match="rule 7"):
        parse_palettes({"positions": {"p": {"uk": {"pan": 0.1, "tilt": 0.1}}}}, patch)


# ------------------------------------------------------------------ validation (hard rules through scenes)


@pytest.mark.parametrize(
    "layer, msg",
    [
        ({"fixtures": ["wash"], "dimmer": 1.0}, "rule 1"),
        ({"fixtures": ["bars"], "intensity": 0.5}, "rule 1"),
        ({"fixtures": ["smoke"], "haze": 1.0}, "rule 5"),
        ({"fixtures": ["heads"], "position": "left"}, "rule 7"),
        ({"fixtures": ["uk"], "effect": "random_move"}, "rule 7"),
        ({"fixtures": ["bars"], "position": "left"}, "no pan/tilt"),
        ({"fixtures": ["bars"], "effect": "laser_show"}, "unknown effect"),
        ({"fixtures": ["bars"], "effect": "colour_chase", "colours": ["blue"]}, "at least 2"),
        ({"fixtures": ["bars"], "effect": "pixel_chase", "position": "left"}, "unknown keys"),
        ({"fixtures": ["mh_a"], "effect": "random_move", "period_s": 2, "dark_move_s": 3}, "shorter"),
        ({"colour": "blue"}, "needs fixtures"),
    ],
)
def test_layer_validation(patch, pal, layer, msg):
    with pytest.raises(LookError, match=msg):
        scene(patch, pal, layer)


def test_scene_level_forbidden(patch, pal):
    with pytest.raises(LookError, match="rule 5"):
        parse_scene({"haze": 1, "layers": [{"fixtures": ["bars"], "colour": "blue"}]}, patch, pal)


# ------------------------------------------------------------------ static layers and order


def test_static_layers_and_override_order(patch, pal, rig):
    sc = scene(
        patch, pal,
        {"fixtures": ["bars"], "colour": "blue"},
        {"fixtures": ["bar_2"], "colour": "red"},
        {"fixtures": ["mh_a"], "colour": "amber", "position": "kit", "gobo": "dots", "speed": 0.3},
        show_colour="red",
    )
    lk = play(sc, rig, 1.0)
    assert lk.fixtures["bar_1"].colour == {"red": 0, "green": 0, "blue": 1}
    assert lk.fixtures["bar_2"].colour == {"red": 1, "green": 0, "blue": 0}
    m = lk.fixtures["mh_a"]
    assert (m.pan, m.tilt, m.gobo, m.speed) == (0.4, 0.3, 40, 0.3)
    assert lk.show_colour == {"red": 1, "green": 0, "blue": 0}


# ------------------------------------------------------------------ effects


def test_colour_chase_steps_and_spread(patch, pal, rig):
    sc = scene(patch, pal, {"fixtures": ["bar_1", "bar_2"], "effect": "colour_chase",
                            "colours": ["red", "blue"], "period_s": 2, "spread": 1})
    lk = play(sc, rig, 0.1)
    assert lk.fixtures["bar_1"].colour["red"] == 1  # first colour
    assert lk.fixtures["bar_2"].colour["blue"] == 1  # spread 1 over 2 fixtures = half a cycle ahead
    lk = play(sc, rig, 1.1)
    assert lk.fixtures["bar_1"].colour["blue"] == 1


def test_colour_chase_fade(patch, pal, rig):
    sc = scene(patch, pal, {"fixtures": ["wash"], "effect": "colour_chase",
                            "colours": ["red", "blue"], "period_s": 2, "fade": True})
    c = play(sc, rig, 0.5).fixtures["wash"].colour  # quarter cycle = halfway red -> blue
    assert c["red"] == pytest.approx(0.5) and c["blue"] == pytest.approx(0.5)


def test_pixel_chase_moves_across_bars(patch, pal, rig):
    sc = scene(patch, pal, {"fixtures": ["bar_1", "bar_2"], "effect": "pixel_chase",
                            "colour": "red", "width": 1, "period_s": 4})  # 4 pixels, 1 s each
    def lit(t):
        lk = play(sc, rig, t)
        px = lk.fixtures["bar_1"].pixels + lk.fixtures["bar_2"].pixels
        return [i for i, p in enumerate(px) if p.get("red")]
    assert lit(0.1) == [0]
    assert lit(1.1) == [1]
    assert lit(2.1) == [2]  # crosses onto bar_2
    assert lit(3.9) == [3]
    assert lit(4.1) == [0]  # wraps


def test_pixel_chase_tail_and_background(patch, pal, rig):
    sc = scene(patch, pal, {"fixtures": ["bar_1", "bar_2"], "effect": "pixel_chase",
                            "colour": "red", "background": "blue", "width": 1, "tail": 1, "period_s": 4})
    lk = play(sc, rig, 2.0)
    px = lk.fixtures["bar_1"].pixels + lk.fixtures["bar_2"].pixels
    assert px[2]["red"] == 1  # head
    assert 0 < px[1]["red"] < 1  # tail
    assert px[0] == {"red": 0, "green": 0, "blue": 1}  # background


def test_flash_effect(patch, pal, rig):
    sc = scene(patch, pal, {"fixtures": ["wash"], "effect": "flash", "colour": "red", "rate_hz": 2, "duty": 0.25})
    assert play(sc, rig, 0.05).fixtures["wash"].colour == {"red": 1, "green": 0, "blue": 0}
    assert play(sc, rig, 0.2).fixtures["wash"].colour == {}  # off part of the cycle = black colour
    assert play(sc, rig, 0.55).fixtures["wash"].colour["red"] == 1


def test_sweep(patch, pal, rig):
    sc = scene(patch, pal, {"fixtures": ["mh_a"], "effect": "sweep", "from": "left", "to": "right", "period_s": 4})
    assert play(sc, rig, 0).fixtures["mh_a"].pan == pytest.approx(0.2)
    assert play(sc, rig, 2).fixtures["mh_a"].pan == pytest.approx(0.8)
    assert play(sc, rig, 4).fixtures["mh_a"].pan == pytest.approx(0.2)


def test_random_move_deterministic_within_range_and_changes(patch, pal, rig):
    sc = scene(patch, pal, {"fixtures": ["mh_a"], "effect": "random_move", "period_s": 2,
                            "pan": [0.3, 0.6], "tilt": [0.1, 0.2], "stagger": False, "seed": "x"})
    positions = set()
    for t in range(0, 40, 2):
        a = play(sc, rig, t + 0.5).fixtures["mh_a"]
        b = play(sc, rig, t + 1.5).fixtures["mh_a"]
        assert (a.pan, a.tilt) == (b.pan, b.tilt)  # holds within a period
        assert 0.3 <= a.pan <= 0.6 and 0.1 <= a.tilt <= 0.2
        positions.add(round(a.pan, 4))
    assert len(positions) > 10  # actually moves


def test_random_move_dark_between_positions(patch, pal, rig):
    sc = scene(
        patch, pal,
        {"fixtures": ["mh_a"], "colour": "red"},
        {"fixtures": ["mh_a"], "effect": "random_move", "period_s": 4, "dark_move_s": 1, "stagger": False},
    )
    assert play(sc, rig, 0.5).fixtures["mh_a"].colour["red"] == 1  # scene start: lit
    assert play(sc, rig, 4.5).fixtures["mh_a"].colour == {}  # just moved: dark
    assert play(sc, rig, 5.5).fixtures["mh_a"].colour["red"] == 1


def test_layers_run_together(patch, pal, rig):
    """Colour + effect + movement at once (more than two layers)."""
    sc = scene(
        patch, pal,
        {"fixtures": ["mh_a"], "effect": "colour_chase", "colours": ["red", "blue"], "period_s": 2},
        {"fixtures": ["mh_a"], "effect": "sweep", "from": "left", "to": "right", "period_s": 4},
        {"fixtures": ["mh_a"], "gobo": "dots"},
    )
    m = play(sc, rig, 1.5).fixtures["mh_a"]
    assert m.colour["blue"] == 1 and 0.2 < m.pan < 0.8 and m.gobo == 40


# ------------------------------------------------------------------ through the engine + rule layer


def test_scene_output_obeys_rules(patch, pal, rig, clock):
    sc = scene(patch, pal, {"fixtures": ["bars", "wash", "mh_a"], "colour": "red"},
               {"fixtures": ["mh_a"], "position": {"pan": 0.0, "tilt": 1.0}})
    out = LogDriver()
    e = Engine(rig, [out], clock=clock)
    e.set_scene(sc)
    frame = e.frames[0]
    assert frame[19] == 255  # bar_1 red
    assert frame[5] == 255  # mh_a dimmer from MASTER
    assert (frame[2] << 8 | frame[3]) == round(0.75 * 65535)  # tilt limit (rule 8)
    assert frame[69] == 0  # haze untouched (rule 5)
    e.set_master(False)
    assert e.frames[0][19] == 0 and e.frames[0][5] == 0  # MASTER owns on/off


def test_scene_animates_in_engine(patch, pal, rig, clock):
    sc = scene(patch, pal, {"fixtures": ["wash"], "effect": "flash", "colour": "red", "rate_hz": 1, "duty": 0.5})
    e = Engine(rig, [LogDriver()], clock=clock)
    e.set_scene(sc)
    assert e.frames[0][40] == 255  # wash red
    clock.advance(0.6)
    e.tick()
    assert e.frames[0][40] == 0


def test_flash_uses_scene_show_colour(patch, pal, rig, clock):
    sc = scene(patch, pal, {"fixtures": ["bars"], "colour": "blue"}, show_colour="amber")
    e = Engine(rig, [LogDriver()], clock=clock)
    e.set_scene(sc)
    e.set_master(False)
    e.flash(["bar_1"], 127, "show")
    assert e.frames[0][19:22] == bytes([255, 128, 0])


def test_missing_fixtures_skipped(patch, pal):
    small = parse_rig({"fixtures": ["bars", "kick"]}, patch)
    sc = scene(patch, pal, {"fixtures": ["mh_a"], "effect": "sweep", "from": "left", "to": "right"},
               {"fixtures": ["bars"], "colour": "blue"})
    lk = play(sc, small, 1)
    assert "mh_a" not in lk.fixtures and "bar_1" in lk.fixtures


def test_shipped_scenes_play():
    from pathlib import Path

    from dmx_suite.showfiles import load_show

    show = load_show(Path(__file__).resolve().parents[1] / "shows")
    assert {"blue_chase", "opera", "red_movers", "strobe_hit"} <= set(show.scenes)
    for sc in show.scenes.values():
        e = Engine(show.rig, [LogDriver()])
        e.set_scene(sc)
        for _ in range(5):
            e.tick()
