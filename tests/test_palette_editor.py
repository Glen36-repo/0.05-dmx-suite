"""Colour wheel and palette editor (v3.1): colour theory, kelvin presets, what each light can make
of a colour, palettes in palettes.yaml, named colour renames and in-use checks, import/export."""

import shutil
from pathlib import Path

import pytest

from dmx_suite.colourtheory import (
    KELVIN_PRESETS,
    from_hsv,
    generate,
    hex_of,
    hue_distance,
    kelvin,
    muddy,
    scheme_of,
    to_hsv,
)
from dmx_suite.fixtures import ConfigError, parse_patch
from dmx_suite.look import parse_colour
from dmx_suite.palettes import CURATED, parse_palettes
from dmx_suite.showfiles import load_show
from dmx_suite.store import ShowStore, StoreError

from conftest import PATCH
from rulecheck import rule_matrix

SHOWS = Path(__file__).resolve().parents[1] / "shows"
RED = {"red": 1.0, "green": 0.0, "blue": 0.0}


# ------------------------------------------------------------------ colour theory


@pytest.mark.parametrize("scheme, want", [("analogous", "analogous"), ("complementary", "complementary"),
                                           ("triadic", "triadic"), ("mono", "mono"), ("split", "split")])
def test_generated_palettes_follow_their_scheme(scheme, want):
    cols = generate(RED, scheme, 3 if scheme in ("triadic", "split") else 2 if scheme == "complementary" else 4)
    assert cols[0] == {"red": 1.0, "green": 0.0, "blue": 0.0}  # base first
    assert scheme_of(cols) == want


def test_generate_counts_and_no_repeats():
    for scheme in ("analogous", "complementary", "triadic", "split", "mono"):
        for n in (2, 5, 8):
            cols = generate({"red": 0.2, "green": 0.4, "blue": 1.0}, scheme, n)
            assert len(cols) == n and len({hex_of(c) for c in cols}) == n
    with pytest.raises(ValueError):
        generate(RED, "rainbow")


def test_complementary_is_opposite():
    a, b = generate({"red": 0.0, "green": 0.3, "blue": 1.0}, "complementary", 2)
    assert hue_distance(to_hsv(a)[0], to_hsv(b)[0]) == pytest.approx(0.5, abs=0.01)


def test_kelvin_presets_run_warm_to_cool():
    warm, cool = kelvin(2700), kelvin(9000)
    assert warm["red"] == 1.0 and warm["blue"] < 0.7
    assert cool["blue"] == 1.0 and cool["red"] < 0.9
    blues = [kelvin(k)["blue"] for _, k in KELVIN_PRESETS]
    assert blues == sorted(blues)
    assert hex_of(kelvin(6500))[:3] == "#ff"


def test_muddy_colours():
    assert muddy({"red": 0.4, "green": 0.3, "blue": 0.2})  # brown
    assert not muddy(RED) and not muddy({"red": 1, "green": 1, "blue": 1})


def test_hsv_round_trip():
    c = from_hsv(0.6, 0.8, 0.9)
    h, s, v = to_hsv(c)
    assert (h, s, v) == pytest.approx((0.6, 0.8, 0.9), abs=0.001)


# ------------------------------------------------------------------ palettes in palettes.yaml


def test_palette_sets_parse_and_resolve_named_colours():
    p = parse_palettes({"colours": {"band_red": "#ff0010"},
                        "palettes": {"set": {"name": "Set", "tags": ["warm"], "colours": ["band_red", "#00ff00", "white"]}}},
                       parse_patch(PATCH))
    s = p.sets["set"]
    assert s["resolved"][0] == {"red": 1.0, "green": 0.0, "blue": 16 / 255}
    assert s["tags"] == ["warm"] and not s.get("builtin")


@pytest.mark.parametrize("bad, msg", [
    ({"x": {"colours": []}}, "at least one colour"),
    ({"x": {"colours": ["nope"]}}, "unknown colour"),
    ({"x": {"colours": ["#fff"]}}, "not #rrggbb"),
    ({"X": {"colours": ["white"]}}, "lower case"),
    ({"x": {"colours": ["white"], "mood": 1}}, "name, tags and colours"),
])
def test_bad_palettes(bad, msg):
    with pytest.raises((ConfigError, Exception), match=msg):
        parse_palettes({"palettes": bad}, parse_patch(PATCH))


def test_curated_palettes_always_there():
    p = parse_palettes({}, parse_patch(PATCH))
    assert set(CURATED) <= set(p.sets) and all(p.sets[k]["builtin"] for k in CURATED)
    assert {"warm", "cool", "fire", "ice", "neon", "white", "band"} == set(CURATED)
    mine = parse_palettes({"palettes": {"warm": {"colours": ["#ff0000"]}}}, parse_patch(PATCH))
    assert not mine.sets["warm"]["builtin"] and len(mine.sets["warm"]["colours"]) == 1


# ------------------------------------------------------------------ store


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups"))
    return ShowStore(root)


def test_rename_named_colour_updates_every_scene(store):
    users = store.colour_users("blue")
    assert any(u.startswith("scenes/") for u in users)
    store.put_entry("palettes", "palettes", "mine", {"name": "Mine", "colours": ["blue", "red"]})
    store.rename_colour("blue", "band_blue")
    files = load_show(store.root)
    assert "band_blue" in files.palettes.colours and "blue" not in files.palettes.colours
    assert files.palettes.sets["mine"]["colours"] == ["band_blue", "red"]
    assert store.colour_users("blue") == [] and store.colour_users("band_blue")


def test_changing_a_named_colour_changes_every_scene(store):
    store.put_entry("palettes", "colours", "blue", "#0000ff")
    files = load_show(store.root)
    blue = {"red": 0.0, "green": 0.0, "blue": 1.0}
    assert any(ly.params.get("colour") == blue for sc in files.scenes.values() for ly in sc.layers)


def test_in_use_deletes_refused(store):
    with pytest.raises(StoreError, match="still used"):
        store.put_entry("palettes", "colours", "blue", None)
    store.put_entry("palettes", "palettes", "mine", {"colours": ["red"]})
    store.put_entry("palettes", "palettes", "mine", None)  # unused: fine
    with pytest.raises(StoreError, match="built in"):
        store.rename_colour("white", "bright")


def test_export_and_import_a_palette(store, tmp_path):
    store.put_entry("palettes", "colours", "band_red", "#ff0010")
    store.put_entry("palettes", "palettes", "gig", {"name": "Gig", "tags": ["high"], "colours": ["band_red", "#00ff00"]})
    data = store.export_palette("gig")
    assert data["colours"] == {"band_red": "#ff0010"} and data["palette"]["gig"]["tags"] == ["high"]
    other = tmp_path / "other"
    shutil.copytree(SHOWS, other, ignore=shutil.ignore_patterns(".backups"))
    s2 = ShowStore(other)
    s2.import_palette(data)
    assert load_show(other).palettes.sets["gig"]["resolved"][0]["red"] == 1.0
    with pytest.raises(StoreError, match="already here"):
        s2.import_palette(data)
    s2.import_palette(data, overwrite=True)


def test_rename_palette(store):
    store.put_entry("palettes", "palettes", "gig", {"colours": ["red"]})
    store.rename_palette("gig", "gig_night")
    assert "gig_night" in load_show(store.root).palettes.sets


# ------------------------------------------------------------------ what each light makes (colour wheel)


@pytest.fixture
def app(tmp_path):
    from dmx_suite.app import App
    from dmx_suite.output import LogDriver

    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups"))
    return App(load_show(root), [LogDriver()])


def test_colour_preview_rgb_and_wheel(app):
    res = app.colour_preview("#ff8000", ["bar_1", "mh_a", "kick"])
    assert res["colour"] == "#ff8000"
    rows = {r["id"]: r for r in res["fixtures"]}
    assert rows["bar_1"]["channels"]["red"] == 1.0 and rows["bar_1"]["shown"] == "#ff8000"
    assert not rows["bar_1"]["differs"]


def test_colour_preview_mixes_for_rgbw_and_snaps_wheels(app):
    patch = parse_patch({"types": {
        "rgbw": {"kind": "wash", "colour_mix": "auto", "channels": ["red", "green", "blue", "white"]},
        "wheel": {"kind": "head", "channels": ["pan", "tilt", "dimmer", "colour_wheel"],
                  "wheel": {"open": {"value": 0, "colour": "#ffffff"}, "red": {"value": 10, "colour": "#ff0000"},
                            "blue": {"value": 20, "colour": "#0000ff"}}},
        "uv": {"kind": "wash", "colour_mix": "auto", "channels": ["red", "green", "blue", "uv"]},
    }, "fixtures": [{"id": "w", "type": "rgbw", "address": 1}, {"id": "h", "type": "wheel", "address": 10},
                    {"id": "u", "type": "uv", "address": 20}]})
    app.engine.rig.patch = patch
    res = {r["id"]: r for r in app.colour_preview({"red": 1, "green": 1, "blue": 1}, ["w"])["fixtures"]}
    assert res["w"]["channels"] == {"red": 0.0, "green": 0.0, "blue": 0.0, "white": 1.0}  # white from RGB
    res = {r["id"]: r for r in app.colour_preview("#e00010", ["h"])["fixtures"]}
    assert res["h"]["slot"] == "red" and res["h"]["shown"] == "#ff0000" and res["h"]["differs"]
    res = {r["id"]: r for r in app.colour_preview({"blue": 0.5, "uv": 1.0}, ["u"])["fixtures"]}
    assert res["u"]["channels"]["uv"] == 1.0  # UV only when asked


def test_palette_preview_under_gig_lock_refused(app):
    from dmx_suite.store import LockedError

    msg = app.palette_preview("warm", "chase", 2)
    assert "previewing" in msg
    app.set_gig_lock(True)
    with pytest.raises(LockedError):
        app.palette_preview("warm")


def test_colour_parse_matches_what_the_wheel_sends():
    """The wheel sends #rrggbb and W/A/UV 0-1; the scene stores exactly that."""
    assert parse_colour({"red": 1.0, "white": 0.5, "uv": 0.25}, "c") == {"red": 1.0, "white": 0.5, "uv": 0.25}


# ------------------------------------------------------------------ rules


def test_palette_previews_keep_every_rule():
    """A palette chase over every light: no dimmer under 0.05 band, no haze, heads within limits."""
    from dmx_suite.scenes import parse_scene

    def play(e, clock):
        from dmx_suite.palettes import parse_palettes

        pal = parse_palettes({}, e.rig.patch)
        lights = ["bar_1", "bar_2", "wash", "uk", "mh_a"]
        sc = parse_scene({"layers": [{"fixtures": lights, "effect": "colour_chase", "period_s": 1,
                                      "colours": CURATED["fire"]["colours"], "fade": True}]}, e.rig.patch, pal, "p")
        e.set_scene(sc)

    rule_matrix(play, seconds=1.0)
