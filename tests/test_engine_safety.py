"""The show must go on: loop timing, render faults, value checks, and the last-good fallback."""

import logging
import shutil
import time
from pathlib import Path

import pytest

from conftest import LOOK, PATCH, RIG, Clock, View
from dmx_suite.cli import build_parser, resolve_shows, start_session
from dmx_suite.engine import FRAME_HZ, Engine
from dmx_suite.fixtures import ConfigError, parse_patch
from dmx_suite.look import Look, LookError, parse_look
from dmx_suite.output import LogDriver
from dmx_suite.rig import parse_rig
from dmx_suite.showfiles import check_all, load_show
from dmx_suite.store import ShowStore

SHOWS = Path(__file__).resolve().parents[1] / "shows"
PERIOD = 1 / FRAME_HZ


def build(clock=None, drivers=None):
    patch = parse_patch(PATCH)
    clock = clock or Clock()
    e = Engine(parse_rig(RIG, patch), drivers or [LogDriver()], parse_look(LOOK, patch), clock=clock)
    e.tick()
    return e, View(e), clock


# ------------------------------------------------------------------ loop timing


def test_early_wakes_never_push_the_grid_ahead():
    """A pedal sweep (a fader change every 5 ms for a second) used to push frames seconds ahead."""
    e, _, clock = build()
    next_tick = clock()
    sent0 = e.frames_sent
    for _ in range(200):
        e.set_grand(0.3 + 0.001 * (_ % 50))  # wakes the loop early, as a CC would
        next_tick, wait = e.loop_step(next_tick)
        assert next_tick - clock() <= PERIOD + 1e-9  # never more than a frame ahead
        assert wait <= PERIOD + 1e-9
        clock.advance(0.005)
    assert 38 <= e.frames_sent - sent0 <= 42  # about 40 frames in the second, not 200


def test_ticks_stay_on_the_40_hz_grid_after_a_late_tick():
    e, _, clock = build()
    next_tick = clock()
    clock.advance(0.1)  # the laptop stalled for 100 ms
    next_tick, _ = e.loop_step(next_tick)
    assert next_tick > clock() and abs((next_tick - 1000.0) / PERIOD - round((next_tick - 1000.0) / PERIOD)) < 1e-6


def test_control_change_sends_once():
    e, _, clock = build()
    next_tick, _ = e.loop_step(clock())  # a grid tick
    sent = e.frames_sent
    e.set_master(False)  # sends straight away...
    assert e.frames_sent == sent + 1
    clock.advance(0.001)
    e.loop_step(next_tick)  # ...and the wake that follows only re-plans, it doesn't send again
    assert e.frames_sent == sent + 1


def test_flash_end_is_cut_exactly():
    e, view, clock = build()
    clock.advance(2)
    e.set_master(False)
    e.flash(["bar_1"], 127, "white", length_ms=10)
    next_tick, wait = e.loop_step(clock())
    assert wait <= 0.010 + 1e-9  # wakes for the flash end, before the next frame
    clock.advance(0.010)
    e.loop_step(next_tick)
    assert view.emitters("bar_1") == [0] * 6


def test_default_clock_is_high_resolution():
    assert Engine.__init__.__defaults__[-1] is time.perf_counter


# ------------------------------------------------------------------ render faults


class Boom:
    def __init__(self, after: int = 0) -> None:
        self.calls, self.after = 0, after

    def __call__(self, now):
        self.calls += 1
        if self.calls > self.after:
            raise ValueError("bad value in a show file")
        return Look()


def test_render_error_falls_back_to_static_look():
    e, view, clock = build()
    e.set_source(Boom())  # never raises out of the control call
    assert e.fault and "bad value" in e.fault and e.faults == 1
    assert e.source is None and e.look is e.static_look
    assert view("mh_a", "red") == 255  # static look is on the rig
    sent = e.frames_sent
    e.tick()
    assert e.frames_sent == sent + 1


def test_static_look_failing_too_holds_the_last_good_frame(monkeypatch):
    out = LogDriver()
    e, _, clock = build(drivers=[out])
    good = bytes(e.frames[0])

    def broken(*a, **k):
        raise RuntimeError("rule layer bug")

    monkeypatch.setattr(e.rules, "render", broken)
    sent = out.frames
    e.tick()
    assert out.frames == sent + 1 and bytes(out.last[0]) == good  # still sending, same frame
    assert "holding the last good frame" in e.fault


def test_frame_listener_error_doesnt_stop_output():
    e, _, _ = build()
    e.on_frame.append(lambda frames: 1 / 0)
    sent = e.frames_sent
    for _ in range(3):
        e.tick()
    assert e.frames_sent == sent + 3 and e.fault is None


def test_driver_errors_logged_once_a_minute(caplog):
    class Broken(LogDriver):
        name = "broken"

        def send(self, universe, frame):
            raise OSError("unplugged")

    e, _, clock = build(drivers=[Broken()])
    with caplog.at_level(logging.ERROR, logger="dmx_suite.engine"):
        for _ in range(100):
            clock.advance(0.025)
            e.tick()
    assert e.driver_errors >= 100
    assert sum("broken failed" in r.getMessage() for r in caplog.records) == 1


def test_engine_thread_keeps_running_through_faults():
    e, _, _ = build(clock=time.perf_counter)
    e.start()
    try:
        e.set_source(Boom(after=3))
        n = e.frames_sent
        time.sleep(0.25)
        assert e.frames_sent > n + 5 and e._thread.is_alive()
    finally:
        e.stop()


def test_status_bar_shows_the_fault():
    from dmx_suite.app import App

    sf = load_show(SHOWS, "full")
    app = App(sf, [LogDriver()])
    app.engine.set_source(Boom())
    eng = next(d for d in app.devices() if d["kind"] == "engine")
    assert eng["state"] == "bad" and "static look" in eng["detail"]
    assert app.snapshot()["fault"]["count"] == 1


# ------------------------------------------------------------------ values checked at load


@pytest.mark.parametrize("key, value", [("gobo", 300), ("gobo", -1), ("colour_wheel", 1.5), ("strobe", True),
                                        ("gobo", "dots"), ("colour_wheel", None)])
def test_raw_dmx_values_checked_in_looks(key, value):
    with pytest.raises(LookError, match="DMX value"):
        parse_look({"fixtures": {"mh_a": {"colour": [1, 0, 0], key: value}}}, parse_patch(PATCH))


def test_good_raw_dmx_values_load():
    lk = parse_look({"fixtures": {"mh_a": {"colour": [1, 0, 0], "gobo": 255, "colour_wheel": 0, "strobe": 10.0}}},
                    parse_patch(PATCH))
    assert (lk.fixtures["mh_a"].gobo, lk.fixtures["mh_a"].strobe) == (255, 10)


@pytest.mark.parametrize("change, msg", [
    ({"haze": {"pulse_on_s": "fast"}}, "pulse_on_s must be a number"),
    ({"haze": {"max_on_s": 0}}, "max_on_s must be 1 s"),
    ({"haze": {"rest_s": -5}}, "rest_s must be 0 s"),
    ({"haze": "on"}, "haze: needs settings"),
    ({"fade_s": -1}, "fade_s must be 0 s"),
    ({"grand_master": "loud"}, "grand_master must be a number"),
    ({"kick_colour": {"pink": 100}}, "kick_colour"),
    ({"head_limits": {"mh_a": 5}}, "head_limits mh_a"),
    ({"head_limits": {"mh_a": {"pan": [10]}}}, r"\[min, max\]"),
])
def test_rig_numbers_checked(change, msg):
    with pytest.raises(ConfigError, match=msg):
        parse_rig({**RIG, **change}, parse_patch(PATCH))


@pytest.fixture
def shows(tmp_path):
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json", ".giglock"))
    return root


@pytest.mark.parametrize("path, text, where", [
    ("scenes/opera.yaml", "layers: [unclosed\n", "opera.yaml: not valid YAML"),
    ("scenes/opera.yaml", "version: 2\nlayers: 5\n", "scenes"),
    ("looks/default.yaml", "version: 2\nfixtures: [bars]\n", "fixtures:"),
    ("rigs/full.yaml", "- a list\n", "full.yaml: expected a mapping"),
    ("fixtures.yaml", "version: 2\ntypes: 7\n", "fixtures.yaml"),
])
def test_broken_files_are_named_not_crashes(shows, path, text, where):
    (shows / path).write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match=where.replace("[", r"\[")):
        load_show(shows, "full")
    problems = check_all(shows)  # never crashes either
    assert any(path.split("/")[-1] in p for p in problems)


# ------------------------------------------------------------------ last good show files at start-up


def _args(root: Path):
    return resolve_shows(build_parser().parse_args(["--shows", str(root), "run", "--sim", "--no-web", "--headless"]))


def test_broken_show_folder_runs_last_good_version(shows):
    store = ShowStore(shows)
    store.put("scene", "opera", {**store.read("scene", "opera"), "name": "Opera 2"})  # a normal edit: backup made
    good = (shows / "scenes" / "opera.yaml").read_text(encoding="utf-8")
    (shows / "scenes" / "opera.yaml").write_text("layers: [unclosed\n", encoding="utf-8")  # broken by hand
    lines = []
    session = start_session(_args(shows), out=lines.append)
    try:
        app = session.app
        assert app.show_problem and "not valid YAML" in app.show_problem["problem"]
        assert app.files.root == shows  # edits still go to the real folder
        assert app.files.scenes["opera"].name == "Opera"  # the version from before the last change
        assert any(d["kind"] == "files" and d["state"] == "bad" for d in app.devices())
        assert any("SHOW FILE PROBLEM" in ln for ln in lines)
        assert (shows / "scenes" / "opera.yaml").read_text(encoding="utf-8") == "layers: [unclosed\n"  # untouched
        (shows / "scenes" / "opera.yaml").write_text(good, encoding="utf-8")  # fixed
        assert any("now running them" in n for n in app.reload())
        assert app.show_problem is None and app.files.scenes["opera"].name == "Opera 2"
    finally:
        session.stop()


def test_broken_folder_without_backups_still_reports(shows):
    (shows / "scenes" / "opera.yaml").write_text("layers: [unclosed\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid YAML"):
        start_session(_args(shows), out=lambda *a: None)
