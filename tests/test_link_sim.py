"""NodeLink against the simulated node, with a controllable clock."""

import pytest

from dmx_suite.node import protocol as p
from dmx_suite.node.health import HealthTracker, State
from dmx_suite.node.link import NodeLink
from dmx_suite.node.sim import SimNode, SimReceiver, SimTransport


class Clock:
    def __init__(self) -> None:
        self.ms = 0

    def __call__(self) -> int:
        return self.ms

    def s(self) -> float:
        return self.ms / 1000


RX1 = bytes.fromhex("F412FA00A001")
RX2 = bytes.fromhex("F412FA00A002")


@pytest.fixture
def rig():
    clock = Clock()
    node = SimNode(
        receivers=[SimReceiver(RX1, rssi=-50), SimReceiver(RX2, rssi=-85, loss_pct=20)],
        clock_ms=clock,
    )
    health = HealthTracker(clock=clock.s, wall_clock=clock.s)
    link = NodeLink(SimTransport(node), health)
    return clock, node, link


def test_ping(rig):
    _, _, link = rig
    assert link.ping(timeout=0.2) is not None


def test_frame_goes_out_immediately(rig):
    _, node, link = rig
    before = node.dmx_packets_sent
    frame = bytearray(512)
    frame[0] = 255
    link.send_frame(frame)
    # no poll / tick needed: the node put it on the wire as it arrived
    assert node.dmx_packets_sent == before + 1
    assert node.output[0] == 255
    assert node.mode == p.Mode.LIVE


def test_frame_relayed_to_receivers(rig):
    _, node, link = rig
    link.send_frame(bytes([1, 2, 3]))
    assert node.receivers[0].frame[:4] == bytes([1, 2, 3, 0])


def test_boots_into_fallback_then_live_then_fallback(rig):
    clock, node, link = rig
    look = p.FallbackLook(hold_ms=1000, period_s=10, level=100, rgb_addr=[1])
    assert link.set_fallback(look, timeout=0.2) == p.AckCode.OK
    link.poll()
    assert node.mode == p.Mode.FALLBACK
    assert node.output[0:3] == bytes([100, 0, 0])

    link.send_frame(bytes([0, 0, 0, 77]))
    assert node.mode == p.Mode.LIVE and node.output[3] == 77

    clock.ms += 900
    link.poll()
    assert node.mode == p.Mode.LIVE  # holding last frame
    clock.ms += 200
    link.poll()
    assert node.mode == p.Mode.FALLBACK
    assert node.output[3] == 0 and node.output[0] == 100


def test_blackout_is_sticky(rig):
    clock, node, link = rig
    link.send_frame(bytes([255] * 10))
    link.blackout()
    assert node.output == bytes(512)
    clock.ms += 10_000
    link.poll()
    assert node.mode == p.Mode.BLACKOUT
    assert node.output == bytes(512)


def test_status_and_heartbeats(rig):
    clock, node, link = rig
    for _ in range(40):
        link.send_frame(bytes(512))
        clock.ms += 25
    clock.ms += 1
    link.request_status()
    link.poll()
    st = link.stats.last_status
    assert st is not None and st.frames_rx == 40 and st.receivers_online == 2
    states = {mac: rec.state for mac, rec in link.health.nodes.items()}
    assert states[p.mac_str(node.mac)] == State.NEW
    assert states[p.mac_str(RX1)] == State.NEW


def test_assign_names_receiver_and_health_follows(rig):
    clock, node, link = rig
    link.poll()
    assert link.assign(RX1, 0, "Left bars", timeout=0.2) == p.AckCode.OK
    assert link.assign(RX2, 0, "Right bars", timeout=0.2) == p.AckCode.OK
    assert link.assign(node.mac, 0, "Main node", timeout=0.2) == p.AckCode.OK
    clock.ms += 1000
    link.poll()
    recs = link.health.nodes
    assert recs[p.mac_str(RX1)].state == State.ONLINE
    assert recs[p.mac_str(RX1)].name == "Left bars"
    assert recs[p.mac_str(RX2)].state == State.WEAK  # -85 dBm, 20 % loss
    assert recs[p.mac_str(node.mac)].state == State.ONLINE


def test_assign_unknown_target(rig):
    _, _, link = rig
    assert link.assign(bytes(6), 0, "x", timeout=0.2) == p.AckCode.UNKNOWN_TARGET


def test_receiver_drop_goes_offline_and_alerts(rig):
    clock, node, link = rig
    link.assign(RX1, 0, "Left bars", timeout=0.2)
    clock.ms += 1000
    link.poll()
    node.receivers[0].online = False
    for _ in range(4):
        clock.ms += 1000
        link.poll()
    rec = link.health.nodes[p.mac_str(RX1)]
    assert rec.state == State.OFFLINE
    assert rec in link.health.alerts()
    events = [e for e in link.health.log if e.mac == p.mac_str(RX1)]
    assert [e.new for e in events][-2:] == [State.ONLINE, State.OFFLINE]


def test_unknown_message_type_is_dropped_by_parser(rig):
    _, node, link = rig
    link.t.write(p.encode(0x40, b""))
    assert node.parser.crc_errors == 1
