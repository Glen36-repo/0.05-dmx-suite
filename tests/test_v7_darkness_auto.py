# ruff: noqa: F811 - pytest fixtures imported from other tests are used as arguments
"""v7 A3 Darkness Auto: moves between Min and Max on the Darkness layer, time at Max as a share of time,
a minimum hold at each marker, hands on = back to Manual, per-set modes, Claude's set_darkness."""

import pytest
import yaml
from test_autopilot import app, run  # noqa: F401 - pytest fixture
from test_v6_darkness import running  # noqa: F401 - pytest fixture

from dmx_suite.autopilot import parse_config
from dmx_suite.darkness import Darkness
from dmx_suite.fixtures import ConfigError


class T:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def auto(mn=10, mx=70, at=30, hold=None, interval=10.0, mood="mid"):
    clock = T()
    d = Darkness(clock, lambda: mood, interval=lambda: interval)
    d.configure({"darkness_mode": "auto", "darkness_auto": {"min": mn, "max": mx, "time_at_max": at, "hold_s": hold}})
    return d, clock


def simulate(d, clock, seconds, every):
    """Step on a clock like the Darkness layer; returns (share of time at Max, darkness values seen)."""
    at_max, seen, end = 0.0, [], clock.t + seconds
    while clock.t < end:
        marker = d.step(clock.t)
        clock.t += every
        at_max += every if marker == "max" else 0.0
        seen.append(d(clock.t))
    return at_max / seconds, seen


# ------------------------------------------------------------------ settings


def test_settings():
    c = parse_config({"darkness_mode": "auto", "darkness_auto": {"min": 5, "max": 80},
                      "set_darkness": {"low": 10, "high": {"mode": "auto", "min": 20, "max": 90, "time_at_max": 50}}})
    assert c["darkness_auto"] == {"min": 5, "max": 80, "time_at_max": 30, "hold_s": None}
    assert c["set_darkness"]["high"]["mode"] == "auto"


@pytest.mark.parametrize("bad, msg", [
    ({"darkness_mode": "random"}, "manual or auto"),
    ({"darkness_auto": {"min": 80, "max": 20}}, "min is above max"),
    ({"darkness_auto": {"max": 120}}, "0-100"),
    ({"darkness_auto": {"hold_s": -1}}, "hold_s"),
    ({"darkness_auto": {"speed": 1}}, "hold_s, max, min, time_at_max"),
    ({"set_darkness": {"mid": {"mode": "x"}}}, "manual or auto"),
    ({"set_darkness": {"mid": "dark"}}, "0-100"),
])
def test_bad_settings(bad, msg):
    with pytest.raises(ConfigError, match=msg):
        parse_config(bad)


# ------------------------------------------------------------------ the markers


@pytest.mark.parametrize("at", [10, 30, 50, 75])
def test_share_at_max_over_an_hour(at):
    d, clock = auto(at=at, interval=10)
    share, seen = simulate(d, clock, 3600, 10)
    assert abs(share - at / 100) <= 0.02
    assert all(0.10 - 1e-9 <= v <= 0.70 + 1e-9 for v in seen)  # never outside Min..Max


def test_share_with_a_staggered_clock_and_spread():
    import random

    d, clock = auto(at=40, interval=12)
    rng = random.Random(3)
    at_max, end, t0 = 0.0, clock.t + 3600, clock.t
    while clock.t < end:
        marker = d.step(clock.t)
        dt = 12 * (1 + rng.uniform(-0.25, 0.25))
        clock.t += dt
        at_max += dt if marker == "max" else 0.0
    assert abs(at_max / (clock.t - t0) - 0.40) <= 0.02


def test_minimum_hold_at_each_marker():
    d, clock = auto(at=50, hold=30, interval=5)
    last, since, flips = None, clock.t, []
    for _ in range(400):  # ticks far quicker than the hold, with a big deficit at the start
        m = d.step(clock.t)
        if m != last:
            if last is not None:
                flips.append(clock.t - since)
            last, since = m, clock.t
        clock.t += 1
    assert flips and min(flips) >= 30


def test_hold_defaults_to_the_layer_interval():
    d, _ = auto(interval=17)
    assert d.status()["hold_s"] == 17


def test_eases_with_the_look_fade():
    d, clock = auto(mn=0, mx=100, at=100, interval=1)
    d.fade = 1.0
    clock.t += 1  # Auto starts at Min and holds it for the hold time first
    assert d.step(clock.t) == "max"
    mid = d(clock.t + 0.5)
    assert 0 < mid < 1 and d(clock.t + 3) == 1.0


def test_slider_or_pedal_drops_to_manual():
    d, clock = auto()
    d.step(clock.t)
    d.set(0.25, "cc")
    st = d.status()
    assert st["mode"] == "manual" and st["dropped"] and st["darkness"] == 25
    assert d.step(clock.t + 100) is None  # no more marker moves


def test_set_change_loads_that_sets_mode():
    mood = ["low"]
    clock = T()
    d = Darkness(clock, lambda: mood[0], interval=lambda: 10)
    d.configure({"darkness": 20, "set_darkness": {"low": 15, "high": {"mode": "auto", "min": 30, "max": 90}}})
    assert d(clock.t) == pytest.approx(0.15, abs=0.2) and d.status()["mode"] == "manual"
    mood[0] = "high"
    d(clock.t)
    st = d.status()
    assert st["mode"] == "auto" and st["min"] == 30 and st["max"] == 90
    mood[0] = "low"
    d(clock.t)
    assert d.status()["mode"] == "manual" and d.status()["darkness"] == 15


# ------------------------------------------------------------------ in the app


def test_autopilot_drives_auto_darkness(app):
    app.save_autopilot({"darkness_mode": "auto", "darkness_auto": {"min": 0, "max": 80, "time_at_max": 50},
                        "timing": "staggered", "layers": {"darkness": {"every_s": 5, "spread": 0}}})
    app.autopilot.set_on(True, app.t.t)
    markers = set()
    for _ in range(12):
        run(app, 5)
        markers.add(app.darkness.status()["marker"])
    assert markers == {"min", "max"}
    assert app.darkness.status()["hold_s"] == 5


def test_api_auto_and_back_to_manual(running):
    from test_web import call

    app, url, *_ = running
    status, body = call(f"{url}/api/darkness", "POST", {"mode": "auto", "min": 10, "max": 60, "time_at_max": 40})
    assert status == 200 and body["mode"] == "auto" and body["max"] == 60
    assert call(f"{url}/api/darkness", "POST", {"min": 70, "max": 20})[0] == 400
    status, body = call(f"{url}/api/darkness", "POST", {"value": 30})
    assert body["mode"] == "manual" and body["dropped"] and body["darkness"] == 30


def test_set_darkness_saved_per_set(running):
    from test_web import call

    app, url, root, _ = running
    status, body = call(f"{url}/api/darkness/set", "POST",
                        {"set": "high", "value": {"mode": "auto", "min": 20, "max": 90, "time_at_max": 25}})
    assert status == 200
    sd = yaml.safe_load((root / "rigs" / "full.yaml").read_text())["autopilot"]["set_darkness"]
    assert sd["high"] == {"mode": "auto", "min": 20, "max": 90, "time_at_max": 25}
    call(f"{url}/api/darkness/set", "POST", {"set": "high", "value": {"time_at_max": 60}})  # merged
    sd = yaml.safe_load((root / "rigs" / "full.yaml").read_text())["autopilot"]["set_darkness"]
    assert sd["high"] == {"mode": "auto", "min": 20, "max": 90, "time_at_max": 60}
    call(f"{url}/api/darkness/set", "POST", {"set": "high", "value": 40})  # a plain number: Manual for that set
    assert yaml.safe_load((root / "rigs" / "full.yaml").read_text())["autopilot"]["set_darkness"]["high"] == 40


def test_claude_set_darkness(running):
    from dmx_suite.claude_tools import DmxTools

    app, url, root, claude = running
    t = DmxTools(shows=root, url=url, token=claude)
    assert t.set_darkness("auto", 5, 75, 20).startswith("darkness Auto: 5-75 %, 20 %")
    assert app.darkness.status()["mode"] == "auto"
    assert "back to Manual" in t.set_autopilot(40)
    assert t.set_darkness(mode="auto", set="mid").startswith("saved")
    sd = yaml.safe_load((root / "rigs" / "full.yaml").read_text())["autopilot"]["set_darkness"]
    assert sd["mid"] == {"mode": "auto"}
    app.set_gig_lock(True)
    try:
        assert t.set_darkness(mode="manual", value=10).startswith("darkness Manual")  # live: allowed
    finally:
        app.set_gig_lock(False)


def test_mcp_registers_set_darkness():
    pytest.importorskip("mcp")
    import asyncio

    from test_v6_darkness import SHOWS

    from dmx_suite.claude_tools import DmxTools
    from dmx_suite.mcp_server import build_server

    names = {x.name for x in asyncio.run(build_server(DmxTools(shows=SHOWS)).list_tools())}
    assert "set_darkness" in names
