"""FX banks, ride controls, look quality rules, rig size scaling and classification (v3.3);
drum-reactive effects and Flash FX; every item under every rule on a reference and a small rig."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from dmx_suite.classify import auto_rig, natural_class, parse_auto
from dmx_suite.drums import DrumBus
from dmx_suite.engine import Engine
from dmx_suite.fixtures import ConfigError, parse_patch
from dmx_suite.fxbanks import BY_ID, FLASH_ITEMS, ITEMS, Pick, RideSettings, available, can_run, combine, compose
from dmx_suite.look import parse_look
from dmx_suite.output import LogDriver
from dmx_suite.palettes import CURATED, parse_palettes
from dmx_suite.quality import DEFAULTS, Quality, check_rules, load_rules, palette_hue_change
from dmx_suite.rig import parse_rig
from dmx_suite.scenes import ScenePlayer, parse_scene
from dmx_suite.showfiles import load_show

from conftest import PATCH, RIG, Clock
from rulecheck import rule_matrix

SHOWS = Path(__file__).resolve().parents[1] / "shows"
GOLDEN = Path(__file__).parent / "data" / "golden_v3_fx.json"

TWO_PARS = {
    "types": {"par": {"kind": "wash", "channels": ["red", "green", "blue"]}},
    "fixtures": [{"id": "par_1", "type": "par", "address": 1}, {"id": "par_2", "type": "par", "address": 10}],
}


def small_rig():
    patch = parse_patch(TWO_PARS)
    return parse_rig({"name": "two pars", "profile": "generic"}, patch)


def ref_rig(profile="0.05_band", **extra):
    return parse_rig({**RIG, "profile": profile, **extra}, parse_patch(PATCH))


# ------------------------------------------------------------------ classification


def test_natural_classes():
    patch = parse_patch(PATCH)
    got = {f: natural_class(fx) for f, fx in patch.fixtures.items()}
    assert got == {"mh_a": "head", "bar_1": "pixel", "bar_2": "pixel", "wash": "wash", "uk": "wash",
                   "kick": "wash", "smoke": None}


def test_auto_rig_band_and_generic():
    band = auto_rig(ref_rig())
    assert band.classes["head"] == ["mh_a"] and band.classes["kick"] == ["kick"]
    assert "smoke" not in band.of  # haze is never in the auto show (rule 5)
    assert "kick" not in band.colour_lights  # MASTER-exempt: keeps its own rules (rule 3)
    generic = auto_rig(ref_rig("generic"))
    assert generic.classes["kick"] == [] and "kick" in generic.classes["wash"]
    assert band.pixels == 4


def test_overrides_and_exclude():
    r = ref_rig(auto={"classes": {"wash": "strobe"}, "exclude": ["bar_2"]})
    ar = auto_rig(r)
    assert ar.classes["strobe"] == ["wash"] and "bar_2" not in ar.of and ar.excluded == ["bar_2"]


@pytest.mark.parametrize("bad, msg", [
    ({"classes": {"wash": "head"}}, "can't move"),
    ({"classes": {"wash": "pixel"}}, "no pixels"),
    ({"classes": {"smoke": "wash"}}, "haze"),
    ({"classes": {"nope": "wash"}}, "unknown fixture"),
    ({"classes": {"wash": "laser"}}, "one of"),
    ({"exclude": ["nope"]}, "unknown fixture"),
    ({"colours": 1}, "classes"),
])
def test_bad_auto(bad, msg):
    with pytest.raises(ConfigError, match=msg):
        parse_auto(bad, parse_patch(PATCH))


# ------------------------------------------------------------------ rig size scaling


def test_two_pars_get_a_reduced_set():
    ar = auto_rig(small_rig())
    ids = {i.id for i in available(ar)}
    assert not any(BY_ID[i].bank == "move" for i in ids)  # no heads
    assert not ids & {"bounce", "comet", "fill", "gradient", "radial", "plasma", "bars", "chase_in", "tom_roll"}
    assert {"static", "colour_fade", "pulse", "split", "kick_pump", "blinder"} <= ids
    for i in ITEMS:
        if i.id not in ids:
            assert not can_run(i, ar)


def test_full_rig_unlocks_more():
    files = load_show(SHOWS)
    ar = auto_rig(files.rig)
    ids = {i.id for i in available(ar)}
    assert {"ballyhoo", "comet", "gradient", "crossfire"} <= ids


def test_switching_rig_re_evaluates():
    full, small = load_show(SHOWS, rig="full"), load_show(SHOWS, rig="small")
    a, b = {i.id for i in available(auto_rig(full.rig))}, {i.id for i in available(auto_rig(small.rig))}
    assert "pan_sweep" in a and "pan_sweep" not in b


# ------------------------------------------------------------------ composing picks


def pal_colours(key="cool"):
    return list(CURATED[key]["colours"])


@pytest.mark.parametrize("item", [i.id for i in ITEMS])
def test_every_item_composes_and_keeps_every_rule(item):
    """Every FX item, on the reference rig, under both profiles, through the rule check."""
    it = BY_ID[item]
    pick = Pick(move=item if it.bank == "move" else "pan_sweep",
                colour=item if it.bank == "colour" else "static",
                drum=item if it.bank == "drum" else None, palette="cool")

    def play(e, clock):
        bus = DrumBus()
        for k in range(6):
            bus.add("x", ["kick", "snare", "tom", "cymbal", "activity"], 0.8, clock() + 0.1 * k)
        import dmx_suite.drums as drums

        drums.BUS = bus
        pal = parse_palettes({}, e.rig.patch).with_points(
            parse_rig({**RIG, "positions": {"kit": {"tags": ["band", "safe"], "heads": {"mh_a": {"pan": 0.4, "tilt": 0.3}}}}},
                      e.rig.patch).points)
        data = compose(pick, auto_rig(e.rig), pal_colours())
        sc = parse_scene(data, e.rig.patch, pal, "pick")
        e.set_source(ScenePlayer(sc, e.rig, clock()))

    try:
        rule_matrix(play, seconds=1.0)
    finally:
        import dmx_suite.drums as drums

        drums.BUS = DrumBus()


@pytest.mark.parametrize("item", [i.id for i in ITEMS if i.bank != "move"])
def test_items_on_two_pars(item):
    """Small rig: what can't run is left out; what's left still loads and plays."""
    r = small_rig()
    ar = auto_rig(r)
    pick = Pick(colour=item if BY_ID[item].bank == "colour" else "static", drum=item if BY_ID[item].bank == "drum" else None)
    data = compose(pick, ar, pal_colours("warm"))
    pal = parse_palettes({}, r.patch)
    sc = parse_scene(data, r.patch, pal, "small")
    look = ScenePlayer(sc, r, 0.0)(1.0)
    assert set(look.fixtures) <= {"par_1", "par_2"}


def test_compose_targets_and_palette():
    ar = auto_rig(load_show(SHOWS).rig)
    data = compose(Pick(move="circle", colour="comet", palette="fire"), ar, pal_colours("fire"))
    fixtures = [ly["fixtures"] for ly in data["layers"]]
    assert ["bar_1", "bar_2", "bar_3", "bar_4"] in fixtures  # comet on the pixels
    assert any("mh_a" in f and "wash_l" in f and "uking_l" in f for f in fixtures)  # the rest hold the palette
    assert any(ly.get("effect") == "move" and ly["fixtures"] == ["mh_a", "mh_b"] for ly in data["layers"])
    assert not any("smoke" in f for f in fixtures)
    assert ["kick"] in fixtures and not any("kick" in f and len(f) > 1 for f in fixtures)  # v7: own layer
    small = compose(Pick(move="circle", colour="comet", palette="fire"), auto_rig(ref_rig()), pal_colours("fire"))
    assert not any(ly.get("effect") == "comet" for ly in small["layers"])  # 4 pixels: not enough for a comet


# ------------------------------------------------------------------ ride controls


def test_ride_settings_scale_the_look():
    ar = auto_rig(ref_rig())
    slow_ride = RideSettings(speed=0.5, fan=0.0, size=0.0)
    slow = compose(Pick(move="pan_sweep", colour="colour_chase", ride=slow_ride), ar, pal_colours())
    fast = compose(Pick(move="pan_sweep", colour="colour_chase", ride=RideSettings(speed=2.0, fan=1.0, size=1.0, shift=0.25)),
                   ar, pal_colours())
    s = {ly.get("effect"): ly for ly in slow["layers"]}
    f = {ly.get("effect"): ly for ly in fast["layers"]}
    assert s["colour_chase"]["period_s"] == 4 * f["colour_chase"]["period_s"]
    assert s["colour_chase"]["spread"] == 0 and f["colour_chase"]["spread"] == 1
    assert s["move"]["size"] < f["move"]["size"] <= 0.5
    assert f["move"]["shift"] == 0.25


def test_bank_settings_ride_on_global():
    c = combine(RideSettings(speed=2, fan=0.5), RideSettings(speed=0.5, fan=0.9))
    assert c.speed == 1.0 and c.fan == pytest.approx(0.9)
    assert RideSettings.from_dict({"speed": 99, "fan": -1}).to_dict()["speed"] == 4.0


def test_layer_shift_moves_the_phase():
    patch = parse_patch(PATCH)
    pal = parse_palettes({}, patch)
    r = ref_rig()
    a = parse_scene({"layers": [{"fixtures": ["bars"], "effect": "wave", "period_s": 2}]}, patch, pal, "a")
    b = parse_scene({"layers": [{"fixtures": ["bars"], "effect": "wave", "period_s": 2, "shift": 0.25}]}, patch, pal, "b")
    assert ScenePlayer(b, r, 0.0)(0.0).fixtures["bar_1"].pixels == ScenePlayer(a, r, 0.0)(0.5).fixtures["bar_1"].pixels


# ------------------------------------------------------------------ effects: determinism and golden frames


def frames_for(item_id: str, rig) -> list[str]:
    import dmx_suite.drums as drums

    old = drums.BUS
    bus = DrumBus()
    for k in range(8):
        bus.add("x", ["kick", "snare", "tom", "cymbal", "activity"], (k % 4 + 1) / 4, 1000.0 + 0.2 * k)
    drums.BUS = bus
    try:
        it = BY_ID[item_id]
        pick = Pick(move=item_id if it.bank == "move" else None, colour=item_id if it.bank == "colour" else "static",
                    drum=item_id if it.bank == "drum" else None, palette="neon")
        pal = load_show(SHOWS).palettes if "mh_a" in rig.patch.fixtures else parse_palettes({}, rig.patch)
        sc = parse_scene(compose(pick, auto_rig(rig), pal_colours("neon")), rig.patch, pal, "g")
        clock = Clock()
        e = Engine(rig, [LogDriver()], parse_look({}, rig.patch), clock=clock)
        e.set_source(ScenePlayer(sc, rig, clock()))
        out = []
        for t in (0.0, 0.3, 1.1, 2.6):
            clock.t = 1000.0 + t
            e.tick()
            out.append(hashlib.sha256(b"".join(bytes([u]) + bytes(f) for u, f in sorted(e.frames.items()))).hexdigest()[:12])
        return out
    finally:
        drums.BUS = old


def capture_golden() -> dict[str, list[str]]:
    out = {}
    full = load_show(SHOWS).rig  # the reference rig: the 0.05 full rig
    for it in ITEMS:
        out[f"ref|{it.id}"] = frames_for(it.id, full)
        if can_run(it, auto_rig(small_rig())):
            out[f"small|{it.id}"] = frames_for(it.id, small_rig())
    return out


def test_golden_frames_for_every_item():
    """Every FX item's frames on a reference and a small rig, fixed (python -m tests.test_fx_banks rewrites)."""
    now = capture_golden()
    want = json.loads(GOLDEN.read_text(encoding="utf-8"))
    changed = sorted(k for k in want if now.get(k) != want[k])
    assert not changed, f"changed: {changed[:6]}"
    assert now.keys() == want.keys()
    still = sorted(k for k, v in now.items() if len(set(v)) == 1)
    assert set(still) <= {"ref|static", "small|static", "ref|kit", "ref|split", "small|split", "ref|random_points"}, still


# ------------------------------------------------------------------ drum-reactive


def run_effect(layer, bus, times, fixtures=("bars",)):
    import dmx_suite.drums as drums

    patch = parse_patch(PATCH)
    pal = parse_palettes({}, patch)
    r = ref_rig()
    old, drums.BUS = drums.BUS, bus
    try:
        sc = parse_scene({"layers": [{"fixtures": list(fixtures), **layer}]}, patch, pal, "d")
        p = ScenePlayer(sc, r, 0.0)
        return [p(t) for t in times]
    finally:
        drums.BUS = old


def lvl(look, fid="bar_1"):
    fl = look.fixtures.get(fid)
    if fl is None:
        return 0.0
    cs = fl.pixels or [fl.colour]
    return max((max(c.values(), default=0.0) for c in cs), default=0.0)


def test_kick_pump():
    bus = DrumBus()
    bus.add("kick", ["kick"], 1.0, 10.0)
    before, at, later = run_effect({"effect": "kick_pump", "floor": 0.3, "decay_s": 0.2}, bus, [9.9, 10.0, 11.0])
    assert lvl(before) == pytest.approx(0.3) and lvl(at) == pytest.approx(1.0) and lvl(later) < 0.32


def test_tom_roll_walks():
    bus = DrumBus()
    looks = []
    for k in range(3):
        bus.add("t", ["tom"], 1.0, 10.0 + 0.1 * k)
        looks.append(run_effect({"effect": "tom_roll", "decay_s": 0.05}, bus, [10.0 + 0.1 * k], ("bar_1", "bar_2", "wash"))[0])
    lit = [max(("bar_1", "bar_2", "wash"), key=lambda f: lvl(lk, f)) for lk in looks]
    assert lit == ["bar_1", "bar_2", "wash"]


def test_cymbal_shimmer_dies_away():
    bus = DrumBus()
    bus.add("c", ["cymbal"], 1.0, 5.0)
    looks = run_effect({"effect": "cymbal_shimmer", "length_s": 1.0}, bus, [5.0 + i / 20 for i in range(10)] + [6.5])
    assert any(lvl(lk) > 0 for lk in looks[:5]) and lvl(looks[-1]) == 0


def test_fill_build_ramps():
    calm, busy = DrumBus(), DrumBus()
    for k in range(12):
        busy.add("s", ["snare", "activity"], 1.0, 9.0 + k * 0.08)
    a = run_effect({"effect": "fill_build", "window_s": 1.5, "full_hits": 10}, calm, [10.0])[0]
    b = run_effect({"effect": "fill_build", "window_s": 1.5, "full_hits": 10}, busy, [10.0])[0]
    assert sum(lvl(b, f) for f in ("bar_1", "bar_2")) > sum(lvl(a, f) for f in ("bar_1", "bar_2"))


def test_velocity_colour():
    soft, hard = DrumBus(), DrumBus()
    soft.add("s", ["activity"], 0.0, 1.0)
    hard.add("s", ["activity"], 1.0, 1.0)
    layer = {"effect": "velocity_colour", "colours": ["#0000ff", "#ff0000"]}
    a = run_effect(layer, soft, [1.1], ("wash",))[0].fixtures["wash"].colour
    b = run_effect(layer, hard, [1.1], ("wash",))[0].fixtures["wash"].colour
    assert a["blue"] == 1.0 and b["red"] == 1.0


# ------------------------------------------------------------------ Move FX


def move_looks(pattern, times, **extra):
    patch = parse_patch({**PATCH, "fixtures": [*PATCH["fixtures"], {"id": "mh_b", "type": "head", "address": 90}]})
    r = parse_rig({**RIG, "layout": {"mh_a": {"x": 1, "y": 1}, "mh_b": {"x": 9, "y": 1}},
                   "positions": {"kit": {"tags": ["band", "safe"], "heads": {"mh_a": {"pan": 0.4, "tilt": 0.3},
                                                                             "mh_b": {"pan": 0.6, "tilt": 0.3}}},
                                 "crowd": {"tags": ["audience"], "heads": {"mh_a": {"pan": 0.2, "tilt": 0.6}}}}}, patch)
    pal = parse_palettes({}, patch).with_points(r.points)
    sc = parse_scene({"layers": [{"fixtures": ["mh_a", "mh_b"], "effect": "move", "pattern": pattern, **extra}]}, patch, pal, "m")
    p = ScenePlayer(sc, r, 0.0)
    return [p(t) for t in times]


@pytest.mark.parametrize("pattern", ["pan_sweep", "tilt_sweep", "circle", "figure8", "fan", "swim", "float", "crossfire",
                                     "audience", "ballyhoo"])
def test_move_patterns_stay_in_range_and_move(pattern):
    looks = move_looks(pattern, [i * 0.37 for i in range(30)], period_s=4, size=0.3)
    spots = [(lk.fixtures["mh_a"].pan, lk.fixtures["mh_a"].tilt) for lk in looks]
    assert all(0 <= x <= 1 and 0 <= y <= 1 for x, y in spots) and len({(round(x, 4), round(y, 4)) for x, y in spots}) > 3


def test_mirror_flips_the_right_heads():
    lk = move_looks("pan_sweep", [1.0], period_s=4, size=0.3, mirror=True)[0]
    a, b = lk.fixtures["mh_a"].pan - 0.5, lk.fixtures["mh_b"].pan - 0.5
    assert a == pytest.approx(-b)


def test_points_by_tag_and_dark_moves():
    lk = move_looks("point", [0.0], tags="band")[0]
    assert (lk.fixtures["mh_a"].pan, lk.fixtures["mh_b"].pan) == (0.4, 0.6)
    looks = move_looks("random_points", [i * 0.25 for i in range(40)], tags="safe,audience", period_s=2, dark_move_s=0.5)
    assert {lk.fixtures["mh_a"].pan for lk in looks} <= {0.4, 0.2}
    lk = move_looks("point", [0.0], tags="ceiling")[0]  # no point tagged ceiling: any point
    assert lk.fixtures["mh_a"].pan in (0.4, 0.2)


# ------------------------------------------------------------------ Flash FX


@pytest.fixture
def app(tmp_path):
    from dmx_suite.app import App

    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups"))
    t = Clock()
    a = App(load_show(root), [LogDriver()], clock=t)
    a.t = t
    a.engine.tick()
    return a


def emit(app, fid):
    fx = app.engine.rig.patch.fixtures[fid]
    from dmx_suite.fixtures import EMITTERS

    return [app.engine.frames[fx.universe][fx.slot(c)] for c in fx.type.channels if c.role in EMITTERS]


FLASH_KINDS = ["blinder", "colour_hit", "strobe", "blackout", "freeze", "flash_decay"]  # v8: chase / split hit gone


@pytest.mark.parametrize("kind", FLASH_KINDS)
def test_flash_fx_never_touch_kick_or_haze(app, kind):
    app.engine.haze.set_mode("manual", app.t())
    app.engine.tick()
    kick, haze = emit(app, "kick"), app.engine.frames[0][[c for u, c in app.engine.haze_slots()][0]]
    app.flash_fx(kind, True, "red", "left", 300)
    for _ in range(5):
        app.t.advance(0.05)
        app.engine.tick()
        assert emit(app, "kick") == kick  # rule 3
        assert app.engine.frames[0][[c for u, c in app.engine.haze_slots()][0]] == haze  # rule 5
    app.t.advance(0.5)
    app.engine.tick()
    assert not [o for o in app.engine.overrides if o.key == f"flashfx/{kind}"]  # timed: gone by itself


def test_blinder_held_until_release(app):
    app.flash_fx("blinder", True)
    app.t.advance(5)
    app.engine.tick()
    assert max(emit(app, "bar_1")) == 255
    app.flash_fx("blinder", False)
    app.engine.tick()
    assert not app.engine.overrides


def test_blackout_fx_darkens_but_master_and_haze_stay(app):
    app.flash_fx("blackout", True)
    app.engine.tick()
    assert app.engine.master and not app.engine.blackout
    assert max(emit(app, "wash_l")) == 0
    app.flash_fx("blackout", False)


def test_flash_fx_from_a_pad(app):
    from dmx_suite.midi.inputs import FakeMidiIn
    from dmx_suite.midi.map import parse_map
    from dmx_suite.midi.monitor import MidiMonitor
    from dmx_suite.midi.router import MidiRouter

    r = MidiRouter(app.engine, parse_map({"mappings": [{"input": "crash", "action": "flash_fx", "fx": "blinder"}]}),
                   MidiMonitor(), app.ctl, app.files.inputs)
    r.flash_fx = app.flash_fx_input
    m = FakeMidiIn(r.handle_mido)
    assert m.note(49, 120) == "Crash: blinder on" or m.note(49, 120).endswith("blinder on")
    assert any(o.key == "flashfx/blinder" for o in app.engine.overrides)
    m.note_off(49)
    assert not app.engine.overrides
    with pytest.raises(ConfigError, match="flash_fx needs fx"):
        parse_map({"mappings": [{"input": "crash", "action": "flash_fx", "fx": "laser"}]})


# ------------------------------------------------------------------ quality rules


def test_two_busy_effects_refused():
    q = Quality()
    assert any("two busy" in x for x in q.combo_issues(Pick(move="ballyhoo", colour="sparkle"), "high"))
    assert q.combo_issues(Pick(move="ballyhoo", colour="static"), "high") == []


def test_mood_speeds_and_speed_match():
    q = Quality()
    assert any("too fast" in x for x in q.combo_issues(Pick(move="pan_sweep", colour="comet"), "low"))
    assert any("too slow" in x for x in q.combo_issues(Pick(move="float", colour="static"), "high"))
    assert any("don't match" in x for x in q.combo_issues(Pick(move="float", colour="comet"), "mid"))


def test_contrast():
    q = Quality()
    pals = {k: [parse_palettes({}, parse_patch(PATCH)).sets[k]["resolved"]][0] for k in CURATED}
    a = Pick(move="pan_sweep", colour="static", palette="cool")
    assert not q.contrast_ok(a, Pick(move="pan_sweep", colour="static", palette="ice"), pals)  # blue to blue
    assert q.contrast_ok(a, Pick(move="pan_sweep", colour="static", palette="fire"), pals)
    assert q.contrast_ok(a, Pick(move="circle", colour="static", palette="cool"), pals)
    assert palette_hue_change(pals["fire"], pals["cool"]) > 0.3


def test_curated_palettes_pass_the_palette_rules():
    q = Quality()
    pal = parse_palettes({}, parse_patch(PATCH))
    for k in ("warm", "cool", "fire", "ice"):
        assert q.palette_issues(pal.sets[k]["resolved"]) == [], k
    assert q.palette_issues([{"red": 0.4, "green": 0.3, "blue": 0.2}])  # brown


def test_rules_are_data(tmp_path):
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups"))
    (root / "quality.yaml").write_text("version: 5\nmax_busy: 0.5\nbusy: {static: 0.9}\n", encoding="utf-8")
    r = load_rules(root)
    assert r["max_busy"] == 0.5 and r["lead_busy"] == DEFAULTS["lead_busy"]
    q = Quality(r)
    assert q.combo_issues(Pick(colour="static"), "mid")
    with pytest.raises(ConfigError):
        check_rules({"busy": {"nope": 1}})
    with pytest.raises(ConfigError):
        check_rules({"speed": 1})


# ------------------------------------------------------------------ in the app and over the API


def test_ride_play_and_catalogue(app):
    cat = app.fx_catalogue()
    assert cat["rig"]["classes"]["head"] == ["mh_a", "mh_b"]
    assert {i["id"] for i in cat["items"] if i["available"]} >= {"pan_sweep", "comet"}
    res = app.ride_play({"move": "pan_sweep", "colour": "colour_chase", "palette": "fire", "ride": {"speed": 2}})
    assert res["ok"] and app.ctl.mode == "ride" and "pan_sweep" in app.ctl.describe()
    app.engine.tick()
    assert app.engine.frames[0] != bytearray(512)


def test_drum_bus_fed_from_named_inputs(app):
    from dmx_suite.midi.inputs import FakeMidiIn

    app.bus.clear()
    FakeMidiIn(app.router.handle_mido).note(36, 64)  # kick (TD-25 input, roles kick + activity)
    h = app.bus.last("kick", app.t())
    assert h is not None and h.input == "kick" and h.strength == pytest.approx(64 / 127)


def test_flash_items_listed():
    assert {i.id for i in FLASH_ITEMS} == {"blinder", "colour_hit", "strobe", "blackout", "freeze", "flash_decay"}


# ------------------------------------------------------------------ v7 A1: the kick light follows the look


def _kick_colours(pick, times, darkness=None):
    show = load_show(SHOWS)
    r = show.rig
    data = compose(pick, auto_rig(r), [show.palettes.colour(c, "t") for c in CURATED[pick.palette]["colours"]])
    sc = parse_scene(data, r.patch, show.palettes, "ap")
    play = ScenePlayer(sc, r, 0.0, darkness=darkness)
    return [play(t).fixtures["kick"].colour for t in times]


def test_kick_takes_the_palette_colour():
    (c,) = _kick_colours(Pick(colour="static", palette="fire"), [1.0])
    assert c["red"] > 0.5 and c.get("blue", 0) < 0.2  # fire: red / orange, not the rig's white kick_colour


def test_kick_follows_a_colour_chase():
    cols = _kick_colours(Pick(colour="colour_chase", palette="fire"), [i * 0.25 for i in range(40)])
    assert len({tuple(sorted(c.items())) for c in cols}) > 1  # it changes colour with the chase


def test_kick_holds_the_palette_under_a_pixel_item():
    (c,) = _kick_colours(Pick(colour="comet", palette="fire"), [1.0])
    assert c["red"] > 0.5


def test_kick_stays_lit_at_full_darkness():
    cols = _kick_colours(Pick(colour="colour_chase", palette="fire"), [i * 0.5 for i in range(10)], darkness=lambda now: 1.0)
    assert all(any(v > 0 for v in c.values()) for c in cols)


def test_kick_gets_no_move_drum_or_flash_layers():
    ar = auto_rig(load_show(SHOWS).rig)
    data = compose(Pick(move="circle", colour="colour_chase", drum="kick_pump", palette="fire"), ar, pal_colours("fire"))
    kick_layers = [ly for ly in data["layers"] if "kick" in ly["fixtures"]]
    assert len(kick_layers) == 1 and kick_layers[0]["effect"] == "colour_chase"


if __name__ == "__main__":
    GOLDEN.write_text(json.dumps(capture_golden(), indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print("wrote", GOLDEN)
