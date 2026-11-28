"""v6 Part A: Autopilot Darkness and per-effect `lit`. The brief's acceptance tests, plus: black is colour
off (never dimmer), hand-made scenes and Override untouched, drum flash keeps black slots black, soft edges,
easing, YAML back-compat, the CC role, API and MCP."""

import shutil
from pathlib import Path

import pytest
import yaml

from dmx_suite.effects.base import BLACK, gapped, static_on, window, with_black
from dmx_suite.look import LookError
from dmx_suite.output import LogDriver
from dmx_suite.scenes import ScenePlayer, parse_scene
from dmx_suite.showfiles import load_show

SHOWS = Path(__file__).resolve().parents[1] / "shows"
BARS = ["bar_1", "bar_2", "bar_3", "bar_4"]


@pytest.fixture(scope="module")
def files():
    return load_show(SHOWS)


def lit_px(look, fids=BARS):
    """(lit, total) pixels over these lights."""
    on = n = 0
    for f in fids:
        fl = look.fixtures.get(f)
        for px in (fl.pixels if fl and fl.pixels else [fl.colour if fl else {}]):
            n += 1
            on += any(v > 0.001 for v in px.values())
    return on, n


def play(files, scene, darkness=None, edge=0.0, t=0.0):
    sc = parse_scene(scene, files.patch, files.palettes, "t")
    pl = ScenePlayer(sc, files.rig, 0.0, darkness=None if darkness is None else (lambda now: darkness), edge=edge)
    return pl(t)


SWEEP = {"layers": [{"fixtures": ["bars"], "effect": "linear_wave", "colour": [1, 0, 0], "background": [0, 0, 1],
                     "waveform": "sine", "period_s": 2}]}


# ---------------------------------------------------------------- helpers


def test_window_and_with_black_and_gaps():
    assert window(0.3, 1.0) == 1.0 and window(0.0, 0.0) == 0.0
    assert window(0.2, 0.5) == 1.0 and window(0.3, 0.5) == 0.0  # band 0.5 wide round the centre
    assert 0 < window(0.25, 0.5, edge=1.0) < 1  # soft edge
    assert with_black(["r", "b"], 0.5) == ["r", BLACK, "b", BLACK]
    seq = with_black(["r", "g", "b", "w"], 0.75)
    assert seq.count(BLACK) == 1 and len(seq) == 5
    seq = with_black(["r", "g", "b"], 0.6)  # >= 50 %: never two blacks in a row
    assert all(not (a is BLACK and b is BLACK) for a, b in zip(seq, seq[1:] + seq[:1]))
    assert gapped(0.1, 2, 0.5) == (0, pytest.approx(0.4)) and gapped(0.3, 2, 0.5) is None
    assert [static_on(i, 0.5) for i in range(4)] == [False, True, False, True]
    assert [static_on(i, 1 / 3) for i in range(6)].count(True) == 2


# ---------------------------------------------------------------- acceptance (brief)


def test_linear_sweep_on_the_four_bars(files):
    on, n = lit_px(play(files, SWEEP, 0.0))
    assert on == n == 32  # darkness 0 = continuous colour
    half = [lit_px(play(files, SWEEP, 0.5, t=t))[0] for t in (0, 0.3, 0.7, 1.1)]
    assert all(14 <= x <= 18 for x in half), half  # half of each sweep black
    narrow = [lit_px(play(files, SWEEP, 0.9, t=t))[0] for t in (0, 0.3, 0.7, 1.1)]
    assert all(1 <= x <= 5 for x in narrow), narrow  # a narrow travelling band
    # it travels: the lit pixels move
    def where(t):
        look = play(files, SWEEP, 0.9, t=t)
        return [any(p.values()) for f in BARS for p in look.fixtures[f].pixels]

    assert where(0.0) != where(0.5)


def test_palette_cycle_at_50_alternates_colour_and_black(files):
    sc = {"layers": [{"fixtures": ["wash_l"], "effect": "colour_chase", "colours": [[1, 0, 0], [0, 0, 1]], "period_s": 4}]}
    seq = [play(files, sc, 0.5, t=t).fixtures["wash_l"].colour for t in (0.5, 1.5, 2.5, 3.5)]
    assert seq[0]["red"] == 1 and not any(seq[1].values()) and seq[2]["blue"] == 1 and not any(seq[3].values())


def test_kick_light_unchanged_at_any_darkness(files):
    sc = {"layers": [{"fixtures": ["all"], "colour": [0, 1, 0]}]}
    for d in (0.0, 0.5, 1.0):
        look = play(files, sc, d)
        assert look.fixtures["kick"].colour == {"red": 0, "green": 1, "blue": 0} or look.fixtures["kick"].colour.get("green") == 1
    assert lit_px(play(files, sc, 1.0), BARS)[0] == 0  # everything else black at 100 %


def test_dimmers_unchanged_only_colour_changes(tmp_path):
    from dmx_suite.app import App

    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json"))
    out = LogDriver()
    app = App(load_show(root), [out])
    try:
        app.engine.set_master(True)
        app.ride_play({"colour": "static", "palette": "warm"})
        dimmers = [(f, c) for f in app.engine.rig.fixtures for c in f.type.channels if c.role in ("dimmer", "dimmer_fine")]
        frames = []
        t = [app.engine.clock()]
        app.engine.clock = app.darkness.clock = lambda: t[0]
        for d in (0.0, 0.5, 1.0):
            app.darkness.set(d, "slider")
            t[0] += 5.0  # past the easing
            app.engine.output()
            frames.append(bytes(app.engine.frames[0]))
        for f, c in dimmers:
            assert len({fr[f.slot(c)] for fr in frames}) == 1, f"{f.id} {c.role} moved with darkness"
        bar = app.engine.rig.patch.fixtures["bar_1"]
        emit = [bar.slot(c) for c in bar.type.channels]
        assert sum(frames[0][s] for s in emit) > sum(frames[2][s] for s in emit) == 0
    finally:
        app.engine.stop()


def test_pedal_sweep_is_smooth(tmp_path):
    from dmx_suite.darkness import Darkness

    t = [100.0]
    d = Darkness(lambda: t[0], lambda: "mid")
    d.fade = 0.0
    prev, worst = d(t[0]), 0.0
    for step in range(128):  # the pedal heel to toe in CC steps, a step every 20 ms; sampled at 40 Hz
        d.set(step / 127, "cc")
        for _ in range(2):
            t[0] += 0.01
            v = d(t[0])
            worst = max(worst, abs(v - prev))
            prev = v
    assert worst < 0.03  # no step jumps
    t[0] += 1
    assert d(t[0]) == pytest.approx(1.0)


def test_set_change_loads_each_sets_darkness():
    from dmx_suite.darkness import Darkness

    t, mood = [0.0], ["mid"]
    d = Darkness(lambda: t[0], lambda: mood[0])
    d.configure({"darkness": 10, "set_darkness": {"low": 70, "high": 0}})
    t[0] += 5
    assert d(t[0]) == pytest.approx(0.1) and d.source == "default"
    d.set(0.4, "cc")
    t[0] += 5
    assert d(t[0]) == pytest.approx(0.4)  # a live move holds...
    mood[0] = "low"
    t[0] += 0.01
    d(t[0])
    t[0] += 5
    assert d(t[0]) == pytest.approx(0.7) and d.source == "set"  # ...until the next set change
    mood[0] = "high"
    d(t[0])
    t[0] += 5
    assert d(t[0]) == 0.0


# ---------------------------------------------------------------- rules


def test_hand_made_scenes_play_as_authored(tmp_path):
    from dmx_suite.app import App

    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json"))
    app = App(load_show(root), [LogDriver()])
    try:
        app.darkness.set(1.0, "slider")
        name = next(iter(app.files.scenes))
        app.ctl.select_scene(name)
        assert app.engine.source.darkness is None  # only Autopilot looks get darkness
        app.ride_play({"colour": "static", "palette": "warm"})
        src = app.engine.source
        src = getattr(src, "new", src)
        assert src.darkness is app.darkness
    finally:
        app.engine.stop()


def test_lit_and_darkness_multiply(files):
    sc = {"layers": [{"fixtures": ["bars"], "effect": "palette", "colours": [[1, 1, 1]], "lit": 60}]}
    assert abs(lit_px(play(files, sc))[0] - 32 * 0.6) <= 1
    assert abs(lit_px(play(files, sc, 0.5))[0] - 32 * 0.3) <= 1  # 60 % x (1 - 50 %) = 30 %


def test_static_colour_pattern_moves_with_shift(files):
    a = {"layers": [{"fixtures": ["bars"], "colour": [1, 0, 0], "lit": 50}]}
    b = {"layers": [{"fixtures": ["bars"], "colour": [1, 0, 0], "lit": 50, "shift": 0.03125}]}  # one pixel of 32
    pa = [any(p.values()) for p in play(files, a).fixtures["bar_1"].pixels]
    pb = [any(p.values()) for p in play(files, b).fixtures["bar_1"].pixels]
    assert pa == [False, True] * 4 and pb == [True, False] * 4


def test_movers_keep_moving_dark(files):
    sc = {"layers": [{"fixtures": ["mh_a"], "effect": "circle", "centre": {"pan": 0.5, "tilt": 0.5}, "size": 0.3,
                      "period_s": 2},
                     {"fixtures": ["mh_a"], "colour": [1, 1, 1]}]}
    a, b = play(files, sc, 1.0, t=0.0).fixtures["mh_a"], play(files, sc, 1.0, t=0.5).fixtures["mh_a"]
    assert not any(a.colour.values()) and (a.pan, a.tilt) != (b.pan, b.tilt)


def test_gradient_gaps_and_rainbow_gaps(files):
    g = {"layers": [{"fixtures": ["bars"], "effect": "gradient", "colours": [[1, 0, 0], [0, 0, 1]], "mapping": "order"}]}
    r = {"layers": [{"fixtures": ["bars"], "effect": "rainbow", "spread": 1}]}
    for sc in (g, r):
        assert lit_px(play(files, sc))[0] == 32
        assert abs(lit_px(play(files, sc, 0.5))[0] - 16) <= 3


def test_generic_pattern_for_effects_that_dont_shape_their_own(files):
    sc = {"layers": [{"fixtures": ["bars"], "effect": "pulse", "colour": [1, 1, 1], "period_s": 2}]}
    assert abs(lit_px(play(files, sc, 0.5, t=0.9))[0] - 16) <= 1


def test_drum_flash_keeps_black_slots_black(tmp_path):
    from dmx_suite.app import App

    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json"))
    app = App(load_show(root), [LogDriver()])
    try:
        e = app.engine
        app.ride_play({"colour": "static", "palette": "warm"})
        app.darkness.set(0.5, "slider")
        base = e.clock()
        e.clock = lambda: base + 5
        e.set_master(False)
        e.flash(["bar_1"], 127, {"red": 1.0, "green": 1.0, "blue": 1.0})
        e.output()
        bar = e.rig.patch.fixtures["bar_1"]
        reds = [e.frames[0][bar.slot(c)] for c in bar.type.channels if c.role == "red"]
        assert 0 < sum(1 for v in reds if v) < 8, reds  # only the lit pixels flash
    finally:
        app.engine.stop()


def test_override_ignores_darkness(files):
    from dmx_suite.busk import Override, apply

    look = play(files, {"layers": [{"fixtures": ["bars"], "colour": [1, 0, 0]}]}, 1.0)
    assert lit_px(look)[0] == 0
    o = Override("x", "colour", ["bar_1"], colour={"red": 0, "green": 1, "blue": 0})
    out = apply(look, [o], 0.0)
    assert out.fixtures["bar_1"].colour["green"] == 1 and not out.fixtures["bar_1"].unlit


def test_soft_edges_follow_fade(files):
    hard = [p.get("red", 0) for f in BARS for p in play(files, SWEEP, 0.5, edge=0.0, t=0.4).fixtures[f].pixels]
    soft = [p.get("red", 0) for f in BARS for p in play(files, SWEEP, 0.5, edge=1.0, t=0.4).fixtures[f].pixels]
    assert sum(1 for v in soft if 0 < v < 0.5) > sum(1 for v in hard if 0 < v < 0.5)


# ---------------------------------------------------------------- YAML


def test_yaml_lit_and_back_compat(files):
    sc = parse_scene({"lit": 40, "layers": [{"fixtures": ["bars"], "colour": [1, 0, 0]},
                                            {"fixtures": ["wash_l"], "colour": [1, 0, 0], "lit": 80}]},
                     files.patch, files.palettes, "x")
    assert [ly.lit for ly in sc.layers] == [0.4, 0.8]
    plain = parse_scene({"layers": [{"fixtures": ["bars"], "colour": [1, 0, 0]}]}, files.patch, files.palettes)
    assert plain.layers[0].lit == 1.0
    with pytest.raises(LookError, match="lit"):
        parse_scene({"layers": [{"fixtures": ["bars"], "colour": [1, 0, 0], "lit": 150}]}, files.patch, files.palettes)


def test_autopilot_block_darkness_keys():
    from dmx_suite.autopilot import parse_config
    from dmx_suite.fixtures import ConfigError

    c = parse_config({"darkness": 20, "set_darkness": {"low": 60, "high": 0}})
    assert c["darkness"] == 20 and c["set_darkness"]["low"] == 60
    assert parse_config(None)["darkness"] == 0  # back-compat
    for bad in ({"darkness": 120}, {"set_darkness": {"verse": 10}}, {"set_darkness": {"low": -1}}):
        with pytest.raises(ConfigError):
            parse_config(bad)


def test_cc_role_with_range_and_curve():
    from dmx_suite.fixtures import ConfigError
    from dmx_suite.midi.named import parse_inputs

    inp = parse_inputs({"devices": {"fcb1010": {"channel": 1, "inputs": {
        "pedal_a": {"type": "control_change", "number": 27, "roles": ["darkness"], "range": [10, 90]}}}}})
    i = inp.inputs["pedal_a"]
    assert i.level(0) == pytest.approx(0.1) and i.level(127) == pytest.approx(0.9)
    assert i.to_dict()["range"] == [10.0, 90.0]
    with pytest.raises(ConfigError, match="needs a CC"):
        parse_inputs({"devices": {"x": {"inputs": {"pad": {"type": "note", "notes": [40], "roles": ["darkness"]}}}}})


# ---------------------------------------------------------------- app, MIDI, API, MCP


@pytest.fixture
def running(tmp_path):
    from test_web import CLAUDE, TOKEN

    from dmx_suite.app import App
    from dmx_suite.web.server import WebServer

    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json"))
    app = App(load_show(root), [LogDriver()], state_path=root / ".state.json")
    web = WebServer(app, "127.0.0.1", 0, token=TOKEN, claude_token=CLAUDE)
    web.start()
    yield app, f"http://127.0.0.1:{web.port}", root, CLAUDE
    web.stop()
    app.engine.stop()


def test_midi_cc_rides_darkness(running):
    import mido

    from dmx_suite.midi.named import parse_inputs

    app, *_ = running
    app.router.inputs = parse_inputs({"devices": {"fcb1010": {"channel": 1, "inputs": {
        "pedal_a": {"type": "control_change", "number": 27, "roles": ["darkness"]}}}}})
    app.router.handle_mido(mido.Message("control_change", channel=0, control=27, value=127), "FCB1010")
    st = app.darkness.status()
    assert st["darkness"] == 100 and st["source"] == "cc" and st["cc"]["input"] == "pedal_a"
    app.router.handle_mido(mido.Message("control_change", channel=0, control=27, value=0), "FCB1010")
    assert app.darkness.status()["darkness"] == 0


def test_midi_map_action(running):
    from dmx_suite.midi.map import CONTINUOUS

    app, *_ = running
    assert "darkness" in CONTINUOUS
    assert app.ride_action("darkness", {}, 0.25) == "darkness 25%"


def test_api_and_mcp(running):
    from test_web import call

    from dmx_suite.claude_tools import DmxTools

    app, url, root, claude = running
    status, body = call(f"{url}/api/darkness", "POST", {"value": 40})
    assert status == 200 and body["darkness"] == 40 and body["source"] == "slider"
    t = DmxTools(shows=root, url=url, token=claude)
    assert t.set_autopilot(55).startswith("darkness 55")
    assert app.darkness.status()["source"] == "claude"
    assert t.set_set_darkness("low", 70).startswith("saved")
    assert yaml.safe_load((root / "rigs" / "full.yaml").read_text())["autopilot"]["set_darkness"]["low"] == 70
    st = yaml.safe_load(t.autopilot_status(1))["darkness"]
    assert st["set_darkness"]["low"] == 70 and st["darkness"] == 55
    msg = t.preview_look("{colour: static, palette: warm}", 2, darkness=80)
    assert "darkness 80" in msg and app.darkness.status()["darkness"] == 55  # live value untouched
    app.set_gig_lock(True)
    assert call(f"{url}/api/darkness", "POST", {"value": 10})[0] == 200  # a live control
    app.set_gig_lock(False)


def test_mcp_registers_darkness_tools():
    pytest.importorskip("mcp")
    import asyncio

    from dmx_suite.claude_tools import DmxTools
    from dmx_suite.mcp_server import build_server

    names = {x.name for x in asyncio.run(build_server(DmxTools(shows=SHOWS)).list_tools())}
    assert {"set_autopilot", "set_set_darkness"} <= names
