"""R8: node protocol v1.1 in the simulated node (mirrors firmware 0.2): per-universe radio sequence
numbers and real loss measurement, fallback and blackout on every universe, radio channel, request ids."""

from dmx_suite.node import protocol as p
from dmx_suite.node.sim import SimNode, SimReceiver


class Clock:
    def __init__(self):
        self.t = 0

    def __call__(self):
        return self.t


def node(*receivers, clock=None):
    return SimNode(receivers=list(receivers), clock_ms=clock or Clock())


def frame(v):
    return bytes([v]) * p.DMX_CHANNELS


def test_two_universes_dont_look_like_loss():
    # firmware 0.1 shared one sequence counter: a receiver on universe 0 saw every universe-1
    # packet as a gap and reported ~50 % loss
    clock = Clock()
    a = SimReceiver(bytes(6), universe=0)
    b = SimReceiver(bytes([1] * 6), universe=1)
    n = node(a, b, clock=clock)
    for i in range(40):
        clock.t += 25
        n.receive(p.dmx_frame(frame(i), 0))
        n.receive(p.dmx_frame(frame(i), 1))
    assert a.take_loss() == 0 and b.take_loss() == 0
    assert a.frame[0] == 39 and b.frame[0] == 39


def test_loss_is_measured_from_sequence_gaps():
    clock = Clock()
    r = SimReceiver(bytes(6), universe=0, loss_pct=20)
    n = node(r, clock=clock)
    for i in range(500):
        clock.t += 25
        n.receive(p.dmx_frame(frame(i & 0xFF), 0))
    assert 12 <= r.take_loss() <= 28  # about the 20 % lost on the air


def test_fallback_and_blackout_cover_every_universe():
    clock = Clock()
    a = SimReceiver(bytes(6), universe=0)
    b = SimReceiver(bytes([1] * 6), universe=1)
    n = node(a, b, clock=clock)
    base = bytearray(p.DMX_CHANNELS)
    base[0] = 200
    look = p.FallbackLook(hold_ms=1000, period_s=0, level=0, base=bytes(base))
    n.receive(p.set_fallback_universe(1, look, req=7))
    ack = p.decode(p.Parser().feed(n.take_output())[0])
    assert isinstance(ack, p.Ack) and ack.code == p.AckCode.OK and ack.req == 7
    for _ in range(4):
        clock.t += 25
        n.receive(p.dmx_frame(frame(50), 0))
        n.receive(p.dmx_frame(frame(60), 1))
    clock.t += 2500  # the laptop goes quiet (past the 2 s hold)
    n.step()
    clock.t += 30
    n.step()
    assert n.mode == p.Mode.FALLBACK
    assert b.frame[0] == 200  # universe 1's own fallback look, by radio
    assert a.frame[0] == 0  # universe 0 has none: black, not the last frame held forever
    n.receive(p.dmx_frame(frame(90), 1))
    n.receive(p.blackout())
    assert a.frame[0] == 0 and b.frame[0] == 0  # blackout reached universe 1 too
    clock.t += 120
    n.step()
    assert b.frame[0] == 0  # and the keep-alive keeps it black


def test_fallback_slots_are_limited():
    n = node()
    look = p.FallbackLook(base=bytes(p.DMX_CHANNELS))
    for u in range(p.MAX_FALLBACKS):
        n.receive(p.set_fallback_universe(u, look))
    n.receive(p.set_fallback_universe(9, look))
    acks = [m for m in (p.decode(x) for x in p.Parser().feed(n.take_output())) if isinstance(m, p.Ack)]
    assert [a.code for a in acks] == [p.AckCode.OK] * p.MAX_FALLBACKS + [p.AckCode.BAD_VALUE]


def test_channel_change_takes_the_receivers_along():
    clock = Clock()
    r = SimReceiver(bytes(6))
    away = SimReceiver(bytes([2] * 6), online=False)  # switched off: misses the move
    n = node(r, away, clock=clock)
    n.receive(p.set_channel(6))
    n.receive(p.encode(p.MsgType.SET_CHANNEL, bytes([14])))  # out of range (the encoder refuses it)
    acks = [m for m in (p.decode(x) for x in p.Parser().feed(n.take_output())) if isinstance(m, p.Ack)]
    assert [a.code for a in acks] == [p.AckCode.OK, p.AckCode.BAD_VALUE]
    assert n.channel == 6 and r.channel == 6 and away.channel == 1
    assert n.status().channel == 6 and n.status().dev_key


def test_requests_without_an_id_still_work():
    n = node(SimReceiver(bytes([9] * 6)))
    n.receive(p.assign(bytes([9] * 6), 1, "Left"))
    ack = next(m for m in (p.decode(x) for x in p.Parser().feed(n.take_output())) if isinstance(m, p.Ack))
    assert ack.code == p.AckCode.OK and ack.req is None
    assert n.receivers[0].name == "Left" and n.receivers[0].universe == 1
