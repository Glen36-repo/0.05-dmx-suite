"""v4 item 8: universe -> interface routing, explicit and visible."""

import shutil
from pathlib import Path

import pytest
import yaml
from test_output import FakeSerial

from dmx_suite.app import App
from dmx_suite.claude_tools import DmxTools
from dmx_suite.fixtures import ConfigError
from dmx_suite.output import LogDriver, make_driver
from dmx_suite.output.enttec import EnttecProDriver
from dmx_suite.rig import parse_outputs, routing_problems
from dmx_suite.showfiles import check_all, load_show
from dmx_suite.store import StoreError

SHOWS = Path(__file__).resolve().parents[1] / "shows"


def test_outputs_get_a_universe_with_a_warning_when_missing():
    outs, warn = parse_outputs([{"driver": "enttec_open", "port": "COM3"}, {"driver": "node", "port": "COM5", "universe": 3},
                                {"driver": "artnet", "universes": {0: 1}}])
    assert outs[0] == {"driver": "usb_dmx_open", "port": "COM3", "universe": 0}
    assert "universe" not in outs[1]  # a node link carries every universe; nodes are set one by one
    assert len(warn) == 1 and "COM3" in warn[0] and "universe 0" in warn[0]
    assert parse_outputs(None) == ([{"driver": "null"}], [])
    for bad in ([{"driver": "laser"}], [{"driver": "usb_dmx_pro", "port": "COM4", "universe": 16}], [{"port": "COM3"}], {}):
        with pytest.raises(ConfigError):
            parse_outputs(bad)


def test_one_universe_to_several_outputs_and_problems(tmp_path):
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json"))
    p = root / "rigs" / "full.yaml"
    rig = yaml.safe_load(p.read_text())
    rig["outputs"] = [{"driver": "usb_dmx_open", "port": "COM3", "universe": 0},
                      {"driver": "usb_dmx_pro", "port": "COM4", "universe": 0},  # mirror U0
                      {"driver": "usb_dmx_pro", "port": "COM5", "universe": 2}]  # no lights on U2
    p.write_text(yaml.safe_dump(rig))
    fx = yaml.safe_load((root / "fixtures.yaml").read_text())
    fx["fixtures"][-2]["universe"] = 1  # kick on U1, which nothing sends
    (root / "fixtures.yaml").write_text(yaml.safe_dump(fx))
    files = load_show(root)
    probs = routing_problems(files.rig)
    assert any("universe 1 has lights but no output" in x for x in probs)
    assert any("sends universe 2, which has no lights" in x for x in probs)
    assert not any("universe 0 has lights" in x for x in probs)
    assert any("universe 1 has lights" in w for w in check_all(root))


def test_shipped_rig_routing_is_clean():
    files = load_show(SHOWS)
    assert routing_problems(files.rig) == []


def test_routing_table_reads_what_each_interface_sent():
    files = load_show(SHOWS)
    log = make_driver({"driver": "log"})
    ser = FakeSerial()
    pro = EnttecProDriver("COM9", universe=1, serial_factory=lambda *a: ser)  # carries U1 only: no lights there
    pro.cfg = {"driver": "usb_dmx_pro", "port": "COM9", "universe": 1, "alias": "Stage DMX"}
    app = App(files, [log, pro])
    r = app.routing()
    assert [(row["universe"], row["driver"]) for row in r["rows"]] == [(0, "log")]  # the Pro carries no used universe
    assert r["rows"][0]["frames"] == 0 and r["rows"][0]["last_frame_age_ms"] is None
    app.engine.output()
    row = app.routing()["rows"][0]
    assert row["frames"] == 1 and row["last_frame_age_ms"] is not None and row["all_zero"] is not None
    assert pro.wire.frame(0) is None  # never sent U0: nothing to show for it
    tile = next(d for d in app.devices() if d["kind"] == "output")
    assert tile["name"] == "Simulator"  # sim tiles keep their text
    pro.close()


def test_wire_only_records_successful_writes():
    ser = FakeSerial()
    d = EnttecProDriver("COM9", serial_factory=lambda *a: ser)
    d.send(0, bytes([7]) + bytes(511))
    assert d.flush()
    assert d.wire.frame(0)[0] == 7 and d.wire.stats(0)["all_zero"] is False

    def broken(*a):
        raise OSError("unplugged")

    d2 = EnttecProDriver("COM8", serial_factory=broken, threaded=False)
    d2.send(0, bytes([9]) + bytes(511))
    assert d2.wire.frame(0) is None and d2.wire.stats(0)["frames"] == 0
    d.close()
    d2.close()


def test_set_output_api_and_tools(tmp_path):
    from test_web import CLAUDE, TOKEN, call

    from dmx_suite.web.server import WebServer

    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json"))
    app = App(load_show(root), [LogDriver()], state_path=root / ".state.json")
    web = WebServer(app, "127.0.0.1", 0, token=TOKEN, claude_token=CLAUDE)
    web.start()
    try:
        url = f"http://127.0.0.1:{web.port}"
        status, body = call(f"{url}/api/routing")
        assert status == 200 and body["universes"] == [0] and body["rows"][0]["universe"] == 0
        t = DmxTools(shows=root, url=url, token=CLAUDE)
        assert "rows" in t.list_outputs()
        assert t.set_output(0, universe=0, alias="Stage DMX").startswith("saved")
        assert yaml.safe_load((root / "rigs" / "full.yaml").read_text())["outputs"][0]["alias"] == "Stage DMX"
        with pytest.raises(StoreError, match="universe 0-15"):
            t.set_output(0, universe=20)
        assert t.set_output(-1, driver="artnet").startswith("saved")
        assert len(yaml.safe_load((root / "rigs" / "full.yaml").read_text())["outputs"]) == 2
        app.set_gig_lock(True)
        with pytest.raises(StoreError, match="gig lock"):
            t.set_output(0, universe=1)
    finally:
        web.stop()
        app.engine.stop()


def test_list_outputs_offline(tmp_path):
    root = tmp_path / "shows"
    shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json"))
    out = yaml.safe_load(DmxTools(shows=root, url="http://127.0.0.1:9", token="x" * 20).list_outputs())
    assert out["outputs"][0]["universe"] == 0 and "no live stats" in out["note"]


def test_node_health_lists_universes_of_wired_outputs():
    app = App(load_show(SHOWS), [LogDriver()])
    assert app.nodes()[0]["universes"] == [0]
