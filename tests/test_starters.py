"""R7: starter shows for any rig, and spotting DMX interfaces for the setup wizard."""

import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from dmx_suite import settings
from dmx_suite.app import App
from dmx_suite.detect import guess, interfaces
from dmx_suite.fixtures import parse_patch
from dmx_suite.output import LogDriver
from dmx_suite.rig import parse_rig
from dmx_suite.showfiles import load_show
from dmx_suite.starters import starter

SHOWS = Path(__file__).resolve().parents[1] / "shows"


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "shows"
    shutil.copytree(SHOWS, r, ignore=shutil.ignore_patterns(".backups", ".state.json", ".giglock"))
    return r


@pytest.mark.parametrize("profile", ["0.05_band", "generic"])
def test_starter_show_is_valid_and_plays(root, profile):
    rig = (root / "rigs" / "full.yaml").read_text().replace("profile: 0.05_band", f"profile: {profile}")
    (root / "rigs" / "full.yaml").write_text(rig)
    app = App(load_show(root), [LogDriver()])
    r = app.make_starter()
    assert "starter_circles" in r["scenes"]  # the rig has moving heads
    assert app.ctl.show.key == "starter" and app.ctl.set_name == "calm"
    app.engine.set_master(True)
    assert any(app.engine.output()[0])  # something is lit
    with pytest.raises(ValueError, match="already a starter show"):
        app.make_starter()
    app.make_starter(overwrite=True)
    app.engine.stop()


def test_starter_without_moving_heads():
    patch = parse_patch({"types": {"par": {"kind": "wash", "channels": ["dimmer", "red", "green", "blue"]}},
                         "fixtures": [{"id": f"p{i}", "type": "par", "address": 1 + 4 * i} for i in range(4)]})
    scenes, show = starter(parse_rig({"name": "pars", "profile": "generic"}, patch))
    assert "starter_circles" not in scenes
    assert all(step["scene"] in scenes for s in show["sets"].values() for step in s["steps"])


def test_starter_needs_lights():
    patch = parse_patch({"types": {"smoke": {"kind": "haze", "channels": ["haze"]}},
                         "fixtures": [{"id": "s", "type": "smoke", "address": 1}]})
    with pytest.raises(ValueError, match="add some lights"):
        starter(parse_rig({"name": "x"}, patch))


def test_interface_guesses():
    assert guess(0x303A, 0x1001, "USB JTAG/serial debug unit") == "node"
    assert guess(0x0403, 0x6001, "DMX USB PRO") == "usb_dmx_pro"
    assert guess(0x0403, 0x6001, "FT232R USB UART") == "usb_dmx_open"
    assert guess(0x2341, 0x0043, "Arduino Uno") is None
    port = SimpleNamespace
    ports = [port(device="COM7", description="Arduino Uno", manufacturer="", product="", vid=0x2341, pid=0x43),
             port(device="COM3", description="FT232R USB UART", manufacturer="FTDI", product="", vid=0x0403, pid=0x6001)]
    found = interfaces(ports)
    assert [f["port"] for f in found] == ["COM3", "COM7"]  # likely interfaces first
    assert found[0]["driver"] == "usb_dmx_open" and found[0]["usb"] == "0403:6001"
    assert isinstance(interfaces(), list)  # the real listing works (empty here)


def test_wizard_setting():
    assert settings.first_run()
    settings.save({"wizard": "skipped"})
    assert not settings.first_run()
    with pytest.raises(ValueError):
        settings.save({"wizard": "maybe"})
