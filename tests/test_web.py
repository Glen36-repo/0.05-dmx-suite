"""Browser UI / API server, Claude tools against it, and the MCP server wrapper."""

import asyncio
import http.client
import json
import shutil
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from dmx_suite.app import App
from dmx_suite.claude_tools import DmxTools
from dmx_suite.output import LogDriver
from dmx_suite.showfiles import load_show
from dmx_suite.store import StoreError
from dmx_suite.web.server import WebServer

SHOWS = Path(__file__).resolve().parents[1] / "shows"
TOKEN = "test-token-0123456789abcdef"


@pytest.fixture
def running(tmp_path):
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json"))
    app = App(load_show(root), [LogDriver()], state_path=root / ".state.json", log_dir=tmp_path / "logs")
    app.ctl.select_show("band", "mid")
    web = WebServer(app, "127.0.0.1", 0, token=TOKEN)
    web.start()
    yield app, f"http://127.0.0.1:{web.port}", root
    web.stop()
    app.engine.stop()


def call(url, method="GET", body=None, token=TOKEN, host=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-DMX-Token"] = token
    if host:
        headers["Host"] = host
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(), method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


# ------------------------------------------------------------------ API


def test_state_and_page(running):
    app, url, _ = running
    status, s = call(url + "/api/state")
    assert status == 200 and s["now"]["show"] == "band" and len(s["fixtures"]) == 12
    with urllib.request.urlopen(url + "/") as r:
        html = r.read().decode()
    assert TOKEN in html and "0.05 DMX Suite" in html
    with urllib.request.urlopen(url + "/static/app.js") as r:
        assert r.status == 200


def test_writes_need_token(running):
    _, url, _ = running
    assert call(url + "/api/control", "POST", {"cmd": "master"}, token=None)[0] == 401
    assert call(url + "/api/control", "POST", {"cmd": "master"}, token="wrong" * 6)[0] == 401


def test_unknown_host_refused(running):
    _, url, _ = running
    assert call(url + "/api/state", host="evil.example.com")[0] == 403
    assert call(url + "/api/state", host="localhost:1234")[0] == 200


def test_static_path_traversal(running):
    _, url, _ = running
    port = int(url.rsplit(":", 1)[1])
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("GET", "/static/../server.py")
    assert conn.getresponse().status == 404


def test_control_commands(running):
    app, url, _ = running
    assert call(url + "/api/control", "POST", {"cmd": "master", "on": False})[1]["ok"]
    assert not app.engine.master
    call(url + "/api/control", "POST", {"cmd": "set", "set": "high"})
    assert app.ctl.now().set == "high"
    call(url + "/api/control", "POST", {"cmd": "grand", "level": 0.5})
    assert app.engine.masters.grand.target == 0.5
    call(url + "/api/control", "POST", {"cmd": "position", "fixture": "mh_a", "pan": 0.2, "tilt": 0.9})
    app.engine.output()
    mh = next(f for f in app.fixture_view() if f["id"] == "mh_a")
    assert mh["override"] and mh["tilt"] == pytest.approx(0.75, abs=0.01)  # head limit still applies
    status, err = call(url + "/api/control", "POST", {"cmd": "position", "fixture": "uking_l", "pan": 0.2, "tilt": 0.2})
    assert status == 400 and "rule 7" in err["error"]
    status, err = call(url + "/api/control", "POST", {"cmd": "chan", "channel": 156, "value": 255})
    assert status == 400 and "rule 5" in err["error"]
    assert call(url + "/api/control", "POST", {"cmd": "nope"})[0] == 400


def test_store_via_api_reloads_live(running):
    app, url, root = running
    teal = {"name": "Teal", "layers": [{"fixtures": ["bars"], "colour": "#00a090"}]}
    status, r = call(url + "/api/store/scene/teal", "PUT", {"data": teal})
    assert status == 200 and r["backup"]
    assert "teal" in app.files.scenes  # live reload
    call(url + "/api/control", "POST", {"cmd": "scene", "scene": "teal"})
    assert app.ctl.now().scene == "teal"
    status, r = call(url + "/api/store/scene/teal", "PUT", {"data": {"layers": [{"fixtures": ["bars"], "dimmer": 1}]}})
    assert status == 400 and "rule 1" in r["error"]


def test_gig_lock(running):
    app, url, _ = running
    call(url + "/api/giglock", "POST", {"on": True})
    assert call(url + "/api/store/scene/x", "PUT", {"data": {"layers": [{"fixtures": ["bars"], "colour": "red"}]}})[0] == 423
    assert call(url + "/api/preview", "POST", {"scene": "opera"})[0] == 423
    assert call(url + "/api/claude/haze", "POST", {"action": "manual"})[0] == 423
    assert call(url + "/api/control", "POST", {"cmd": "set", "set": "low"})[0] == 200  # the band still runs the show
    call(url + "/api/giglock", "POST", {"on": False})
    assert call(url + "/api/preview", "POST", {"scene": "opera", "seconds": 5})[0] == 200
    assert app.engine.previewing is not None


def test_midi_learn_and_monitor_over_api(running):
    app, url, _ = running
    from dmx_suite.midi.inputs import FakeMidiIn

    call(url + "/api/midi/learn", "POST", {"action": "flash", "params": {"fixtures": ["washes"]}})
    FakeMidiIn(app.router.handle_mido).note(70, 100)
    status, rows = call(url + "/api/midi?since=0")
    assert rows[-1]["result"].startswith("learned")
    assert app.router.map.get("note", 10, 70).action == "flash"
    res = call(url + "/api/midi/save", "POST", {})[1]
    assert res["ok"] and res["backup"]  # through the store: validated and backed up
    saved = app.files.midimap_path.read_text(encoding="utf-8")
    assert "number: 70" in saved and "# TD-25" in saved  # new mapping written, comments kept


def test_events_stream(running):
    _, url, _ = running
    port = int(url.rsplit(":", 1)[1])
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", "/api/events")
    r = conn.getresponse()
    assert r.getheader("Content-Type") == "text/event-stream"
    line = r.fp.readline().decode()
    assert line.startswith("data: ") and '"state"' in line
    conn.close()


# ------------------------------------------------------------------ Claude tools


def test_claude_tools_online(running):
    app, url, root = running
    t = DmxTools(shows=root, url=url, token=TOKEN)
    assert "Safety rules" in t.get_guide()
    assert "mh_a" in t.list_fixtures()
    scene = "name: Slow purple\nlayers:\n  - {fixtures: [bars], colour: purple}\n  - {fixtures: [movers], position: drum_kit}"
    assert t.validate_scene(scene).startswith("ok")
    assert "rule 7" in t.validate_scene("layers:\n  - {fixtures: [ukings], effect: random_move}")
    assert t.save("scene", "slow_purple", scene).startswith("saved (backup")
    assert "slow_purple" in app.files.scenes
    assert "previewing Slow purple" in t.preview_scene("slow_purple", 3)
    assert "previewing" in t.preview_scene(scene, 3)  # unsaved YAML
    assert "describe" in t.now_playing()
    assert t.set_haze("manual") == "haze manual"
    with pytest.raises(StoreError, match="footswitch"):
        t.set_haze("boost")
    with pytest.raises(StoreError, match="rule 1"):
        t.save("scene", "bad", "layers:\n  - {fixtures: [bars], dimmer: 1}")
    app.set_gig_lock(True)
    with pytest.raises(StoreError, match="gig lock"):
        t.save("scene", "x", scene)
    with pytest.raises(StoreError, match="gig lock"):
        t.preview_scene("opera")


def test_claude_tools_offline(tmp_path):
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json"))
    t = DmxTools(shows=root, url="http://127.0.0.1:9", token=TOKEN)  # nothing listening
    assert "engine isn't running" in t.save("scene", "teal", "layers:\n  - {fixtures: [bars], colour: blue}")
    assert (root / "scenes" / "teal.yaml").exists()
    assert "colours:" in t.get_palettes()
    assert "opera: Opera" in t.list("scene")
    with pytest.raises(StoreError, match="isn't running"):
        t.preview_scene("opera")


def test_mcp_server_lists_tools(tmp_path):
    pytest.importorskip("mcp")
    from dmx_suite.mcp_server import build_server

    server = build_server(DmxTools(shows=SHOWS, url="http://127.0.0.1:9", token=TOKEN))
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert {"get_guide", "save_item", "validate_scene", "preview_scene", "set_haze", "node_health"} <= names
    result = asyncio.run(server.call_tool("validate_scene", {"scene_yaml": "layers:\n  - {fixtures: [bars], dimmer: 1}"}))
    text = json.dumps(result, default=lambda o: getattr(o, "__dict__", str(o)))
    assert "rule 1" in text


def test_node_drop_alert_and_health_log(tmp_path):
    from dmx_suite.output import NodeSerialDriver

    node = NodeSerialDriver("sim")
    app = App(load_show(SHOWS), [node], log_dir=tmp_path / "logs")
    clock = [1000.0]
    health = node.link.health
    health._clock = lambda: clock[0]
    for _ in range(2):
        node.link.t.node._next_hb_ms = 0
        node.link.poll()
    clock[0] += 10  # receivers stop being heard
    health.tick()
    assert any(a["state"] == "offline" for a in app.alerts)
    log = next((tmp_path / "logs").glob("health-*.jsonl")).read_text()
    assert '"to": "offline"' in log
    assert {"mac", "state", "rssi"} <= set(app.nodes()[0])
    app.engine.stop()


def test_groups_over_http_apply_live(running):
    app, url, _ = running
    status, r = call(url + "/api/store/group", "POST", {"action": "set", "name": "front", "fixtures": ["wash_l", "wash_r"]})
    assert status == 200 and r["backup"]
    assert app.catalogue()["groups"]["front"] == ["wash_l", "wash_r"]  # no restart
    status, r = call(url + "/api/store/group", "POST", {"action": "set", "name": "all", "fixtures": ["kick"]})
    assert status == 400
    app.set_gig_lock(True)
    assert call(url + "/api/store/group", "POST", {"action": "delete", "name": "front"})[0] == 423
