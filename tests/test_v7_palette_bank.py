# ruff: noqa: F811 - pytest fixtures imported from other tests are used as arguments
"""v7 A2 palette bank: palettes the autopilot never picks, saved per rig in `auto: exclude_palettes`,
still playable by hand, allowed under gig lock; MIDI, API and Claude actions."""

import pytest
import yaml
from test_autopilot import app  # noqa: F401 - pytest fixture
from test_exclude_fx import picks, rig_auto
from test_v6_darkness import running  # noqa: F401 - pytest fixture

from dmx_suite.classify import parse_auto
from dmx_suite.fixtures import ConfigError
from dmx_suite.midi.map import AUTOPILOT_ACTIONS, parse_map, validate


def test_config(app):
    assert parse_auto({"exclude_palettes": ["ice", "ice", "fire"]}, app.files.patch).exclude_palettes == ["ice", "fire"]
    with pytest.raises(ConfigError, match="list of palette names"):
        parse_auto({"exclude_palettes": "ice"}, app.files.patch)


def test_excluded_palettes_are_never_picked(app):
    pals = list(app.files.palettes.sets)
    out = pals[: len(pals) // 2]
    for k in out:
        app.exclude_palette(k, True)
    assert set(rig_auto(app)["exclude_palettes"]) == set(out)  # saved in the rig file
    got = picks(app, n=170)  # 510 changes
    assert not {p.palette for p in got} & set(out)
    cat = app.fx_catalogue()["palettes"]
    assert all(cat[k]["excluded"] for k in out) and not cat[pals[-1]]["excluded"]
    assert cat["fire"]["swatches"][0] == "#ff0000"


def test_put_back_and_all_excluded(app):
    app.exclude_palette("fire", True)
    app.exclude_palette("fire", False)
    assert "exclude_palettes" not in rig_auto(app)
    for k in app.files.palettes.sets:
        app.exclude_palette(k, True)
    assert picks(app, n=3)  # everything left out: the exclusions are ignored rather than playing nothing


def test_tap_plays_an_excluded_palette(app):
    app.exclude_palette("ice", True)
    app.ride_action("autopilot_palette", {"palette": "ice"})
    assert app.ride_pick.palette == "ice"


def test_unknown_palette(app):
    with pytest.raises(ValueError, match="no palette"):
        app.exclude_palette("nope", True)


def test_allowed_under_gig_lock(app):
    app.set_gig_lock(True)
    try:
        app.exclude_palette("neon", True)
    finally:
        app.set_gig_lock(False)
    assert rig_auto(app)["exclude_palettes"] == ["neon"]


def test_midi_action_toggles(app):
    assert "exclude_palette" in AUTOPILOT_ACTIONS
    def one(**params):
        return parse_map({"mappings": [{"input": "pedal_1", "action": "exclude_palette", **params}]}).mappings[0]

    validate(one(palette="ice"))
    with pytest.raises(ConfigError, match="needs palette"):
        validate(one())
    assert app.ride_action("exclude_palette", {"palette": "ice"}) == "palette ice left out"
    assert app.ride_action("exclude_palette", {"palette": "ice"}) == "palette ice put back"
    assert app.ride_action("exclude_palette", {"palette": "ice", "excluded": True}) == "palette ice left out"


def test_api_and_claude(running):
    from test_web import call

    from dmx_suite.claude_tools import DmxTools

    app, url, root, claude = running
    status, body = call(f"{url}/api/autopilot/palette", "POST", {"palette": "fire", "excluded": True})
    assert status == 200 and body["excluded"] == ["fire"]
    t = DmxTools(shows=root, url=url, token=claude)
    assert "left out" in t.exclude_palette("ice")
    assert yaml.safe_load((root / "rigs" / "full.yaml").read_text())["auto"]["exclude_palettes"] == ["fire", "ice"]
    assert "back in" in t.exclude_palette("fire", False)
    assert "autopilot_palette ok" in t.play_palette("ice")
    assert app.ride_pick.palette == "ice"
    assert call(f"{url}/api/autopilot/palette", "POST", {"palette": "nope", "excluded": True})[0] == 400


def test_mcp_registers_palette_tools():
    pytest.importorskip("mcp")
    import asyncio

    from test_v6_darkness import SHOWS

    from dmx_suite.claude_tools import DmxTools
    from dmx_suite.mcp_server import build_server

    names = {x.name for x in asyncio.run(build_server(DmxTools(shows=SHOWS)).list_tools())}
    assert {"play_palette", "exclude_palette"} <= names
