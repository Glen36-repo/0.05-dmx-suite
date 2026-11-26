"""Shared test rig: built in code so tests don't depend on the placeholder show files."""

import pytest

from dmx_suite.engine import Engine
from dmx_suite.fixtures import parse_patch
from dmx_suite.look import parse_look
from dmx_suite.output import LogDriver
from dmx_suite.rig import parse_rig

PATCH = {
    "types": {
        "head": {
            "kind": "head",
            "channels": [
                "pan", "pan_fine", "tilt", "tilt_fine",
                {"role": "pt_speed", "invert": True},
                "dimmer",
                {"role": "strobe", "default": 7},
                "red", "green", "blue",
                "gobo",
                {"role": "fixed", "default": 42},
            ],
        },
        "bar": {
            "kind": "bar",
            "channels": [
                {"role": "red", "pixel": 0}, {"role": "green", "pixel": 0}, {"role": "blue", "pixel": 0},
                {"role": "red", "pixel": 1}, {"role": "green", "pixel": 1}, {"role": "blue", "pixel": 1},
            ],
        },
        "wash": {"kind": "wash", "channels": ["dimmer", "red", "green", "blue"]},
        "uking": {
            "kind": "head",
            "colour_only": True,
            "home": {"pan": 0.25, "tilt": 0.75},
            "channels": ["pan", "tilt", {"role": "pt_speed", "invert": True}, "dimmer", "red", "green", "blue"],
        },
        "kick": {"kind": "kick", "channels": ["red", "green", "blue"]},
        "smoke": {"kind": "haze", "channels": ["haze"]},
    },
    "fixtures": [
        {"id": "mh_a", "type": "head", "address": 1, "groups": ["heads"]},
        {"id": "bar_1", "type": "bar", "address": 20, "groups": ["bars"]},
        {"id": "bar_2", "type": "bar", "address": 30, "groups": ["bars"]},
        {"id": "wash", "type": "wash", "address": 40},
        {"id": "uk", "type": "uking", "address": 50, "groups": ["heads"]},
        {"id": "kick", "type": "kick", "address": 60},
        {"id": "smoke", "type": "smoke", "address": 70},
    ],
}

RIG = {
    "name": "test",
    "fade_s": 0.4,
    "head_limits": {"mh_a": {"pan": [10, 90], "tilt": [0, 75]}},
    "haze": {"enabled": True, "level": 50, "boost_level": 100, "boost_cooldown_s": 10,
             "max_on_s": 60, "rest_s": 30, "pulse_on_s": 5, "pulse_every_s": 60},
    "kick_colour": {"red": 100, "green": 50, "blue": 0},
    "startup": {"master": True},
}

LOOK = {
    "show_colour": [0, 0, 1],
    "fixtures": {
        "mh_a": {"colour": [1, 0, 0], "pan": 0.5, "tilt": 0.5, "gobo": 30},
        "bars": {"colour": [0, 1, 0]},
        "wash": {"colour": [0, 0, 1]},
        "uk": {"colour": [1, 1, 0]},
    },
}


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


@pytest.fixture(autouse=True)
def _app_data(monkeypatch, tmp_path):
    """Resume state and logs go to a scratch app-data folder, never the real one."""
    monkeypatch.setenv("DMX_SUITE_DATA", str(tmp_path / "appdata"))


@pytest.fixture
def patch():
    return parse_patch(PATCH)


@pytest.fixture
def rig(patch):
    return parse_rig(RIG, patch)


@pytest.fixture
def look(patch):
    return parse_look(LOOK, patch)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def out():
    return LogDriver()


@pytest.fixture
def engine(rig, look, out, clock):
    e = Engine(rig, [out], look, clock=clock)
    e.tick()
    return e


class View:
    """Read a fixture's channels by role from the last frame."""

    def __init__(self, engine):
        self.e = engine

    def __call__(self, fid: str, role: str, pixel=None) -> int:
        fx = self.e.rig.patch.fixtures[fid]
        frame = self.e.frames[fx.universe]
        for ch in fx.type.channels:
            if ch.role == role and (pixel is None or ch.pixel == pixel):
                return frame[fx.slot(ch)]
        raise KeyError(role)

    def emitters(self, fid: str) -> list[int]:
        from dmx_suite.fixtures import EMITTERS

        fx = self.e.rig.patch.fixtures[fid]
        frame = self.e.frames[fx.universe]
        return [frame[fx.slot(c)] for c in fx.type.channels if c.role in EMITTERS or c.role == "dimmer"]


@pytest.fixture
def view(engine):
    return View(engine)
