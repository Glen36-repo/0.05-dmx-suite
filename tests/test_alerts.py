"""Alerts and banners (v3.1): episodes, dismiss, auto-clear, snooze, mute per rig, critical
alerts, quiet mode, the log, and the API; alerts never touch the DMX output."""

import json
import shutil
from pathlib import Path

import pytest

from dmx_suite.alerts import AlertCenter, classify

SHOWS = Path(__file__).resolve().parents[1] / "shows"


class T:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


UM_BAD = {"kind": "midi", "name": "MIDI UM-ONE", "state": "bad", "detail": "unplugged"}
UM_OK = {"kind": "midi", "name": "MIDI UM-ONE", "state": "ok", "detail": "UM-ONE 1"}
OUT_BAD = {"kind": "output", "name": "Enttec Open DMX", "state": "bad", "detail": "COM3 unplugged"}
OUT_OK = {"kind": "output", "name": "Enttec Open DMX", "state": "ok", "detail": "COM3"}
ENGINE_BAD = {"kind": "engine", "name": "Engine", "state": "bad", "detail": "fault"}


@pytest.fixture
def clock():
    return T()


@pytest.fixture
def ac(tmp_path, clock):
    return AlertCenter(tmp_path / "alerts.json", tmp_path / "logs", clock, rig="full")


def ids(snap):
    return [b["id"] for b in snap["banners"]]


def test_classify():
    assert classify(UM_BAD) == "warning" and classify(UM_OK) is None
    assert classify(OUT_BAD) == "critical" and classify(ENGINE_BAD) == "critical"
    assert classify({"kind": "claude", "state": "idle"}) is None
    assert classify({"kind": "engine", "state": "warn"}) == "info"
    assert classify({"kind": "output", "state": "sim"}) is None


def test_dismissed_stays_hidden_until_the_state_changes(ac, clock):
    ac.update([UM_BAD])
    assert ids(ac.snapshot()) == ["midi:MIDI UM-ONE"]
    first = ac.snapshot()["new_at"]
    ac.dismiss("midi:MIDI UM-ONE")
    for _ in range(5):  # still unplugged: stays hidden
        clock.t += 1
        ac.update([UM_BAD])
        assert ids(ac.snapshot()) == []
    s = ac.snapshot()
    assert s["count"] == 1 and s["list"][0]["state"] == "dismissed"
    clock.t += 1
    ac.update([UM_OK])  # back: auto-clear
    assert ac.snapshot()["count"] == 0 and ac.snapshot()["list"][0]["state"] == "cleared"
    clock.t += 1
    ac.update([UM_BAD])  # drops out again: a new banner
    s = ac.snapshot()
    assert ids(s) == ["midi:MIDI UM-ONE"] and s["banners"][0]["episode"] == 2 and s["new_at"] > first


def test_banner_clears_on_its_own(ac, clock):
    ac.update([UM_BAD])
    clock.t += 1
    ac.update([UM_OK])
    assert ac.snapshot()["banners"] == []


def test_critical_can_be_minimised_not_dismissed(ac):
    ac.update([OUT_BAD])
    with pytest.raises(ValueError, match="minimise"):
        ac.dismiss("output:Enttec Open DMX")
    with pytest.raises(ValueError):
        ac.snooze("output:Enttec Open DMX", "10min")
    ac.minimise("output:Enttec Open DMX")
    ac.minimise("output:all")
    s = ac.snapshot()
    assert s["banners"] == [] and s["critical"]  # red light stays on
    ac.mute("output:Enttec Open DMX")
    assert ac.snapshot()["critical"]  # critical can't be muted away


def test_all_outputs_lost(ac):
    ac.update([OUT_BAD])
    assert "output:all" in ids(ac.snapshot())
    ac.update([OUT_BAD, OUT_OK | {"name": "Art-Net"}])
    assert "output:all" not in [a["id"] for a in ac.snapshot()["list"] if a["state"] != "cleared"]


def test_snooze_runs_out(ac, clock):
    ac.update([UM_BAD])
    ac.snooze("midi:MIDI UM-ONE", "10min")
    assert ac.snapshot()["banners"] == []
    clock.t += 599
    ac.update([UM_BAD])
    assert ac.snapshot()["banners"] == []
    clock.t += 2
    ac.update([UM_BAD])
    assert ids(ac.snapshot()) == ["midi:MIDI UM-ONE"]
    ac.snooze("midi:MIDI UM-ONE", "gig")
    clock.t += 10 ** 7
    assert ac.snapshot()["banners"] == []
    with pytest.raises(ValueError):
        ac.snooze("midi:MIDI UM-ONE", "1 week")


def test_mute_holds_for_this_rig_and_restart(ac, tmp_path, clock):
    ac.mute("midi:MIDI UM-ONE")
    ac.update([UM_BAD])
    s = ac.snapshot()
    assert s["banners"] == [] and s["list"][0]["state"] == "muted" and s["muted"] == ["midi:MIDI UM-ONE"]
    again = AlertCenter(tmp_path / "alerts.json", None, clock, rig="full")  # restart: still muted
    again.update([UM_BAD])
    assert again.snapshot()["banners"] == []
    other = AlertCenter(tmp_path / "alerts.json", None, clock, rig="small")  # another rig: not muted
    other.update([UM_BAD])
    assert ids(other.snapshot()) == ["midi:MIDI UM-ONE"]
    ac.set_rig("small")  # rig switch drops the mutes
    assert ac.snapshot()["muted"] == [] and ac.snapshot()["list"][0]["state"] == "active"
    ac.mute("midi:MIDI UM-ONE")
    ac.mute("midi:MIDI UM-ONE", False)
    assert ids(ac.snapshot()) == ["midi:MIDI UM-ONE"]


def test_quiet_mode_only_critical_banners(ac):
    ac.set_quiet(True)
    ac.update([UM_BAD, OUT_BAD])
    s = ac.snapshot()
    assert set(ids(s)) == {"output:Enttec Open DMX", "output:all"} and s["count"] == 3  # UM-ONE in the list


def test_critical_banners_first(ac, clock):
    ac.update([UM_BAD])
    clock.t += 1
    ac.update([UM_BAD, ENGINE_BAD])
    assert ids(ac.snapshot())[0] == "engine:Engine"


def test_log_file(ac, tmp_path, clock):
    ac.update([UM_BAD])
    ac.dismiss("midi:MIDI UM-ONE")
    clock.t += 1
    ac.update([UM_OK])
    lines = [json.loads(x) for p in (tmp_path / "logs").glob("alerts-*.jsonl") for x in p.read_text().splitlines()]
    assert [x["event"] for x in lines] == ["new", "dismissed", "cleared"]
    assert lines[0]["device"] == "MIDI UM-ONE" and lines[0]["message"] == "unplugged"


# ------------------------------------------------------------------ in the app


@pytest.fixture
def app(tmp_path):
    from dmx_suite.app import App
    from dmx_suite.output import LogDriver
    from dmx_suite.showfiles import load_show

    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups"))
    a = App(load_show(root), [LogDriver()], state_path=tmp_path / "state" / "s.json", log_dir=tmp_path / "logs")
    return a


class FakeInputs:
    def __init__(self):
        self.connected = False

    def status(self):
        return [{"name": "UM-ONE", "connected": self.connected, "port": None}]


def test_app_alerts_from_midi_status(app):
    app.midi_inputs = FakeInputs()
    s = app.snapshot()["alert_center"]
    assert ids(s) == ["midi:MIDI UM-ONE"]
    app.alert_center.dismiss("midi:MIDI UM-ONE")
    assert app.snapshot()["alert_center"]["banners"] == []
    app.midi_inputs.connected = True
    s = app.snapshot()["alert_center"]
    assert s["banners"] == [] and all(a["state"] == "cleared" for a in s["list"] if a["kind"] == "midi")


def test_alerts_never_change_the_output(app):
    app.engine.tick()
    before = {u: bytes(f) for u, f in app.engine.frames.items()}
    app.midi_inputs = FakeInputs()
    for _ in range(3):
        app.snapshot()
        app.alert_center.mute("midi:MIDI UM-ONE")
        app.alert_center.set_quiet(True)
        app.engine.tick()
    assert {u: bytes(f) for u, f in app.engine.frames.items()} == before


def test_rig_switch_clears_mutes(app):
    app.alert_center.mute("midi:MIDI UM-ONE")
    app.switch_rig("small")
    assert app.alert_center.muted == set()
