"""v4 item 15: Monitor - DMX out, MIDI in and MIDI out watchers; Claude's monitor_dmx / monitor_midi."""

import asyncio
import json
import shutil

import mido
import pytest
import yaml
from test_web import CLAUDE, SHOWS, TOKEN, call

from dmx_suite.app import App
from dmx_suite.claude_tools import DmxTools
from dmx_suite.midi.monitor import MidiMonitor, note_name
from dmx_suite.midi.outputs import MidiOutputs
from dmx_suite.output import LogDriver
from dmx_suite.showfiles import load_show
from dmx_suite.store import StoreError
from dmx_suite.web.server import WebServer


class FakeOut:
    def __init__(self):
        self.sent = []

    def send(self, msg):
        self.sent.append(msg)


def test_note_names_and_rates():
    assert note_name(60) == "C4" and note_name(36) == "C2" and note_name(38) == "D2"
    m = MidiMonitor()
    for _ in range(3):
        m.clock(100.0)
    rates = m.rates(now=101.0)
    assert rates["clock_per_s"] == 0.8


def test_midi_in_log_has_note_input_roles_action():
    app = App(load_show(SHOWS), [LogDriver()])
    app.router.handle_mido(mido.Message("note_on", channel=9, note=38, velocity=100), "TD-25")
    app.router.handle_mido(mido.Message("note_on", channel=9, note=99, velocity=90), "TD-25")
    rows = app.monitor_midi("in", 10)
    snare, odd = rows[-2], rows[-1]
    assert snare["note"] == "D2" and snare["input"] == "Snare" and "snare" in snare["roles"] and snare["result"] != "unmapped"
    assert odd["result"] == "unmapped"
    assert [r["number"] for r in app.monitor_midi("in", 10, unmapped=True)] == [99]
    assert app.monitor_status()["rates"]["hits_per_s"] > 0
    assert app.monitor_status()["midi_in_sim"] is True


def test_midi_out_send_is_logged_and_locked():
    app = App(load_show(SHOWS), [LogDriver()])
    with pytest.raises(ValueError, match="no MIDI outputs"):
        app.midi_send("x", "note_on", 1, 60, 100)
    port = FakeOut()
    app.midi_outputs = MidiOutputs(["Feedback"], app.midi_out_monitor, lister=lambda: ["Feedback 1"], opener=lambda n: port)
    assert app.midi_send("Feedback", "control_change", 2, 7, 64) == "Feedback 1"
    assert port.sent[0].type == "control_change" and port.sent[0].channel == 1
    out = app.monitor_midi("out", 5)
    assert out[-1]["direction"] == "out" and out[-1]["number"] == 7 and out[-1]["result"] == "test send"
    with pytest.raises(ValueError):
        app.midi_send("Feedback", "note_on", 17, 60, 100)
    app.set_gig_lock(True)
    with pytest.raises(Exception, match="gig lock"):
        app.midi_send("Feedback", "note_on", 1, 60, 100)


@pytest.fixture
def running(tmp_path):
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json"))
    app = App(load_show(root), [LogDriver()], state_path=root / ".state.json")
    web = WebServer(app, "127.0.0.1", 0, token=TOKEN, claude_token=CLAUDE)
    web.start()
    yield app, f"http://127.0.0.1:{web.port}", root
    web.stop()
    app.engine.stop()


def test_monitor_api_and_claude_tools(running):
    app, url, root = running
    app.engine.output()
    status, names = call(f"{url}/api/monitor/channels?u=0")
    assert status == 200 and names["27"] == "bar_1 red px1"
    app.router.handle_mido(mido.Message("note_on", channel=9, note=38, velocity=100), "TD-25")
    status, rows = call(f"{url}/api/monitor/midi?dir=in&n=5")
    assert status == 200 and rows[-1]["note"] == "D2"
    t = DmxTools(shows=root, url=url, token=CLAUDE)
    d = yaml.safe_load(t.monitor_dmx(0, "", "27-29"))
    assert d["source"] == "Simulator" and set(d["channels"]) == {27, 28, 29} and d["channels"][27]["name"] == "bar_1 red px1"
    m = yaml.safe_load(t.monitor_midi("in", 5))
    assert m["events"][-1]["input"] == "Snare" and "rates" in m and "energy" in m
    with pytest.raises(StoreError):
        t.monitor_dmx(0, "", "one-two")
    app.set_gig_lock(True)  # watching works under gig lock
    assert call(f"{url}/api/monitor/status")[0] == 200


def test_monitor_dmx_says_when_nothing_went_out(running):
    from dmx_suite.output.enttec import EnttecProDriver

    app, url, root = running

    def broken(*a):
        raise OSError("unplugged")

    dead = EnttecProDriver("COM8", serial_factory=broken, threaded=False)
    app.engine.drivers.insert(0, dead)
    app.engine.output()
    t = DmxTools(shows=root, url=url, token=CLAUDE)
    d = yaml.safe_load(t.monitor_dmx(0, "0"))
    assert d["no_frames"] and d["channels"] == {} and "nothing is going out" in d["note"]
    app.engine.drivers.remove(dead)
    dead.close()


def test_save_input_keeps_device_and_takes_device_info(tmp_path):
    pytest.importorskip("mcp")
    from dmx_suite.mcp_server import build_server

    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json"))
    server = build_server(DmxTools(shows=root, url="http://127.0.0.1:9", token=CLAUDE))
    args = {"device": "pads", "name": "pad_1", "value_yaml": "{name: Pad 1, type: note, notes: [60]}",
            "device_info_yaml": "{name: SamplePad, port: H2MIDI, channel: 10}"}
    result = json.dumps(asyncio.run(server.call_tool("save_input", args)), default=lambda o: getattr(o, "__dict__", str(o)))
    assert "saved" in result
    data = yaml.safe_load((root / "inputs.yaml").read_text())
    pads = data["devices"]["pads"]
    assert pads["inputs"]["pad_1"]["notes"] == [60] and pads["name"] == "SamplePad" and pads["port"] == "H2MIDI"
    with pytest.raises(StoreError, match="needs device"):
        DmxTools(shows=root, url="http://127.0.0.1:9", token=CLAUDE).save_input("", "x", "{type: note, notes: [1]}")
