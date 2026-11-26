from dmx_suite.node import protocol as p
from dmx_suite.node.health import HealthTracker, State


def hb(name="Left bars", rssi=-50, loss=0, mac=b"\x01\x02\x03\x04\x05\x06"):
    return p.Heartbeat(mac, p.NodeType.DMX_RX, (0, 1, 0), 1, rssi, loss, 10, 0, name)


def make():
    t = [0.0]
    return t, HealthTracker(clock=lambda: t[0], wall_clock=lambda: t[0])


def test_expected_node_missing_shows_offline_straight_away():
    _, h = make()
    h.expect([("01:02:03:04:05:06", "Left bars")])
    h.tick()
    rec = h.nodes["01:02:03:04:05:06"]
    assert rec.state == State.OFFLINE
    assert rec.name == "Left bars"
    assert rec in h.alerts()


def test_states():
    t, h = make()
    assert h.update(hb()).state == State.ONLINE
    assert h.update(hb(rssi=-81)).state == State.WEAK
    assert h.update(hb(loss=11)).state == State.WEAK
    assert h.update(hb(name="")).state == State.NEW
    assert h.update(hb(rssi=None, loss=None)).state == State.ONLINE  # wired: n/a
    t[0] = 3.4
    h.tick()
    assert h.nodes["01:02:03:04:05:06"].state == State.ONLINE
    t[0] = 3.6
    h.tick()
    assert h.nodes["01:02:03:04:05:06"].state == State.OFFLINE


def test_log_and_listeners_only_on_change():
    t, h = make()
    seen = []
    h.listeners.append(seen.append)
    h.update(hb())
    h.update(hb())
    t[0] = 10
    h.tick()
    h.update(hb())
    assert [(e.old, e.new) for e in seen] == [
        (None, State.ONLINE),
        (State.ONLINE, State.OFFLINE),
        (State.OFFLINE, State.ONLINE),
    ]
