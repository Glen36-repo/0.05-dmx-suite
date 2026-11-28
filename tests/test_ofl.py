import json
from pathlib import Path

import pytest

from dmx_suite.cli import main
from dmx_suite.fixtures import ConfigError, parse_patch
from dmx_suite.ofl import import_ofl, ofl_to_type

DATA = Path(__file__).parent / "data"


def load(name):
    return json.loads((DATA / name).read_text())


def roles(entry):
    t = next(iter(entry.values()))
    return [c if isinstance(c, str) else c["role"] for c in t["channels"]], t


def test_eurolite_tmh7():
    entry, warnings = ofl_to_type(load("eurolite_led-tmh-7.json"))
    r, t = roles(entry)
    assert r == ["pan", "tilt", "pt_speed", "red", "green", "blue", "fixed", "strobe", "dimmer", "pan_fine", "tilt_fine"]
    assert t["channels"][2] == {"role": "pt_speed", "invert": True}  # OFL says fast -> slow
    assert t["channels"][7] == {"role": "strobe", "default": 255}  # OFL default value (shutter open)
    assert t["kind"] == "head" and t["verified"] is False and not warnings


def test_adj_pocket_spot_needs_mode_and_maps_wheels():
    with pytest.raises(ConfigError, match="pick a mode"):
        ofl_to_type(load("american-dj_inno-pocket-spot.json"))
    entry, _ = ofl_to_type(load("american-dj_inno-pocket-spot.json"), mode="11-channel", key="pocket")
    r, t = roles(entry)
    assert list(entry) == ["pocket"]
    assert r[:6] == ["pan", "pan_fine", "tilt", "tilt_fine", "colour_wheel", "gobo"]
    assert t["channels"][6] == {"role": "strobe", "default": 8}  # first "Open" range


def test_switching_channel_warns():
    entry, warnings = ofl_to_type(load("cameo_hydrabeam-100.json"), mode="14-channel")
    assert warnings and "switching" in warnings[0]


def test_imported_types_load_as_patch():
    types = {}
    for f, mode in [("eurolite_led-tmh-7.json", None), ("american-dj_inno-pocket-spot.json", "9-channel"),
                    ("cameo_hydrabeam-100.json", "14-channel")]:
        types.update(ofl_to_type(load(f), mode)[0])
    p = parse_patch({"types": types, "fixtures": [{"id": k, "type": k, "address": 1 + 20 * i} for i, k in enumerate(types)]})
    assert len(p.fixtures) == 3


def test_unknown_mode_and_kind_override():
    with pytest.raises(ConfigError, match="no mode"):
        ofl_to_type(load("american-dj_inno-pocket-spot.json"), mode="99-channel")
    entry, _ = ofl_to_type(load("eurolite_led-tmh-7.json"), kind="wash")
    assert next(iter(entry.values()))["kind"] == "wash"


def test_matrix_without_pixels_rejected():
    data = {"name": "Bar", "availableChannels": {}, "modes": [{"name": "m", "channels": [{"insert": "matrixChannels"}]}]}
    with pytest.raises(ConfigError, match="matrix"):
        ofl_to_type(data)


BAR = {
    "name": "Test Bar 4",
    "categories": ["Pixel Bar"],
    "matrix": {"pixelCount": [4, 1, 1]},
    "availableChannels": {"Dimmer": {"capability": {"type": "Intensity"}, "fineChannelAliases": ["Dimmer fine"]}},
    "templateChannels": {
        "Red $pixelKey": {"capability": {"type": "ColorIntensity", "color": "Red"}},
        "Green $pixelKey": {"capability": {"type": "ColorIntensity", "color": "Green"}},
        "Blue $pixelKey": {"capability": {"type": "ColorIntensity", "color": "Blue"}},
    },
    "modes": [
        {"name": "per pixel", "channels": [
            "Dimmer", "Dimmer fine",
            {"insert": "matrixChannels", "repeatFor": "eachPixelABC", "channelOrder": "perPixel",
             "templateChannels": ["Red $pixelKey", "Green $pixelKey", "Blue $pixelKey"]}]},
        {"name": "per colour", "channels": [
            {"insert": "matrixChannels", "repeatFor": ["4", "3", "2", "1"], "channelOrder": "perChannel",
             "templateChannels": ["Red $pixelKey", "Blue $pixelKey"]}]},
    ],
}


def test_pixel_matrix_expands():
    entry, _ = ofl_to_type(BAR, mode="per pixel", key="bar4")
    t = entry["bar4"]
    assert t["kind"] == "bar" and t["colour_mix"] == "auto"
    assert t["channels"][:2] == ["dimmer", "dimmer_fine"]
    assert t["channels"][2:8] == [{"role": "red", "pixel": 0}, {"role": "green", "pixel": 0}, {"role": "blue", "pixel": 0},
                                  {"role": "red", "pixel": 1}, {"role": "green", "pixel": 1}, {"role": "blue", "pixel": 1}]
    assert len(t["channels"]) == 2 + 12
    entry, _ = ofl_to_type(BAR, mode="per colour", key="bar4")
    ch = entry["bar4"]["channels"]
    assert ch[:4] == [{"role": "red", "pixel": i} for i in range(4)]  # repeatFor order: pixel 0 is "4"
    assert ch[4:] == [{"role": "blue", "pixel": i} for i in range(4)]
    p = parse_patch({"types": entry, "fixtures": [{"id": "b", "type": "bar4", "address": 1}]})
    assert p.types["bar4"].pixels == 4


def test_colour_and_gobo_wheel_slots_come_across():
    entry, _ = ofl_to_type(load("american-dj_inno-pocket-spot.json"), mode="11-channel", key="pocket")
    t = entry["pocket"]
    assert t["wheel"]["open"] == {"value": 0, "colour": "#ffffff"}
    assert t["wheel"]["red"]["colour"] == "#ff0000" and t["wheel"]["red"]["value"] > 0
    assert "light_blue" in t["wheel"] and len(t["gobos"]) >= 5 and t["gobos"]["open"] == 0
    p = parse_patch({"types": entry, "fixtures": [{"id": "s", "type": "pocket", "address": 1}]})
    assert p.types["pocket"].wheel_value("red") == t["wheel"]["red"]["value"]


# ------------------------------------------------------------------ export


def roles_of(t):
    return [c if isinstance(c, str) else c["role"] for c in t["channels"]]


@pytest.mark.parametrize("key", ["mhl36", "lcb803", "starcolor72", "uking_mini", "kick_rgb", "smoke"])
def test_export_then_import_keeps_every_channel(key):
    import yaml

    from dmx_suite.ofl import type_to_ofl

    shipped = yaml.safe_load((Path(__file__).resolve().parents[1] / "shows" / "fixtures.yaml").read_text())["types"][key]
    data = type_to_ofl(key, shipped, "2026-11-26")
    assert data["$schema"].endswith("fixture.json") and data["meta"]["createDate"] == "2026-11-26"
    back, _ = ofl_to_type(json.loads(json.dumps(data)), key=key)
    assert roles_of(back[key]) == roles_of(shipped)


def test_export_wheels_and_inverts_round_trip():
    from dmx_suite.ofl import type_to_ofl

    t = {"name": "Spot", "kind": "head", "channels": ["pan", "pan_fine", {"role": "tilt"}, "pt_speed", "dimmer", "colour_wheel",
                                                     "gobo", "zoom", "zoom_fine", {"role": "frost", "invert": True}, "prism"],
         "wheel": {"open": {"value": 0, "colour": "#ffffff"}, "red": {"value": 16, "colour": "#ff0000"}},
         "gobos": {"open": 0, "dots": 20}}
    data = type_to_ofl("spot", t, "2026-11-26")
    assert data["wheels"]["Color Wheel"]["slots"][1] == {"type": "Color", "name": "Red", "colors": ["#ff0000"]}
    back, _ = ofl_to_type(data, key="spot")
    b = back["spot"]
    assert roles_of(b) == roles_of(t)
    assert b["wheel"]["red"] == {"value": 16, "colour": "#ff0000"} and b["gobos"]["dots"] == 20
    assert {"role": "frost", "invert": True} in b["channels"]


def test_export_cli(tmp_path, capsys):
    out = tmp_path / "mhl36.json"
    assert main(["export-ofl", "mhl36", "-o", str(out)]) == 0
    assert json.loads(out.read_text())["name"] == "BeamZ MHL36"
    assert main(["export-ofl", "nope"]) == 1


def test_import_output_and_cli(capsys):
    text = import_ofl(DATA / "eurolite_led-tmh-7.json")
    assert text.startswith("# imported from Open Fixture Library")
    assert main(["import-ofl", str(DATA / "eurolite_led-tmh-7.json"), "--key", "tmh7"]) == 0
    assert "tmh7:" in capsys.readouterr().out
