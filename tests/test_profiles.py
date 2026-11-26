"""Rule profiles: every rule under both shipped profiles ("0.05 band" and "generic"), profile
parsing, per-profile validation, and the 0.05 shows still rendering exactly as v1 did."""

import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from conftest import LOOK, PATCH, RIG, Clock, View
from golden import GOLDEN, SHOWS, capture

from dmx_suite.auto import RigGroups
from dmx_suite.engine import Engine
from dmx_suite.fixtures import ConfigError, parse_patch
from dmx_suite.look import LookError, parse_look
from dmx_suite.output import LogDriver
from dmx_suite.profile import (
    BAND_005,
    GENERIC,
    V1_DEFAULT,
    parse_profile,
    resolve_exempt,
)
from dmx_suite.rig import parse_rig
from dmx_suite.showfiles import check_all, load_show

PROFILES = ["0.05_band", "generic"]


def build(profile, look=LOOK, **rig_changes):
    patch = parse_patch(PATCH)
    data = {**RIG, **rig_changes}
    if profile is not None:
        data["profile"] = profile
    rig = parse_rig(data, patch)
    clock = Clock()
    e = Engine(rig, [LogDriver()], parse_look(look, patch), clock=clock)
    e.tick()
    return e, View(e), clock


@pytest.fixture(params=PROFILES)
def each(request):
    return build(request.param)


# ------------------------------------------------------------------ parsing


def test_no_profile_is_v1_band_profile():
    assert parse_profile(None) is V1_DEFAULT is BAND_005


@pytest.mark.parametrize("key, p", [("0.05_band", BAND_005), ("generic", GENERIC)])
def test_named_profiles(key, p):
    assert parse_profile(key) is p


def test_custom_profile_from_a_base():
    p = parse_profile({"base": "0.05_band", "name": "Club", "master_exempt": ["wash"]})
    assert (p.key, p.name, p.master_gate, p.drum_flash, p.master_exempt) == ("custom", "Club", True, True, ("wash",))
    assert parse_profile({"base": "generic"}) is GENERIC  # no changes = the shipped profile


@pytest.mark.parametrize("data, msg", [
    ("disco", "unknown profile"),
    ({"base": "disco"}, "unknown profile"),
    ({"base": "generic", "strobe": 1}, "unknown keys"),
    ({"base": "generic", "drum_flash": True}, "needs master_gate"),
    ({"base": "0.05_band", "master_gate": False}, "needs master_gate"),
    ({"base": "generic", "master_gate": "yes"}, "true or false"),
    (["generic"], "profile name"),
])
def test_bad_profiles(data, msg):
    with pytest.raises(ConfigError, match=msg):
        parse_profile(data)


def test_exempt_resolves_kinds_groups_and_ids():
    patch = parse_patch(PATCH)
    present = list(patch.fixtures)
    band = resolve_exempt(BAND_005, patch, present)
    assert band == {"kick"}  # by kind, as v1 did
    custom = parse_profile({"base": "0.05_band", "master_exempt": ["bars", "wash"]})
    assert resolve_exempt(custom, patch, present) == {"bar_1", "bar_2", "wash"}
    assert resolve_exempt(custom, patch, ["bar_1"]) == {"bar_1"}  # only fixtures in the rig
    assert resolve_exempt(GENERIC, patch, present) == frozenset()
    no_gate = replace(GENERIC, master_exempt=("kick",))
    assert resolve_exempt(no_gate, patch, present) == frozenset()  # meaningless without MASTER on/off


def test_bad_exempt_name_rejected():
    with pytest.raises(ConfigError, match="unknown fixture or group"):
        parse_rig({**RIG, "profile": {"base": "0.05_band", "master_exempt": ["nope"]}}, parse_patch(PATCH))


# ------------------------------------------------------------------ 0.05 shows unchanged


def test_shipped_rigs_use_band_profile():
    for name in ("full", "small"):
        assert load_show(SHOWS, rig=name).rig.profile is BAND_005


def _no_strobe_limit(rig):
    # v1 had no strobe limit; this compares the profile split alone (strobe tests are below)
    return replace(rig, strobe_limit_hz=None)


def test_band_profile_renders_v1_frames_byte_for_byte():
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    now = capture(_no_strobe_limit)
    diff = sorted(k for k in golden if now.get(k) != golden[k])
    assert not diff, f"{len(diff)} scenarios changed, e.g. {diff[:5]}"
    assert now.keys() == golden.keys()


def test_rig_without_profile_renders_v1_frames():
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert capture(lambda rig: replace(_no_strobe_limit(rig), profile=V1_DEFAULT)) == golden


# ------------------------------------------------------------------ safety rules: both profiles


def test_rule4_no_glow(each):
    e, view, _ = each
    e.set_look(parse_look({"fixtures": {"mh_a": {"colour": [1, 0, 0]}}}, e.rig.patch))
    for fid in ("bar_1", "bar_2", "wash", "uk"):
        assert view.emitters(fid) == [0] * len(view.emitters(fid))
    e.set_look(parse_look({"fixtures": {"wash": {"colour": [0, 0, 0]}}}, e.rig.patch))
    assert view.emitters("wash") == [0, 0, 0, 0]


def test_rule5_haze_only_from_haze_controls(each):
    e, view, _ = each
    assert view("smoke", "haze") == 0
    with pytest.raises(LookError, match="rule 5"):
        parse_look({"haze": 1}, e.rig.patch)
    e.haze.set_mode("manual", e.clock())
    e.tick()
    assert view("smoke", "haze") == round(0.5 * 255)  # rig haze level 50 %
    e.set_grand(0.0, instant=True)
    e.tick()
    assert view("smoke", "haze") == round(0.5 * 255)  # rule 6: grand master never touches haze


def test_rule6_grand_master_scales_intensity_only(each):
    e, view, _ = each
    pan, tilt, red = view("mh_a", "pan"), view("mh_a", "tilt"), view("mh_a", "red")
    e.set_grand(0.5, instant=True)
    e.tick()
    assert view("mh_a", "dimmer") == 128
    assert (view("mh_a", "pan"), view("mh_a", "tilt"), view("mh_a", "red")) == (pan, tilt, red)
    assert view("bar_1", "green", 0) == 128  # no dimmer: RGB scaled


def test_rule7_colour_only_head_stays_home(each):
    e, view, _ = each
    assert view("uk", "pan") == round(0.25 * 255) and view("uk", "tilt") == round(0.75 * 255)
    with pytest.raises(LookError, match="rule 7"):
        parse_look({"fixtures": {"uk": {"pan": 0.9}}}, e.rig.patch)


def test_rule8_head_limits(each):
    e, view, _ = each
    e.set_look(parse_look({"fixtures": {"mh_a": {"colour": [1, 0, 0], "pan": 0.0, "tilt": 1.0}}}, e.rig.patch))
    assert view("mh_a", "pan") == round(0.10 * 65535) >> 8
    assert view("mh_a", "tilt") == round(0.75 * 65535) >> 8


def test_blackout_darkens_everything_but_haze(each):
    e, view, _ = each
    e.haze.set_mode("manual", e.clock())
    e.set_blackout(True)
    for fid in ("mh_a", "bar_1", "wash", "uk", "kick"):
        assert set(view.emitters(fid)) == {0}
    assert view("smoke", "haze") > 0


# ------------------------------------------------------------------ rule 1: MASTER on/off


def test_rule1_band_master_owns_on_off():
    e, view, _ = build("0.05_band")
    assert view("mh_a", "dimmer") == 255
    e.set_master(False)
    assert view("mh_a", "dimmer") == 0 and view("mh_a", "red") == 0


def test_rule1_generic_lights_follow_the_scene():
    e, view, _ = build("generic")
    e.set_master(False)  # MASTER has no say under generic
    assert view("mh_a", "dimmer") == 255 and view("mh_a", "red") == 255
    assert view("wash", "dimmer") == 255


def test_generic_intensity_sets_the_level():
    look = {"fixtures": {"mh_a": {"colour": [1, 0, 0], "intensity": 0.5}, "bars": {"colour": [0, 1, 0], "intensity": 0.2}}}
    e, view, _ = build("generic", look=look)
    assert view("mh_a", "dimmer") == 128 and view("mh_a", "red") == 255  # dimmer carries the level
    assert view("bar_1", "green", 0) == 51  # no dimmer: RGB scaled
    e.set_grand(0.5, instant=True)
    e.tick()
    assert view("mh_a", "dimmer") == 64  # intensity x grand master


def test_band_rule_layer_ignores_intensity():
    # validation refuses it first (below); the rule layer ignores it as a second guard
    look = {"fixtures": {"mh_a": {"colour": [1, 0, 0], "intensity": 0.1}}}
    e, view, _ = build("0.05_band", look=look)
    assert view("mh_a", "dimmer") == 255


def test_intensity_zero_is_dark_under_generic():
    look = {"fixtures": {"wash": {"colour": [1, 1, 1], "intensity": 0}, "bars": {"colour": [1, 1, 1], "intensity": 0}}}
    e, view, _ = build("generic", look=look)
    assert view("wash", "dimmer") == 0  # dimmer fixture: the dimmer carries the level
    assert view.emitters("bar_1") == [0] * 6  # no dimmer: RGB scaled to 0


# ------------------------------------------------------------------ rule 2: drum flash


def test_rule2_band_flashes_with_master_off():
    e, view, _ = build("0.05_band")
    e.set_master(False)
    assert e.flash(["bar_1"], 127, "white")
    assert view("bar_1", "red", 0) == 255


def test_rule2_generic_has_no_drum_flash():
    e, view, _ = build("generic")
    e.set_master(False)
    before = bytes(e.frames[0])
    assert not e.flash(["bar_1"], 127, "white")
    assert bytes(e.frames[0]) == before
    assert view("bar_1", "red", 0) == 0 and view("bar_1", "green", 0) == 255  # look, not a flash


# ------------------------------------------------------------------ rule 3: fixtures MASTER ignores


def test_rule3_band_kick_ignores_master():
    e, view, _ = build("0.05_band")
    e.set_master(False)
    assert view.emitters("kick") == [255, 128, 0]  # rig kick_colour
    assert e.flash(["kick", "bar_1"], 127, "white")
    assert view.emitters("kick") == [255, 128, 0]  # flashes never drive it
    assert view("bar_1", "blue", 0) == 255


def test_rule3_generic_kick_is_an_ordinary_light():
    e, view, _ = build("generic")
    assert e.rig.exempt == frozenset()
    assert view.emitters("kick") == [0, 0, 0]  # not in the look: dark (rule 4), no kick_colour
    e.set_look(parse_look({"fixtures": {"kick": {"colour": [0, 0, 1]}}}, e.rig.patch))
    assert view.emitters("kick") == [0, 0, 255]


def test_rule3_custom_exempt_list():
    e, view, _ = build({"base": "0.05_band", "master_exempt": ["wash"]})
    e.set_master(False)
    assert view("wash", "dimmer") == 255 and view("wash", "blue") == 255
    assert view.emitters("kick") == [0, 0, 0]  # no longer exempt: MASTER off darkens it
    assert e.flash(["wash", "bar_1"], 127, "white")
    assert view("wash", "red") == 0  # exempt fixtures never flash


def test_find_darkens_exempt_fixtures():
    e, view, _ = build({"base": "0.05_band", "master_exempt": ["wash", "kick"]})
    e.find_fixture("mh_a")
    assert view.emitters("wash") == [0, 0, 0, 0] and view.emitters("kick") == [0, 0, 0]
    e.find_fixture("kick")
    assert view.emitters("kick") == [255, 255, 255]


def test_auto_show_groups_follow_profile():
    band = RigGroups.of(parse_rig({**RIG, "profile": "0.05_band"}, parse_patch(PATCH)))
    gen = RigGroups.of(parse_rig({**RIG, "profile": "generic"}, parse_patch(PATCH)))
    assert band.kick == ["kick"] and "kick" not in band.washes
    assert gen.kick == [] and "kick" in gen.washes


# ------------------------------------------------------------------ validation per rig profile


INTENSITY_SCENE = {"name": "Half", "layers": [{"fixtures": ["bars"], "colour": "blue", "intensity": 0.5}]}


@pytest.fixture
def shows(tmp_path):
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json", ".giglock"))
    return root


def _set_profile(root: Path, profile: str) -> None:
    for p in (root / "rigs").glob("*.yaml"):
        p.write_text(p.read_text(encoding="utf-8").replace("profile: 0.05_band", f"profile: {profile}"), encoding="utf-8")


def test_intensity_scene_refused_on_band_rigs(shows):
    (shows / "scenes" / "half.yaml").write_text(yaml.safe_dump(INTENSITY_SCENE), encoding="utf-8")
    problems = [p for p in check_all(shows) if not p.startswith("warning")]
    assert any("rig full" in p and "scenes/half.yaml" in p and "rule 1" in p for p in problems)
    assert any("rig small" in p for p in problems)
    with pytest.raises(ConfigError, match="rule 1"):
        load_show(shows, rig="full")


def test_intensity_look_refused_on_band_rigs(shows):
    dim = {"fixtures": {"bars": {"colour": [1, 0, 0], "intensity": 0.3}}}
    (shows / "looks" / "dim.yaml").write_text(yaml.safe_dump(dim), encoding="utf-8")
    assert any("looks/dim.yaml" in p and "rule 1" in p for p in check_all(shows))


def test_intensity_scene_fine_on_generic_rigs(shows):
    _set_profile(shows, "generic")
    (shows / "scenes" / "half.yaml").write_text(yaml.safe_dump(INTENSITY_SCENE), encoding="utf-8")
    assert [p for p in check_all(shows) if not p.startswith("warning")] == []
    assert load_show(shows, rig="full").scenes["half"].uses_intensity


def test_drum_flash_mappings_warn_on_generic_rigs(shows):
    assert not any("drum flash" in p for p in check_all(shows))
    _set_profile(shows, "generic")
    assert any(p.startswith("warning") and "drum flash" in p and "rule 2" in p for p in check_all(shows))


# ------------------------------------------------------------------ strobe rate limit (safety)


def _lit_fraction(view, e) -> float:
    lights = [f.id for f in e.rig.fixtures if view.emitters(f.id)]
    return sum(1 for f in lights if any(view.emitters(f))) / len(lights)


def _onsets(samples: list[tuple[float, float]]) -> list[float]:
    """Times the rig's lit fraction jumps by FLASH_STEP or more from its low since the last jump."""
    out, low = [], 1.0
    for t, lit in samples:
        if lit - low >= 0.25:
            out.append(t)
            low = lit
        low = min(low, lit)
    return out


def test_strobe_limit_from_rig_file():
    patch = parse_patch(PATCH)
    assert parse_rig(RIG, patch).strobe_limit_hz == 3.0  # on by default
    assert parse_rig({**RIG, "strobe_limit_hz": 10}, patch).strobe_limit_hz == 10.0
    for bad in (0, 0.1, 30, "fast", None):
        with pytest.raises(ConfigError, match="strobe_limit_hz"):
            parse_rig({**RIG, "strobe_limit_hz": bad}, patch)


def test_raised_strobe_limit_warns(shows):
    assert not any("strobe" in p for p in check_all(shows))
    rig = shows / "rigs" / "full.yaml"
    rig.write_text(rig.read_text(encoding="utf-8") + "\nstrobe_limit_hz: 8\n", encoding="utf-8")
    assert any(p.startswith("warning: rigs/full.yaml: strobe limit raised to 8") for p in check_all(shows))


def test_strobe_limit_holds_a_20_hit_drum_roll():
    e, view, clock = build("0.05_band")
    clock.advance(5)
    e.set_master(False)
    clock.advance(5)
    lights = [f.id for f in e.rig.fixtures if f.id not in e.rig.exempt]
    samples, start = [], clock()
    for i in range(200):  # 1 s in 5 ms steps; a hit every 50 ms (20 hits), each 40 ms long
        if i % 10 == 0:
            e.flash(lights, 127, "white", length_ms=40)
        else:
            e.tick()
        samples.append((clock() - start, _lit_fraction(view, e)))
        clock.advance(0.005)
    onsets = _onsets(samples)
    assert 2 <= len(onsets) <= 3  # 20 hits, at most 3 flashes reach the rig
    assert all(b - a >= 1 / 3 - 1e-9 for a, b in zip(onsets, onsets[1:]))
    assert e.rules.held > 0


@pytest.mark.parametrize("profile", PROFILES)
def test_strobe_limit_holds_a_fast_strobe_effect(profile):
    from dmx_suite.palettes import parse_palettes
    from dmx_suite.scenes import ScenePlayer, parse_scene

    e, view, clock = build(profile)
    pal = parse_palettes({"colours": {"white": [1, 1, 1]}}, e.rig.patch)
    sc = parse_scene({"layers": [{"fixtures": ["all"], "effect": "flash", "colour": "white", "rate_hz": 10, "duty": 0.5}]},
                     e.rig.patch, pal, "strobe")
    clock.advance(5)
    e.set_source(ScenePlayer(sc, e.rig, clock()))
    samples = []
    for _ in range(120):  # 3 s at 40 frames a second
        clock.advance(0.025)
        e.tick()
        samples.append((clock(), _lit_fraction(view, e)))
    onsets = _onsets(samples)
    assert 8 <= len(onsets) <= 10  # 30 flashes asked for, about 3 a second delivered
    assert all(b - a >= 1 / 3 - 1e-9 for a, b in zip(onsets, onsets[1:]))


def test_raised_strobe_limit_lets_more_through():
    from dmx_suite.palettes import parse_palettes
    from dmx_suite.scenes import ScenePlayer, parse_scene

    e, view, clock = build("generic", strobe_limit_hz=12)
    pal = parse_palettes({"colours": {"white": [1, 1, 1]}}, e.rig.patch)
    sc = parse_scene({"layers": [{"fixtures": ["all"], "effect": "flash", "colour": "white", "rate_hz": 10, "duty": 0.5}]},
                     e.rig.patch, pal, "strobe")
    clock.advance(5)
    e.set_source(ScenePlayer(sc, e.rig, clock()))
    samples = []
    for _ in range(120):
        clock.advance(0.025)
        e.tick()
        samples.append((clock(), _lit_fraction(view, e)))
    assert len(_onsets(samples)) >= 25


def test_chases_are_not_flashes():
    """Light moving round the rig without a rig-wide jump passes through untouched."""
    from dmx_suite.palettes import parse_palettes
    from dmx_suite.scenes import ScenePlayer, parse_scene

    def frames(limit):
        e, _, clock = build("generic")
        e.rig.strobe_limit_hz = limit
        pal = parse_palettes({"colours": {"red": [1, 0, 0], "blue": [0, 0, 1]}}, e.rig.patch)
        sc = parse_scene({"layers": [
            {"fixtures": ["bars"], "effect": "pixel_chase", "colour": "red", "width": 1, "period_s": 0.3},
            {"fixtures": ["mh_a", "wash", "uk", "kick"], "effect": "colour_chase", "colours": ["red", "blue"],
             "period_s": 0.2, "spread": 1},
        ]}, e.rig.patch, pal, "chase")
        clock.advance(5)
        e.set_source(ScenePlayer(sc, e.rig, clock()))
        out = []
        for _ in range(120):
            clock.advance(0.025)
            e.tick()
            out.append(bytes(e.frames[0]))
        return out

    assert frames(3.0) == frames(None)
