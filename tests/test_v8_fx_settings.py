# ruff: noqa: F811 - pytest fixtures imported from test_autopilot are used as arguments
"""v8 Part A item 14: per-FX settings on the rig (fxoverrides.py) — priority as pick weight (0 = excluded),
Darkness Follow / Exempt / Reduced, the effect's own params, moods, min / max time on screen, and variants
(duplicates) that the autopilot picks as their own types but never right after their original."""

import collections

import pytest
import yaml
from test_autopilot import app  # noqa: F401 - pytest fixture
from test_v6_darkness import lit_px, running  # noqa: F401 - pytest fixture

from dmx_suite import fxoverrides as fo
from dmx_suite.autopilot import parse_config
from dmx_suite.classify import auto_rig
from dmx_suite.fixtures import ConfigError
from dmx_suite.fxbanks import BY_ID, Pick, available, compose
from dmx_suite.scenes import ScenePlayer, parse_scene

COLOURS = ["#ff0000", "#0000ff"]


def rig_file(app):
    return yaml.safe_load((app.files.root / "rigs" / f"{app.names[0]}.yaml").read_text(encoding="utf-8"))


def changes(app, n, mood="mid"):
    ap = app.autopilot
    ap.set_on(True, app.t.t)
    ap.set_mood(mood, app.t.t)
    out = []
    for _ in range(n):
        out.append(Pick.from_dict(ap.change(app.t.t, "timer").look))
        app.t.advance(1)
    return out


# ---------------------------------------------------------------- config


def test_config_checks():
    c = parse_config({"fx": {"fan": {"priority": 4, "darkness": 0.5, "moods": ["high", "mid"], "min_s": 10, "max_s": 40,
                                     "params": {"period_s": 6}}},
                      "variants": {"fan_v1": {"of": "fan", "name": " Fan slow ", "params": {"period_s": 12}}}})
    assert c["fx"]["fan"]["moods"] == ["mid", "high"]
    assert c["variants"]["fan_v1"] == {"of": "fan", "name": "Fan slow", "params": {"period_s": 12}}
    bad = [({"fx": {"fan": {"priority": 6}}}, "0-5"),
           ({"fx": {"fan": {"darkness": "half"}}}, "follow, exempt or 0-1"),
           ({"fx": {"fan": {"moods": []}}}, "low, mid, high"),
           ({"fx": {"fan": {"min_s": 50, "max_s": 20}}}, "min_s is more than max_s"),
           ({"fx": {"fan": {"params": {"nope": 1}}}}, "has no setting 'nope'"),
           ({"fx": {"fan": {"params": {"colour": "red"}}}}, "has no setting 'colour'"),  # colours come from the palette
           ({"fx": {"fan": {"speed": 1}}}, "settings are"),
           ({"variants": {"fan_v1": {"name": "x"}}}, "needs of"),
           ({"variants": {"fan": {"of": "fan"}}}, "isn't an FX type"),
           ({"variants": {"strobe_v1": {"of": "strobe"}}}, "not a Move, Colour or Drum"),
           ({"palette_settings": {"ice": {"params": {}}}}, "settings are")]
    for d, msg in bad:
        with pytest.raises(ConfigError, match=msg):
            parse_config(d)


def test_param_ranges_from_the_effect():
    item = BY_ID["fan"]
    keys = {p.key for p in fo.editable_params(item)}
    assert "period_s" in keys and "colour" not in keys and "fixtures" not in keys
    p = next(p for p in fo.editable_params(item) if p.key == "period_s")
    if p.lo is not None:
        with pytest.raises(ConfigError, match="a number"):
            fo.check_params(item, {"period_s": p.lo - 1}, "x")
    assert fo.editable_params(BY_ID["blinder"]) == []


def test_rig_items_apply_overrides_and_add_variants():
    cfg = parse_config({"fx": {"fan": {"priority": 5, "moods": ["low"], "params": {"period_s": 7}}},
                        "variants": {"fan_v1": {"of": "fan", "params": {"period_s": 20}}, "fan_v2": {"of": "fan"}}})
    items = fo.rig_items(cfg)
    assert items["fan"].priority == 5 and items["fan"].moods == ("low",) and items["fan"].layer["period_s"] == 7
    assert items["fan"].overridden and not items["pan_sweep"].overridden
    assert items["fan_v1"].label == f"{BY_ID['fan'].label} 2"
    assert items["fan_v2"].label.endswith(" 3")
    assert items["fan_v1"].layer["period_s"] == 20 and items["fan_v1"].of == "fan" and items["fan_v1"].priority == 3
    assert list(items).index("fan_v1") == list(items).index("fan") + 1  # next to the original
    assert BY_ID["fan"].layer.get("period_s") == 6  # the bank itself never changes
    assert fo.family(items["fan_v2"]) == "fan" == fo.family(items["fan"])


def test_exclude_restores_the_old_priority():
    assert fo.exclude({"priority": 5}, True) == {"priority": 0, "restore": 5}
    assert fo.exclude({"priority": 0, "restore": 5}, False) == {"priority": 5}
    assert fo.exclude({}, True) == {"priority": 0}
    assert fo.exclude({"priority": 0}, False) == {}
    assert [fo.next_badge(p) for p in (1, 2, 3, 4, 5, 0)] == [2, 3, 4, 5, 1, 1]  # never to 0


# ---------------------------------------------------------------- the app


def test_badge_exclude_and_reset_write_only_changes(app):
    assert app.set_fx_priority("fan")["priority"] == 4  # tap: 3 -> 4
    assert rig_file(app)["autopilot"]["fx"]["fan"] == {"priority": 4}
    app.exclude_fx("fan", True)
    assert rig_file(app)["autopilot"]["fx"]["fan"] == {"priority": 0, "restore": 4}
    assert "fan" in app.rig_auto().excluded_fx
    app.exclude_fx("fan", False)
    assert rig_file(app)["autopilot"]["fx"]["fan"] == {"priority": 4}
    app.save_fx("fan", {"priority": 4, "darkness": "exempt"})
    assert app.fx_item("fan")["darkness"] == "exempt"
    app.save_fx("fan", None)  # Reset to defaults
    assert "fx" not in (rig_file(app).get("autopilot") or {})
    with pytest.raises(ValueError):
        app.set_fx_priority("blinder")  # Flash FX: no priority


def test_fx_item_lists_params_with_values(app):
    app.save_fx("fan", {"params": {"period_s": 9}})
    j = app.fx_item("fan")
    p = {x["key"]: x for x in j["params"]}
    assert p["period_s"]["value"] == 9 and p["period_s"]["default"] == 6
    assert j["overrides"] == {"params": {"period_s": 9}} and j["overridden"] and not j["variant"]


def test_duplicate_and_delete(app):
    out = app.duplicate_fx("fan")
    vid = out["id"]
    assert vid == "fan_v1" and out["item"]["of"] == "fan"
    assert app.duplicate_fx("fan", "Fan wide")["id"] == "fan_v2"
    assert rig_file(app)["autopilot"]["variants"]["fan_v2"]["name"] == "Fan wide"
    v3 = app.duplicate_fx("fan_v2")["item"]  # a copy of a variant is another variant of the original
    assert v3["of"] == "fan" and v3["label"] == f"{BY_ID['fan'].label} 4"
    app.save_fx(vid, {"priority": 5, "params": {"period_s": 15}})
    assert rig_file(app)["autopilot"]["variants"][vid]["of"] == "fan"  # of / name kept
    cat = {i["id"]: i for i in app.fx_catalogue()["items"]}
    assert cat[vid]["priority"] == 5 and cat[vid]["of"] == "fan"
    app.ride_action("autopilot_fx", {"bank": "move", "item": vid}, None)  # plays by hand like any type
    assert app.ride_pick.move == vid
    with pytest.raises(ValueError, match="can't be deleted"):
        app.delete_fx("fan")
    app.delete_fx(vid)
    assert vid not in rig_file(app)["autopilot"]["variants"]


def test_gig_lock(app):
    app.set_gig_lock(True)
    from dmx_suite.store import LockedError

    with pytest.raises(LockedError):
        app.save_fx("fan", {"priority": 5})
    with pytest.raises(LockedError):
        app.set_fx_priority("fan")
    with pytest.raises(LockedError):
        app.duplicate_fx("fan")
    app.exclude_fx("fan", True)  # Exclude mode still works mid-gig
    assert "fan" in app.rig_auto().excluded_fx


# ---------------------------------------------------------------- picking


def test_priority_is_pick_weight(app):
    """chase_in / chase_out: same busy, speed and moods, so only the priority differs."""
    app.set_fx_priority("chase_in", 5)
    app.set_fx_priority("chase_out", 1)
    c = collections.Counter(p.colour for p in changes(app, 2000))
    ratio = c["chase_in"] / max(1, c["chase_out"])
    # about 5x: a type can't follow itself (contrast rules), which pulls the busiest a little down
    assert 3.5 <= ratio <= 6.5, (c["chase_in"], c["chase_out"])


def test_untouched_bank_picks_as_before(app, monkeypatch):
    """Every tile at one priority: chosen by score as in v7 (the seeded v6 / v7 decision tests replay exactly)."""
    from dmx_suite.autopilot import Autopilot

    called = []
    monkeypatch.setattr(Autopilot, "_by_priority", lambda *a: called.append(1) or a[1][0])
    app.save_fx("fan", {"darkness": "exempt", "moods": ["mid"]})  # settings, but no priority
    changes(app, 30)
    assert not called


def test_priority_0_never_picked_but_plays_on_tap(app):
    app.set_fx_priority("twinkle", 0)
    assert "twinkle" not in {p.colour for p in changes(app, 300)}
    app.ride_action("autopilot_fx", {"bank": "colour", "item": "twinkle"}, None)
    assert app.ride_pick.colour == "twinkle"


def test_variant_and_original_never_back_to_back(app):
    for i in available(app.rig_auto(), "colour"):
        if i.id not in ("colour_fade", "twinkle", "carousel"):
            app.exclude_fx(i.id, True)
    app.duplicate_fx("colour_fade")
    got = [p.colour for p in changes(app, 400, "low")]
    fam = {"colour_fade", "colour_fade_v1"}
    assert "colour_fade_v1" in got and "colour_fade" in got  # both picked as their own types
    assert not any(a in fam and b in fam and a != b for a, b in zip(got, got[1:]))


def test_moods_override(app):
    app.save_fx("kit", {"moods": ["high"]})
    assert "kit" not in {i.id for i in available(app.rig_auto(), "move", "low")}
    assert "kit" in {i.id for i in available(app.rig_auto(), "move", "high")}


def test_min_max_time_on_screen(app):
    ap = app.autopilot
    ap.set_on(True, app.t.t)
    ap.set_mood("high", app.t.t)  # 20 s +- 20 %
    for i in available(app.rig_auto(), "colour"):
        app.save_fx(i.id, {"min_s": 50})
    for _ in range(20):
        ap.change(app.t.t, "timer")
        assert ap.st.next_change - app.t.t >= 50 - 1e-6
    for i in available(app.rig_auto(), "colour"):
        app.save_fx(i.id, {"max_s": 5})
    for _ in range(20):
        ap.change(app.t.t, "timer")
        assert ap.st.next_change - app.t.t <= 5 + 1e-6


# ---------------------------------------------------------------- darkness per FX


def _bars_lit(app, item_cfg, darkness, palette_cfg=None):
    cfg = parse_config({"fx": {"wave": item_cfg} if item_cfg else {}, "palette_settings": palette_cfg or {}})
    rig = app.engine.rig
    old = rig.autopilot
    rig.autopilot = cfg
    try:
        ar = auto_rig(rig)
    finally:
        rig.autopilot = old
    data = compose(Pick(colour="wave", palette="fire"), ar, COLOURS)
    sc = parse_scene(data, app.files.patch, app.files.palettes, "t")
    pl = ScenePlayer(sc, rig, 0.0, darkness=lambda now: darkness)
    return data, lit_px(pl(0.0))


def test_follow_exempt_reduced(app):
    data, (on, n) = _bars_lit(app, None, 1.0)
    assert all("darkness" not in ly for ly in data["layers"])  # Follow: the scene is exactly as before
    assert on == 0
    data, (on, n) = _bars_lit(app, {"darkness": "exempt"}, 1.0)
    assert on == n  # Exempt: fully lit at 100 % Darkness
    _, (half, n) = _bars_lit(app, {"darkness": 0.5}, 1.0)  # Reduced 50 %: like Darkness 50 %
    _, (fifty, _) = _bars_lit(app, None, 0.5)
    assert half == fifty and 0 < half < n


def test_palette_exempt(app):
    _, (on, n) = _bars_lit(app, None, 1.0, {"fire": {"darkness": "exempt"}})
    assert on == n


def test_layer_darkness_key_in_scenes(app):
    sc = parse_scene({"layers": [{"fixtures": ["bars"], "colour": "red", "darkness": 0}]},
                     app.files.patch, app.files.palettes, "t")
    assert sc.layers[0].dark == {"*": 0.0}
    with pytest.raises(Exception, match="isn't one of this layer's lights"):
        parse_scene({"layers": [{"fixtures": ["bars"], "colour": "red", "darkness": {"mh_a": 0}}]},
                    app.files.patch, app.files.palettes, "t")


# ---------------------------------------------------------------- API and Claude


def test_api_and_claude(running):
    from test_web import call

    from dmx_suite.claude_tools import DmxTools

    app, url, root, claude = running
    st, it = call(f"{url}/api/autopilot/fx", "POST", {"action": "get", "item": "fan"})
    assert st == 200 and it["priority"] == 3 and any(p["key"] == "period_s" for p in it["params"])
    st, r = call(f"{url}/api/autopilot/fx", "POST", {"action": "priority", "item": "fan"})
    assert st == 200 and r["priority"] == 4
    assert call(f"{url}/api/autopilot/fx", "POST", {"action": "save", "item": "fan", "overrides": {"priority": 9}})[0] == 400
    t = DmxTools(shows=root, url=url, token=claude)
    assert "priority 5" in t.save_fx("fan", "{priority: 5, darkness: exempt, params: {period_s: 8}}")
    got = yaml.safe_load(t.get_fx("fan"))
    assert got["overrides"] == {"priority": 5, "darkness": "exempt", "params": {"period_s": 8}}
    assert "fan_v1" in t.duplicate_fx("fan", "Fan wide")
    assert "priority 0 (excluded)" in t.set_fx_priority("fan_v1", 0)
    assert "fan_v1" in app.rig_auto().excluded_fx
    assert "deleted fan_v1" in t.delete_fx("fan_v1")
    assert "defaults" in t.save_fx("fan", "{}")
    assert "priority 2" in t.set_fx_priority(palette="ice", priority=2)
    assert yaml.safe_load(t.get_fx(palette="ice"))["priority"] == 2
    st, r = call(f"{url}/api/autopilot/fx", "POST", {"action": "preview", "item": "rainbow"})
    assert st == 200 and "previewing" in r["message"]
