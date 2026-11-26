import pytest

from dmx_suite.haze import Haze, HazeMode
from dmx_suite.rig import HazeConfig


def cfg(**kw):
    base = dict(level=0.5, boost_level=1.0, pulse_on_s=5, pulse_every_s=60, boost_s=0,
                max_on_s=60, rest_s=30, boost_cooldown_s=10, auto_off_s=0)
    base.update(kw)
    return HazeConfig(**base)


def test_off_by_default():
    h = Haze(cfg(), 0)
    assert h.tick(0) == 0 and h.mode == HazeMode.OFF


def test_default_mode_from_rig():
    assert Haze(cfg(default_mode="manual"), 0).mode == HazeMode.MANUAL


def test_manual_latch():
    h = Haze(cfg(), 0)
    h.toggle_manual(0)
    assert h.tick(1) == 0.5
    h.toggle_manual(2)
    assert h.tick(3) == 0


def test_pulse_timing():
    h = Haze(cfg(), 0)
    h.set_mode("pulse", 100)
    assert h.tick(100) == 0.5
    assert h.tick(104.9) == 0.5
    assert h.tick(105.1) == 0
    assert h.status(105.1).next_pulse_in_s == pytest.approx(54.9)
    assert h.tick(160.5) == 0.5


def test_boost_while_held_then_back_to_mode():
    h = Haze(cfg(), 0)
    h.set_mode("pulse", 0)
    h.tick(10)
    assert h.boost_press(10)
    assert h.tick(11) == 1.0
    h.boost_release(12)
    assert h.tick(12) == 0  # back to pulse (off phase)


def test_timed_boost():
    h = Haze(cfg(boost_s=3), 0)
    h.boost_press(0)
    h.boost_release(0.1)  # release doesn't cut a timed boost
    assert h.tick(2.9) == 1.0
    assert h.tick(3.1) == 0


def test_boost_works_in_off_mode_and_cooldown():
    h = Haze(cfg(), 0)
    assert h.boost_press(0)
    h.boost_release(2)
    assert not h.boost_press(5)  # 10 s cooldown
    assert h.status(5).boost_cooldown_s == 7
    assert h.boost_press(12.1)


def test_max_on_time_forces_rest():
    h = Haze(cfg(max_on_s=60, rest_s=30), 0)
    h.toggle_manual(0)
    for t in range(0, 60):
        assert h.tick(t) == 0.5
    assert h.tick(60) == 0  # hit the limit
    assert h.status(60).resting
    assert h.tick(89) == 0
    assert h.tick(90.1) == 0.5  # rest over


def test_auto_off_timer():
    h = Haze(cfg(auto_off_s=600), 0)
    h.toggle_manual(0)
    assert h.status(100).auto_off_in_s == 500
    h.tick(599)
    assert h.tick(600) == 0 and h.mode == HazeMode.OFF


def test_disabled_by_rig_blocks_everything():
    h = Haze(cfg(enabled=False, default_mode="manual"), 0)
    assert h.mode == HazeMode.OFF
    h.toggle_manual(0)
    assert not h.boost_press(0)
    assert h.tick(1) == 0
    assert not h.status(1).enabled


def test_stop_cuts_boost_too():
    h = Haze(cfg(), 0)
    h.toggle_manual(0)
    h.boost_press(0)
    h.stop(1)
    assert h.tick(1) == 0
