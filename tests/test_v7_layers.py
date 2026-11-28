# ruff: noqa: F811 - pytest fixtures imported from test_autopilot are used as arguments
"""v7 A4 layer timing: Move FX, Colour FX (with the drum item), Palette and Darkness change together (v6) or
each on its own clock (staggered); a lock per layer; every single-layer change passes the quality rules."""

import json
from pathlib import Path

import pytest
from test_autopilot import app, run  # noqa: F401 - pytest fixture

from dmx_suite.autopilot import parse_config
from dmx_suite.fixtures import ConfigError
from dmx_suite.fxbanks import Pick

DATA = Path(__file__).parent / "data"


def session(a, seconds=600):
    """The seeded session the v6 reference was recorded with (drums, a 20 s gap at 280 s)."""
    ap, clock = a.autopilot, a.t
    ap.set_on(True, clock.t)
    out, t0 = [], clock.t
    while clock.t < t0 + seconds:
        clock.advance(0.25)
        el = clock.t - t0
        if el < 280 or el > 300:
            rate = 2 if el < 120 else 6 if el < 240 else 3
            if int(el * 4) % max(1, int(4 / rate)) == 0:
                a.bus.add("x", ["kick", "snare", "activity"], 0.5 + 0.4 * ((int(el) // 30) % 2), clock.t)
        d = ap.tick(clock.t)
        if d:
            out.append(d)
    return out


def staggered(a, **layers):
    a.autopilot.cfg = parse_config({"timing": "staggered", "layers": layers})


# ------------------------------------------------------------------ settings


def test_layer_settings():
    c = parse_config({"timing": "staggered", "layers": {"palette": {"on": "song"}, "move": {"every_s": 30}}})
    assert c["layers"]["palette"] == {"on": "song", "spread": 25, "locked": False}
    assert c["layers"]["move"] == {"every_s": 30, "spread": 25, "locked": False}
    assert c["layers"]["colour"]["every_looks"] == 1.0  # untouched layers keep their default


@pytest.mark.parametrize("bad, msg", [
    ({"timing": "random"}, "together or staggered"),
    ({"layers": {"haze": {"on": "song"}}}, "move, colour, palette, darkness"),
    ({"layers": {"move": {"every_s": 1}}}, "2-3600"),
    ({"layers": {"move": {"every_looks": 0}}}, "0.1-50"),
    ({"layers": {"move": {"on": "bar"}}}, "song or set"),
    ({"layers": {"move": {"every_s": 30, "on": "song"}}}, "one of every_s"),
    ({"layers": {"move": {"spread": 80}}}, "0-50"),
    ({"layers": {"move": {"locked": "yes"}}}, "true or false"),
])
def test_bad_layer_settings(bad, msg):
    with pytest.raises(ConfigError, match=msg):
        parse_config(bad)


# ------------------------------------------------------------------ together (v6)


def test_together_replays_the_v6_decisions(app):
    want = json.loads((DATA / "v6_autopilot_decisions.json").read_text(encoding="utf-8"))
    got = [{"t": round(d.time - 1000.0, 2), "trigger": d.trigger, "mood": d.mood, "look": d.look} for d in session(app)]
    t0 = got and want and (got[0]["t"] - want[0]["t"])
    assert [{**g, "t": round(g["t"] - t0, 2)} for g in got] == want


def test_together_lock_holds_one_layer(app):
    app.autopilot.set_on(True, app.t.t)
    pal = app.autopilot.st.pick.palette
    assert app.ride_action("autopilot_lock", {"layer": "palette"}) == "palette lock on"
    moves = set()
    for _ in range(20):
        d = app.autopilot.change(app.t.t, "timer")
        app.t.advance(1)
        assert d.look["palette"] == pal
        moves.add(d.look["move"])
    assert len(moves) > 1  # the others keep changing


def test_palette_lock_action_still_works(app):
    app.ride_action("ride_palette", {"palette": "fire"})
    app.ride_action("palette_lock", {})  # v3 action: the palette layer's lock
    app.autopilot.set_on(True, app.t.t)
    for _ in range(5):
        app.autopilot.next(app.t.t)
        assert app.autopilot.st.pick.palette == "fire"
    assert app.snapshot()["ride"]["palette_lock"]


# ------------------------------------------------------------------ staggered


def test_staggered_changes_one_layer_at_a_time(app):
    staggered(app)
    app.autopilot.set_on(True, app.t.t)
    decisions = [d for d in run(app, 400) if d.trigger == "timer"]
    assert len(decisions) > 10
    prev = None
    for d in decisions:
        assert len(d.layers) == 1 and d.layers[0] in ("move", "colour", "palette")
        if prev is not None:
            changed = {k for k in ("move", "colour", "palette") if d.look[k] != prev[k]} | (
                {"colour"} if d.look["drum"] != prev["drum"] else set())
            assert changed <= set(d.layers)  # nothing else moved
        prev = d.look
    assert {d.layers[0] for d in decisions} == {"move", "colour", "palette"}


def test_staggered_spread_keeps_layers_apart(app):
    staggered(app)
    app.autopilot.set_on(True, app.t.t)
    times = [d.time for d in run(app, 600) if d.trigger == "timer"]
    close = sum(1 for a, b in zip(times, times[1:]) if b - a < 1.0)
    assert len(times) > 20 and close / len(times) < 0.1  # almost never two layers within a second


def test_staggered_lock_and_quality_rules(app):
    staggered(app)
    ap = app.autopilot
    ap.set_on(True, app.t.t)
    ap.set_lock("move", True)
    move = ap.st.pick.move
    q = app.quality()
    pal = {k: v.get("resolved", []) for k, v in app.files.palettes.sets.items()}
    prev = None
    for d in run(app, 400):
        assert d.look["move"] == move and "move" not in d.layers
        p = Pick.from_dict(d.look)
        assert not q.combo_issues(p, d.mood)
        if prev is not None:
            assert q.contrast_ok(prev, p, pal)
        prev = p
    st = ap.status(app.t.t)["layers"]
    assert st["move"]["locked"] and st["move"]["next_s"] is None and st["colour"]["next_s"] is not None


def test_staggered_never_repeats_recent_looks(app):
    staggered(app)
    app.autopilot.set_on(True, app.t.t)
    keys = [Pick.from_dict(d.look).key() for d in run(app, 600)]
    n = app.autopilot.cfg["no_repeat"]
    assert all(k not in keys[max(0, i - n):i] for i, k in enumerate(keys))


def test_song_and_set_layers(app):
    staggered(app, palette={"on": "song"}, move={"on": "set"})
    ap = app.autopilot
    ap.set_on(True, app.t.t)
    pal, move = ap.st.pick.palette, ap.st.pick.move
    for d in run(app, 300):
        assert d.look["palette"] == pal and d.look["move"] == move  # neither has a clock
    assert ap.status(app.t.t)["layers"]["palette"]["on"] == "song"
    d = ap.change(app.t.t, "song_start")
    assert "move" not in d.layers or d.look["move"] == move  # a set layer doesn't change on a song
    ap.set_mood("high" if ap.st.mood != "high" else "low", app.t.t)
    assert ap.decisions[-1].trigger == "mood"


def test_palette_only_change_keeps_heads_moving(app):
    """A palette change swaps colours only: the move layer isn't restarted, so heads don't jump."""
    staggered(app)
    ap = app.autopilot
    ap.set_on(True, app.t.t)
    while not ap.st.pick.move:
        ap.change(app.t.t, "start")
    run(app, 3)
    d = ap.change(app.t.t, "timer", layers=("palette",))
    assert d.layers == ("palette",)
    head = "mh_a"
    fx = app.engine.rig.patch.fixtures[head]
    pan = next(c for c in fx.type.channels if c.role == "pan")
    before = []
    for _ in range(8):  # positions just before and after: a smooth path, no jump back to the start
        app.t.advance(0.025)
        app.engine.tick()
        before.append(app.engine.frames[fx.universe][fx.slot(pan)])
    steps = [abs(b - a) for a, b in zip(before, before[1:])]
    assert max(steps) <= 20


def test_darkness_layer_steps_on_its_own_clock(app):
    calls = []
    app.autopilot.darkness_step = lambda now, why: calls.append((now, why))
    staggered(app, darkness={"every_s": 5, "spread": 0})
    app.autopilot.set_on(True, app.t.t)
    calls.clear()
    run(app, 31)
    assert len(calls) >= 5 and all(w == "timer" for _, w in calls)
    app.autopilot.set_lock("darkness", True)
    calls.clear()
    run(app, 20)
    assert calls == []


def test_together_darkness_steps_with_each_look(app):
    calls = []
    app.autopilot.darkness_step = lambda now, why: calls.append(why)
    app.autopilot.set_on(True, app.t.t)
    app.autopilot.next(app.t.t)
    assert calls == ["start", "next"]


def test_midi_lock_action(app):
    from dmx_suite.midi.map import parse_map, validate

    def one(**p):
        return parse_map({"mappings": [{"input": "pedal_1", "action": "autopilot_lock", **p}]}).mappings[0]

    validate(one(layer="darkness"))
    with pytest.raises(ConfigError, match="needs layer"):
        validate(one(layer="haze"))
    assert app.ride_action("autopilot_lock", {"layer": "colour"}) == "colour lock on"
    assert app.ride_action("autopilot_lock", {"layer": "colour"}) == "colour lock off"
    with pytest.raises(ValueError):
        app.ride_action("autopilot_lock", {"layer": "haze"})


# ------------------------------------------------------------------ settings saved from the page / Claude


def test_merge_settings():
    from dmx_suite.autopilot import merge_settings

    cur = {"gap_s": 6, "layers": {"move": {"every_s": 30, "spread": 10}}, "moods": {"low": 70}}
    out = merge_settings(cur, {"layers": {"move": {"on": "song"}}, "between": {"count_in": 3}, "timing": "staggered"})
    assert out["layers"]["move"] == {"on": "song", "spread": 10}  # the schedule replaced, spread kept
    assert out["between"] == {"gap_s": 6, "count_in": 3} and "gap_s" not in out
    assert out["moods"] == {"low": 70} and out["timing"] == "staggered"
    with pytest.raises(ConfigError):
        merge_settings(cur, {"timing": "sometimes"})


def test_save_autopilot_from_the_page(app):
    r = app.save_autopilot({"timing": "staggered", "layers": {"palette": {"on": "set"}}})
    assert r["backup"] and app.autopilot.cfg["timing"] == "staggered"
    assert app.autopilot.cfg["layers"]["palette"]["on"] == "set"
    with pytest.raises(ValueError, match="together or staggered"):
        app.save_autopilot({"timing": "x"})
    with pytest.raises(ValueError, match="no autopilot settings"):
        app.save_autopilot({})


def test_settings_api_respects_gig_lock(app):
    from dmx_suite.store import LockedError

    app.set_gig_lock(True)
    try:
        with pytest.raises(LockedError):
            app.save_autopilot({"timing": "staggered"})
    finally:
        app.set_gig_lock(False)


def test_claude_structured_settings(tmp_path):
    import shutil

    import yaml
    from test_autopilot import SHOWS

    from dmx_suite.claude_tools import DmxTools
    from dmx_suite.store import StoreError

    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups"))
    t = DmxTools(shows=root)
    t.save_autopilot_settings("full", timing="staggered", layers={"palette": {"on": "song"}},
                              between={"gap_s": 6, "look": {"scene": "starter_warm"}})
    ap = yaml.safe_load((root / "rigs" / "full.yaml").read_text())["autopilot"]
    assert ap["timing"] == "staggered" and ap["layers"]["palette"] == {"on": "song"}
    assert ap["between"] == {"gap_s": 6, "look": {"scene": "starter_warm"}}
    t.save_autopilot_settings("full", "{no_repeat: 6}")
    assert yaml.safe_load((root / "rigs" / "full.yaml").read_text())["autopilot"]["timing"] == "staggered"  # kept
    with pytest.raises(StoreError, match="together or staggered"):
        t.save_autopilot_settings("full", timing="sometimes")
    with pytest.raises(StoreError, match="no autopilot settings"):
        t.save_autopilot_settings("full")
