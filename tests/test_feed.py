"""R6 live feed: one snapshot a tick for every screen, sent only when it changes, with a heartbeat."""

import http.client
import json
import shutil
import threading
import time
from pathlib import Path

import pytest

from dmx_suite.app import App
from dmx_suite.output import LogDriver
from dmx_suite.showfiles import load_show
from dmx_suite.web import feed as feed_mod
from dmx_suite.web import server as server_mod
from dmx_suite.web.feed import LiveFeed
from dmx_suite.web.server import WebServer

SHOWS = Path(__file__).resolve().parents[1] / "shows"


def test_feed_versions_only_on_change():
    box = {"n": 1}
    f = LiveFeed(lambda: dict(box), tick_s=0.01)
    f.build()
    v1, p1 = f.version, f.payload
    f.build()
    assert f.version == v1 and f.builds == 2  # same state: no new version
    box["n"] = 2
    f.build()
    assert f.version == v1 + 1 and json.loads(f.payload) == {"n": 2} and p1 != f.payload


def test_feed_wait_wakes_on_change_and_times_out():
    box = {"n": 1}
    f = LiveFeed(lambda: dict(box), tick_s=0.01)
    f.build()
    t0 = time.monotonic()
    assert f.wait(f.version, 0.1)[0] == f.version and time.monotonic() - t0 >= 0.09
    seen = f.version
    threading.Timer(0.05, lambda: (box.update(n=3), f.build())).start()
    v, p = f.wait(seen, 2.0)
    assert v == seen + 1 and json.loads(p)["n"] == 3


def test_feed_survives_a_broken_snapshot():
    calls = {"n": 0}

    def snap():
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return {"n": calls["n"]}

    f = LiveFeed(snap)
    f.build()
    f.build()  # logged, keeps the last good state
    assert json.loads(f.payload) == {"n": 1}
    f.build()
    assert json.loads(f.payload) == {"n": 3}


@pytest.fixture
def web(tmp_path, monkeypatch):
    monkeypatch.setattr(feed_mod, "HEARTBEAT_S", 0.3)
    monkeypatch.setattr(server_mod, "HEARTBEAT_S", 0.3)
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json", ".giglock"))
    app = App(load_show(root), [LogDriver()])
    w = WebServer(app, "127.0.0.1", 0, token="t" * 24, claude_token="c" * 24)
    w.start()
    yield app, w
    w.stop()
    app.engine.stop()


def _events(w, n, timeout=5):
    conn = http.client.HTTPConnection("127.0.0.1", w.port, timeout=timeout)
    conn.request("GET", "/api/events")
    r = conn.getresponse()
    out = []
    while len(out) < n:
        line = r.fp.readline().decode()
        if line.startswith("data: "):
            out.append(json.loads(line[6:]))
    conn.close()
    return out


def test_screens_share_one_snapshot_a_tick(web):
    app, w = web
    calls = {"n": 0}
    real = app.snapshot

    def counted():
        calls["n"] += 1
        return real()

    w.feed.snapshot = counted
    results = []
    threads = [threading.Thread(target=lambda: results.append(_events(w, 3))) for _ in range(4)]
    for t in threads:
        t.start()
    time.sleep(1.0)
    for t in threads:
        t.join(5)
    assert len(results) == 4 and all("state" in r[0] for r in results)
    assert calls["n"] <= 15  # ~10 a second for everyone, not 10 per screen


def test_quiet_show_sends_heartbeats_not_repeats(web):
    app, w = web
    w.feed.snapshot = lambda: {"still": True}  # nothing changes
    w.feed.build()
    got = _events(w, 3)
    assert got[0] == {"state": {"still": True}}
    assert got[1:] == [{"beat": 1}, {"beat": 1}]


def test_midi_lines_come_through_without_a_new_state(web):
    app, w = web
    w.feed.snapshot = lambda: {"still": True}
    w.feed.build()
    threading.Timer(0.1, lambda: app.router.handle_mido(__import__("mido").Message("note_on", note=36, velocity=90))).start()
    got = _events(w, 2)
    assert "midi" in got[1] and "state" not in got[1]
