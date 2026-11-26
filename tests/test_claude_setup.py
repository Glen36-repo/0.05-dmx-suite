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
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    entry = claude_setup.server_entry(tmp_path)
    assert entry == {"command": sys.executable, "args": ["--shows", str(tmp_path), "mcp"]}


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
