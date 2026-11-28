# ruff: noqa: F811 - pytest fixtures imported from test_autopilot are used as arguments
"""v7 A6 between songs: settings on the Autopilot page (on/off, no-activity time, song start, count-in,
fades, ignore inputs, min song length) and a pre-built scene as the between-songs / walk look."""

import shutil

import pytest
import yaml
from test_autopilot import SHOWS, app, hits, run  # noqa: F401 - pytest fixture

from dmx_suite.fixtures import ConfigError
from dmx_suite.showfiles import load_show

from rulecheck import _haze, check_frame


def song(app, seconds, input_id="snare", roles=("snare", "activity")):
    return run(app, seconds, drums=lambda t: app.bus.add(input_id, list(roles), 0.8, t))


def settings(app, **between):
    app.autopilot.cfg["between"].update(between)


def test_gap_ends_a_song_after_the_minimum(app):
    settings(app, min_song_s=20, gap_s=4)
    ap = app.autopilot
    ap.set_on(True, app.t.t)
    song(app, 10)
    assert not [d for d in run(app, 8) if d.trigger == "song_end"]  # 10 s in: a gap doesn't end it
    song(app, 15)
    ended = [d for d in run(app, 6) if d.trigger == "song_end"]
    assert ended and ap.st.between


def test_off_never_goes_between(app):
    settings(app, on=False, min_song_s=0)
    app.autopilot.set_on(True, app.t.t)
    song(app, 5)
    assert not [d for d in run(app, 30) if d.trigger == "song_end"] and not app.autopilot.st.between
    assert app.autopilot.status(app.t.t)["between_on"] is False


def test_ignored_input_neither_keeps_nor_starts_a_song(app):
    settings(app, min_song_s=0, ignore=["fcb_pad"])
    ap = app.autopilot
    ap.set_on(True, app.t.t)
    song(app, 6)
    # the pad tapped while talking: not activity, so the song still ends
    ended = [d for d in song(app, 6, "fcb_pad") if d.trigger == "song_end"]
    assert ended and ap.st.between
    assert not [d for d in song(app, 3, "fcb_pad") if d.trigger == "song_start"] and ap.st.between
    assert [d for d in song(app, 1) if d.trigger == "song_start"]  # the kit starts it


def test_count_in_mode_ignores_a_single_hit(app):
    settings(app, min_song_s=0, start="count_in", count_in=4)
    ap = app.autopilot
    ap.set_on(True, app.t.t)
    song(app, 5)
    run(app, 6)
    assert ap.st.between
    app.bus.add("snare", ["snare", "activity"], 0.8, app.t.t + 0.1)
    assert not [d for d in run(app, 3) if d.trigger == "song_start"] and ap.st.between
    hits(app.bus, app.t.t + 0.1, 4, 0.5, roles=("count_in", "activity"))
    started = [d for d in run(app, 2.5) if d.trigger == "song_start"]
    assert started and "count-in" in started[0].why and not ap.st.between


def test_fades_in_and_out(app):
    fades = []
    play = app.autopilot.play
    app.autopilot.play = lambda pick, fade: (fades.append(fade), play(pick, fade))
    settings(app, min_song_s=0, fade_in=7, fade_out=0.3)
    ap = app.autopilot
    ap.set_on(True, app.t.t)
    song(app, 5)
    fades.clear()
    run(app, 6)
    assert fades == [7]  # into the between-songs look
    song(app, 1)
    assert fades[-1] == 0.3  # out into the next song


def test_default_fades(app):
    fades = []
    play = app.autopilot.play
    app.autopilot.play = lambda pick, fade: (fades.append(fade), play(pick, fade))
    settings(app, min_song_s=0)
    ap = app.autopilot
    ap.set_on(True, app.t.t)
    song(app, 5)
    fades.clear()
    run(app, 6)
    assert fades == [ap.cfg["fade"]["low"]]
    song(app, 1)
    assert fades[-1] == ap.cfg["fade"][ap.st.mood]  # the song's mood fade


def test_status_shows_time_since_last_hit(app):
    settings(app, min_song_s=0)
    ap = app.autopilot
    ap.set_on(True, app.t.t)
    song(app, 3)
    run(app, 7)
    st = ap.status(app.t.t)
    assert st["between"] and 6.5 <= st["since_hit_s"] <= 7.5


# ------------------------------------------------------------------ a scene between songs


def test_scene_plays_as_authored(app):
    settings(app, min_song_s=0, look={"scene": "blue_chase"})
    ap = app.autopilot
    app.darkness.set(1.0, "slider")  # full darkness: an Autopilot look would be black
    ap.set_on(True, app.t.t)
    song(app, 5)
    ended = [d for d in run(app, 6) if d.trigger == "song_end"]
    assert ended and ended[0].look == {"scene": "blue_chase"}
    assert app.ctl.mode == "ride" and ap.st.on  # the autopilot stays on
    run(app, ap.cfg["fade"]["low"] + 0.5)  # past the fade into it
    src = app.engine.source
    assert getattr(src, "new", src).darkness is None  # played as authored: no Darkness
    lit = [f.id for f in app.engine.rig.fixtures if any(app.engine.frames[f.universe][f.slot(c)]
                                                        for c in f.type.channels if c.role in ("red", "green", "blue"))]
    assert lit  # not blacked by darkness
    started = [d for d in song(app, 1) if d.trigger == "song_start"]
    assert started and "move" in started[0].look  # the autopilot takes over again


def test_walk_on_scene(app):
    app.autopilot.cfg["walk_on"] = {"scene": "red_movers"}
    app.autopilot.set_on(True, app.t.t)
    app.ride_action("walk_on", {})
    assert app.autopilot.decisions[-1].look == {"scene": "red_movers"}


def test_missing_scene_falls_back_to_the_default_look(app):
    settings(app, min_song_s=0, look={"scene": "gone"})
    ap = app.autopilot
    ap.set_on(True, app.t.t)
    song(app, 5)
    ended = [d for d in run(app, 6) if d.trigger == "song_end"]
    assert ended and ended[0].look["palette"] == "white" and "refused" in ended[0].why


def test_unknown_scene_refused_at_load(tmp_path):
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups"))
    p = root / "rigs" / "full.yaml"
    rig = yaml.safe_load(p.read_text())
    rig["autopilot"] = {"between": {"look": {"scene": "nope"}}}
    p.write_text(yaml.safe_dump(rig))
    with pytest.raises(ConfigError, match="unknown scene 'nope'"):
        load_show(root)


@pytest.mark.parametrize("profile", ["0.05_band", "generic"])
def test_rules_and_haze_between_songs(tmp_path, profile):
    """Both profiles: a scene and a generated look between songs, haze running, every frame checked."""
    from dmx_suite.app import App
    from dmx_suite.drums import DrumBus
    from dmx_suite.output import LogDriver

    from conftest import Clock

    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups"))
    p = root / "rigs" / "full.yaml"
    rig = yaml.safe_load(p.read_text())
    rig["profile"] = profile
    p.write_text(yaml.safe_dump(rig))
    clock = Clock()
    a = App(load_show(root), [LogDriver()], log_dir=tmp_path / "logs", clock=clock)
    a.bus = DrumBus()
    a.autopilot.bus = a.autopilot.energy.bus = a.bus
    a.t = clock
    a.engine.tick()
    a.engine.haze.set_mode("manual", clock.t)  # haze on: nothing between songs may change it (rule 5)
    a.engine.tick()
    haze0 = _haze(a.engine)
    for look in ({"scene": "blue_chase"}, {"colour": "static", "palette": "white"}):
        a.autopilot.cfg["between"].update(look=look, min_song_s=0)
        a.autopilot.set_on(True, clock.t)
        for k in range(120):  # a song, the gap, the next song
            clock.advance(0.1)
            if k < 40 or k > 100:
                a.bus.add("snare", ["snare", "activity"], 0.8, clock.t)
            a.autopilot.tick(clock.t)
            a.engine.tick()
            check_frame(a.engine, haze0, f"{profile} {look} k={k}")
        assert any(d.trigger == "song_end" for d in a.autopilot.decisions)
        a.autopilot.set_on(False, clock.t)
