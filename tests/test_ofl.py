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


def test_matrix_templates_rejected():
    data = {"name": "Bar", "availableChannels": {}, "modes": [{"name": "m", "channels": [{"insert": "matrixChannels"}]}]}
    with pytest.raises(ConfigError, match="matrix"):
        ofl_to_type(data)


def test_import_output_and_cli(capsys):
    text = import_ofl(DATA / "eurolite_led-tmh-7.json")
    assert text.startswith("# imported from Open Fixture Library")
    assert main(["import-ofl", str(DATA / "eurolite_led-tmh-7.json"), "--key", "tmh7"]) == 0
    assert "tmh7:" in capsys.readouterr().out
