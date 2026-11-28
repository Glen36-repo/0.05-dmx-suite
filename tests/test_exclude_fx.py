# ruff: noqa: F811 - pytest fixtures imported from test_autopilot are used as arguments
"""Excluded FX types (v4.1): types the autopilot never picks, saved per rig in `auto: exclude_fx`, still
playable by hand, allowed under gig lock; re-roll and "more like this" skip them too."""

import pytest
import yaml
from test_autopilot import app  # noqa: F401 - pytest fixture

from dmx_suite.classify import parse_auto
from dmx_suite.fixtures import ConfigError
from dmx_suite.fxbanks import Pick, available


def rig_auto(app):
    return yaml.safe_load((app.files.root / "rigs" / f"{app.names[0]}.yaml").read_text(encoding="utf-8")).get("auto") or {}


def picks(app, moods=("low", "mid", "high"), n=25):
    ap = app.autopilot
    ap.set_on(True, app.t.t)
    out = []
    for mood in moods:
        ap.set_mood(mood, app.t.t)
        for _ in range(n):
            out.append(Pick.from_dict(ap.change(app.t.t, "timer").look))
            app.t.advance(1)
    return out


def test_config_accepts_known_types_only(app):
    patch = app.files.patch
    assert parse_auto({"exclude_fx": ["static", "police", "pan_sweep", "kick_pump"]}, patch).exclude_fx == \
        ["static", "police", "pan_sweep", "kick_pump"]
    with pytest.raises(ConfigError, match="unknown FX type 'nope'"):
        parse_auto({"exclude_fx": ["nope"]}, patch)
    with pytest.raises(ConfigError, match="Flash FX"):
        parse_auto({"exclude_fx": ["strobe"]}, patch)  # played by hand only
    with pytest.raises(ConfigError, match="a list"):
        parse_auto({"exclude_fx": "static"}, patch)


def test_excluded_types_are_never_picked(app):
    ar = app.autopilot.rig_auto()
    colours = [i.id for i in available(ar, "colour")]
    moves = [i.id for i in available(ar, "move")]
    out_c, out_m = colours[: len(colours) // 2], moves[: len(moves) // 2]
    for k in out_c + out_m + ["kick_pump"]:
        app.exclude_fx(k, True)
    assert set(rig_auto(app)["exclude_fx"]) == set(out_c + out_m + ["kick_pump"])  # saved in the rig file
    got = picks(app)
    assert not {p.colour for p in got} & set(out_c)
    assert not {p.move for p in got} & set(out_m)
    assert "kick_pump" not in {p.drum for p in got}
    cat = {i["id"]: i for i in app.fx_catalogue()["items"]}
    assert all(cat[k]["excluded"] for k in out_c) and not cat[colours[-1]]["excluded"]


def test_put_back_and_nothing_left(app):
    app.exclude_fx("static", True)
    app.exclude_fx("static", False)
    assert "exclude_fx" not in rig_auto(app)  # nothing left: the key goes
    ar = app.autopilot.rig_auto()
    for i in available(ar, "colour"):  # every colour type out: the autopilot still plays something
        app.exclude_fx(i.id, True)
    for i in available(ar, "move"):
        app.exclude_fx(i.id, True)
    got = picks(app, n=5)
    assert all(p.colour for p in got) and all(p.move is None for p in got)


def test_by_hand_still_plays_an_excluded_type(app):
    app.exclude_fx("rainbow", True)
    app.ride_action("autopilot_fx", {"bank": "colour", "item": "rainbow"}, None)
    assert app.ride_pick.colour == "rainbow"


def test_reroll_and_more_skip_excluded(app):
    ar = app.autopilot.rig_auto()
    keep = "colour_fade"
    for i in available(ar, "colour"):
        if i.id != keep:
            app.exclude_fx(i.id, True)
    for _ in range(6):
        app.reroll(["move", "drum", "palette", "feel"], "mid")
        assert app.ride_pick.colour == keep
    assert {p["colour"] for p in app.more_like_this(6)} <= {keep}


def test_allowed_under_gig_lock(app):
    app.set_gig_lock(True)
    app.exclude_fx("police", True)
    assert rig_auto(app)["exclude_fx"] == ["police"]


def test_saving_light_classes_keeps_excluded_types(app):
    from dmx_suite.web.server import WebServer

    app.exclude_fx("police", True)
    web = WebServer(app, "127.0.0.1", 0, token="t" * 32)
    web.start()
    try:
        import json
        import urllib.request

        req = urllib.request.Request(f"http://127.0.0.1:{web.port}/api/store/auto", method="POST",
                                     data=json.dumps({"exclude": ["wash_l"]}).encode(),
                                     headers={"Content-Type": "application/json", "X-DMX-Token": "t" * 32})
        with urllib.request.urlopen(req, timeout=5) as r:
            assert r.status == 200
    finally:
        web.stop()
    assert rig_auto(app) == {"exclude": ["wash_l"], "exclude_fx": ["police"]}


def test_unknown_type_refused(app):
    with pytest.raises(ValueError):
        app.exclude_fx("nope", True)
    with pytest.raises(ValueError):
        app.exclude_fx("blinder", True)  # Flash FX
