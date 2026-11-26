"""Status bar: output drivers survive unplug/replug and report state; Claude and screens show up."""

import http.client
import shutil
import time
import urllib.request
from pathlib import Path

import pytest

from dmx_suite.app import App
from dmx_suite.claude_tools import DmxTools
from dmx_suite.node.link import ReconnectingSerial
from dmx_suite.output import LogDriver, NodeSerialDriver, enttec
from dmx_suite.output.enttec import EnttecOpenDriver, EnttecProDriver
from dmx_suite.showfiles import load_show
from dmx_suite.web.server import WebServer

SHOWS = Path(__file__).resolve().parents[1] / "shows"
TOKEN = "test-token-0123456789abcdef"
CLAUDE = "claude-token-0123456789abcdef"


class Plug:
    """A USB serial port we can unplug and plug back in."""

    def __init__(self, present=True):
        self.present = present
        self.opens = 0
        self.writes = []

    def factory(self, *args):
        if not self.present:
            raise OSError("could not open port COM9: FileNotFoundError")
        self.opens += 1
        plug = self

        class Ser:
            break_condition = False

            def write(self, data):
                if not plug.present:
                    raise OSError("device disconnected")
                plug.writes.append(bytes(data))

            def flush(self):
                pass

            def close(self):
                pass

        return Ser()


@pytest.fixture(autouse=True)
def fast_reopen(monkeypatch):
    monkeypatch.setattr(enttec, "REOPEN_S", 0.05)
    monkeypatch.setattr(ReconnectingSerial, "REOPEN_S", 0.05)


def wait_for(pred, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


def test_enttec_pro_missing_at_start_then_plugged_in():
    plug = Plug(present=False)
    d = EnttecProDriver("COM9", serial_factory=plug.factory)  # doesn't raise: the show carries on
    assert d.state()["state"] == "bad" and "not found" in d.state()["detail"]
    d.send(0, bytes(512))
    assert not plug.writes
    plug.present = True

    def plugged_in():  # resends until the reopen timer allows a retry (Windows clocks tick ~16 ms)
        d.send(0, bytes(512))
        d.flush()
        return bool(plug.writes)

    assert wait_for(plugged_in)
    assert len(plug.writes) == 1 and d.state()["state"] == "ok"


def test_enttec_pro_unplug_and_replug():
    plug = Plug()
    d = EnttecProDriver("COM9", serial_factory=plug.factory)
    d.send(0, bytes(512))
    d.flush()
    plug.present = False
    d.send(0, bytes(512))  # write fails: port dropped
    d.flush()
    assert d.state()["state"] == "bad" and "unplugged" in d.state()["detail"]
    plug.present = True

    def back():  # resends until the reopen timer allows a retry
        d.send(0, bytes(512))
        d.flush()
        return d.state()["state"] == "ok"

    assert wait_for(back)
    assert plug.opens == 2


def test_enttec_open_keeps_streaming_after_replug():
    plug = Plug()
    d = EnttecOpenDriver("COM9", serial_factory=plug.factory)
    try:
        assert wait_for(lambda: d.state()["state"] == "ok")
        plug.present = False
        assert wait_for(lambda: d.state()["state"] == "bad")
        plug.present = True
        n = len(plug.writes)
        assert wait_for(lambda: len(plug.writes) > n + 3)  # streaming again by itself
        assert d.state()["state"] == "ok" and plug.opens == 2
    finally:
        d.close()


def test_node_serial_unplug_and_replug():
    plug = {"present": True, "n": 0}

    class T:
        def write(self, data):
            if not plug["present"]:
                raise OSError("gone")

        def read(self):
            if not plug["present"]:
                raise OSError("gone")
            return b""

        def close(self):
            pass

    def opener(port):
        if not plug["present"]:
            raise OSError("not found")
        plug["n"] += 1
        return T()

    rs = ReconnectingSerial("COM5", opener)
    assert rs.is_open
    plug["present"] = False
    rs.write(b"x")
    assert not rs.is_open and rs.errors == 1
    assert rs.read() == b""  # no exception into the reader thread
    plug["present"] = True
    time.sleep(0.06)
    rs.write(b"x")
    assert rs.is_open and plug["n"] == 2


def test_node_driver_states(monkeypatch):
    d = NodeSerialDriver("sim")
    assert d.state()["state"] == "sim"
    d.close()


# ------------------------------------------------------------------ app devices list


@pytest.fixture
def app():
    a = App(load_show(SHOWS), [LogDriver()])
    yield a
    a.engine.stop()


def test_devices_list(app):
    kinds = [d["kind"] for d in app.devices()]
    assert kinds[:2] == ["engine", "output"] and "claude" in kinds and "screens" in kinds
    claude = next(d for d in app.devices() if d["kind"] == "claude")
    assert claude["state"] == "idle" and claude["detail"].startswith("not set up")


def test_claude_states(app):
    app.note_client("claude")  # MCP server check-in
    c = next(d for d in app.devices() if d["kind"] == "claude")
    assert c["state"] == "ok" and c["detail"] == "connected" and not c["active"]
    app.note_client("claude", "save_item")
    c = next(d for d in app.devices() if d["kind"] == "claude")
    assert c["active"] and c["detail"].startswith("save_item")
    app.set_gig_lock(True)
    assert "read-only" in next(d for d in app.devices() if d["kind"] == "claude")["detail"]
    app.clients["claude"]["last"] -= 120  # Claude Desktop closed
    c = next(d for d in app.devices() if d["kind"] == "claude")
    assert c["state"] == "idle" and "last seen" in c["detail"]


def test_engine_fps(app):
    app.engine.start()
    try:
        app.engine_fps()
        time.sleep(1.1)
        assert 30 <= app.engine_fps() <= 50
        assert next(d for d in app.devices() if d["kind"] == "engine")["state"] == "ok"
    finally:
        app.engine.stop()


# ------------------------------------------------------------------ through the server


@pytest.fixture
def server(tmp_path):
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json"))
    a = App(load_show(root), [LogDriver()])
    web = WebServer(a, "127.0.0.1", 0, token=TOKEN, claude_token=CLAUDE)
    web.start()
    yield a, f"http://127.0.0.1:{web.port}", root
    web.stop()
    a.engine.stop()


def test_claude_ping_and_calls_tracked(server):
    a, url, root = server
    t = DmxTools(shows=root, url=url, token=CLAUDE)
    assert t.ping()
    assert a.clients["claude"]["calls"] == 0  # a check-in isn't a call
    t.call_label = "now_playing"
    t.now_playing()
    assert a.clients["claude"]["last_call"] == "now_playing"
    assert not DmxTools(shows=root, url="http://127.0.0.1:9", token=CLAUDE).ping()


def test_screens_counted(server):
    a, url, _ = server
    port = int(url.rsplit(":", 1)[1])
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", "/api/events")
    r = conn.getresponse()
    r.fp.readline()
    assert len(a.screens) == 1 and next(iter(a.screens.values()))["local"]
    r.close()  # the response holds the socket open until it's closed too
    conn.close()
    assert wait_for(lambda: not a.screens)  # closed tab drops off


def test_devices_endpoint(server):
    _, url, _ = server
    import json

    with urllib.request.urlopen(url + "/api/devices") as r:
        devs = json.loads(r.read())
    assert {d["kind"] for d in devs} >= {"engine", "output", "midi", "claude", "screens"}
