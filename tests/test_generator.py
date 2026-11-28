"""Generator, presets, look ratings and the review list (v3.5): same seed = same files, every
generated file passes `dmx-suite check` and every rule, lock-and-re-roll keeps what's locked,
capture matches the live frame, bans are never chosen again, presets in shows and setlists."""

import shutil
from pathlib import Path

import pytest
import yaml

from dmx_suite.drums import DrumBus
from dmx_suite.engine import Engine
from dmx_suite.fixtures import ConfigError
from dmx_suite.fxbanks import BY_ID, Pick
from dmx_suite.generator import STYLES, song_plan
from dmx_suite.output import LogDriver
from dmx_suite.presets import STARTERS, look_key, parse_presets
from dmx_suite.scenes import ScenePlayer, parse_scene
from dmx_suite.showfiles import check_all, load_show

from conftest import Clock

SHOWS = Path(__file__).resolve().parents[1] / "shows"


@pytest.fixture
def app(tmp_path):
    from dmx_suite.app import App

    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups"))
    clock = Clock()
    a = App(load_show(root), [LogDriver()], clock=clock)
    a.bus = DrumBus()
    a.autopilot.bus = a.autopilot.energy.bus = a.bus
    a.t = clock
    a.engine.tick()
    return a


def errors(root):
    return [p for p in check_all(root) if not p.startswith("warning")]


# ------------------------------------------------------------------ presets


def test_starter_presets_load_and_compose_on_every_rig(app):
    files = app.files
    assert set(STARTERS) <= set(files.presets)
    for k in STARTERS:
        assert f"preset:{k}" in files.scenes
    small = load_show(app.files.root, rig="small")
    assert all(f"preset:{k}" in small.scenes for k in STARTERS)
    assert errors(app.files.root) == []


@pytest.mark.parametrize("bad, msg", [
    ({"presets": {"x": {"pick": {"colour": "laser"}}}}, "isn't a colour"),
    ({"presets": {"x": {"pick": {"move": "static"}}}}, "isn't a move"),
    ({"presets": {"x": {"pick": {"colour": "static", "palette": "nope"}}}}, "unknown palette"),
    ({"presets": {"x": {"pick": {"ride": {"speed": 9}}}}}, "feel speed"),  # v3 key still read
    ({"presets": {"X": {"pick": {}}}}, "lower case"),
    ({"presets": {"x": {"name": "x"}}}, "name, tags and pick"),
    ({"other": {}}, "presets only"),
])
def test_bad_presets(bad, msg):
    with pytest.raises(ConfigError, match=msg):
        parse_presets(bad, {"warm", "cool"})


def test_save_play_and_delete_a_preset(app):
    app.ride_play({"move": "circle", "colour": "colour_chase", "palette": "fire", "feel": {"speed": 2.0}})
    app.save_preset("chorus_fire", "Chorus fire", ["high"])
    pre = app.files.presets["chorus_fire"]
    assert pre["pick"] == {"move": "circle", "colour": "colour_chase", "palette": "fire", "feel": {"speed": 2.0}}
    app.ride_play({"colour": "static", "palette": "white"})
    app.play_preset("chorus_fire")
    assert app.ride_pick.colour == "colour_chase" and app.ride_pick.ride.speed == 2.0
    app.delete_preset("chorus_fire")
    assert "chorus_fire" not in app.files.presets
    with pytest.raises(ValueError, match="starter"):
        app.delete_preset("calm_warm")


def test_presets_as_show_steps_and_setlist_cues(app):
    app.save_preset("chorus_fire", pick={"move": "circle", "colour": "colour_chase", "palette": "fire"})
    app.store.put("show", "pre_show", {"name": "Pre", "sets": {"main": {"steps": [{"preset": "chorus_fire", "hold_s": 5},
                                                                                 {"preset": "calm_warm", "hold_s": 5}]}}})
    app.store.put("setlist", "gig", {"name": "Gig", "songs": [{"name": "Intro", "preset": "calm_warm"},
                                                              {"name": "Rocker", "show": "pre_show"}]})
    app.reload()
    app.ctl.select_show("pre_show")
    app.engine.tick()
    assert app.ctl.player.scene.name == "chorus_fire" or app.ctl.player.current.scene == "preset:chorus_fire"
    app.ctl.load_setlist("gig")
    assert app.ctl.scene_key == "preset:calm_warm"
    with pytest.raises(ValueError, match="still used"):
        app.delete_preset("chorus_fire")


def test_song_limits_the_autopilot_to_presets(app):
    app.store.put("setlist", "gig", {"name": "Gig", "songs": [
        {"name": "Encore", "presets": ["band_groove", "fire_wave"], "mood": "high"},
        {"name": "Ballad", "preset": "calm_warm"}]})
    app.reload()
    app.ctl.load_setlist("gig")
    ap = app.autopilot
    assert ap.st.on and ap.st.allowed == ["band_groove", "fire_wave"] and ap.st.mood == "high"
    allowed = {look_key(STARTERS[k]["pick"]) for k in ("band_groove", "fire_wave")}
    for _ in range(6):
        ap.next(app.t())
        assert ap.st.pick.key() in allowed
    app.ctl.next_song()  # a normal song: any look again (and the scene takes over)
    assert ap.st.allowed is None


def test_bad_setlist_presets(app):
    from dmx_suite.store import StoreError

    with pytest.raises(StoreError, match="unknown preset"):
        app.store.put("setlist", "gig", {"songs": [{"name": "x", "presets": ["nope"]}]})
    with pytest.raises(StoreError, match="no show or scene"):
        app.store.put("setlist", "gig", {"songs": [{"name": "x", "presets": ["calm_warm"], "scene": "opera"}]})


# ------------------------------------------------------------------ ratings and the review list


def test_banned_looks_are_never_chosen_again(app):
    ap = app.autopilot
    ap.set_mood("mid", app.t())
    ap.set_on(True, app.t())
    banned = set()
    for _ in range(6):
        k = ap.st.pick.key()
        app.rate_look(k, -2)
        banned.add(k)
        ap.next(app.t())
    for _ in range(30):
        ap.next(app.t())
        assert ap.st.pick.key() not in banned
    gen = app.generator("x")
    for _ in range(20):
        assert gen.pick("mid").key() not in banned


def test_liked_looks_are_favoured(app):
    gen = app.generator("likes")
    first = gen.pick("mid")
    app.rate_look(first.key(), 1)
    gen2 = app.generator("likes")
    assert gen2.pick("mid").key() == first.key()


def test_ratings_file_and_clear(app):
    app.rate_look({"move": "circle", "colour": "static", "palette": "warm"}, 1)
    data = yaml.safe_load((app.files.root / "ratings.yaml").read_text())
    assert data["looks"] == {"circle|static|-|warm": 1}
    app.rate_look("circle|static|-|warm", 0)
    assert app.look_ratings() == {}
    with pytest.raises(ValueError):
        app.rate_look("x", 3)


def test_review_list_covers_what_the_rig_can_do(app):
    r = app.review_looks(palette="warm", limit=1000)
    assert r["total"] == len(r["looks"]) > 50
    assert {lk["colour"] for lk in r["looks"]} >= {"static", "comet"}
    moves = app.review_looks(bank="move", mood="high", palette="fire", limit=1000)["looks"]
    assert {lk["colour"] for lk in moves} == {"static"} and "ballyhoo" in {lk["move"] for lk in moves}
    app.rate_look(r["looks"][0], -1)
    assert app.review_looks(palette="warm")["looks"][0]["rating"] == -1


# ------------------------------------------------------------------ generator


def test_same_seed_same_files(app):
    a = app.generator("s1").scenes("high", "rock", None, 5, "rock")
    b = app.generator("s1").scenes("high", "rock", None, 5, "rock")
    c = app.generator("s2").scenes("high", "rock", None, 5, "rock")
    assert a == b and a != c
    assert all(d["generated"]["seed"] == "s1" and d["generated"]["mood"] == "high" for d in a.values())


@pytest.mark.parametrize("style", sorted(STYLES))
def test_generated_scenes_pass_check_and_rules(app, style):
    q = app.quality()
    res = app.generate("scenes", {"mood": "mid" if style != "ballad" else "low", "style": style, "count": 4,
                                  "prefix": style, "seed": "t"})
    assert len(res["scenes"]) == 4
    assert errors(app.files.root) == []
    picks = [Pick.from_dict(yaml.safe_load((app.files.root / "scenes" / f"{k}.yaml").read_text())["generated"]["pick"])
             for k in res["scenes"]]
    for p in picks:
        mood = "low" if style == "ballad" else "mid"
        assert q.combo_issues(p, mood) == [], (style, p)
    pals = {k: v["resolved"] for k, v in app.files.palettes.sets.items()}
    for a, b in zip(picks, picks[1:]):  # never two busy effects together; consecutive looks contrast
        assert q.contrast_ok(a, b, pals)
    for k in res["scenes"]:  # no haze, no kick light
        text = (app.files.root / "scenes" / f"{k}.yaml").read_text()
        assert "smoke" not in text and "haze" not in text and "kick:" not in text


def test_style_limits(app):
    gen = app.generator("o")
    for _ in range(10):
        p = gen.pick("low", "opera")
        assert p.colour in STYLES["opera"]["colour"] and p.palette == "white" and p.drum is None


def test_generate_show_from_a_mood_plan(app):
    plan = [{"section": "verse", "mood": "low", "length": 2}, {"section": "chorus", "mood": "high", "length": 2},
            {"section": "verse", "mood": "low", "length": 2}, {"section": "bridge", "mood": "mid", "length": 1}]
    res = app.generate("show", {"name": "Opener", "plan": plan, "seed": "p", "hold_s": 20})
    assert res["shows"] == ["opener"] and set(res["scenes"]) == {"opener_verse", "opener_chorus", "opener_bridge"}
    show = yaml.safe_load((app.files.root / "shows" / "opener.yaml").read_text())
    steps = show["sets"]["song"]["steps"]
    assert [s["scene"] for s in steps] == ["opener_verse", "opener_chorus", "opener_verse", "opener_bridge"]
    assert steps[0]["hold_s"] == 20 and steps[3]["hold_s"] == 10 and all("fade_s" in s for s in steps)
    assert show["generated"]["plan"][1] == {"section": "chorus", "mood": "high", "length": 2}
    app.ctl.select_show("opener")
    app.engine.tick()
    assert errors(app.files.root) == []


def test_starter_show_per_song(app):
    songs = [{"name": "Slow one", "scene": "opera", "mood": "low", "bpm": 70},
             {"name": "Fast one", "scene": "opera", "mood": "high", "bpm": 160}]
    app.store.put("setlist", "gig", {"name": "Gig", "songs": songs})
    app.reload()
    res = app.generate("setlist", {"setlist": "gig", "seed": "g"})
    assert set(res["shows"]) == {"slow_one", "fast_one"}
    slow = yaml.safe_load((app.files.root / "shows" / "slow_one.yaml").read_text())
    assert slow["sets"]["song"]["steps"][0]["hold_s"] == pytest.approx(8 * 4 * 60 / 70 / 2, abs=0.01)
    plan, hold = song_plan("high", 160)
    assert [m for _, m, _ in plan] == ["mid", "mid", "high", "mid", "high", "mid"] and hold == 12.0
    with pytest.raises(ValueError, match="already exists"):
        app.generate("setlist", {"setlist": "gig", "seed": "g"})
    app.generate("setlist", {"setlist": "gig", "seed": "g", "overwrite": True})


def test_generator_refused_under_gig_lock(app):
    from dmx_suite.store import LockedError

    app.set_gig_lock(True)
    with pytest.raises(LockedError):
        app.generate("scenes", {"count": 2})


# ------------------------------------------------------------------ lock and re-roll, more like this, capture


def test_reroll_keeps_locked_parts(app):
    app.ride_play({"move": "circle", "colour": "colour_chase", "drum": None, "palette": "fire", "ride": {"speed": 1.5}})
    base = app.ride_pick
    for locks in (["colour"], ["move", "palette"], ["ride"], ["colour", "move", "palette"]):
        app.ride_play(base.to_dict())
        app.reroll(locks, "mid", seed="r")
        new = app.ride_pick
        for k in locks:
            if k == "ride":
                assert new.ride.speed == 1.5
            else:
                assert getattr(new, k) == getattr(base, k)
        assert new.key() != base.key() or locks == ["ride"]
    with pytest.raises(ValueError):
        app.generator("x").reroll(base, ("laser",))


def test_more_like_this(app):
    app.ride_play({"move": "circle", "colour": "colour_chase", "palette": "fire"})
    picks = app.more_like_this(4, seed="m")
    assert len(picks) == 4 and all(p["move"] == "circle" and p["colour"] == "colour_chase" for p in picks)
    assert len({(p["palette"], p["feel"]["fan"]) for p in picks}) > 1


def test_capture_matches_the_live_frame(app):
    app.ride_play({"move": "pan_sweep", "colour": "colour_chase", "palette": "cool"}, 0)
    start = app.t()
    app.t.advance(1.3)
    app.engine.tick()
    live_frame = bytes(app.engine.frames[0])
    app.capture_look("big_chorus")
    data = yaml.safe_load((app.files.root / "scenes" / "big_chorus.yaml").read_text())
    assert data["generated"]["pick"]["colour"] == "colour_chase"
    sc = parse_scene({k: v for k, v in data.items() if k != "version"}, app.files.patch, app.files.palettes, "c")
    clock = Clock()
    clock.t = start
    e = Engine(app.engine.rig, [LogDriver()], app.files.look, clock=clock)
    e.set_source(ScenePlayer(sc, app.engine.rig, start))
    clock.t = start + 1.3
    e.tick()
    assert bytes(e.frames[0]) == live_frame


def test_capture_a_still_of_any_look(app):
    app.ctl.select_scene("opera")
    app.t.advance(2)
    app.engine.tick()
    before = bytes(app.engine.frames[0])
    app.capture_look("opera_still")
    data = yaml.safe_load((app.files.root / "scenes" / "opera_still.yaml").read_text())
    assert data["layers"] and "generated" in data
    app.reload()
    app.ctl.select_scene("opera_still")
    app.engine.tick()
    still = bytes(app.engine.frames[0])
    diff = sum(1 for a, b in zip(before, still) if abs(a - b) > 1)
    assert diff <= 4  # the still holds what was showing (a moving head may differ in its fine channel)


# ------------------------------------------------------------------ Claude


def test_claude_tools_generate_and_presets(app, tmp_path):
    from dmx_suite.web.server import WebServer

    web = WebServer(app, "127.0.0.1", 0, token="t" * 32)
    web.start()
    try:
        from dmx_suite.claude_tools import DmxTools

        tools = DmxTools(app.files.root, url=f"http://127.0.0.1:{web.port}", token=app_claude_token())
        out = tools.generate("scenes", "{mood: low, style: ballad, count: 3, prefix: slow, seed: c}")
        assert "slow_1" in out
        assert "calm_warm" in tools.list_presets()
        preset = "{name: Verse blues, tags: [low], pick: {colour: colour_fade, palette: cool}}"
        assert "saved" in tools.save_preset("verse_blues", preset)
        assert "verse_blues" in app.files.presets
    finally:
        web.stop()


def app_claude_token():
    from dmx_suite.access import claude_token

    return claude_token()


def test_every_fx_item_has_a_bank():
    assert {i.bank for i in BY_ID.values()} == {"move", "colour", "drum", "flash"}
