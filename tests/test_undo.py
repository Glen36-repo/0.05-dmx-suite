"""R6 undo/redo: every change since start-up can be undone and redone, byte for byte."""

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
from dmx_suite.store import LockedError, ShowStore, StoreError
from dmx_suite.web.server import WebServer

SHOWS = Path(__file__).resolve().parents[1] / "shows"
UI = "ui-token-0123456789abcdefgh"
CLAUDE = "claude-token-0123456789abcd"
SCENE = {"name": "Undo test", "layers": [{"fixtures": ["bars"], "colour": "red"}]}


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "shows"
    shutil.copytree(SHOWS, r, ignore=shutil.ignore_patterns(".backups", ".state.json", ".giglock"))
    return r


def test_undo_and_redo_a_new_file(root):
    s = ShowStore(root)
    p = root / "scenes" / "undo_test.yaml"
    s.put("scene", "undo_test", SCENE)
    text = p.read_text()
    assert s.history()["undo"][0]["note"] == "put scene undo_test" and s.history()["undo"][0]["who"] == "ui"
    s.undo()
    assert not p.exists() and s.history()["redo"]
    s.redo()
    assert p.read_text() == text and not s.history()["redo"]


def test_undo_gives_back_the_exact_file_with_comments(root):
    s = ShowStore(root)
    p = root / "palettes.yaml"
    original = p.read_bytes()  # exactly, line endings too (CRLF in a Windows checkout)
    assert b"#" in original  # the shipped file has comments
    s.put_entry("palettes", "colours", "undo_pink", [1, 0.4, 0.7])
    s.put_entry("palettes", "colours", "undo_teal", [0, 0.8, 0.8])
    assert "undo_teal" in p.read_text()
    s.undo()
    s.undo()
    assert p.read_bytes() == original


def test_a_new_change_clears_redo(root):
    s = ShowStore(root)
    s.put("scene", "undo_a", SCENE)
    s.undo()
    s.put("scene", "undo_b", SCENE)
    assert s.history()["redo"] == []
    with pytest.raises(StoreError, match="nothing to redo"):
        s.redo()


def test_undo_refused_when_the_file_changed_another_way(root):
    s = ShowStore(root)
    s.put("scene", "undo_a", SCENE)
    (root / "scenes" / "undo_a.yaml").write_text("name: hand edit\nlayers: []\n")
    with pytest.raises(StoreError, match="changed since"):
        s.undo()


def test_unlimited_within_a_session(root):
    s = ShowStore(root)
    for i in range(30):
        s.put_entry("palettes", "colours", f"undo_c{i}", [i / 30, 0, 0])
    for _ in range(30):
        s.undo()
    assert "undo_c" not in (root / "palettes.yaml").read_text()
    with pytest.raises(StoreError, match="nothing to undo"):
        s.undo()


def test_claude_undoes_only_its_own_change(root):
    s = ShowStore(root)
    with s.acting("claude"):
        s.put("scene", "by_claude", SCENE)
    s.put("scene", "by_you", SCENE)
    done = s.undo("claude")
    assert done["note"] == "put scene by_claude"
    assert not (root / "scenes" / "by_claude.yaml").exists() and (root / "scenes" / "by_you.yaml").exists()
    with pytest.raises(StoreError, match="no change by claude"):
        s.undo("claude")


def test_gig_lock_blocks_undo(root):
    lock = {"on": False}
    s = ShowStore(root, lambda: lock["on"])
    s.put("scene", "undo_a", SCENE)
    lock["on"] = True
    with pytest.raises(LockedError):
        s.undo()


# ------------------------------------------------------------------ through the server


def call(port, path, method="GET", body=None, token=UI):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method,
                                 headers={"Content-Type": "application/json", "X-DMX-Token": token},
                                 data=None if body is None else json.dumps(body).encode())
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


@pytest.fixture
def running(root):
    app = App(load_show(root), [LogDriver()])
    web = WebServer(app, "127.0.0.1", 0, token=UI, claude_token=CLAUDE)
    web.start()
    yield app, web.port
    web.stop()
    app.engine.stop()


def test_undo_over_the_api_reloads_the_show(running, root):
    app, port = running
    assert call(port, "/api/store/scene/undo_api", "PUT", {"data": SCENE})[0] == 200
    assert "undo_api" in app.files.scenes
    status, r = call(port, "/api/undo", "POST", {})
    assert status == 200 and r["change"]["note"] == "put scene undo_api" and r["redo"]
    assert "undo_api" not in app.files.scenes  # reloaded
    status, r = call(port, "/api/redo", "POST", {})
    assert status == 200 and "undo_api" in app.files.scenes
    assert call(port, "/api/undo")[1]["undo"][0]["who"] == "ui"


def test_claude_undo_over_the_api(running, root):
    app, port = running
    tools = DmxTools(shows=root, url=f"http://127.0.0.1:{port}", token=CLAUDE)
    tools.save("scene", "claude_one", "name: c\nlayers:\n  - {fixtures: [bars], colour: red}\n")
    call(port, "/api/store/scene/yours", "PUT", {"data": SCENE})
    assert call(port, "/api/undo", "POST", {}, token=CLAUDE)[0] == 403  # only its own
    assert "claude_one" in tools.undo_last_change()
    assert "claude_one" not in app.files.scenes and "yours" in app.files.scenes
    hist = call(port, "/api/undo")[1]
    assert [c["who"] for c in hist["undo"]] == ["ui"] and hist["redo"][0]["who"] == "claude"


def test_claude_undo_offline(root):
    tools = DmxTools(shows=root, url="http://127.0.0.1:9", token=CLAUDE)
    tools.save("scene", "offline_one", "name: c\nlayers:\n  - {fixtures: [bars], colour: red}\n")
    assert "offline_one" in tools.undo_last_change()
    assert not (root / "scenes" / "offline_one.yaml").exists()
