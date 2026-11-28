"""v4 Claude (MCP) tools: layout, outputs/routing, devices, monitor, haze settings, steps."""

import asyncio
import json
import shutil

import pytest
import yaml
from test_web import CLAUDE, SHOWS, call, running  # noqa: F401 - pytest fixture

from dmx_suite.claude_tools import DmxTools
from dmx_suite.store import StoreError


def offline_tools(tmp_path):
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json"))
    return DmxTools(shows=root, url="http://127.0.0.1:9", token=CLAUDE), root


# ---------------------------------------------------------------- layout (item 6)


def test_layout_tools_online(running):  # noqa: F811
    app, url, root = running
    t = DmxTools(shows=root, url=url, token=CLAUDE)
    view = yaml.safe_load(t.get_layout())
    assert view["rig"] == "full" and "bar_1" in view["layout"] and view["haze"] == ["smoke"]
    assert "smoke" not in view["layout"] and view["stage"]["cells_per_m"] == 4
    with pytest.raises(StoreError, match="unknown fixture"):
        t.set_layout("{nope: {x: 1, y: 1}}")
    assert t.set_layout("{wash_l: {x: 3, y: 12, z: 2.5}, wash_r: {rotation: 90}}").startswith("saved")
    rig = yaml.safe_load((root / "rigs" / "full.yaml").read_text())
    assert rig["layout"]["wash_l"] == {"x": 3.0, "y": 12.0, "rot": 0.0, "z": 2.5}
    assert rig["layout"]["wash_r"]["rot"] == 90.0 and "x" in rig["layout"]["wash_r"]  # default spot kept
    assert app.engine.rig.layout["wash_l"].z == 2.5  # applied live
    assert "# Head position points" in (root / "rigs" / "full.yaml").read_text()  # comments kept
    status, body = call(f"{url}/api/layout")
    assert status == 200 and body["layout"]["wash_l"]["placed"] is True
    app.set_gig_lock(True)
    with pytest.raises(StoreError, match="gig lock"):
        t.set_layout("{wash_l: {x: 5, y: 12}}")


def test_layout_tools_offline(tmp_path):
    t, root = offline_tools(tmp_path)
    assert "bar_1" in t.get_layout()
    assert "engine isn't running" in t.set_layout("{bar_2: {x: 20, y: 6, reverse: true}}")
    assert yaml.safe_load((root / "rigs" / "full.yaml").read_text())["layout"]["bar_2"]["reverse"] is True
    assert t.set_layout("{bar_2: {x: 21, y: 6}}", rig="small").startswith("saved to rigs/small.yaml")


def test_delete_fixture(running):  # noqa: F811
    app, url, root = running
    t = DmxTools(shows=root, url=url, token=CLAUDE)
    t.set_layout("{wash_r: {x: 9, y: 12}}")
    with pytest.raises(StoreError, match="no fixture"):
        t.delete_fixture("nope")
    with pytest.raises(StoreError, match="kick"):  # a look names it: refused, nothing changes
        t.delete_fixture("kick")
    assert t.delete_fixture("wash_r").startswith("saved")
    assert "wash_r" not in app.engine.rig.patch.fixtures
    assert "wash_r" not in (yaml.safe_load((root / "rigs" / "full.yaml").read_text()).get("layout") or {})


def test_mcp_lists_v4_layout_tools():
    pytest.importorskip("mcp")
    from dmx_suite.mcp_server import build_server

    server = build_server(DmxTools(shows=SHOWS, url="http://127.0.0.1:9", token=CLAUDE))
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert {"get_layout", "set_layout", "save_layout_position", "delete_fixture"} <= names
    text = json.dumps(asyncio.run(server.call_tool("get_layout", {})), default=lambda o: getattr(o, "__dict__", str(o)))
    assert "bar_1" in text
