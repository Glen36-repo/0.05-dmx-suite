"""R7 fixture model: colour mixing, named wheel and gobo slots, 16-bit and inverted channels, beam
controls, sub-masters apart from kind. Safety rules are checked again under both shipped profiles."""

import copy

import pytest

from dmx_suite.colourmix import mix, nearest_slot
from dmx_suite.faders import Masters
from dmx_suite.fixtures import ConfigError, Kind, parse_patch
from dmx_suite.look import LookError, parse_look
from dmx_suite.rig import parse_rig
from dmx_suite.rules import ControlState, RuleLayer
from dmx_suite.versions import upgrade

TYPES = {
    "rgbw": {"kind": "wash", "channels": ["dimmer", "red", "green", "blue", "white"]},
    "rgba": {"kind": "wash", "channels": ["red", "green", "blue", "amber"]},
    "whiteonly": {"kind": "wash", "channels": ["dimmer", "white"]},
    "par": {"kind": "wash", "channels": ["dimmer"]},
    "par16": {"kind": "wash", "channels": ["dimmer", "dimmer_fine"]},
    "wheelhead": {
        "kind": "head",
        "channels": ["pan", {"role": "pan_fine"}, {"role": "tilt", "invert": True}, "dimmer", "colour_wheel",
                     "gobo", "zoom", "zoom_fine", "focus", {"role": "frost", "invert": True}, {"role": "prism", "default": 0}],
        "wheel": {"open": {"value": 0, "colour": "#ffffff"}, "red": {"value": 20, "colour": "#ff0000"},
                  "blue": {"value": 40, "colour": [0, 0, 1]}, "spin": 200},
        "gobos": {"dots": 30, "star": 60},
    },
    "old": {"kind": "wash", "colour_mix": "off", "channels": ["dimmer", "red", "green", "blue", "white"]},
}
FIXTURES = [
    {"id": "w", "type": "rgbw", "address": 1},
    {"id": "a", "type": "rgba", "address": 10},
    {"id": "wo", "type": "whiteonly", "address": 20},
    {"id": "p", "type": "par", "address": 30},
    {"id": "p16", "type": "par16", "address": 31, "sub": "bar"},
    {"id": "h", "type": "wheelhead", "address": 40},
    {"id": "o", "type": "old", "address": 60},
]


def build(profile="generic"):
    patch = parse_patch({"types": copy.deepcopy(TYPES), "fixtures": copy.deepcopy(FIXTURES)})
    rig = parse_rig({"name": "t", "profile": profile}, patch)
    return patch, rig


def render(rig, look, master=True, grand=1.0, subs=None):
    masters = Masters(grand, subs or {}, 1.0, 0.0)
    return RuleLayer(rig).render(look, ControlState(master, False, {}, 0.0), masters)[0]


def ch(frame, patch, fid, role):
    fx = patch.fixtures[fid]
    return frame[fx.slot(next(c for c in fx.type.channels if c.role == role))]


# ------------------------------------------------------------------ colour mixing


def test_rgbw_takes_the_white_out_of_rgb():
    patch, _ = build()
    t = patch.types["rgbw"]
    assert mix({"red": 1, "green": 1, "blue": 1}, t) == {"red": 0, "green": 0, "blue": 0, "white": 1}
    assert mix({"red": 1, "green": 0.5, "blue": 0.2}, t) == pytest.approx({"red": 0.8, "green": 0.3, "blue": 0, "white": 0.2})
    assert mix({"red": 1, "white": 0.3}, t) == {"red": 1, "white": 0.3}  # an explicit white is kept as is


def test_rgba_takes_the_orange_into_amber():
    patch, _ = build()
    got = mix({"red": 1, "green": 0.5, "blue": 0}, patch.types["rgba"])
    assert got["amber"] == pytest.approx(1) and got["red"] == pytest.approx(0) and got["green"] == pytest.approx(0)
    assert "amber" not in mix({"red": 0, "green": 0, "blue": 1}, patch.types["rgba"])


def test_white_only_and_dimmer_only_lights_follow_brightness():
    patch, rig = build()
    look = parse_look({"fixtures": {"wo": {"colour": [0, 0, 0.5]}, "p": {"colour": [0.4, 0.2, 0]}}}, patch)
    f = render(rig, look)
    assert ch(f, patch, "wo", "white") == 128 and ch(f, patch, "wo", "dimmer") == 255
    assert ch(f, patch, "p", "dimmer") == 102  # 0.4 of full


def test_colour_wheel_head_picks_the_nearest_slot():
    patch, rig = build()
    t = patch.types["wheelhead"]
    assert nearest_slot({"red": 0.9, "green": 0.1, "blue": 0}, t).value == 20
    assert nearest_slot({"red": 0, "green": 0.1, "blue": 0.5}, t).value == 40
    assert nearest_slot({"red": 1, "green": 1, "blue": 1}, t).value == 0
    f = render(rig, parse_look({"fixtures": {"h": {"colour": [0, 0, 1]}}}, patch))
    assert ch(f, patch, "h", "colour_wheel") == 40 and ch(f, patch, "h", "dimmer") == 255


def test_colour_mix_off_sends_colours_as_given():
    patch, rig = build()
    f = render(rig, parse_look({"fixtures": {"o": {"colour": [1, 1, 1]}, "w": {"colour": [1, 1, 1]}}}, patch))
    assert [ch(f, patch, "o", r) for r in ("red", "green", "blue", "white")] == [255, 255, 255, 0]
    assert [ch(f, patch, "w", r) for r in ("red", "green", "blue", "white")] == [0, 0, 0, 255]


def test_older_fixture_files_upgrade_to_colour_mix_off():
    data = upgrade({"version": 3, "types": {"x": {"kind": "wash", "channels": ["red"]}}}, "fixtures")
    assert data["types"]["x"]["colour_mix"] == "off"
    assert "colour_mix" not in upgrade({"version": 4, "types": {"x": {"kind": "wash", "channels": ["red"]}}},
                                       "fixtures")["types"]["x"]


# ------------------------------------------------------------------ named slots


def test_named_wheel_and_gobo_slots_in_looks():
    patch, rig = build()
    look = parse_look({"fixtures": {"h": {"colour_wheel": "red", "gobo": "star"}}}, patch)
    f = render(rig, look)
    assert ch(f, patch, "h", "colour_wheel") == 20 and ch(f, patch, "h", "gobo") == 60
    with pytest.raises(LookError, match="slot named 'nope'"):
        parse_look({"fixtures": {"h": {"gobo": "nope"}}}, patch)


def test_named_slots_in_scenes():
    from dmx_suite.palettes import parse_palettes
    from dmx_suite.scenes import parse_scene

    patch, _ = build()
    pal = parse_palettes({"colours": {"red": [1, 0, 0]}}, patch)
    sc = parse_scene({"name": "s", "layers": [{"fixtures": ["h", "w"], "colour": "red", "gobo": "dots",
                                                 "colour_wheel": "blue", "zoom": 0.25}]}, patch, pal)
    lay = sc.layers[0].params
    assert lay["gobo"] == {"h": 30, "w": None} and lay["colour_wheel"] == {"h": 40, "w": None}
    with pytest.raises(LookError, match="has a colour wheel slot named .blue."):
        parse_scene({"name": "s", "layers": [{"fixtures": ["w"], "colour_wheel": "blue"}]}, patch, pal)


def test_bad_slots_refused_in_fixture_files():
    bad = copy.deepcopy(TYPES)
    bad["wheelhead"]["wheel"]["red"] = {"value": 300}
    with pytest.raises(ConfigError, match="0-255"):
        parse_patch({"types": bad, "fixtures": []})
    bad = copy.deepcopy(TYPES)
    bad["rgbw"]["channels"].append({"role": "red", "invert": True})
    with pytest.raises(ConfigError, match="can't be inverted"):
        parse_patch({"types": bad, "fixtures": []})
    bad = copy.deepcopy(TYPES)
    bad["rgbw"]["channels"].append("zoom_fine")
    with pytest.raises(ConfigError, match="zoom_fine needs a zoom"):
        parse_patch({"types": bad, "fixtures": []})


# ------------------------------------------------------------------ 16-bit, invert, beam


def test_fine_channels_and_invert():
    patch, rig = build()
    look = parse_look({"fixtures": {"h": {"colour": [1, 1, 1], "pan": 0.5, "tilt": 0.25, "zoom": 0.5, "focus": 0.2,
                                          "frost": 0.25, "prism": 128}}}, patch)
    f = render(rig, look)
    v16 = round(0.5 * 65535)
    assert (ch(f, patch, "h", "pan"), ch(f, patch, "h", "pan_fine")) == (v16 >> 8, v16 & 0xFF)
    assert ch(f, patch, "h", "tilt") == round(0.75 * 255)  # inverted
    assert (ch(f, patch, "h", "zoom"), ch(f, patch, "h", "zoom_fine")) == (v16 >> 8, v16 & 0xFF)
    assert ch(f, patch, "h", "focus") == round(0.2 * 255)
    assert ch(f, patch, "h", "frost") == round(0.75 * 255)  # inverted
    assert ch(f, patch, "h", "prism") == 128
    f = render(rig, parse_look({"fixtures": {"p16": {"colour": [1, 1, 1]}}}, patch), grand=0.5)
    d16 = round(0.5 * 65535)
    assert (ch(f, patch, "p16", "dimmer"), ch(f, patch, "p16", "dimmer_fine")) == (d16 >> 8, d16 & 0xFF)


def test_sub_master_apart_from_kind():
    patch, rig = build()
    assert patch.fixtures["p16"].sub == Kind.BAR and patch.fixtures["p"].sub == Kind.WASH
    look = parse_look({"fixtures": {"p16": {"colour": [1, 1, 1]}, "p": {"colour": [1, 1, 1]}}}, patch)
    f = render(rig, look, subs={Kind.BAR: 0.0})
    assert ch(f, patch, "p16", "dimmer") == 0 and ch(f, patch, "p", "dimmer") == 255
    with pytest.raises(ConfigError, match="sub must be"):
        parse_patch({"types": TYPES, "fixtures": [{"id": "x", "type": "par", "address": 1, "sub": "haze"}]})


# ------------------------------------------------------------------ safety rules still hold


@pytest.mark.parametrize("profile", ["generic", "0.05_band"])
def test_rule4_dark_fixtures_fully_off_including_fine_and_mixed(profile):
    patch, rig = build(profile)
    f = render(rig, parse_look({"fixtures": {}}, patch))
    for fid in ("w", "a", "wo", "p", "p16", "h", "o"):
        fx = patch.fixtures[fid]
        for c in fx.type.channels:
            if c.role in ("dimmer", "dimmer_fine", "red", "green", "blue", "white", "amber"):
                assert f[fx.slot(c)] == 0, (fid, c.role)


@pytest.mark.parametrize("profile", ["generic", "0.05_band"])
def test_rule6_grand_master_never_touches_beam_or_position(profile):
    patch, rig = build(profile)
    look = parse_look({"fixtures": {"h": {"colour": [1, 1, 1], "pan": 0.3, "zoom": 0.6, "gobo": "dots"}}}, patch)
    full, half = render(rig, look), render(rig, look, grand=0.5)
    for role in ("pan", "zoom", "zoom_fine", "gobo", "colour_wheel", "frost"):
        assert ch(full, patch, "h", role) == ch(half, patch, "h", role), role
    assert ch(half, patch, "h", "dimmer") < ch(full, patch, "h", "dimmer")


def test_rule1_master_off_darkens_mixed_lights_under_the_band_profile():
    patch, rig = build("0.05_band")
    look = parse_look({"fixtures": {"w": {"colour": [1, 1, 1]}, "p": {"colour": [1, 1, 1]}}}, patch)
    f = render(rig, look, master=False)
    assert ch(f, patch, "w", "white") == 0 and ch(f, patch, "p", "dimmer") == 0
