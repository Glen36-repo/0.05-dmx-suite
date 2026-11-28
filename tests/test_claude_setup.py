"""Adding the 0.05 tools to Claude Desktop's config."""

import json
import sys
from pathlib import Path

import pytest

from dmx_suite import claude_setup
from dmx_suite.cli import main


def test_creates_standard_config_when_none(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    (cfg,) = claude_setup.config_paths()
    assert cfg == tmp_path / "Roaming" / "Claude" / "claude_desktop_config.json"
    claude_setup.setup(Path("S:/shows"))
    entry = json.loads(cfg.read_text())["mcpServers"]["dmx-suite"]
    assert entry["command"] == sys.executable
    assert entry["args"][-3:] == ["--shows", str(Path("S:/shows")), "mcp"]


def test_updates_store_install_and_keeps_other_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    cfg = tmp_path / "Local/Packages/Claude_pzs8sxrjxfjjc/LocalCache/Roaming/Claude/claude_desktop_config.json"
    cfg.parent.mkdir(parents=True)
    original = {"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}
    cfg.write_text(json.dumps(original))

    assert claude_setup.config_paths() == [cfg]
    assert claude_setup.setup(tmp_path / "shows") == [(cfg, True)]
    data = json.loads(cfg.read_text())
    assert data["theme"] == "dark"
    assert data["mcpServers"]["other"] == {"command": "x"}
    assert "dmx-suite" in data["mcpServers"]
    assert json.loads(cfg.with_name(cfg.name + ".bak").read_text()) == original

    # running again changes nothing
    assert claude_setup.setup(tmp_path / "shows") == [(cfg, False)]


def test_frozen_app_points_at_its_exe(monkeypatch, tmp_path):
    exe = tmp_path / "app" / "0.05 DMX Suite.exe"  # no console exe beside it
    exe.parent.mkdir()
    exe.write_text("")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    entry = claude_setup.server_entry(tmp_path)
    assert entry == {"command": str(exe), "args": ["--shows", str(tmp_path), "mcp"]}


def test_bad_config_is_left_alone(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text("[1, 2]")
    with pytest.raises(ValueError):
        claude_setup.add_server(cfg, {"command": "x"})
    assert cfg.read_text() == "[1, 2]"


def test_cli_command(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert main(["--shows", str(tmp_path / "shows"), "claude-setup"]) == 0
    assert "restart Claude Desktop" in capsys.readouterr().out
    assert (tmp_path / "Claude" / "claude_desktop_config.json").is_file()


# ------------------------------------------------------------------ Connect to Claude (Setup page)


@pytest.fixture
def laptop(monkeypatch, tmp_path):
    """A laptop with Claude Desktop (opened once, no config yet) and Claude Code."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "Roaming" / "Claude").mkdir(parents=True)
    (tmp_path / "home").mkdir()
    code = tmp_path / "home" / ".claude.json"
    code.write_text(json.dumps({"projects": {}, "mcpServers": {"github": {"command": "gh"}}}))
    return tmp_path


def by_kind(st):
    return {t["kind"]: t for t in st["targets"]}


def test_status_before_connect(laptop):
    st = claude_setup.status(laptop / "shows")
    t = by_kind(st)
    assert t["desktop"]["installed"] and t["desktop"]["registered"] == "no"
    assert t["code"]["installed"] and t["code"]["registered"] == "no"
    assert st["program_ok"] and st["shows"] == str(laptop / "shows")


def test_connect_then_disconnect_keeps_everything_else(laptop):
    shows = laptop / "shows"
    changed = claude_setup.connect(shows)
    assert len(changed) == 2
    t = by_kind(claude_setup.status(shows))
    assert t["desktop"]["registered"] == "current" and t["code"]["registered"] == "current"
    code = json.loads((laptop / "home" / ".claude.json").read_text())
    assert code["mcpServers"]["github"] == {"command": "gh"} and code["projects"] == {}
    assert code["mcpServers"]["dmx-suite"]["args"][-3:] == ["--shows", str(shows), "mcp"]
    assert claude_setup.connect(shows) == []  # already there
    # another show: the entry points elsewhere until updated
    t = by_kind(claude_setup.status(laptop / "other.dms"))
    assert t["desktop"]["registered"] == "other" and t["desktop"]["entry_shows"] == str(shows)
    assert len(claude_setup.disconnect()) == 2
    code = json.loads((laptop / "home" / ".claude.json").read_text())
    assert "dmx-suite" not in code["mcpServers"] and code["mcpServers"]["github"] == {"command": "gh"}
    assert (laptop / "home" / ".claude.json.bak").exists()
    assert claude_setup.disconnect() == []


def test_apps_not_installed_are_left_alone(monkeypatch, tmp_path):
    for k in ("APPDATA", "LOCALAPPDATA", "USERPROFILE", "HOME"):
        monkeypatch.setenv(k, str(tmp_path / k))
    st = claude_setup.status(tmp_path / "shows")
    assert not any(t["installed"] for t in st["targets"])
    assert claude_setup.connect(tmp_path / "shows") == []
    assert not (tmp_path / "APPDATA" / "Claude").exists()


def test_unreadable_config_reported_not_overwritten(laptop):
    bad = laptop / "home" / ".claude.json"
    bad.write_text("{not json")
    t = by_kind(claude_setup.status(laptop / "shows"))
    assert t["code"]["error"]
    with pytest.raises(ValueError):
        claude_setup.connect(laptop / "shows", only=["code"])
    assert bad.read_text() == "{not json"


def test_frozen_app_uses_the_console_exe(monkeypatch, tmp_path):
    gui = tmp_path / "0.05 DMX Suite.exe"
    console = tmp_path / "dmx-suite.exe"
    gui.write_text("")
    console.write_text("")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(gui))
    assert claude_setup.server_entry(tmp_path / "s")["command"] == str(console)


def test_api_connect_local_only_and_not_for_claude(laptop):
    import shutil

    from dmx_suite.app import App
    from dmx_suite.output import LogDriver
    from dmx_suite.showfiles import load_show
    from dmx_suite.web.server import WebServer

    root = laptop / "shows"
    shutil.copytree(Path(__file__).resolve().parents[1] / "shows", root, ignore=shutil.ignore_patterns(".backups"))
    app = App(load_show(root), [LogDriver()])
    web = WebServer(app, "127.0.0.1", 0, token="u" * 32)
    web.start()
    try:
        import urllib.request

        def call(path, method="GET", token="u" * 32):
            req = urllib.request.Request(f"http://127.0.0.1:{web.port}{path}", method=method,
                                         data=b"{}" if method == "POST" else None,
                                         headers={"X-DMX-Token": token, "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())

        status, st = call("/api/claude")
        assert status == 200 and by_kind(st)["desktop"]["registered"] == "no" and st["last_seen"] is None
        status, r = call("/api/claude/connect", "POST")
        assert status == 200 and len(r["changed"]) == 2 and by_kind(r["status"])["code"]["registered"] == "current"
        assert app.devices()[-2]["kind"] == "claude" or any(d["kind"] == "claude" and "open Claude" in d["detail"]
                                                            for d in app.devices())
        from dmx_suite.access import claude_token

        assert call("/api/claude/disconnect", "POST", token=claude_token())[0] == 403  # Claude can't unplug itself
        assert call("/api/claude", token=claude_token())[0] == 403
        status, r = call("/api/claude/disconnect", "POST")
        assert status == 200 and len(r["changed"]) == 2
    finally:
        web.stop()
