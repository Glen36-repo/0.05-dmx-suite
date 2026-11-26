"""R8: what the app does with the 0.05 node: fallback looks pushed on connect, firmware and pairing-key
checks, naming confirmed by the node's own heartbeat, swapping in a spare, the radio channel."""

import shutil
import time
from pathlib import Path

import pytest

from dmx_suite.app import App
from dmx_suite.node import protocol as p
from dmx_suite.node import sim
from dmx_suite.output import NodeSerialDriver
from dmx_suite.showfiles import load_show

SHOWS = Path(__file__).resolve().parents[1] / "shows"


def wait(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def make(tmp_path):
    made = []

    def build():
        root = tmp_path / "shows"
        if not root.exists():
            shutil.copytree(SHOWS, root, ignore=shutil.ignore_patterns(".backups", ".state.json", ".giglock"))
        drv = NodeSerialDriver("sim")
        app = App(load_show(root), [drv])
        made.append(app)
        node = drv.link.t.node
        app.engine.output()  # the first frame: the node announces itself
        return app, drv, node

    yield build
    for a in made:
        a.engine.stop()


def pump(app, pred, timeout=5.0):
    """Keep frames (and so the simulated node's replies) flowing until pred() holds."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.engine.output()
        if pred():
            return True
        time.sleep(0.02)
    return False


def test_fallback_looks_pushed_on_connect(make):
    app, drv, node = make()
    assert pump(app, lambda: app.node_setup.get("fallbacks"))
    assert app.node_setup["fallbacks"] == {0: "ok"} and app.node_setup["fw"] == "0.2.0"
    assert node.fallbacks[0].base == app.fallback_frames()[0]  # the static look, MASTER on
    haze = next(f for f in app.engine.rig.fixtures if f.kind.value == "haze")
    assert node.fallbacks[0].base[haze.address - 1] == 0  # never haze in a fallback (rule 5)
    assert drv.link.v11


def test_old_firmware_is_flagged_and_still_works(make, monkeypatch):
    monkeypatch.setattr(sim, "FW_VERSION", (0, 1, 0))
    app, drv, node = make()
    assert pump(app, lambda: app.node_setup.get("fallbacks"))
    assert not drv.link.v11
    assert app.node_setup["fallbacks"] == {0: "ok"}  # v1 message, no request id
    assert any("older than this app expects" in d["detail"] for d in app.devices())


def test_development_key_shown(make):
    app, drv, node = make()
    assert pump(app, lambda: drv.link.stats.last_status is not None)
    assert any("development pairing key" in d["detail"] for d in app.devices())
    node.dev_key = False
    node._next_hb_ms = 0
    assert pump(app, lambda: not drv.link.stats.last_status.dev_key)
    assert not any("development pairing key" in d["detail"] for d in app.devices())


def test_naming_is_confirmed_by_the_node(make):
    app, drv, node = make()
    rx = node.receivers[0]
    assert pump(app, lambda: p.mac_str(rx.mac) in drv.link.health.nodes)
    done = {}

    def name_it():
        done.update(app.assign_node(p.mac_str(rx.mac), 2, "Left bars"))

    import threading

    th = threading.Thread(target=name_it)
    th.start()
    assert pump(app, lambda: "ok" in done, timeout=8)
    th.join()
    assert done["confirmed"] and rx.name == "Left bars" and rx.universe == 2


def test_naming_not_confirmed_when_the_receiver_doesnt_answer(make):
    app, drv, node = make()
    rx = node.receivers[0]
    assert pump(app, lambda: p.mac_str(rx.mac) in drv.link.health.nodes)
    rx.online = False  # it went out of range after it was last heard
    code, confirmed = drv.link.assign_confirmed(rx.mac, 1, "Gone", confirm_s=0.5)
    assert code == p.AckCode.OK and not confirmed


def test_replace_a_dead_receiver_with_a_spare(make):
    app, drv, node = make()
    dead, spare = node.receivers[0], node.receivers[1]
    dead.name, dead.universe = "Left bars", 0
    assert pump(app, lambda: drv.link.health.nodes.get(p.mac_str(dead.mac)) is not None
                and drv.link.health.nodes[p.mac_str(dead.mac)].name == "Left bars")
    dead.online = False
    rec = drv.link.health.nodes[p.mac_str(dead.mac)]
    rec.last_seen = -1e9  # long gone
    drv.link.health.tick()
    import threading

    done = {}
    th = threading.Thread(target=lambda: done.update(app.replace_node(p.mac_str(dead.mac), p.mac_str(spare.mac))))
    th.start()
    assert pump(app, lambda: "ok" in done, timeout=8)
    th.join()
    assert spare.name == "Left bars" and done["confirmed"]
    nodes = app.store.read("rig", "full")["nodes"]
    assert {"mac": p.mac_str(spare.mac), "name": "Left bars"} in nodes
    assert p.mac_str(dead.mac) not in drv.link.health.nodes


def test_radio_channel_moves_node_and_receivers(make):
    app, drv, node = make()
    assert pump(app, lambda: drv.link.v11)
    import threading

    done = {}
    th = threading.Thread(target=lambda: done.update(app.set_radio_channel(6)))
    th.start()
    assert pump(app, lambda: "ok" in done, timeout=8)
    th.join()
    assert node.channel == 6 and all(r.channel == 6 for r in node.receivers)
    assert app.store.read("rig", "full")["radio_channel"] == 6
    assert app.engine.rig.radio_channel == 6
    with pytest.raises(Exception, match="1-13"):
        app.set_radio_channel(20)
